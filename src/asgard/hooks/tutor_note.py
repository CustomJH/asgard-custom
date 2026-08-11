#!/usr/bin/env python3
# Asgard tutor-note — 되짚기의 세 도달 시점. 인자 하나로 갈린다:
#   (기본)  Stop            — 이 턴이 쓴 코드를 물음으로 되돌린다
#   brief   UserPromptSubmit — 같은 자리를 다시 건드리기 **전에** 남은 물음을 꺼낸다
#   tip     PostToolUse      — 일하는 **도중** 한 번, 지금 서 있는 자리를 말해 준다
#
# 세 시점을 한 파일에 두는 이유: 판정기가 하나여야 세 화면이 어긋나지 않는다. 파일을 나누면
# 되짚기 규칙이 세 벌이 되고, 세 벌은 반드시 갈라진다(훅 계약).
#
# `tip`이 나중에 생긴 이유가 이 층의 실측이다. 앞의 둘은 턴의 **경계**에만 닿는다 — 시작과 끝.
# 그런데 사람이 실제로 받아 넘기는 자리는 그 사이다: 다섯 번째 변경에서, 검토가 얕아진 채로,
# 읽기 전에 닫는다. 경계에서만 말하는 층은 그 구간을 통째로 못 본다.
#
# 왜 훅인가: 되짚기는 모델이 기억해야 하는 일이 되면 안 된다. 캐논에 "마지막에 리뷰 자료를
# 주어라"를 한 줄 더 쓰는 방식은 이 저장소에서 이미 실패가 측정된 방법이다 — 제약을 얹을수록
# 그만큼 흘린다(2605.06445). 게다가 여기서 흘리면 아무도 모른다: 되짚기가 빠진 턴과 되짚을 것이
# 없던 턴은 화면에서 똑같이 생겼다. 그래서 세는 일은 기계가 하고, 모델의 주의력은 "왜 그렇게
# 했는가"에만 남긴다 — 그 칸은 기계가 못 채운다.
#
# 왜 **안 막는가**: 튜터는 규율이지 관문이 아니다. health와 같은 등급이다. 되짚기를 강제로
# 통과시키면 사람은 되짚기를 끄는 법을 먼저 배운다. 여기서 하는 일은 사용자에게 한 화면을
# 건네는 것뿐이고, 답할지 말지는 사용자가 정한다.
#
# 판정 대상은 **이 세션이 실제로 쓴 경로**다 (write_sentinel이 남긴 목록) — craft-gate와 같은
# 계약. 사용자가 원래 갖고 있던 dirt를 이 턴의 물음으로 돌려주면 그건 남의 빚을 묻는 것이다.
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence

# 발화 계측은 훅과 함께 깔리는 공용 라이브러리가 쥔다 — 이 훅은 자기 이름만 넘긴다.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.firing import run  # noqa: E402

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 산출이 통째로 증발한다. UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass

MAX_SHOWN = 1  # Stop은 하루치 리뷰가 아니라 한 턴의 속도 조절기다 — 한 번에 한 판단만 둔다
MAX_BACK = 1  # 이번 질문이 없을 때만 옛 물음 하나가 들어온다
# 설명 절은 물음과 다른 축이라 상한도 따로다. 물음은 사람에게 **일을 시키므로** 한 번에 하나가
# 맞지만, 설명은 시키는 것이 없어서 자리가 하나면 스물일곱 곳이 바뀐 턴에서도 한 곳만 보인다 —
# 그게 요약처럼 읽히던 이유다. 셋은 엔진 `tutor_teach.card` 의 기본값이고, 두 화면은 같아야 한다.
EXPLAIN_SHOWN = 3
# 파일을 바꾼 호출 몇 번마다 팁을 한 번 물어볼 것인가. 작게 잡으면 도구 호출마다 프로세스가
# 뜨고, 크게 잡으면 짧은 작업에서는 한 번도 안 닿는다. 여덟은 한 번의 작업 단위(파일 서넛을
# 오가며 고치는 구간)가 끝날 무렵 한 번 닿는 값이다.
TIP_EVERY = 8
REPORT_REL = os.path.join(".asgard", "tutor", "last-review.md")
_KIND = {
    "contract-break": "공개 계약 바뀜",
    "behavior-removed": "동작 사라짐",
    "test-removed": "판정 사라짐",
    "silent-failure": "조용히 삼킨 실패",
    "new-dependency": "외부 의존 늘어남",
    "untested-surface": "판정 없는 새 표면",
    "todo-left": "안 끝난 표식",
}


