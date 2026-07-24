"""노른 (norn) — 위그드라실을 손질하는 손. 자라난 기억을 주기적으로 돌보는 자가 진화 패스.

노르니르가 우르드 샘물을 길어 나무가 마르지 않게 돌보듯, 노른은 위키를 손질한다:
같은 사실은 하나로 모으고(merge), 낱개 관측 뒤의 패턴을 승격하고(insight), 낡은 가지는
접어 보관하고(archive), 서로 어긋난 기록은 사람에게 알린다(contradiction).

계약 — LLM 은 델타만 제안하고, 커밋은 결정론 코드가 한다:
- 전면 재작성 금지. 델타 단위 제안만 받아야 반복 손질이 기억을 뭉개지 않는다.
- 각 op 는 기계 검증을 통과한 것만 남는다 — LLM 의 주장은 검증 입력일 뿐이다:
  merge 는 결정적 유사도 플로어 미달이면 기각, archive 는 lint decay-candidate 만 자격,
  insight 는 실존 소스 2개 이상 + 인젝션/시크릿 스캔 통과, confidence 는 근거 수로
  코드가 계산한다 (자기 신고 불신).
- 환경 의존 실패·도구 부정 주장은 기억으로 굳히지 않는다 — 그날의 사정이 원칙으로
  박제되면 미래의 자신을 거부하는 근거가 된다.
- 적용 전 pages/ 전체 백업 (norn-backups/, 최근 5개 유지), 삭제 없음 — archive 는
  archive/ 로 이동해 언제든 복원 가능하다 (norn-restore).
- 게이트는 노른 산출물도 신뢰하지 않는다 — insight 페이지 역시 힌트일 뿐 완료 증거가 아니다.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import os
import re
import shutil

from .index import _db, write_index
from .pages import lint
from .pages import merge as _merge_pages
from .policy import _memory_settings, memory_dir, scan_secrets, scan_threats
from .recall import _containment, _jaccard
from .store import (
    LOG,
    PAGES,
    _atomic_write,
    _lock,
    _page_path,
    _pages,
    _read,
    _today,
    ensure_home,
    log_op,
    poisoned,
    valid_slug,
)

STATE_FILE = "norn-state.json"
BACKUP_DIR = "norn-backups"
ARCHIVE_DIR = "archive"
REPORTS_DIR = "reports"
BACKUP_KEEP = 5

OPS_THRESHOLD = 25  # log.md 신규 연산 누적 문턱 — config [memory].norn_ops_threshold
MIN_INTERVAL_DAYS = 3  # 노른 간 최소 간격 — config [memory].norn_min_interval_days
MERGE_FLOOR = 0.25  # merge 결정적 유사도 플로어 — LLM 주장과 무관하게 코드가 본다
MAX_MERGES, MAX_ARCHIVES, MAX_INSIGHTS, MAX_CONTRADICTIONS = 3, 3, 2, 3
INSIGHT_MAX_CHARS = 1200
INSIGHT_MIN_SOURCES, INSIGHT_MAX_SOURCES = 2, 6

# 자기중독 방지 — 환경 의존 실패·도구 부정 주장은 통찰이 아니라 그날의 사정이다.
_FORBIDDEN_INSIGHT = re.compile(
    r"command not found|no such file|permission denied|not installed|rate.?limit|"
    r"(?:tool|mcp|browser)s?\s+(?:is\s+)?(?:broken|not\s+work)|do(?:es)?\s+not\s+work|not supported|"
    r"credential|api.?key|unauthorized|미설치|권한 거부|작동하지 않",
    re.IGNORECASE,
)

# LLM행 기본 프롬프트는 영어 정본 — 사람 표면은 한국어 유지.
_NORN_SYS = (
    "You are the Norn tender of Yggdrasil, a personal memory wiki. Review the page catalog "
    "and propose a SMALL set of consolidation deltas. You never rewrite the library wholesale: "
    "you emit deltas only, and deterministic code validates and applies them.\n\n"
    "Allowed operations (JSON array `ops`):\n"
    '- {"op":"merge","src":"<slug>","dst":"<slug>","why":"..."} — src is absorbed into dst, then '
    "src is removed. Only when both pages state the same fact or one strictly contains the other.\n"
    '- {"op":"archive","slug":"<slug>","why":"..."} — retire a stale page (kept restorable). Only '
    "slugs listed under `decay_candidates` are eligible; anything else will be dropped.\n"
    '- {"op":"insight","title":"...","text":"...","sources":["<slug>","<slug>"],"why":"..."} — a NEW '
    "higher-order pattern that is only visible across 2+ existing pages (inductive reasoning: "
    "preferences, tendencies, recurring behaviors). The text must be self-contained, declarative, "
    "grounded ONLY in the listed source pages, and must not merely restate a single page.\n"
    '- {"op":"contradiction","a":"<slug>","b":"<slug>","why":"..."} — two pages make incompatible '
    "claims. Report only; a human resolves it.\n\n"
    "Rules:\n"
    '- Output STRICT JSON: {"ops":[...]} and nothing else. No prose, no code fences.\n'
    "- Be conservative. An empty ops list is a valid, common outcome — do not invent work.\n"
    "- Never put environment-dependent failures, negative claims about tools, or credentials in "
    "insight text.\n"
    '- Never merge a page of kind "user" into a page of another kind.\n'
    "- Write insight text in the dominant language of the source pages."
)


def _settings_int(key: str, default: int) -> int:
    try:
        v = _memory_settings().get(key)
        return max(1, int(v)) if v is not None else default
    except Exception:
        return default


def _merge_floor() -> float:
    try:
        v = _memory_settings().get("norn_merge_floor")
        return float(v) if v is not None else MERGE_FLOOR
    except Exception:
        return MERGE_FLOOR


def _state_path(d: str) -> str:
    return os.path.join(d, STATE_FILE)


def _load_state(d: str) -> dict:
    try:
        state = json.load(open(_state_path(d), encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def _save_state(d: str, state: dict) -> None:
    with contextlib.suppress(Exception):
        _atomic_write(_state_path(d), json.dumps(state, ensure_ascii=False, indent=1))


def _log_lines(d: str) -> int:
    """log.md 누적 연산 행 수 — 노른 트리거의 결정적 활동 신호 (LLM·중요도 점수 불요)."""
    try:
        return sum(1 for line in open(os.path.join(d, LOG), encoding="utf-8") if line.startswith("- "))
    except Exception:
        return 0


def norn_due(d: str | None = None) -> tuple[bool, str]:
    """트리거 판정 — (due, 사유). 연산 누적 문턱 + 최소 간격 — 활동이 쌓였을 때만 손질한다."""
    d = d or memory_dir()
    state = _load_state(d)
    threshold = _settings_int("norn_ops_threshold", OPS_THRESHOLD)
    interval = _settings_int("norn_min_interval_days", MIN_INTERVAL_DAYS)
    delta = _log_lines(d) - int(state.get("log_lines", 0))
    if delta < threshold:
        return False, f"연산 누적 {delta}/{threshold}건 — 아직 이르다"
    last = str(state.get("last_norn", ""))
    if last:
        try:
            days = (_dt.date.today() - _dt.date.fromisoformat(last[:10])).days
            if days < interval:
                return False, f"최근 노른 {days}일 전 — 최소 간격 {interval}일"
        except ValueError:
            pass
    return True, f"연산 누적 {delta}건 (문턱 {threshold})"


# ── 신호 수집 (결정론) ─────────────────────────────────────────────────────────


def signals(d: str | None = None) -> dict:
    """LLM 에게 보여줄 증거 카드 — 페이지 카탈로그·usage·lint 판정. 쓰기 없음."""
    d = d or memory_dir()
    uses: dict[str, int] = {}
    with contextlib.suppress(Exception):
        conn = _db(d)
        uses = dict(conn.execute("SELECT slug, uses FROM usage").fetchall())
        conn.close()
    pages: list[dict] = []
    for slug in _pages(d):
        pg = _read(d, slug)
        if not pg or poisoned(*pg):
            continue  # 오염 페이지는 노른 대상도 아니다 — lint 가 threat 로 보고한다
        meta, body = pg
        first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
        pages.append(
            {
                "slug": slug,
                "title": meta.get("title", slug),
                "kind": meta.get("kind", "note"),
                "updated": meta.get("updated", meta.get("created", "")),
                "uses": int(uses.get(slug, 0)),
                "excerpt": first[:160],
            }
        )
    findings = lint(d)
    return {
        "pages": pages,
        "decay_candidates": sorted({f["slug"] for f in findings if f["code"] == "decay-candidate"}),
        "near_duplicates": [
            f["msg"].replace("≈ ", f"{f['slug']} ≈ ") for f in findings if f["code"] == "near-duplicate"
        ],
    }


# ── 계획 (LLM 제안 → 결정적 검증) ──────────────────────────────────────────────


def _confidence(n_sources: int) -> str:
    """근거 수가 confidence 를 결정한다 — 2=low, 3~4=medium, 5+=high (LLM 자기 신고 불신)."""
    return "high" if n_sources >= 5 else "medium" if n_sources >= 3 else "low"


def _parse_ops(raw: str) -> list[dict]:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("norn: LLM output is not JSON")
    payload = json.loads(raw[start : end + 1])
    ops = payload.get("ops") if isinstance(payload, dict) else None
    if not isinstance(ops, list):
        raise ValueError("norn: LLM output has no ops list")
    return [op for op in ops if isinstance(op, dict)]


def validate_ops(ops: list[dict], d: str) -> tuple[list[dict], list[dict]]:
    """결정적 검증 — 통과한 op 와 (op, 기각 사유). LLM 주장은 검증 입력일 뿐이다."""
    floor = _merge_floor()
    lint_findings = lint(d)
    decay_ok = {f["slug"] for f in lint_findings if f["code"] == "decay-candidate"}
    accepted: list[dict] = []
    dropped: list[dict] = []
    counts = {"merge": 0, "archive": 0, "insight": 0, "contradiction": 0}
    caps = {"merge": MAX_MERGES, "archive": MAX_ARCHIVES, "insight": MAX_INSIGHTS, "contradiction": MAX_CONTRADICTIONS}

    def _drop(op: dict, reason: str) -> None:
        dropped.append({"op": op, "reason": reason})

    def _clean(slug: object) -> tuple[dict, str] | None:
        if not isinstance(slug, str) or not valid_slug(slug):
            return None
        pg = _read(d, slug)
        return pg if pg and not poisoned(*pg) else None

    for op in ops:
        kind = str(op.get("op") or "")
        if kind not in counts:
            _drop(op, f"unknown op: {kind!r}")
            continue
        if counts[kind] >= caps[kind]:
            _drop(op, f"cap reached: {kind} ≤ {caps[kind]}")
            continue
        if kind == "merge":
            src, dst = op.get("src"), op.get("dst")
            ps, pd = _clean(src), _clean(dst)
            if not ps or not pd or src == dst:
                _drop(op, "merge: src/dst missing, poisoned, or identical")
                continue
            if ps[0].get("kind") == "user" and pd[0].get("kind") != "user":
                _drop(op, "merge: user page must not merge into non-user page")
                continue
            a = ps[0].get("title", "") + " " + ps[1]
            b = pd[0].get("title", "") + " " + pd[1]
            sim = max(_containment(a, b), _jaccard(a, b))
            if sim < floor:
                _drop(op, f"merge: similarity {sim:.2f} < floor {floor:.2f} (deterministic backstop)")
                continue
            accepted.append(
                {"op": "merge", "src": src, "dst": dst, "sim": round(sim, 2), "why": str(op.get("why", ""))[:200]}
            )
        elif kind == "archive":
            slug = op.get("slug")
            if not isinstance(slug, str) or slug not in decay_ok:
                _drop(op, "archive: only lint decay-candidates are eligible")
                continue
            accepted.append({"op": "archive", "slug": slug, "why": str(op.get("why", ""))[:200]})
        elif kind == "insight":
            title = str(op.get("title") or "").strip()[:80]
            text = str(op.get("text") or "").strip()
            sources = [s for s in (op.get("sources") or []) if isinstance(s, str)]
            sources = list(dict.fromkeys(sources))
            if not title or not text or len(text) > INSIGHT_MAX_CHARS:
                _drop(op, "insight: missing/oversized title or text")
                continue
            if not (INSIGHT_MIN_SOURCES <= len(sources) <= INSIGHT_MAX_SOURCES):
                _drop(op, f"insight: needs {INSIGHT_MIN_SOURCES}–{INSIGHT_MAX_SOURCES} distinct sources")
                continue
            if any(_clean(s) is None for s in sources):
                _drop(op, "insight: source page missing or poisoned")
                continue
            if _FORBIDDEN_INSIGHT.search(title + " " + text):
                _drop(op, "insight: forbidden capture (env-dependent/tool-negativity/credential)")
                continue
            threat = scan_threats(text, title) or scan_secrets(text, title)
            if threat:
                _drop(op, f"insight: {threat}")
                continue
            accepted.append(
                {
                    "op": "insight",
                    "title": title,
                    "text": text,
                    "sources": sources,
                    "confidence": _confidence(len(sources)),
                    "why": str(op.get("why", ""))[:200],
                }
            )
        else:  # contradiction — 보고 전용, 페이지 실존만 확인
            a, b = op.get("a"), op.get("b")
            if not _clean(a) or not _clean(b) or a == b:
                _drop(op, "contradiction: pages missing, poisoned, or identical")
                continue
            accepted.append({"op": "contradiction", "a": a, "b": b, "why": str(op.get("why", ""))[:200]})
        counts[kind] += 1
    return accepted, dropped


def _complete(root: str, system: str, user: str) -> str:
    """LLM 단발 호출 간접점 — 테스트가 이 지점만 대체한다."""
    from ..agent.oneshot import complete_once

    return complete_once(root, system, user, max_tokens=3000)


def plan_norn(root: str, d: str | None = None) -> dict:
    """신호 수집 → LLM 제안 → 결정적 검증. 반환 = {"ops", "dropped", "signals"}. 쓰기 없음."""
    d = ensure_home(d)
    sig = signals(d)
    if len(sig["pages"]) < 2:
        return {"ops": [], "dropped": [], "signals": sig}
    user = json.dumps(
        {
            "pages": sig["pages"],
            "decay_candidates": sig["decay_candidates"],
            "near_duplicates": sig["near_duplicates"],
        },
        ensure_ascii=False,
    )
    raw = _complete(root, _NORN_SYS, user)
    ops = _parse_ops(raw)
    accepted, dropped = validate_ops(ops, d)
    return {"ops": accepted, "dropped": dropped, "signals": sig}


# ── 적용 (결정론 — 백업 → 커밋 → 보고) ─────────────────────────────────────────


def _backup(d: str) -> str:
    """pages/ 전체 스냅샷 — 손질은 언제든 되돌릴 수 있어야 한다."""
    ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d%H%M%S")
    dst = os.path.join(d, BACKUP_DIR, ts)
    shutil.copytree(os.path.join(d, PAGES), dst)
    backups = sorted(os.listdir(os.path.join(d, BACKUP_DIR)))
    for old in backups[:-BACKUP_KEEP]:
        shutil.rmtree(os.path.join(d, BACKUP_DIR, old), ignore_errors=True)
    return dst


def archive_page(slug: str, d: str | None = None) -> bool:
    """페이지 보관 전이 — pages/ 밖 archive/ 로 이동 (검색·주입에서 사라짐, 복원 가능)."""
    d = d or memory_dir()
    if not valid_slug(slug):
        raise ValueError(f"invalid slug: {slug!r}")
    with _lock(d):
        path = _page_path(d, slug)
        if not os.path.exists(path):
            return False
        adir = os.path.join(d, ARCHIVE_DIR)
        os.makedirs(adir, exist_ok=True)
        ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d%H%M%S")
        shutil.move(path, os.path.join(adir, f"{slug}-{ts}.md"))
        with contextlib.suppress(Exception):
            conn = _db(d)
            with conn:
                conn.execute("DELETE FROM fts WHERE slug = ?", (slug,))
                conn.execute("DELETE FROM vec WHERE slug = ?", (slug,))
            conn.close()
        write_index(d)
        log_op(d, "norn:archive", slug)
    return True


def restore_page(slug: str, d: str | None = None) -> bool:
    """보관 해제 — 최신 아카이브 스냅샷을 pages/ 로 복귀."""
    d = d or memory_dir()
    if not valid_slug(slug):
        raise ValueError(f"invalid slug: {slug!r}")
    adir = os.path.join(d, ARCHIVE_DIR)
    snaps = sorted(
        f
        for f in (os.listdir(adir) if os.path.isdir(adir) else [])
        if re.fullmatch(rf"{re.escape(slug)}-\d{{14}}\.md", f)
    )
    if not snaps:
        return False
    with _lock(d):
        dst = _page_path(d, slug)
        if os.path.exists(dst):
            raise ValueError(f"page '{slug}' already exists — remove it before restoring")
        shutil.move(os.path.join(adir, snaps[-1]), dst)
        write_index(d)
        log_op(d, "norn:restore", slug)
    from .index import reindex

    reindex(d)
    return True


def apply_norn(d: str | None, plan: dict) -> dict:
    """검증 통과 op 만 결정론 커밋. 반환 = {"applied", "failed", "backup", "report"}."""
    d = ensure_home(d)
    ops = list(plan.get("ops") or [])
    applied: list[dict] = []
    failed: list[dict] = []
    backup = _backup(d) if any(op["op"] in ("merge", "archive") for op in ops) else ""
    for op in ops:
        try:
            if op["op"] == "merge":
                _merge_pages(op["src"], op["dst"], d)
                applied.append(op)
            elif op["op"] == "archive":
                if archive_page(op["slug"], d):
                    applied.append(op)
                else:
                    failed.append({**op, "error": "page disappeared"})
            elif op["op"] == "insight":
                from .pages import add

                date = _today()
                provenance = " ".join(f"[[{s}]]" for s in op["sources"])
                body = f"{op['text']}\n\nsources: {provenance} (norn {date}, confidence: {op['confidence']})"
                slug, _ = add(body, title=op["title"], kind="insight", links=",".join(op["sources"]), d=d)
                applied.append({**op, "slug": slug})
            else:  # contradiction — 보고 전용
                applied.append(op)
        except ValueError as e:  # 예산 초과·경합 등 — 노른은 부분 실패를 정직하게 남긴다
            failed.append({**op, "error": str(e)})
    state = _load_state(d)
    state.update({"last_norn": _today(), "log_lines": _log_lines(d)})
    _save_state(d, state)
    log_op(d, "norn", "-", f"applied={len(applied)} failed={len(failed)} dropped={len(plan.get('dropped') or [])}")
    report = _write_report(d, plan, applied, failed, backup)
    return {"applied": applied, "failed": failed, "backup": backup, "report": report}


def _write_report(d: str, plan: dict, applied: list[dict], failed: list[dict], backup: str) -> str:
    """노른 리포트 — reports/ 는 pages/ 밖 (인덱스 예산 무관). Obsidian vault 에서 바로 읽힌다."""
    rdir = os.path.join(d, REPORTS_DIR)
    os.makedirs(rdir, exist_ok=True)
    ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d-%H%M")
    lines = [f"# Norn {ts}", ""]
    for op in applied:
        if op["op"] == "merge":
            lines.append(f"- merge: [[{op['src']}]] → [[{op['dst']}]] (sim {op.get('sim', '?')}) — {op['why']}")
        elif op["op"] == "archive":
            lines.append(f"- archive: {op['slug']} — {op['why']} (복원: asgard memory norn-restore {op['slug']})")
        elif op["op"] == "insight":
            srcs = ", ".join(f"[[{s}]]" for s in op["sources"])
            lines.append(f"- insight: [[{op.get('slug', '')}]] ({op['confidence']}) ← {srcs}")
        else:
            lines.append(f"- ⚠ contradiction: [[{op['a']}]] ↔ [[{op['b']}]] — {op['why']} (사람이 해소)")
    for op in failed:
        lines.append(f"- ✗ {op['op']} 실패 — {op.get('error', '')}")
    for op in plan.get("proposed") or []:  # 자율 런의 잔류 제안 — 백그라운드 결과도 흔적을 남긴다
        target = op.get("slug") or f"{op.get('src', '')} → {op.get('dst', '')}"
        lines.append(f"- (제안) {op['op']}: {target} — 검토: asgard memory norn")
    for row in plan.get("dropped") or []:
        lines.append(f"- (기각) {row['op'].get('op', '?')} — {row['reason']}")
    if backup:
        lines.append(f"\n백업: {os.path.relpath(backup, d)}")
    path = os.path.join(rdir, f"norn-{ts}.md")
    _atomic_write(path, "\n".join(lines) + "\n")
    return path


# ── 자율 계층 (오딘 결정 26-07-24: "추가는 자율, 파괴는 동의") ─────────────────────
#
# 스스로 기록하며 성장하되, 되돌릴 수 없는 것은 손대지 않는다:
# 완전 가역·순수 추가인 op 는 자율로 기록하고, 위키의 형태를 바꾸는
# op(병합·보관)는 제안으로 남긴다. 스킬 승인 게이트(CUS-251)는 이 계층과 무관하게 불변 —
# 여기서 자율화되는 것은 advisory 지식(개인 위키)뿐이고, 그마저 스캔·플로어·캡을 통과한
# 것만이다. 게이트는 여전히 어떤 메모리도 완료 증거로 신뢰하지 않는다.
#
#   off  — 자율 없음: 전부 제안 (넛지만)
#   safe — insight(순수 추가·remove 로 즉시 가역)·contradiction(보고 전용)만 자동, 기본값
#   full — merge·archive 까지 자동 (백업+복원 가능하지만 형태 변경 — 명시 선택)

AUTO_MODES = ("off", "safe", "full")
_AUTO_OPS = {
    "off": frozenset(),
    "safe": frozenset({"insight", "contradiction"}),
    "full": frozenset({"merge", "archive", "insight", "contradiction"}),
}


def auto_mode() -> str:
    """노른 자율 모드 — config [memory].norn_auto ∈ off|safe|full (기본 safe)."""
    try:
        v = str(_memory_settings().get("norn_auto", "safe")).strip().lower()
        return v if v in AUTO_MODES else "safe"
    except Exception:
        return "safe"


def partition_ops(ops: list[dict], mode: str) -> tuple[list[dict], list[dict]]:
    """검증 통과 op 를 (자동 적용분, 제안 잔류분) 으로 가른다 — 모드가 자격을 정한다."""
    allowed = _AUTO_OPS.get(mode, frozenset())
    auto = [op for op in ops if op["op"] in allowed]
    proposed = [op for op in ops if op["op"] not in allowed]
    return auto, proposed


def run_auto(root: str, d: str | None = None) -> dict:
    """자율 노른 1회 — due 판정 → 계획 → 모드 자격분만 적용, 잔류분은 제안으로 보고.

    비-due 여도 강제하지 않는다 (호출측이 due 를 확인하고 부르는 것이 정상 경로지만,
    수동 `norn --auto` 는 즉시 실행을 원하므로 due 를 다시 막지 않는다)."""
    d = ensure_home(d)
    mode = auto_mode()
    plan = plan_norn(root, d)
    auto_ops, proposed = partition_ops(plan["ops"], mode)
    if auto_ops or proposed or plan["dropped"]:
        # 제안·기각뿐이어도 리포트는 남긴다 — 백그라운드 런의 결과가 침묵 속에 사라지지 않는다
        result = apply_norn(d, {"ops": auto_ops, "dropped": plan["dropped"], "proposed": proposed})
    else:
        result = {"applied": [], "failed": [], "backup": "", "report": ""}
        state = _load_state(d)  # 무수확 런도 상태는 전진 — 같은 누적으로 재발화하지 않는다
        state.update({"last_norn": _today(), "log_lines": _log_lines(d)})
        _save_state(d, state)
    return {
        "mode": mode,
        "applied": result["applied"],
        "failed": result["failed"],
        "proposed": proposed,
        "report": result["report"],
    }


# ── 넛지 (latch — 제안 피로 방지) ──────────────────────────────────────────────


def nudge_line(d: str | None = None) -> str | None:
    """노른이 due 이고 같은 누적 상태로 아직 말하지 않았을 때만 한 줄. 그 외 None."""
    d = d or memory_dir()
    due, reason = norn_due(d)
    if not due:
        return None
    state = _load_state(d)
    digest = hashlib.sha1(f"{_log_lines(d)}".encode()).hexdigest()[:12]
    if state.get("nudge_digest") == digest:
        return None
    state["nudge_digest"] = digest
    _save_state(d, state)
    return f"위그드라실 노른 제안 — {reason}. asgard memory norn 으로 통합 검토 (--apply 전엔 무변경)"
