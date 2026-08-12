"""적용 (결정론 — 백업 → 커밋 → 보고). 검증을 통과한 op만 여기까지 온다.

보관(archive)은 삭제가 아니라 `archive/`로의 이동이고 `restore_page`로 되돌아온다.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import os
import re
import shutil

from ..contradiction import ACKNOWLEDGED, contradiction_key
from ..contradiction import record as record_contradictions
from ..index import _db, write_index
from ..pages import merge as _merge_pages
from ..policy import memory_dir
from ..store import (
    PAGES,
    _atomic_write,
    _lock,
    _page_path,
    _read,
    _today,
    ensure_home,
    log_op,
    render_page,
    valid_slug,
)
from .state import _load_state, _log_lines, _save_state
from .validate import _existing_links

BACKUP_DIR = "norn-backups"
ARCHIVE_DIR = "archive"
REPORTS_DIR = "reports"
BACKUP_KEEP = 5


def _backup(d: str) -> str:
    """pages/ 전체 스냅샷 — 손질은 언제든 되돌릴 수 있어야 한다."""
    ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d%H%M%S")
    dst = os.path.join(d, BACKUP_DIR, ts)
    shutil.copytree(os.path.join(d, PAGES), dst)
    backups = sorted(os.listdir(os.path.join(d, BACKUP_DIR)))
    for old in backups[:-BACKUP_KEEP]:
        shutil.rmtree(os.path.join(d, BACKUP_DIR, old), ignore_errors=True)
    return dst


def _add_link(d: str, a: str, b: str) -> bool:
    """양쪽 frontmatter에 서로를 적는다. 반환 = 한 쪽이라도 실제로 바뀌었는가.

    회수(PPR)는 어차피 무향이지만 사람이 페이지를 열었을 때 한쪽에서만 보이면 관계가 반쪽으로
    읽힌다.

    락을 잡는 이유: 이것은 읽고-고쳐-쓰기이고, 노른은 `spawn_pass` 로 분리된 프로세스에서
    돈다 — 사용자의 대화형 ingest 와 진짜로 동시에 실행된다. 락이 없으면 읽은 뒤 남이 쓴
    본문 위에 옛 본문을 덮어써서 그 쓰기가 통째로 사라진다. 다른 쓰기 경로(add·ingest·
    remove·merge)가 전부 같은 락을 지나므로, 여기만 안 지나면 직렬화가 성립하지 않는다."""
    changed = False
    with _lock(d):
        for source, target in ((a, b), (b, a)):
            pg = _read(d, source)
            if not pg:
                continue
            meta, body = pg
            links = _existing_links(meta)
            if target in links:
                continue
            meta = {**meta, "links": ",".join(sorted(links | {target})), "updated": _today()}
            _atomic_write(_page_path(d, source), render_page(meta, body))
            changed = True
    return changed


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
    from ..index import reindex

    reindex(d)
    return True


def apply_norn(d: str | None, plan: dict) -> dict:
    """검증 통과 op만 결정론 커밋. 반환 = {"applied", "failed", "backup", "report"}."""
    d = ensure_home(d)
    ops = list(plan.get("ops") or [])
    applied: list[dict] = []
    failed: list[dict] = []
    # 기존 페이지를 **고치거나 없애는** op 앞에서만 스냅샷을 뜬다. link가 여기 들어가는 것이
    # 요점이다 — 파괴적이지 않다는 말이 무변경이라는 뜻은 아니고, `_add_link`는 양쪽
    # frontmatter를 실제로 다시 쓴다. insight·contradiction은 순수 추가라 뺀다
    # (아무것도 안 고치는 런에서 pages/ 전체를 복사하는 것은 비용만 드는 일이다).
    backup = _backup(d) if any(op["op"] in ("merge", "archive", "link") for op in ops) else ""
    linked = False  # link op이 실제로 페이지를 고쳤는가 — 아래 파생 목차 갱신의 조건
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
                from ..pages import add

                date = _today()
                provenance = " ".join(f"[[{s}]]" for s in op["sources"])
                body = (
                    f"{op['text']}\n\nsources: {provenance} (norn {date}, "
                    f"confidence: {op['confidence']}, grounding: {op.get('grounding', '?')})"
                )
                slug, _ = add(body, title=op["title"], kind="insight", links=",".join(op["sources"]), d=d)
                applied.append({**op, "slug": slug})
            elif op["op"] == "link":
                linked = _add_link(d, op["a"], op["b"]) or linked
                applied.append(op)
            else:  # contradiction — 보고 전용 (아무것도 안 고친다), 장부에만 접수한다
                applied.append(op)
        except ValueError as e:  # 예산 초과·경합 등 — 노른은 부분 실패를 정직하게 남긴다
            failed.append({**op, "error": str(e)})
    # link만 파생 목차를 안 고치고 있었다. 나머지 페이지 쓰기 경로(merge·archive·insight)는
    # 자기 안에서 이미 `write_index`를 부르므로 여기서 또 부를 이유가 없다 — link이 실제로
    # 무엇인가를 고쳤을 때만 한 번 부른다. 갱신 대상은 index.md 뿐이 아니다: maps/ 는 각
    # 페이지의 links를 그대로 적는 목차라(`vault._rows`) link op 직후 곧바로 낡는다.
    if linked:
        with contextlib.suppress(Exception), _lock(d):  # 파생 목차 실패가 손질 결과를 무르지 않는다
            write_index(d)
    # 모순은 리포트 파일 하나로 끝나면 안 된다 — 런마다 새로 생기는 파일에 흩어지면 같은
    # 어긋남이 열 번 뜨고 사람이 이미 판단한 것도 매번 다시 뜬다 (`memory.contradiction`).
    # 여기서도 해소는 없다: 장부에 접수만 하고 페이지는 손대지 않는다.
    ledger = {
        row["key"]: row for row in record_contradictions([op for op in applied if op["op"] == "contradiction"], d)
    }
    state = _load_state(d)
    state.update({"last_norn": _today(), "log_lines": _log_lines(d)})
    _save_state(d, state)
    log_op(d, "norn", "-", f"applied={len(applied)} failed={len(failed)} dropped={len(plan.get('dropped') or [])}")
    report = _write_report(d, plan, applied, failed, backup, ledger)
    return {
        "applied": applied,
        "failed": failed,
        "backup": backup,
        "report": report,
        "contradictions": list(ledger.values()),
    }


def _write_report(
    d: str, plan: dict, applied: list[dict], failed: list[dict], backup: str, ledger: dict[str, dict] | None = None
) -> str:
    """노른 리포트 — reports/ 는 pages/ 밖 (인덱스 예산 무관). Obsidian vault에서 바로 읽힌다."""
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
            lines.append(
                f"- insight: [[{op.get('slug', '')}]] ({op['confidence']}, "
                f"grounding {op.get('grounding', '?')}) ← {srcs}"
            )
        else:
            # 처음 보는 것과 또 보는 것을 가려 쓴다 — 같은 경고가 매번 같은 얼굴로 뜨면
            # 사람은 그 줄을 안 읽게 된다. 장부가 신원을 쥐고 있어 여기선 표시만 한다.
            entry = (ledger or {}).get(contradiction_key(op["a"], op["b"])) or {}
            seen = "" if entry.get("new", True) else f" · {entry.get('count', 2)}번째 감지"
            if entry.get("status") == ACKNOWLEDGED:
                seen += " · 이미 본 것"
            lines.append(f"- ⚠ contradiction: [[{op['a']}]] ↔ [[{op['b']}]] — {op['why']} (사람이 해소){seen}")
    for op in failed:
        lines.append(f"- ✗ {op['op']} 실패 — {op.get('error', '')}")
    for op in plan.get("proposed") or []:  # 자율 런의 잔류 제안 — 백그라운드 결과도 흔적을 남긴다
        if op["op"] == "insight":  # 사람에게 넘어온 통찰 — 판단할 재료를 같이 적는다
            target = f"{op.get('title', '')} (grounding {op.get('grounding', '?')})"
            if flag := op.get("polarity_conflict"):
                target += f" ⚠ 극성 충돌 [{flag}] — 출처와 대조할 것"
        else:
            target = op.get("slug") or f"{op.get('src', '')} → {op.get('dst', '')}"
        lines.append(f"- (제안) {op['op']}: {target} — 검토: asgard memory norn")
    for row in plan.get("dropped") or []:
        lines.append(f"- (기각) {row['op'].get('op', '?')} — {row['reason']}")
    if backup:
        lines.append(f"\n백업: {os.path.relpath(backup, d)}")
    path = os.path.join(rdir, f"norn-{ts}.md")
    _atomic_write(path, "\n".join(lines) + "\n")
    return path
