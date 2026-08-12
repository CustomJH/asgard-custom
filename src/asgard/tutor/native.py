"""네이티브 루프 도달 경로 — 턴 끝에 실을 카드 한 장과, 그 카드가 무엇을 요구하는가(모드).

외부 클라이언트는 Stop 훅이 카드를 만들고, 네이티브 루프에는 훅이 없어서 이 자리가 대신
선다. 판정기는 아래층 하나뿐이므로 두 경로가 다른 답을 낼 수는 없고, 다른 것은 화면 형식뿐이다.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import time

from .. import tutor_growth
from ..health import _read
from ..io_files import read_json, write_json
from ..tutor_model import Checkpoint, Lesson
from .diffs import _at_base
from .labels import _folded_line, _point_label
from .lesson import review
from .pacing import hand_back

# 늦게 읽는 엔진은 이 패키지 밖, 한 단 위(`asgard`)에 있다 — `tutor` 가 패키지가 되면서
# `__package__` 가 `asgard.tutor` 로 한 단 깊어졌다. 기준을 `__name__` 으로 잡는 이유는
# `__package__` 가 `str | None` 이라 타입 검사기가 `.rsplit` 을 거절하기 때문이다.
_ENGINES = __name__.rsplit(".", 2)[0]

MODES = ("explain", "quiz")
DEFAULT_MODE = "explain"


def mode(root: str = "", flag: str = "") -> str:
    """되짚기가 사람에게 무엇을 요구하는가 — 플래그 > env > 프로젝트 설정 > 글로벌 설정 > explain.

    두 모드뿐이다. `quiz` 는 지금까지의 동작 그대로 — 물음을 놓고 `--answer` 왕복을 기다린다.
    `explain` 은 같은 판정을 **요구 없이** 놓는다: 무엇이 바뀌었나, 어떤 순서로 읽나, 무엇을
    맞추려던 변경이었나, 무엇으로 확인했나. 짚을 자리는 그대로 실리되 물음이 아니라 사실로 실려서,
    읽고 지나가면 그걸로 끝난다.

    기본을 `explain` 으로 둔 것은 오딘의 결정이다 (26-08-07). 근거는 저자가 바뀌었다는 것이다 —
    이 층의 물음은 **자기가 쓴 코드**를 되짚는 사람을 전제로 설계됐는데, 실제로 코드를 쓴 쪽은
    에이전트다. 그 자리에서 물음은 되짚기가 아니라 남이 쓴 코드에 대한 시험이 되고, 매 턴 답을
    따로 적어야 하는 숙제가 된다. 세 번째 모드는 안 만든다 — 지금 동작이 곧 `quiz` 다.
    """
    picked = _mode(flag) or _mode(os.environ.get("ASGARD_TUTOR_MODE"))
    if picked:
        return picked
    try:
        from ..settings import load_global, load_project

        for cfg in (load_project(root or os.getcwd()), load_global()):  # 프로젝트가 글로벌을 우선한다
            picked = _mode((cfg.get("tutor") or {}).get("mode"))
            if picked:
                return picked
    except Exception:
        pass  # 없거나 깨진 설정 = 이 계층 침묵 (fail-open, lagom.default_mode 와 같은 규약)
    return DEFAULT_MODE


def _mode(value: object) -> str:
    body = str(value or "").strip().lower()
    return body if body in MODES else ""


def turn_note(root: str, sid: object, limit: int = 1) -> str:
    """네이티브 턴 끝에 실을 되짚기 카드. 없으면 빈 문자열 (토큰 회귀 없음).

    외부 클라이언트는 Stop 훅이 이 일을 한다. 네이티브 루프에는 훅이 없어서 — 단일 프로세스라
    끼어들 자리가 없다 — 도달 경로를 여기 하나 더 둔다. 판정기는 하나이므로 두 경로가 다른
    답을 낼 수는 없고, 다른 것은 화면 형식뿐이다.
    """
    key = str(sid or "").strip()
    paths = _session_writes(root, key)
    if not paths:
        return ""
    quiz = mode(root) == "quiz"
    lesson = review(root, "HEAD", paths)
    points = lesson.ranked
    rows, back = hand_back(root, points, limit, count=quiz)
    shown_rows = _shown_rows(rows, limit)
    told = _explained(root, paths, limit, quiz=quiz and not bool(shown_rows or back))
    why = _rationale_lines(root, paths, quiz)
    if not points and not back and not told and not why:
        return ""  # 물을 것도 설명할 것도 없으면 침묵한다 — 빈 카드는 다음 카드의 신뢰를 깎는다
    shown_points = tuple(point for point, _ in shown_rows)
    if _repeat(root, key, shown_points, back, "\n".join([told, *why])):
        return ""
    return _card(lesson, shown_rows, back, limit, told, why, quiz)


def _rationale_lines(root: str, paths: list[str], quiz: bool) -> list[str]:
    """ "왜 이렇게 했는가" 절. `quiz` 모드에서는 안 그린다 — 그쪽 계약은 이 칸을 빈칸으로 둔다.

    엔진이 없거나 기록을 못 읽으면 빈 목록이고, 그러면 카드는 종전대로 사실과 물음만 낸다.
    """
    if quiz:
        return []
    try:
        module = importlib.import_module(f"{_ENGINES}.tutor_rationale")
        return module.lines(module.rationale(root, paths))
    except Exception:
        return []


def _explained(root: str, paths: list[str], limit: int, quiz: bool = True) -> str:
    """이번 변경의 설명 절. 엔진이 없으면 빈 문자열 — 그러면 카드는 물음만 낸다.

    늦게 읽는 이유는 `_debt_ledger`와 같다: 같은 시각에 만드는 모듈이 없어도 되짚기 시작은
    깨지면 안 된다. 문장은 엔진의 `card`가 그대로 만든다 — 여기서 다시 조립하면 화면이 두 벌이
    되고, 두 벌은 반드시 갈라진다(훅 `_card`와 같은 계약).

    카드가 실제로 그린 말은 그 자리에서 용어집에 적립한다. 이 경로에만 사는 세션(네이티브 루프)은
    `asgard tutor`를 안 거치므로, 여기서 안 적으면 용어집이 영영 안 쌓이고 설명은 회차마다 같은
    길이로 나온다. 적립 목록을 `shown_terms`에서 받는 이유는 하나다 — 카드가 상한에서 자른 말까지
    적으면 사람이 못 본 말이 "이미 설명한 말"이 된다.
    """
    try:
        module = importlib.import_module(f"{_ENGINES}.tutor_teach")
        exp = module.explain(root, "HEAD", paths)
        told = str(module.card(exp, limit, quiz=quiz) or "").strip()
    except Exception:
        return ""
    try:
        if told:
            module.glossary_merge(root, module.shown_terms(exp, limit))
    except Exception:
        pass  # 적립 실패가 카드를 지우지는 않는다 — 그 말은 다음 회차에 한 번 더 설명된다
    return told


def _shown_rows(rows: list[tuple[Checkpoint, str]], limit: int) -> list[tuple[Checkpoint, str]]:
    """한 카드에서 실제로 묻는 후보. 원시 후보 목록과 사람 앞의 질문 목록을 갈라 둔다."""
    return [row for row in rows if row[1] not in ("fold", "quiet")][: max(0, limit)]


def _session_writes(root: str, sid: str) -> list[str]:
    """이 세션이 쓴 경로 (write sentinel). 사용자가 원래 갖고 있던 dirt는 이 턴의 물음이 아니다."""
    if not sid:
        return []
    rows = read_json(os.path.join(root, ".asgard", "state", f"writes-{sid}.json"), [])
    if not isinstance(rows, list):
        return []
    # 한 턴 안에서 만들었다가 지운 scratch 파일은 현재에도 HEAD에도 없다. 그런 경로를
    # "읽지 못했다"고 되묻는 것은 순변화가 0인 작업을 부채로 만드는 일이다.
    return [rel for row in rows if (rel := _session_rel(root, row))]


def _session_rel(root: str, raw: object) -> str:
    root_abs = os.path.abspath(root)
    root_real = os.path.realpath(root_abs)
    value = str(raw or "").strip()
    if not value:
        return ""
    absolute = os.path.abspath(value if os.path.isabs(value) else os.path.join(root_abs, value))
    try:
        if os.path.commonpath((root_abs, absolute)) != root_abs:
            return ""
        if os.path.exists(absolute) and os.path.commonpath((root_real, os.path.realpath(absolute))) != root_real:
            return ""
    except ValueError:
        return ""
    rel = os.path.relpath(absolute, root_abs).replace(os.sep, "/")
    return rel if _read(root, rel) is not None or _at_base(root, rel, "HEAD") is not None else ""


def _repeat(
    root: str, sid: str, points: tuple[Checkpoint, ...], back: list[tutor_growth.Revisit], told: str = ""
) -> bool:
    """같은 물음을 매 턴 다시 놓으면 세 번째부터 아무도 안 읽는다 — 지문이 같으면 침묵."""
    path = os.path.join(root, ".asgard", "state", f"tutor-{sid}.json")
    sig = _fingerprint(points, back, told)
    seen = (read_json(path, {}) or {}).get("signature")
    try:
        write_json(path, {"signature": sig})
    except OSError:
        pass  # 못 적었으면 다음 턴에 같은 카드가 한 번 더 나온다 — 중복이 침묵보다 낫다
    return seen == sig


def _fingerprint(points: tuple[Checkpoint, ...], back: list[tutor_growth.Revisit], told: str = "") -> str:
    """카드에 실릴 것 전부의 지문. 재방문도 설명 절도 여기 들어간다 — 안 넣으면 이번 턴에 처음
    돌아온 옛 물음이나 새로 바뀐 설명이 "직전 턴과 같은 카드"로 판정돼 통째로 사라진다(래치가
    자기 성장 경로를 막는다)."""
    rows = [f"{p.kind}|{p.path}|{p.unit}" for p in points] + [f"revisit|{r.cid}|{r.asks}" for r in back]
    if told:
        rows.append("explain|" + hashlib.sha256(told.encode("utf-8")).hexdigest()[:16])
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()[:16]


def _card(
    lesson: Lesson,
    rows: list[tuple[Checkpoint, str]],
    back: list[tutor_growth.Revisit],
    limit: int,
    told: str = "",
    why: list[str] | None = None,
    quiz: bool = True,
) -> str:
    added, removed = lesson.touched
    head = f"⠶ 되짚기 — 이번 턴 {len(lesson.files)}개 파일 · +{added:,}/-{removed:,}행이에요."
    lines = [head + (" 아래는 **기계가 못 답하는** 것들이에요." if quiz else ""), ""]
    # 설명이 물음보다 위에 온다. 전달된 적 없는 것을 인출부터 시키면 물음은 답이 아니라 침묵을
    # 받는다 — 설명 절은 물음에 답하지 않고 그 물음이 서 있는 자리만 준다.
    if told:
        lines.append(told)
        lines.append("")
    if why:
        lines += [*why, ""]
    if lesson.moved:
        lines.append(f"  구조 이동 — 같은 본문으로 확인된 {lesson.moved}개 단위는 삭제 질문에서 뺐어요.")
    lines += _card_points(rows, limit, quiz)
    if quiz:
        lines += _card_back(back)
        lines += [
            "",
            '  답은 `asgard tutor --answer <표식> "..."` · 오탐이면 `asgard tutor --dismiss <표식>`'
            " · 전체와 '왜 이렇게 했는가' 빈칸은 `asgard tutor --report`",
        ]
    else:
        # 안내는 남기되 요구는 없앤다 — 이 줄은 더 볼 곳을 가리키지, 답을 기다리지 않는다.
        lines += ["", "  전체는 `asgard tutor --report` · 물음 형식으로 되돌리려면 `asgard tutor --quiz`"]
    return "\n".join(lines)


def _card_points(rows: list[tuple[Checkpoint, str]], limit: int, quiz: bool = True) -> list[str]:
    """펼친 것 · 접은 것 · 넘친 것. 셋을 같은 화면에 두는 것이 이 카드의 정직성이다.

    `explain` 모드에서는 물음(`ask`) 대신 사실(`what`)을 넣는다. 같은 판정을 같은 자리에 놓되
    답을 요구하지 않는 것이 이 모드의 전부다 — 짚을 자리를 빼 버리면 되짚기가 아니라 요약이 된다.
    """
    lines: list[str] = []
    folded: dict[str, int] = {}
    quiet: dict[str, int] = {}
    shown = 0
    for point, form in rows:
        if form in ("fold", "quiet"):
            bucket = folded if form == "fold" else quiet
            bucket[point.kind] = bucket.get(point.kind, 0) + 1
            continue
        if shown >= limit:
            continue
        mark = f"  [{point.cid}]" if quiz else ""
        lines.append(f"  {_point_label(point)} — {point.where}{mark}")
        lines.append(f"    {'▸ ' + point.ask if quiz else point.what}")
        shown += 1
    over = sum(1 for _, form in rows if form not in ("fold", "quiet")) - shown
    if over > 0:
        lines.append("  나머지 후보는 이번 회차에 묻지 않아요." if quiz else "  나머지 후보는 보고서에 있어요.")
    if folded:
        lines.append(f"  {_folded_line(folded)} — 이미 답해 오신 종류라 접었어요")
    if quiet:
        lines.append(f"  {_folded_line(quiet)} — 계속 못 닿아서 접었어요 (`asgard tutor --progress`)")
    return lines


def _card_back(back: list[tutor_growth.Revisit]) -> list[str]:
    """되돌아온 물음. 답을 받은 적이 없다는 사실을 숨기지 않고 각도만 바꿔서 다시 놓는다."""
    now = time.time()
    lines: list[str] = []
    for row in back:
        days = row.days(now)
        when = f"{days}일 전에 물었고" if days else "오늘 물었고"
        lines.append(f"  ↩ 다시 — {row.where}  [{row.cid}]  ({when} 아직 답이 없어요)")
        lines.append(f"    ▸ {row.ask}")
    return lines