def _writes(root: str, sid: str) -> list[str]:
    path = os.path.join(root, ".asgard", "state", "writes-" + sid + ".json")
    try:
        with open(path, encoding="utf-8") as handle:
            rows = json.load(handle)
    except Exception:
        return []  # 목록이 없으면 이 세션은 쓴 게 없다 — 되짚을 것도 없다
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for raw in rows:
        value = str(raw or "").strip()
        if not value or not _reviewable(root, value):
            continue
        absolute = os.path.abspath(value if os.path.isabs(value) else os.path.join(root, value))
        out.append(os.path.relpath(absolute, os.path.abspath(root)).replace(os.sep, "/"))
    return out


def _reviewable(root: str, rel: str) -> bool:
    """현재 파일 또는 HEAD의 삭제 파일만. 만들었다 지운 scratch 경로는 순변화가 없다."""
    root_abs = os.path.abspath(root)
    root_real = os.path.realpath(root_abs)
    absolute = os.path.abspath(rel if os.path.isabs(rel) else os.path.join(root_abs, rel))
    try:
        if os.path.commonpath((root_abs, absolute)) != root_abs:
            return False
        relative = os.path.relpath(absolute, root_abs).replace(os.sep, "/")
        if relative == ".." or relative.startswith("../"):
            return False
        if os.path.isfile(absolute) and os.path.commonpath((root_real, os.path.realpath(absolute))) == root_real:
            return True
        proc = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{relative}"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode == 0
    except Exception:
        return False


def _lesson(exe: str, root: str, paths: list[str], sid: str = "") -> dict:
    """`asgard tutor --json`이 유일한 판정 경로 — 훅은 규칙을 자기가 알지 않는다.

    훅은 사용자 저장소 안에서 도는 stdlib 전용 스크립트다(hooks 패키지 계약). 규칙을 복사해
    넣으면 판정이 두 벌이 되고, 두 벌은 반드시 어긋난다.

    `--sid` 는 "왜 이렇게 했는가" 칸이 이 세션의 퀘스트를 고르게 하는 자다. 퀘스트 포인터는
    저장소마다 하나라 옆 세션이 연 기장을 가리킬 수 있고, 훅만이 호스트 세션 이름을 안다.
    """
    # `--record`가 이 호출을 성장 기록에 센다 — 훅이 놓은 물음도 사람 앞에 놓인 물음이다.
    # 안 세면 조절(fading)·재방문이 외부 클라이언트에서만 영원히 1회차에 머문다.
    cmd = [exe, "tutor", "--json", "--record", "--report", "--limit", str(MAX_SHOWN)]
    if sid:
        cmd += ["--sid", sid]
    for path in paths[:200]:
        cmd += ["--path", path]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=root, encoding="utf-8", errors="replace"
        )
        return json.loads(result.stdout or "{}")
    except Exception:
        return {}


def _signature(points: list[dict], back: list[dict], told: Sequence[str] = ()) -> str:
    """카드에 실릴 것 전부의 지문. 같은 카드를 매 턴 다시 놓으면 세 번째부터 아무도 안 읽는다.

    재방문도 설명 절도 지문에 넣는다 — 안 넣으면 오늘 처음 돌아온 옛 물음이나 새로 바뀐 설명이
    "직전 턴과 같은 카드"로 판정돼 통째로 사라진다. 래치가 자기 성장 경로를 막는 형상이다.
    """
    rows = ["%s|%s|%s" % (p.get("kind"), p.get("path"), p.get("unit")) for p in points]
    rows += ["revisit|%s|%s" % (r.get("cid"), r.get("asks")) for r in back]
    if told:
        rows.append("explain|" + hashlib.sha256("\n".join(told).encode("utf-8")).hexdigest()[:16])
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()[:16]


def _latched(root: str, sid: str, sig: str, slot: str = "") -> bool:
    """이미 이 지문을 놓았으면 True. 기록 실패는 False — 못 세면 한 번 더 보여주는 쪽으로."""
    path = os.path.join(root, ".asgard", "state", "tutor-" + slot + sid + ".json")
    try:
        with open(path, encoding="utf-8") as handle:
            if json.load(handle).get("signature") == sig:
                return True
    except Exception:
        pass  # 래치가 없거나 깨졌다 = 아직 안 놓았다 — 못 읽은 것을 "이미 놓았다"로 세면 카드가 통째로 증발한다
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"signature": sig}, handle)
        os.replace(tmp, path)
    except Exception:
        pass  # 못 적었으면 다음 턴에 같은 카드가 한 번 더 나온다 — 중복이 침묵보다 낫다
    return False


