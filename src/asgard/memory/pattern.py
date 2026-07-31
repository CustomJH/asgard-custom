"""패턴 학습 — 대화 원문에서 오딘에 대한 관측(observation)을 뽑아 개인 위키로 승격한다.

상류 개념은 Honcho의 deriver 다: peer의 메시지에서 **explicit**(직접 진술에서 바로
따라나오는 원자 사실)과 **deductive**(그 위의 추론)를 나눠 뽑고, 각 관측은 홀로 읽어도
말이 되게 자립시킨다. Asgard로 옮기면서 바꾼 것은 신뢰의 위치다 — 상류는 LLM 산출을
그대로 저장하지만, 여기서는 노른과 같은 규율을 쓴다: **LLM은 제안하고, 코드가 판정한다**.

판정의 핵심은 근거 접지(grounding)다. explicit 주장은 인용한 턴 안에 실제로 그 낱말이
있어야 한다 — 모델이 "오딘은 Rust를 좋아한다"고 말해도 그 턴에 Rust가 없으면 기각한다.
이 검사 하나가 개인 기억에 허구가 눌러앉는 경로를 막는다. deductive는 접지 대신 근거 턴
2개 이상을 요구하고 confidence를 낮춰 잡는다 (근거 수가 confidence를 정한다 — 노른과 동일).

peer card는 상류의 같은 이름 개념이다: 확신 높은 explicit 관측만 모은 짧은 정체성 요약
페이지 하나. 주입면이 좁으므로 이게 실제로 매 세션 오딘을 설명하는 문장이 된다.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import os
import re

from .norn import _FORBIDDEN_INSIGHT, _confidence
from .pages import add, lint
from .policy import scan_secrets, scan_threats
from .recall import _containment, _content_words, _jaccard, _neutralize, _stem_hit, _stopword
from .store import _atomic_write, _pages, _read, _today, ensure_home, log_op, poisoned, render_page

STATE_FILE = "pattern-state.json"
REPORTS_DIR = "reports"
PEER_CARD_SLUG = "odin-peer-card"

MAX_TURNS = 40  # 한 패스가 보는 최근 턴 상한 — 프롬프트 예산과 접지 검사 비용의 균형
MAX_TURN_CHARS = 700  # 턴 하나당 발췌 상한
MIN_TURNS = 3  # 이보다 적으면 패턴이라 부를 수 없다
MAX_EXPLICIT, MAX_DEDUCTIVE = 5, 3  # 한 패스 승격 상한 (노른 캡과 같은 취지)
OBSERVATION_MIN_CHARS, OBSERVATION_MAX_CHARS = 12, 400
GROUNDING_FLOOR = 0.34  # explicit 주장의 내용어가 인용 턴에 남아 있어야 하는 최소 비율
DUP_FLOOR = 0.55  # 기존 페이지와 이만큼 겹치면 새 관측이 아니다
TURNS_THRESHOLD = 20  # 마지막 패스 이후 누적 턴 문턱 (config [memory].pattern_turns_threshold)
MIN_INTERVAL_DAYS = 1
EVIDENCE_CHARS = 400  # 되묻기에 싣는 관측 본문 상한 (제목 포함)
TURN_EVIDENCE_CHARS = 200  # 턴 근거는 요청/응답 두 쪽이라 절반씩

# 관측이 될 수 없는 것: 한 번의 사정(환경 실패·도구 불평)은 사람에 대한 사실이 아니다.
# 노른의 금지 캡처를 그대로 쓴다 — 같은 자기중독을 막는 같은 규칙이다.
_FORBIDDEN_OBSERVATION = _FORBIDDEN_INSIGHT

# 주어가 오딘(사용자)이어야 관측이다. "이 저장소는 uv를 쓴다"는 프로젝트 사실이지 사람 사실이
# 아니다 — 그건 2차 메모리 몫이고, 여기 들어오면 개인 위키가 프로젝트 노트로 변질된다.
# 한국어는 조사가 주어에 붙는다 ("오딘은"). \b는 한글끼리 붙은 자리에서 경계를 못 잡으므로
# 조사 자리를 명시적으로 열어두고, 그 뒤가 공백·구두점일 때만 주어로 인정한다.
_SUBJECT = re.compile(
    r"^\s*(?:(?:오딘|사용자|유저)[가-힣]{0,3}(?=[\s,.:]|$)|(?:the\s+user|user|odin)\b)",
    re.IGNORECASE,
)

_PATTERN_SYS = """You extract atomic observations about one person from their own messages.