def _card(lesson: dict, points: list[dict], back: list[dict], told: Sequence[str] = (), why: Sequence[str] = ()) -> str:
    """네이티브 루프의 `tutor._card`와 같은 화면을 낸다 — 형식이 갈리면 같은 판정이 클라이언트마다
    다르게 보이고, 그러면 사용자는 어느 쪽이 진짜인지부터 물어야 한다."""
    quiz = str(lesson.get("mode") or "quiz") == "quiz"
    added, removed = int(lesson.get("added") or 0), int(lesson.get("removed") or 0)
    files = len(lesson.get("files") or [])
    head = "⠶ 되짚기 — 이번 턴 %d개 파일 · +%d/-%d행이에요." % (files, added, removed)
    lines = [head + (" 아래는 **기계가 못 답하는** 것들이에요." if quiz else ""), ""]
    if told:
        # 설명이 물음보다 위에 온다 — 전달된 적 없는 것을 인출부터 시키면 물음은 답이 아니라
        # 침묵을 받는다. 네이티브 `tutor._card`가 같은 자리에 같은 절을 놓는다.
        lines += [*told, ""]
    if why:
        lines += [*why, ""]
    moved = sum(len(row.get("units_moved") or ()) for row in (lesson.get("files") or []) if isinstance(row, dict))
    if moved:
        lines.append("  구조 이동 — 같은 본문으로 확인된 %d개 단위는 삭제 질문에서 뺐어요." % moved)
    shown = 0
    folded, quiet = {}, {}
    for point in points:
        form = point.get("form") or "full"
        if form in ("fold", "quiet"):
            bucket = folded if form == "fold" else quiet
            kind = point.get("kind")
            bucket[kind] = bucket.get(kind, 0) + 1
            continue
        if shown >= MAX_SHOWN:
            continue
        mark = "  [%s]" % (point.get("cid") or "?") if quiz else ""
        lines.append("  %s — %s%s" % (_label(point), _where(point), mark))
        lines.append("    " + ("▸ %s" % point.get("ask") if quiz else str(point.get("what") or "")))
        shown += 1
    over = sum(1 for p in points if (p.get("form") or "full") not in ("fold", "quiet")) - shown
    if over > 0:
        lines.append("  나머지 후보는 이번 회차에 묻지 않아요." if quiz else "  나머지 후보는 보고서에 있어요.")
    if folded:
        lines.append("  %s — 이미 답해 오신 종류라 접었어요" % _folded(folded))
    if quiet:
        lines.append("  %s — 계속 못 닿아서 접었어요 (`asgard tutor --progress`)" % _folded(quiet))
    # 보고서 경로는 판정이 실제로 쓴 자리를 적는다 — 상수를 적으면 저장소 설정이 자리를 옮겼을 때
    # 사용자가 여는 경로가 빈 자리가 된다. 안 실려 오면 기본 자리로 돌아간다.
    report = str(lesson.get("report") or "").strip() or REPORT_REL
    if not quiz:
        lines += ["", "  전체: %s  · 물음 형식으로 되돌리려면 `asgard tutor --quiz`" % report]
        return "\n".join(lines)
    for row in back[:MAX_BACK]:
        lines.append("  ↩ 다시 — %s  [%s]  (아직 답이 없어요)" % (_where(row, False), row.get("cid") or "?"))
        lines.append("    ▸ %s" % row.get("ask"))
    lines.append("")
    lines.append('  답은 `asgard tutor --answer <표식> "..."` · 오탐이면 `asgard tutor --dismiss <표식>`')
    lines.append("  전체와 '왜 이렇게 했는가' 빈칸: %s  (다시 보기: `asgard tutor --report`)" % report)
    return "\n".join(lines)


def _why(row: object, limit: int = 4) -> list:
    """`asgard tutor --json` 의 `rationale` 칸을 줄로 옮긴다 — 규칙은 `asgard.tutor_rationale`이
    혼자 갖는다. `_explain` 과 같은 계약이고, `tests/test_tutor_rationale.py` 가 두 산출을
    문자열로 맞대 본다.

    이 절이 들어가는 자리가 이 층의 뒤집힌 전제다: "왜 그렇게 했나"는 코드를 쓴 쪽만 답할 수
    있는데, 에이전트가 쓴 변경에서는 그 쪽이 사람이 아니다. 그래서 사람에게 묻는 대신 그 턴의
    퀘스트 기록(목표·가정·검증 명령)을 사실로 넣어 준다. 기록이 없으면 아무 줄도 안 낸다.
    """
    if not isinstance(row, dict):
        return []
    goals = [str(g) for g in (row.get("goals") or []) if str(g).strip()][: max(0, limit)]
    assumptions = [str(a) for a in (row.get("assumptions") or []) if str(a).strip()]
    evidence = [(str(e[0]), e[1]) for e in (row.get("evidence") or []) if isinstance(e, (list, tuple)) and len(e) >= 2]
    request = " ".join(str(row.get("request") or "").split())
    if not (goals or assumptions or evidence or request):
        return []
    qid = str(row.get("quest_id") or "")
    out = ["⠶ 왜 이렇게 했는가" + (" — 퀘스트 `%s`" % qid if qid else "")]
    if request:
        out.append("  받은 요청 — " + _clip(request, 160))
    for index, goal in enumerate(goals):
        out.append(("  맞추려던 것 — " if index == 0 else "                ") + _clip(goal, 160))
    total = int(row.get("goals_total") or len(goals))
    if total > len(goals):
        out.append("                …외 %d건은 퀘스트 로그에 있어요" % (total - len(goals)))
    for index, assume in enumerate(assumptions):
        out.append(("  가정 — " if index == 0 else "         ") + _clip(assume, 160))
    for index, (cmd, code) in enumerate(evidence):
        out.append(("  확인 — " if index == 0 else "         ") + "%s (exit %s)" % (_clip(cmd, 120), code))
    return out


def _clip(text: str, cap: int) -> str:
    body = " ".join(str(text).split())
    return body if len(body) <= cap else body[: cap - 1] + "…"


def _explain(exp: object, limit: int = EXPLAIN_SHOWN, quiz: bool = True) -> list[str]:
    """`asgard tutor --json`의 `explain` 칸을 그린다 — 훅은 설명을 만들지 않는다.

    칸이 없거나 `null`이면 빈 목록이고, 그러면 카드는 지금까지처럼 물음만 낸다. 훅은 stdlib
    전용이라 엔진을 부를 수 없어서(hooks 패키지 계약) 여기서 하는 일은 이미 판정된 칸을 줄로
    옮기는 것뿐이다 — 무엇을 설명할지 고르는 규칙은 `asgard.tutor_teach`가 혼자 갖는다.

    줄 모양은 `tutor_teach.card`를 그대로 옮긴다. 판정이 하나라도 화면이 둘이면 사용자는 어느
    쪽이 진짜인지부터 물어야 한다 — `tests/test_tutor_note_hook.py`가 두 산출을 문자열로 맞대
    본다. 깊이별로 줄어드는 규칙(`owned`는 한 줄, `first`가 아니면 자리까지)도 거기서 온다.

    설명 절은 물음에 답하지 않는다. 여기 실리는 것은 "무엇이 어디서 바뀌었나"이고, "왜 그렇게
    했나"는 아래 물음이 그대로 열어 둔다.
    """
    if not isinstance(exp, dict):
        return []
    steps, terms = _rows(exp, "steps"), _rows(exp, "terms")
    checks, recall = _texts(exp, "checks"), _texts(exp, "recall")
    gaps = [g for g in _rows(exp, "gaps", list) if len(g) >= 2]
    # `gaps`는 빈 판정에서 뺀다 — 엔진 `tutor_teach.card`와 같은 규칙이다. 못 본 것 하나로 카드를
    # 내면 "읽을 자리 0곳" 두 줄이 턴마다 나가고, 빈 카드는 다음 카드의 신뢰를 깎는다. 그 줄은
    # `--explain`과 보고서가 받는다. 이 조건이 엔진과 갈리면 같은 payload가 화면마다 다르게 나온다.
    if not steps and not terms and not checks:
        return []
    depth = str(exp.get("depth") or "")
    if depth == "owned":
        where = " · ".join(("%s %s" % (_at(step), step.get("unit") or "")).strip() for step in steps[:limit])
        return ["⠶ 설명 — %s" % where] if where else []
    total = _count(exp, "total_units", len(steps))
    flows = _count(exp, "flow_count", 1)
    overview = str(exp.get("overview") or "").strip()
    if not overview:
        overview = (
            "변경 단위 %d곳을 호출 관계 기준 %d개 흐름으로 나눴어요." % (total, flows)
            if total
            else "현재 읽을 코드 단위는 없어요."
        )
    lines = ["⠶ 설명 — " + overview]
    mission = " ".join(str(exp.get("mission") or "").split())
    if depth == "first" and mission:
        lines.append("  임무 — " + mission[:120])
    primary = _count(exp, "primary_units", len(steps))
    shown = steps[: min(max(0, limit), primary)]
    if shown:
        lines.append("  먼저 읽을 흐름 — %d곳" % len(shown))
        for step in shown:
            head = "  %s. %s %s" % (step.get("order"), _at(step), step.get("unit") or "")
            tail = "%s · %s" % (step.get("what") or "", step.get("why_here") or "")
            does = str(step.get("does") or "").strip()
            if does:
                lines.append("%s — %s" % (head, does))
                lines.append("     " + tail)
            else:
                lines.append("%s — %s" % (head, tail))
        if total > len(shown):
            lines.append("  나머지 흐름은 보고서에 접어 뒀어요.")
    if depth != "first":
        return lines
    if terms:
        lines.append("  새로 들어온 말")
        for term in terms[:limit]:
            gloss = str(term.get("gloss") or "")
            lines.append("    `%s` — %s" % (term.get("name"), term.get("where")) + (" — %s" % gloss if gloss else ""))
        if len(terms) > limit:
            lines.append("    나머지 말은 보고서에 접어 뒀어요.")
    lines += ["  확인 — %s" % check for check in checks]
    if quiz:
        lines += ["    ▸ %s" % ask for ask in recall]
    lines += ["  못 본 것 — %s: %s" % (gap[0], gap[1]) for gap in gaps[:limit]]
    return lines