The target peer is "오딘" (Odin) — the human operating this agent. Their messages are the
`request` field of each turn; the agent's replies are context only.

Produce two kinds of observation:
- explicit — a fact that follows directly from what Odin wrote. Every content word you use
  must appear in the cited turn. No inference.
- deductive — an inference across two or more turns (a habit, a preference, a way of working).

Rules:
- Each observation is one self-contained sentence that starts with the subject "오딘".
- Write it so it still makes sense a year from now: absolute dates, named tools, no "yesterday".
- Cite the turn numbers you used in `evidence` (integers from the input).
- Prefer durable traits over one-off events. Skip anything about a broken tool, a missing
  credential, a rate limit, or any other momentary environment problem.
- Skip facts about the repository or the code — those belong to project memory, not to Odin.
- Say nothing you cannot ground in the turns. Fewer, sturdier observations beat many guesses.

Return JSON only:
{"observations": [{"kind": "explicit|deductive", "text": "...", "evidence": [1, 4], "why": "..."}]}
"""


def _settings_int(key: str, default: int) -> int:
    from .policy import _memory_settings

    try:
        value = _memory_settings().get(key)
        return max(1, int(value)) if value is not None else default
    except TypeError, ValueError:
        return default


# ── 상태 ──────────────────────────────────────────────────────────────────────


def _state_path(d: str) -> str:
    return os.path.join(d, STATE_FILE)


def _load_state(d: str) -> dict:
    try:
        with open(_state_path(d), encoding="utf-8") as handle:
            loaded = json.load(handle)
        return loaded if isinstance(loaded, dict) else {}
    except OSError, ValueError:
        return {}


def _save_state(d: str, state: dict) -> None:
    _atomic_write(_state_path(d), json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def pattern_due(root: str, d: str | None = None) -> tuple[bool, str]:
    """다음 패스 자격 — (due, 사유). 턴 누적 문턱 + 최소 간격."""
    d = ensure_home(d)
    state = _load_state(d)
    seen = int(state.get("turns_seen") or 0)
    total = _turn_count(root)
    threshold = _settings_int("pattern_turns_threshold", TURNS_THRESHOLD)
    if total - seen < threshold:
        return False, f"turns since last pass: {total - seen} < {threshold}"
    last = str(state.get("last_pattern") or "")
    if last:
        with contextlib.suppress(ValueError):
            days = (_dt.date.today() - _dt.date.fromisoformat(last)).days
            interval = _settings_int("pattern_min_interval_days", MIN_INTERVAL_DAYS)
            if days < interval:
                return False, f"last pass {days}d ago (min {interval}d)"
    return True, f"{total - seen} new turn(s)"


def nudge_line(root: str, d: str | None = None) -> str | None:
    """패턴 패스가 due 이고 같은 누적 상태로 아직 말하지 않았을 때만 한 줄. 그 외 None.

    latch가 없으면 문턱을 넘긴 뒤 매 턴 같은 말을 반복한다 — 넛지는 한 번이어야 신호다."""
    d = ensure_home(d)
    due, reason = pattern_due(root, d)
    if not due:
        return None
    state = _load_state(d)
    digest = hashlib.sha1(f"{_turn_count(root)}".encode()).hexdigest()[:12]
    if state.get("nudge_digest") == digest:
        return None
    state["nudge_digest"] = digest
    _save_state(d, state)
    return f"패턴 학습 대기 — {reason}. asgard memory pattern으로 관측 검토 (--apply 전엔 무변경)"


# ── 신호 수집 (결정론) ─────────────────────────────────────────────────────────


def _turn_count(root: str) -> int:
    from ..agent.turn_store import store_path

    try:
        with open(store_path(root), "rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def recent_turns(root: str, limit: int = MAX_TURNS) -> list[dict]:
    """최근 턴 원문 — [{seq, ts, quest, request, response}]. 없으면 빈 리스트 (fail-open)."""
    from ..agent.turn_store import store_path

    rows: list[dict] = []
    try:
        with open(store_path(root), encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return []
    start = max(0, len(lines) - limit)
    for offset, line in enumerate(lines[start:], start=start + 1):
        try:
            payload = json.loads(line)
        except ValueError:
            continue  # 손상 라인 — seq는 라인 위치라 계속 전진한다
        request = str(payload.get("request") or "").strip()
        if not request:
            continue
        rows.append(
            {
                "seq": offset,
                "ts": float(payload.get("ts") or 0.0),
                "quest": str(payload.get("quest") or ""),
                "request": request[:MAX_TURN_CHARS],
                "response": str(payload.get("response") or "")[:MAX_TURN_CHARS],
            }
        )
    return rows


def signals(root: str, d: str | None = None) -> dict:
    """LLM에게 보여줄 증거 카드 — 최근 턴과 이미 아는 것. 쓰기 없음."""
    d = ensure_home(d)
    known: list[str] = []
    for slug in _pages(d):
        page = _read(d, slug)
        if not page or poisoned(*page):
            continue
        meta, body = page
        if meta.get("kind") in ("user", "insight"):
            first = next((line.strip() for line in body.splitlines() if line.strip()), "")
            known.append(first[:160])
    return {"turns": recent_turns(root), "known": known[:40]}


# ── 계획 (LLM 제안 → 결정적 검증) ──────────────────────────────────────────────


def _grounded(text: str, turns: list[dict]) -> float:
    """주장의 내용어 중 인용 턴에 실제로 있는 비율. 접지 없는 explicit은 허구다.

    낱말 대조는 집합 교집합이 아니라 어간 일치다 (`_stem_hit`). 한국어는 조사·어미가 뒤에
    붙어서 교집합으로 재면 **완벽히 접지된 관측이 0.000이 나온다** — "금요일에 배포하지
    않는다"와 "금요일에는 배포를 안 하는 게"가 한 낱말도 안 겹친다. 실측(26-07-28,
    한국어 4·영어 1): 접지된 관측 5건 중 3건이 플로어 미달로 오탈락했고, 어간 일치로
    바꾸니 5/5 통과했다. 허구 5건은 두 방식 모두 통과 0 (교집합 0.000, 어간 최대
    0.167)이라 판별력은 오히려 벌어진다 — 플로어를 낮춘 게 아니라 자를 고친 것이다."""
    claim = {word for word in _content_words(text) if not _stopword(word)}
    if not claim:
        return 0.0
    haystack = " ".join(f"{turn['request']} {turn['response']}" for turn in turns).lower()
    return sum(1 for word in claim if _stem_hit(word, haystack)) / len(claim)


def _parse_observations(raw: str) -> list[dict]:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("pattern: LLM output is not JSON")
    payload = json.loads(raw[start : end + 1])
    rows = payload.get("observations") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("pattern: LLM output has no observations list")
    return [row for row in rows if isinstance(row, dict)]


def _existing_texts(d: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for slug in _pages(d):
        page = _read(d, slug)
        if page and not poisoned(*page):
            out.append((slug, page[1]))
    return out


def validate_observations(rows: list[dict], turns: list[dict], d: str) -> tuple[list[dict], list[dict]]:
    """결정적 검증 — 통과한 관측과 (관측, 기각 사유). LLM 주장은 검증 입력일 뿐이다."""
    by_seq = {int(turn["seq"]): turn for turn in turns}
    existing = _existing_texts(d)
    accepted: list[dict] = []
    dropped: list[dict] = []
    counts = {"explicit": 0, "deductive": 0}
    caps = {"explicit": MAX_EXPLICIT, "deductive": MAX_DEDUCTIVE}
    seen_texts: list[str] = []

    def _drop(row: dict, reason: str) -> None:
        dropped.append({"observation": row, "reason": reason})

    for row in rows:
        kind = str(row.get("kind") or "").strip().lower()
        if kind not in caps:
            _drop(row, f"unknown kind: {kind!r}")
            continue
        if counts[kind] >= caps[kind]:
            _drop(row, f"{kind} cap reached ({caps[kind]})")
            continue
        text = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
        if not OBSERVATION_MIN_CHARS <= len(text) <= OBSERVATION_MAX_CHARS:
            _drop(row, f"text length {len(text)} outside [{OBSERVATION_MIN_CHARS}, {OBSERVATION_MAX_CHARS}]")
            continue
        if not _SUBJECT.match(text):
            _drop(row, "subject is not Odin — project facts belong to project memory")
            continue
        if _FORBIDDEN_OBSERVATION.search(text):
            _drop(row, "forbidden capture (momentary environment problem or tool negativity)")
            continue
        threat = scan_threats(text) or scan_secrets(text)
        if threat:
            _drop(row, f"scan: {threat}")
            continue
        evidence: list[int] = []
        for value in row.get("evidence") or []:
            with contextlib.suppress(TypeError, ValueError):
                seq = int(value)
                if seq in by_seq and seq not in evidence:
                    evidence.append(seq)
        if not evidence:
            _drop(row, "no evidence turn from the input")
            continue
        if kind == "deductive" and len(evidence) < 2:
            _drop(row, "deductive needs at least two evidence turns")
            continue
        cited = [by_seq[seq] for seq in evidence]
        if kind == "explicit":
            score = _grounded(text, cited)
            if score < GROUNDING_FLOOR:
                _drop(row, f"not grounded in the cited turns ({score:.2f} < {GROUNDING_FLOOR})")
                continue
        else:
            score = _grounded(text, cited)
        duplicate = next(
            (
                slug
                for slug, body in existing
                if _jaccard(text, body) >= DUP_FLOOR or _containment(text, body) >= DUP_FLOOR
            ),
            "",
        )
        if duplicate:
            _drop(row, f"already known — overlaps [[{duplicate}]]")
            continue
        if any(_jaccard(text, other) >= DUP_FLOOR for other in seen_texts):
            _drop(row, "duplicate of another observation in this pass")
            continue
        seen_texts.append(text)
        counts[kind] += 1
        accepted.append(
            {
                "kind": kind,
                "text": text,
                "evidence": evidence,
                "grounding": round(score, 3),
                # confidence는 LLM 자기 신고가 아니라 근거 수가 정한다. deductive는 한 단계 낮춘다.
                "confidence": _confidence(len(evidence) + (0 if kind == "deductive" else 1)),
                "why": str(row.get("why", ""))[:200],
            }
        )
    return accepted, dropped


def _complete(root: str, system: str, user: str) -> str:
    """LLM 단발 호출 간접점 — 테스트가 이 지점만 대체한다."""
    from .manager import complete

    return complete(root, system, user, max_tokens=2500)


def plan_pattern(root: str, d: str | None = None) -> dict:
    """턴 수집 → LLM 제안 → 결정적 검증. 반환 = {"observations", "dropped", "turns"}. 쓰기 없음."""
    d = ensure_home(d)
    sig = signals(root, d)
    turns = sig["turns"]
    if len(turns) < MIN_TURNS:
        return {"observations": [], "dropped": [], "turns": turns, "reason": f"only {len(turns)} turn(s)"}
    user = json.dumps(
        {
            "turns": [{"turn": turn["seq"], "odin": turn["request"], "agent": turn["response"]} for turn in turns],
            "already_known": sig["known"],
        },
        ensure_ascii=False,
    )
    raw = _complete(root, _PATTERN_SYS, user)
    accepted, dropped = validate_observations(_parse_observations(raw), turns, d)
    return {"observations": accepted, "dropped": dropped, "turns": turns}


# ── 적용 (결정론) ─────────────────────────────────────────────────────────────


def _title_for(text: str) -> str:
    """관측 제목 — 첫 절을 짧게. 슬러그 충돌은 _fresh_slug가 푼다."""
    head = re.split(r"[.·—–]|(?:다|요)\s*$", text.strip())[0].strip()
    return (head or text)[:60]


def apply_pattern(root: str, plan: dict, d: str | None = None) -> dict:
    """검증 통과 관측만 페이지로 승격한다. 반환 = {"applied", "failed", "report", "peer_card"}."""
    d = ensure_home(d)
    applied: list[dict] = []
    failed: list[dict] = []
    for observation in plan.get("observations") or []:
        try:
            kind = "user" if observation["kind"] == "explicit" else "insight"
            evidence = ", ".join(f"turn {seq}" for seq in observation["evidence"])
            body = (
                f"{observation['text']}\n\n"
                f"pattern: {observation['kind']} · confidence: {observation['confidence']} · "
                f"grounding: {observation['grounding']} · evidence: {evidence} ({_today()})"
            )
            slug, _ = add(body, title=_title_for(observation["text"]), kind=kind, d=d)
            applied.append({**observation, "slug": slug})
        except ValueError as exc:  # 예산 초과·경합 — 부분 실패를 정직하게 남긴다
            failed.append({**observation, "error": str(exc)})
    card = write_peer_card(d) if applied else ""
    state = _load_state(d)
    state.update({"last_pattern": _today(), "turns_seen": _turn_count(root)})
    _save_state(d, state)
    log_op(d, "pattern", "-", f"applied={len(applied)} failed={len(failed)} dropped={len(plan.get('dropped') or [])}")
    report = _write_report(d, plan, applied, failed)
    return {"applied": applied, "failed": failed, "report": report, "peer_card": card}


def peer_card_rows(d: str) -> list[tuple[str, str]]:
    """peer card 재료 — kind=user 페이지의 첫 문장. (slug, 문장) 정렬 목록."""
    rows: list[tuple[str, str]] = []
    for slug in _pages(d):
        if slug == PEER_CARD_SLUG:
            continue
        page = _read(d, slug)
        if not page or poisoned(*page):
            continue
        meta, body = page
        if meta.get("kind") != "user":
            continue
        first = next((line.strip() for line in body.splitlines() if line.strip()), "")
        if first:
            rows.append((slug, first[:200]))
    return sorted(rows)


def write_peer_card(d: str | None = None) -> str:
    """오딘 요약 카드 한 장 — kind=user 관측을 모아 재생성한다 (파생물, 언제든 다시 만든다).

    reports/ 가 아니라 pages/ 에 산다: 회상·주입 경로가 이 문장들을 실제로 써야 하기 때문이다.
    대신 예산을 위해 짧게 유지하고, 근거는 [[slug]]로 가리킨다."""
    d = ensure_home(d)
    rows = peer_card_rows(d)
    if not rows:
        return ""
    lines = [f"- {text} [[{slug}]]" for slug, text in rows[:20]]
    body = "오딘에 대해 지금까지 관측된 것들 — 근거 페이지로 이어진다.\n\n" + "\n".join(lines)
    meta = {
        "title": "오딘 — peer card",
        "kind": "user",
        "created": _today(),
        "updated": _today(),
        "description": "패턴 학습이 모은 오딘 요약 (파생 — pages/ 의 kind=user에서 재생성)",
    }
    from .index import reindex
    from .store import _lock, _page_path

    with _lock(d):
        existing = _read(d, PEER_CARD_SLUG)
        if existing:
            meta["created"] = existing[0].get("created", meta["created"])
        _atomic_write(_page_path(d, PEER_CARD_SLUG), render_page(meta, body))
    reindex(d)
    log_op(d, "pattern:card", PEER_CARD_SLUG, f"{len(rows)} observation(s)")
    return PEER_CARD_SLUG


def _write_report(d: str, plan: dict, applied: list[dict], failed: list[dict]) -> str:
    """패턴 리포트 — reports/ 는 pages/ 밖 (인덱스 예산 무관). vault에서 바로 읽힌다."""
    rdir = os.path.join(d, REPORTS_DIR)
    os.makedirs(rdir, exist_ok=True)
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d-%H%M")
    lines = [f"# Pattern {stamp}", "", f"turns considered: {len(plan.get('turns') or [])}", ""]
    for row in applied:
        lines.append(
            f"- {row['kind']}: [[{row['slug']}]] ({row['confidence']}, grounding {row['grounding']}) "
            f"← {', '.join(f'turn {seq}' for seq in row['evidence'])}"
        )
    for row in failed:
        lines.append(f"- ✗ {row['kind']} 실패 — {row.get('error', '')}")
    for row in plan.get("dropped") or []:
        text = str(row["observation"].get("text", ""))[:80]
        lines.append(f"- (기각) {text} — {row['reason']}")
    path = os.path.join(rdir, f"pattern-{stamp}.md")
    _atomic_write(path, "\n".join(lines) + "\n")
    return path


# ── 되묻기 (dialectic) ────────────────────────────────────────────────────────

_ASK_SYS = """You answer questions about 오딘 (Odin) using only the evidence supplied below.