def _say(protocol: str, mode: str, text: str) -> None:
    """사람에게 보이는 한 줄기 — 필드는 호스트와 이벤트가 함께 정한다. 그 자리에서 안 읽는
    이름으로 적으면 카드는 조용히 사라진다.

    세 레인이 각자 이 리터럴을 적고 있어서 codex 는 한 파일 안에 규약이 둘이었다: Stop 은
    `systemMessage`, brief·tip 은 평문 stdout. 평문 쪽이 틀렸다 — codex 의
    `user-prompt-submit.command.output`·`post-tool-use.command.output` 스키마가
    `additionalProperties: false` 라 JSON 이 아닌 출력은 "hook returned invalid ... JSON
    output" 으로 버려진다 (codex-cli 0.146.0 번들 스키마 확인). 두 레인은 켜져 있었을 뿐
    사용자에게 닿은 적이 없다.

    Cursor 만 이벤트별로 갈린다 — `beforeSubmitPrompt` 는 `user_message`, `stop` 은
    `followup_message`. `postToolUse`(팁)에는 사람에게 보이는 필드가 없어 여기서 낸
    `user_message` 는 유효하지만 그려지지 않는다. 남은 `additional_context` 는 모델 통로라
    쓸 수 없다 — 물음을 읽은 모델이 대신 답해 버린다.
    """
    if protocol == "cursor":
        key = "followup_message" if mode == "note" else "user_message"
    else:
        key = "systemMessage"  # Claude Code·Codex 공통 — 세 이벤트 전부 이 필드를 사람에게 보인다
    sys.stdout.write(json.dumps({key: text}, ensure_ascii=False) + "\n")


def _at(step: dict) -> str:
    """`Step.where` — 엔진의 프로퍼티는 JSON에 안 실려서 여기서 같은 규칙으로 다시 만든다."""
    return "%s:%s" % (step.get("path"), step.get("line"))


def _rows(exp: dict, name: str, kind: type = dict) -> list:
    rows = exp.get(name)
    return [row for row in rows if isinstance(row, kind)] if isinstance(rows, list) else []


def _texts(exp: dict, name: str) -> list:
    rows = exp.get(name)
    return [str(row) for row in rows if str(row).strip()] if isinstance(rows, list) else []


def _count(exp: dict, name: str, fallback: int) -> int:
    """payload 의 수 칸 — 비었거나 0이면 fallback, 숫자로 안 읽히면 그것도 fallback.

    `_rows`·`_texts` 와 같은 이유로 있다: 이 훅은 디스크에서 온 payload 를 못 믿는다. 여기서
    죽으면 Stop 시점의 카드가 통째로 사라지고, 막지 않는 훅이라 화면에는 아무것도 안 남는다."""
    value = exp.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)) or not value:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def _label(row: dict) -> str:
    if not row.get("unit") and row.get("kind") == "behavior-removed":
        return "삭제 책임 묶음"
    if not row.get("unit") and row.get("kind") == "test-removed":
        return "판정 책임 묶음"
    return _KIND.get(row.get("kind"), row.get("kind"))


def _where(row: dict, with_line: bool = True) -> str:
    unit = row.get("unit") or ""
    base = "%s:%s" % (row.get("path"), row.get("line")) if with_line else str(row.get("path"))
    return base + (" " + unit if unit else "")


def _folded(counts: dict) -> str:
    return " · ".join("%s %d건" % (_KIND.get(k, k), n) for k, n in sorted(counts.items()))


def _brief(exe: str, root: str, prompt: str) -> str:
    """`asgard tutor --brief`를 그대로 옮긴다 — 훅은 자기 규칙을 안 갖는다(판정기 단일)."""
    if not prompt:
        return ""
    try:
        result = subprocess.run(
            [exe, "tutor", "--brief", "--quiet", "--text", prompt[:2000]],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=root,
            encoding="utf-8",
            errors="replace",
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""  # 브리핑 불능이 턴 시작을 막지 않는다 — 앞서 말하는 층도 관문이 아니다


def _run_tip(protocol: str, root: str, sid: str, data: dict) -> None:
    """일하는 **도중** 한 번. 대부분의 호출은 아무것도 안 찍는다.

    PostToolUse 는 도구를 부를 때마다 돈다 — 여기서 매번 `asgard`를 띄우면 그 값이 되짚기가 주는
    값보다 크다. 그래서 두 겹으로 거른다: ① 파일을 실제로 바꾼 호출만 센다(읽기·검색은 안 센다),
    ② 그중에서도 `TIP_EVERY` 번에 한 번만 밖으로 나간다. 팁을 고르는 판정 자체는 그 뒤에 있고,
    거기서 또 한 번 걸러진다(같은 신호는 한 세션에 한 번) — 그래서 실제로 화면에 닿는 것은 드물다.

    드물어야 하는 이유는 비용이 아니라 신뢰다. 매번 말하는 안내는 배경 소음이 되고, 배경 소음이
    된 안내는 켜져 있어도 꺼진 것과 같다.
    """
    if not _wrote_a_file(data):
        return
    if not _every(root, sid, TIP_EVERY):
        return
    exe = shutil.which("asgard")
    if not exe:
        return
    try:
        result = subprocess.run(
            [exe, "tutor", "--tip", "--sid", sid],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=root,
            encoding="utf-8",
            errors="replace",
        )
        card = (result.stdout or "").strip()
    except Exception:
        return  # 팁 불능이 도구 호출을 막지 않는다 — 되짚기는 규율이지 관문이 아니다
    if not card:
        return
    _say(protocol, "tip", card)


# 이 표는 세 클라이언트의 PostToolUse 매처가 실제로 보내는 이름의 합집합이다 — 매처가 보내는데
# 여기 없는 이름은 계수에서 조용히 빠진다. `Delete` 가 그렇게 빠져 있었다 (Cursor 의
# postToolUse 매처는 `Write|Edit|Delete`). 삭제는 되짚기의 물음 종류 절반(동작 사라짐·판정
# 사라짐)을 만드는 입력이라, 세는 쪽에서 빼면 팁이 가장 필요한 구간을 못 본다.
_WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit", "Delete", "apply_patch")


def _wrote_a_file(data: dict) -> bool:
    """이 도구 호출이 파일을 실제로 바꿨는가. 실패한 write 는 안 센다 — 안 바뀐 것은 안 바뀐 것이다."""
    resp = data.get("tool_response") or data.get("tool_output")
    if isinstance(resp, dict) and (resp.get("is_error") or resp.get("error")):
        return False
    name = str(data.get("tool_name") or "")
    if name and name not in _WRITE_TOOLS:
        return False
    raw = data.get("tool_input")
    tool_input = raw if isinstance(raw, dict) else {}
    path = str(tool_input.get("file_path") or tool_input.get("path") or "")
    # `.asgard` 아래는 이 층 자신의 기록이다 — 자기가 쓴 것을 세면 팁이 자기를 부른다.
    return bool(path) and ".asgard" not in path


def _every(root: str, sid: str, span: int) -> bool:
    """`span` 번에 한 번만 True. 세는 자리를 못 쓰면 False — 못 세면 **덜 말하는** 쪽으로 넘어진다.

    브리핑·되짚기 래치는 반대로 넘어진다(못 세면 한 번 더 보여준다). 방향이 다른 이유는 실패의
    값이 달라서다: 카드는 놓치면 그 턴의 물음이 통째로 사라지지만, 팁은 다음 write 에 또 온다.
    """
    path = os.path.join(root, ".asgard", "state", "tutor-tip-" + sid + ".json")
    try:
        with open(path, encoding="utf-8") as handle:
            count = int(json.load(handle).get("writes") or 0)
    except Exception:
        count = 0
    count += 1
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"writes": count}, handle)
        os.replace(tmp, path)
    except Exception:
        return False
    return count % max(1, span) == 0