The evidence has three origins, and they do not carry the same weight:
- observations — durable facts already promoted into Odin's personal wiki
- episodes — raw excerpts from past conversations, unverified
- project — records from this project's shared memory, about the code, not about Odin

Answer in the same language as the question. Be direct and short. Cite the evidence you used
by its bracketed id. If the evidence does not answer the question, say so plainly and name
what would settle it — never fill the gap with a plausible guess."""


def gather_evidence(question: str, root: str, d: str | None = None, k: int = 5) -> dict:
    """되묻기 근거 수집 — 개인 관측 + 에피소드 + 프로젝트 메모리. 전부 fail-open.

    근거는 **본문**이어야 한다. 제목만 실어 보내면 모델은 답을 못 짓고, 못 지었다는 사실도
    드러나지 않는다 — 근거 칸이 비어 있지 않으니 모든 계기가 초록으로 보인다. 그리고 본문을
    싣는 순간 여기는 주입면이 되므로, 회수 블록과 같은 위생을 건다 (오염 페이지 제외 ·
    각괄호 무력화 · 한 줄로 접기)."""
    d = ensure_home(d)
    evidence: dict[str, list[dict]] = {"observations": [], "episodes": [], "project": []}

    def _clean(*parts: str) -> str:
        """근거 한 조각 — 경계 문자를 무력화하고 한 줄로 접는다. 줄바꿈을 그대로 실으면
        예산만 축내고, 근거 목록을 한 줄씩 읽는 CLI 표면에서는 행이 서로 섞인다."""
        return re.sub(r"\s+", " ", _neutralize(" ".join(parts))).strip()

    with contextlib.suppress(Exception):
        from .recall import query

        for hit in query(question, k=k, d=d):
            page = _read(d, hit["slug"])
            if page is None or poisoned(*page):
                continue
            title = str(hit.get("title") or hit["slug"])
            text = _clean(title, "—", page[1])[:EVIDENCE_CHARS]
            evidence["observations"].append({"id": f"obs:{hit['slug']}", "text": text})
    with contextlib.suppress(Exception):
        from ..agent.episodes import search

        for hit in search(root, question, k=k):
            request, excerpt = str(hit.get("request", "")), str(hit.get("excerpt", ""))
            if scan_threats(request, excerpt):
                continue  # 원문 유래 오염 구간 — 근거로도 안 싣는다
            head, tail = _clean(request)[:TURN_EVIDENCE_CHARS], _clean(excerpt)[:TURN_EVIDENCE_CHARS]
            evidence["episodes"].append({"id": f"turn:{hit['seq']}", "text": f"{head} → {tail}"})
    with contextlib.suppress(Exception):
        from ..memory_context import project_recall_note

        note = project_recall_note(question, start=root, max_results=k).strip()
        if note:
            evidence["project"] = [{"id": "project:recall", "text": note[:1200]}]
    return evidence


def ask(question: str, root: str, d: str | None = None, k: int = 5) -> dict:
    """오딘에 대한 자연어 질문에 근거 기반으로 답한다. 반환 = {"answer", "evidence", "used"}."""
    d = ensure_home(d)
    evidence = gather_evidence(question, root, d, k=k)
    total = sum(len(rows) for rows in evidence.values())
    if not total:
        return {"answer": "", "evidence": evidence, "used": 0, "reason": "no evidence"}
    user = json.dumps({"question": question, "evidence": evidence}, ensure_ascii=False)
    answer = _complete(root, _ASK_SYS, user).strip()
    return {"answer": answer, "evidence": evidence, "used": total}


def lint_note(d: str | None = None) -> list[dict]:
    """패턴이 만든 페이지에 대한 위생 판정 — 기존 lint를 그대로 쓴다 (별도 규칙 없음)."""
    return lint(ensure_home(d))


__all__ = [
    "PEER_CARD_SLUG",
    "apply_pattern",
    "ask",
    "gather_evidence",
    "pattern_due",
    "peer_card_rows",
    "plan_pattern",
    "recent_turns",
    "signals",
    "validate_observations",
    "write_peer_card",
]