def _prompt_of(data: dict) -> str:
    """이번 턴의 요청 문장 — 클라이언트마다 칸 이름이 다르다(Claude/Codex `prompt`, Cursor `user_message`)."""
    raw = data.get("tool_input")
    tool_input = raw if isinstance(raw, dict) else {}
    return str(data.get("prompt") or tool_input.get("prompt") or data.get("user_message") or "").strip()


def _run_brief(protocol: str, root: str, sid: str, data: dict) -> None:
    """일을 **시작하기 전에**이 자리에 남은 답 없는 물음을 사용자 앞에 놓는다 (UserPromptSubmit).

    사용자에게만 보낸다. 모델에 넣지 않는 이유가 이 층의 핵심이다 — 모델이 열린 물음을 보면
    그 물음에 **대신 답해** 버리고, 그러면 되짚기가 막으려던 바로 그 일이 일어난다(미미르 auga
    계약: 물음은 대신 닫아 주는 체크리스트가 아니다).
    """
    exe = shutil.which("asgard")
    if not exe:
        return
    card = _brief(exe, root, _prompt_of(data))
    if not card:
        return
    if _latched(root, sid, hashlib.sha256(card.encode("utf-8")).hexdigest()[:16], "brief-"):
        return
    _say(protocol, "brief", card)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        protocol = sys.argv[1] if len(sys.argv) > 1 else "claude"
        mode = sys.argv[2] if len(sys.argv) > 2 else "note"
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        raw_sid = "cursor" if protocol == "cursor" else data.get("session_id") or "default"
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw_sid))[:64]
        if mode == "brief":
            _run_brief(protocol, root, sid, data)
            sys.exit(0)
        if mode == "tip":
            _run_tip(protocol, root, sid, data)
            sys.exit(0)
        paths = _writes(root, sid)
        if not paths:
            sys.exit(0)
        exe = shutil.which("asgard")
        if not exe:
            sys.exit(0)
        lesson = _lesson(exe, root, paths, sid)
        selected = lesson.get("shown_checkpoints")
        source = selected if isinstance(selected, list) else (lesson.get("checkpoints") or [])
        points = [p for p in source if isinstance(p, dict)]
        back = [r for r in (lesson.get("revisits") or []) if isinstance(r, dict)]
        quiz = str(lesson.get("mode") or "quiz") == "quiz"
        told = _explain(lesson.get("explain"), quiz=quiz and not bool(points or back))
        why = _why(lesson.get("rationale")) if not quiz else []
        if not points and not back and not told and not why:
            sys.exit(0)  # 물을 것도 설명할 것도 없으면 침묵한다 — 빈 카드는 다음 카드의 신뢰를 깎는다
        if _latched(root, sid, _signature(points, back, [*told, *why])):
            sys.exit(0)
        _say(protocol, "note", _card(lesson, points, back, told, why))
    except Exception:
        pass  # 되짚기 불능이 턴을 막지 않는다 — 튜터는 규율이지 관문이 아니다
    sys.exit(0)


if __name__ == "__main__":
    run("tutor-note", main)
