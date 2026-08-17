#!/usr/bin/env python3
# Asgard verifier-context — 판정자에게 하네스가 관측한 실행 기록을 넘긴다 (SubagentStart).
#
# AGENTS.md 의 계약은 이렇다: 판정 턴은 요청·기준·하네스가 관측한 변경 파일·공개 표면 diff·
# **마지막 판정 이후 워커 실행 기록**을 받고, "이 입력을 넓히는 것이 판정에 쓸 수 있는 가장 큰
# 지렛대"다. 그 조립기는 네이티브 루프에만 있었고(agent/heimdall/trinity/notes.py, 소비자는
# bifrost 하나) Claude Code 로 오는 길이 없었다. 그래서 서브에이전트로 뜬 판정자가 사건에 대해
# 아는 것은 **코디네이터가 프롬프트에 타이핑한 것뿐**이었다 — 판정 범위를 판정받는 쪽이 정하는
# 구조다.
#
# 26-08-12 에 그 구멍이 실제로 값을 냈다. 코디네이터가 "이번 델타만 봐라"라고 적었는데 그 시점
# 트리에는 다른 변경이 이미 들어 있었고, 그 라운드는 통째로 안 판정된 채 지나갔다(퀘스트
# harness-followups-260812 turn 12). 다음 판정자가 뒤늦게 잡았고, 그 다음 판정자는 세션 기록을
# **손으로 파서** 같은 입력을 재구성했다 — 있어야 할 입력이 없다는 것과 그것이 값어치 있다는
# 것을 동시에 보여 준다.
#
# 메모리는 여전히 안 준다 (memory-activate 의 NEVER_INJECT, map-activate 도 같다). 판정 독립성은
# "판정자가 아무것도 모른다"가 아니라 "워커의 말이 아니라 하네스의 관측을 읽는다" 이므로, 여기서
# 넓히는 것은 사실 관측뿐이다 — 누구의 해석도 넣지 않는다.
#
# 호스트 셋이 남기는 기록의 깊이가 다르고, 이 훅이 지는 몫은 그 차이를 판정자에게 그대로 넘기는
# 것이다. Claude Code 와 Codex 는 호출과 결과를 다 적고, Cursor 는 호출만 적는다 (transcript.py
# 의 모듈 설명에 세 형식의 실측이 있다). 결과가 없는 호스트에서 성패를 주장하면 판정자가 아무도
# 확인하지 않은 초록을 읽으므로, 그때는 `ran` 으로만 적고 직접 다시 돌리라고 말한다.
#
# Fail-open + stdlib-only: 주입이 실패해서 판정 턴이 죽으면 본말전도라 어떤 오류든 조용히 exit 0.
#
# `from __future__ import annotations` 는 문법 취향이 아니라 그 fail-open 의 조건이다. 훅은 이
# 저장소의 venv 가 아니라 그 기계가 내주는 파이썬으로 돌고 바닥은 3.9 다 (tests/architecture/test_layered.py 의
# `test_hooks_parse_on_old_python`). `list | None` 은 3.9 에서 **파싱은 되고** 함수를 정의하는
# 순간 TypeError 로 죽는데, 그 죽음은 `main()` 의 예외 처리보다 앞이라 fail-open 이 못 받는다 —
# 26-08-13 codex 독립 판정이 3.9.6 에서 실제로 그 traceback 을 냈다.
from __future__ import annotations

import json
import os
import sys

# 주입 스키마·기록 파싱·git 은 훅과 함께 깔리는 공용 라이브러리가 쥔다 — 이 훅이 정하는 것은
# 무엇을 실을지(정책)뿐이다.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.baseline import MAX_CHECKS  # noqa: E402
from asgard_hooklib.contracts import contract_criteria, criteria_contracts  # noqa: E402
from asgard_hooklib.firing import run  # noqa: E402
from asgard_hooklib.inject import client, emit_context  # noqa: E402
from asgard_hooklib.paths import git, quest_dir  # noqa: E402
from asgard_hooklib.policy import load_policy  # noqa: E402
from asgard_hooklib.runners import detect_checks  # noqa: E402
from asgard_hooklib.session import active_quest  # noqa: E402
from asgard_hooklib.transcript import (  # noqa: E402
    FULL,
    INVOCATIONS,
    MISSING,
    UNKNOWN,
    exit_code,
    never_ran,
    read,
    session_file,
)
from asgard_hooklib.tree import current_tree_ref  # noqa: E402

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open 에 삼켜지면 주입이 통째로 증발한다. UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용
    except Exception:
        pass

AGENT = "asgard-verifier"
# 파일을 바꾼 호출. `Delete` 는 Codex 의 패치(`*** Delete File:`)와 Cursor 의 같은 이름 도구가 쓴다 —
# 지우기도 쓰기이고, 여기서 빠지면 판정자가 사라진 파일을 아무도 건드리지 않은 것으로 읽는다.
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "Delete"}
# 상한 셋. 판정자의 컨텍스트는 판정에 쓰라고 있는 것이지 기록을 옮겨 적으라고 있는 것이 아니다 —
# 넘치면 잘랐다는 사실을 본문에 적어 판정자가 직접 더 볼지 정하게 한다.
MAX_FILES = 80
MAX_COMMANDS = 80
MAX_WRITES = 60
MAX_CONTRACTS = 5  # contracts.criteria_contracts 의 상한과 같다 — 넘는 것은 하네스도 안 돌린다
MAX_CHECK_ROWS = 12
CMD_CHARS = 200


def agent(data: dict) -> str:
    """이 SubagentStart 가 띄우는 에이전트 이름 — 호스트마다 필드가 다르다."""
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    return str(
        data.get("agent_type")
        or data.get("agent_name")
        or data.get("subagent_type")
        or tool_input.get("agent_type")
        or tool_input.get("subagent_type")
        or ""
    )


def quest_events(root: str, qid: str) -> list:
    """퀘스트 로그의 이벤트 목록 — 못 읽으면 빈 목록."""
    path = os.path.join(quest_dir(root), qid + ".jsonl")
    events = []
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    events.append(row)
    except OSError:
        return []
    return events


def anchor(events: list) -> tuple:
    """판정 구간의 시작 — `(tree_ref, ts, 앞선 판정의 turn)`.

    마지막 verify 이벤트가 기준이다: 그 뒤에 일어난 일이 이번 판정이 처음 보는 것이다. 판정이
    아직 없으면 퀘스트가 열린 자리(`base_ref` + 첫 이벤트 시각)가 기준이 된다 — 그때는 구간이
    곧 퀘스트 전체다."""
    for event in reversed(events):
        if event.get("event") == "verify" and event.get("tree_ref"):
            return str(event["tree_ref"]), str(event.get("ts") or ""), int(event.get("turn") or 0)
    if not events:
        return "", "", 0
    return str(events[0].get("base_ref") or ""), str(events[0].get("ts") or ""), 0


def in_evidence(path: str) -> bool:
    """판정자가 손댈 수 있는 자리인가 — 하네스 상태는 작업 대상이 아니다.

    트리를 맞대는 것만으로는 안 걸러진다: 트리는 HEAD 에서 씨를 받으므로 **다른 세션이 커밋한**
    `.asgard/` 변경이 기준 커밋과 지금 사이에 그대로 들어온다. 그것을 판정자 앞에 세우면 판정
    대상이 아닌 자리를 지적하게 되고, readonly-guard 는 애초에 그 자리를 쓰기 대상에서 뺀다.
    공유 지도(`.asgard/map/`)만 예외다 — 그쪽은 판정 해시가 덮는다 (AGENTS.md 지도 절)."""
    return not path.startswith(".asgard/") or path.startswith(".asgard/map/")


def changed_files(root: str, ref: str) -> list:
    """기준 이후 실제로 달라진 파일 — 워커의 말이 아니라 git 이 보는 것이다.

    **트리 둘을 맞대는** 이유가 있다. `git diff <ref>` 만 쓰면 추적되지 않는 새 파일이 안 보인다 —
    워커가 파일을 새로 만든 경우가 정확히 그것이라 가장 중요한 변경이 통째로 빠진다. 반대로 기준이
    판정의 `tree_ref` 일 때 그 트리에는 추적 안 되는 파일도 들어 있어서, 그대로 두면 같은 파일이
    "삭제됨"으로 뜬다.

    그래서 지금 트리를 판정 해시와 **같은 규칙으로** 지어 맞댄다 (`current_tree_ref`: `.asgard` 는
    공유 지도만, 쓰레기 디렉터리는 제외). 경계를 여기서 따로 그으면 판정자가 자기 판정의 해시가
    안 덮는 파일을 보고 판단하게 된다. 값은 약 75ms 이고 판정자 배차당 한 번이다."""
    if not ref:
        return []
    now = current_tree_ref(root)
    if not now:
        return []
    rc, out = git(root, "diff", "--name-status", ref, now)
    if rc != 0:
        return []
    rows = []
    for line in out.splitlines():
        row = line.strip()
        if row and in_evidence(row.split("\t")[-1].strip()):
            rows.append(row)
    return rows


def commitments(root: str, events: list) -> tuple:
    """판정자가 자기 명령을 고르기 전에 알아야 하는 셋 — `(계약, 베이스라인 명령, 이미 돌린 행, 그 상태)`.

    퀘스트가 선언한 verify 계약과 프로젝트 베이스라인은 이 판정이 무엇으로 채점되는지를 정하는데,
    지금까지 판정자에게 가는 길이 없었다. 그래서 판정자는 채점 기준을 모르는 채 명령을 골랐고,
    하네스는 PASS 를 받은 뒤 자기 명령을 따로 돌렸다 — 같은 스위트가 한 트리에 두 번 돌았다
    (26-08-13 실측: 판정 130건, 판정자가 직접 부른 명령 965건 중 pytest 253건, 그와 별개로
    하네스 베이스라인이 판정당 median 121.8초).

    넘기는 것은 사실뿐이고 무엇을 돌릴지는 안 정한다. 판정 독립성은 판정자가 명령을 직접
    돌리는 데서 나오므로, 여기서 "다시 안 돌려도 된다"고 말하면 그 독립성을 이 훅이 깎는다.
    이미 돌린 행에는 그것이 **어느 트리에서** 나왔는지를 함께 적어 판정자가 스스로 정하게 한다."""
    contracts = criteria_contracts(contract_criteria(*(e.get("criteria") for e in events)))
    try:
        checks = detect_checks(root, load_policy(root))
    except Exception:
        checks = []  # 정책을 못 읽는 것이 판정 턴을 막을 이유는 안 된다 (이 훅의 fail-open 규약)
    rows: list = []
    state = ""
    for event in reversed(events):
        if event.get("event") != "verify":
            continue
        baseline = event.get("baseline") or {}
        rows = [r for r in (baseline.get("results") or []) if isinstance(r, dict)]
        rows += [r for r in (event.get("criteria_checks") or []) if isinstance(r, dict)]
        state = str(baseline.get("state") or "")
        break
    return contracts, list(checks), rows, state


def check_mark(row: dict) -> str:
    """하네스 실행 행 한 건의 결말 — 명령 표식과 같은 어휘를 쓴다.

    `timeout` 을 종료 코드 없음과 뭉치면 판정자가 "안 끝난 검사"를 "결과를 못 읽은 검사"로 읽는다.
    앞은 상한을 올리면 답이 나오고 뒤는 아니라, 다음에 고칠 자리가 서로 다르다."""
    if row.get("timed_out"):
        return "timeout"
    code = row.get("exit_code")
    return "exit %s" % code if code is not None else "no exit"


def label(call) -> str:
    """이 호출이 어떻게 끝났는가 — 판정자가 워커의 주장과 맞대 볼 한 낱말.

    `ok` 는 오류 표식 없이 돌아온 것이고, `blocked` 는 가드가 막아 **실행되지 않은** 것이다.
    둘을 가르는 이유는 Canon 9 와 같다: 안 돈 명령은 실패의 증거도 성공의 증거도 아니다.

    `ran` 은 셋째 사실이다 — 호출은 갔는데 그 결과가 기록에 없다. Cursor 기록 전체와 Codex 의
    `exec` 가 여기 온다. 이것을 `ok` 로 접으면 판정자가 아무도 확인하지 않은 초록을 읽는다."""
    if never_ran(call.output):
        return "blocked"
    if not call.failed:
        return "ok" if call.outcome_known else "ran"
    code = exit_code(call.output)
    return "exit %d" % code if code is not None else "failed"


def since(record: list, stamp: str) -> list:
    """기준 시각 이후의 호출. 초 단위까지만 비교한다 — 기록과 퀘스트 로그의 소수점 자리가 다르고,
    같은 초는 넣는 쪽으로 남긴다 (판정자에게 조금 더 보이는 것이 덜 보이는 것보다 안전하다)."""
    if not stamp:
        return record
    return [call for call in record if not call.ts or call.ts[:19] >= stamp[:19]]


def unresolved(commands: list) -> list:
    """끝내 초록을 못 본 명령 — 같은 명령이 뒤에서 `ok` 로 다시 돌았으면 해결된 것으로 본다.

    판정이 물어야 할 것은 "실패가 있었나"가 아니라 "실패가 남아 있나"다. 워커가 고치고 다시 돌린
    실패는 작업의 일부이고, 한 번 빨간 뒤 다시 안 돌린 명령이 미해결이다.

    맞대는 것은 **자르지 않은 명령문**이다. 화면용으로 자른 문자열로 비교하면 앞 200자가 같은 서로
    다른 명령 둘이 한 명령으로 보여, 하나가 초록이면 다른 하나의 미해결 실패가 조용히 사라진다.

    `ran` 은 미해결도 해결도 아니다. 결과가 기록에 없는 호출이라 실패로 셀 근거가 없고, 앞선
    실패를 지울 근거도 없다."""
    healed = {cmd for cmd, mark in commands if mark == "ok"}
    return [(cmd, mark) for cmd, mark in commands if mark not in ("ok", "blocked", "ran") and cmd not in healed]


def collect(data: dict) -> tuple:
    """(명령, 쓰기, 기록의 깊이) — 기준 시각 이후 하네스가 본 것.

    셋째 값이 있는 이유: 기록을 못 읽은 것·형식을 모르는 것·결과가 안 남는 것·아무것도 안 돌린
    것이 전부 빈 목록이나 표식 없는 목록으로 뭉개지는데, 판정자에게는 서로 다른 사실이다. 구별
    없이 "Commands (0)" 을 보여 주면 판정자는 워커가 아무 명령도 안 돌렸다고 읽는다 — 실행 기록을
    주려다 없는 사실을 주는 셈이다. 깊이를 정하는 것은 `read` 이고, 여기서는 그것을 그대로 전달한다."""
    record, depth = read(session_file(data))
    commands, writes = [], []
    for call in since(record, data.get("_since", "")):
        if call.tool == "Bash":
            commands.append((str(call.request.get("command") or "").strip().replace("\n", " ⏎ "), label(call)))
        elif call.tool in WRITE_TOOLS:
            writes.append((call.tool, str(call.request.get("file_path") or call.request.get("notebook_path") or "")))
    return commands, writes, depth


# 기록이 없을 때 그 이유를 적는 두 줄. 판정자가 할 일은 같아도(직접 다시 돌려라) 다음에 고칠
# 자리가 다르다 — 없는 파일은 호스트 배선을 의심할 자리이고, 못 알아본 형식은 판독기가 그 호스트를
# 아직 모르는 자리다.
BLANK_REASON = {
    MISSING: "Execution record: unreadable — the session transcript is not on disk, or this host does not",
    UNKNOWN: "Execution record: unrecognized — the session transcript was read, but its rows are not a",
}
BLANK_DETAIL = {
    MISSING: "write one where the harness looks.",
    UNKNOWN: "shape this harness knows how to parse.",
}


def render_commitments(
    lines: list,
    turn: int,
    contracts: list,
    checks: list,
    rows: list,
    state: str,
    moved: int = 0,
) -> None:
    """이 판정이 무엇으로 채점되는지, 그리고 하네스가 이미 무엇을 돌렸는지를 본문에 붙인다.

    `moved` 는 기준 이후 달라진 파일 수다. 이 값을 안 받고 "네가 판정하는 트리가 아니다"라고
    적던 동안 그 문장은 하네스가 모르는 것을 단언했다 — 워커가 파일을 안 바꾸고 명령만 다시
    돌린 라운드에서는 트리가 그대로인데도 같은 문장이 나갔다 (26-08-13 codex 독립 판정 3회차).
    없는 사실을 주는 것이 침묵보다 나쁘다는 이 파일의 규약은 여기에도 걸린다."""
    if contracts:
        lines.append("")
        lines.append(
            "Declared verify contracts (%d) — the harness runs these itself, and it refuses a PASS," % len(contracts)
        )
        lines.append("a close, and the gate while one of them fails or its artifacts are missing:")
        # 계약마다 번호와 기준 원문을 머리에 세운다. 명령과 산출물만 이어 적으면 계약 넷의 줄이
        # 한 덩어리로 붙어, 뒤 계약의 산출물이 앞 계약의 명령에 딸린 것으로 읽힌다 (26-08-13 이
        # 저장소의 실제 주입에서 그렇게 나왔다 — 기준 2·3 의 산출물이 기준 1 의 명령 밑에 섰다).
        for index, item in enumerate(contracts[:MAX_CONTRACTS], 1):
            lines.append("  [%d] %s" % (index, str(item.get("description") or "")[:CMD_CHARS]))
            if item.get("verify_cmd"):
                lines.append("      run       %s" % str(item["verify_cmd"])[:CMD_CHARS])
            if item.get("artifacts"):
                lines.append("      artifacts %s" % " ".join(str(a) for a in item["artifacts"])[:CMD_CHARS])
    if checks:
        # 자르는 수는 하네스가 실제로 돌리는 수와 같아야 한다. 5 로 자르던 동안 여섯째 명령은
        # PASS 채점에 남는데 판정자는 그 존재를 몰랐다 (26-08-13 codex 독립 판정이 잡은 자리).
        lines.append("")
        lines.append("Project baseline — the harness runs this itself when it records a PASS:")
        lines.extend("  %s" % str(c)[:CMD_CHARS] for c in checks[:MAX_CHECKS])
        if len(checks) > MAX_CHECKS:
            lines.append("  … %d more declared, which the harness does not run either" % (len(checks) - MAX_CHECKS))
    if rows:
        where = "the verdict at turn %d" % turn if turn else "the quest opening"
        lines.append("")
        lines.append("Checks the harness already ran at %s (baseline state: %s):" % (where, state or "none"))
        lines.extend(
            "  %-9s %7.1fs  %s"
            % (check_mark(row), float(row.get("secs") or 0.0), str(row.get("cmd") or "")[:CMD_CHARS])
            for row in rows[:MAX_CHECK_ROWS]
        )
        if len(rows) > MAX_CHECK_ROWS:
            lines.append("  … %d more" % (len(rows) - MAX_CHECK_ROWS))
        if moved:
            lines.append("Those ran on the tree at that anchor, not on the tree you are judging — the %d" % moved)
            lines.append("changed file(s) above moved after them.")
        else:
            # 단서는 참인 것만 적는다. "추적된 파일만 본다" 고 적던 동안 그 문장은 거짓이었다 —
            # 비교는 `current_tree_ref` 로 트리 둘을 짓고 그 트리는 `git add -A` 와 `ls-files
            # --others` 로 추적 밖 파일까지 담는다 (tree.py 의 `_STAT_NEUTRAL … add -A`). 반례가
            # 이 저장소에 서 있었다: `??` 로 뜨는 scope_activate.py 가 변경 목록에 M 으로 실렸다.
            # 실제로 빠지는 것은 무시 경로와 지도 밖 `.asgard/` 다 (26-08-14 판정 둘이 각각 잡았다).
            lines.append("Those ran on the tree at that anchor. Nothing shows as changed since, so they may still")
            lines.append("describe this tree — the comparison covers untracked files too, and leaves out ignored")
            lines.append("paths, build junk (.pyc, __pycache__, node_modules, .venv), and .asgard/ outside the")
            lines.append("shared map. Confirm anything that turns on those.")


def render(
    ref: str,
    turn: int,
    files: list,
    commands: list,
    writes: list,
    depth: str = FULL,
    contracts: list | None = None,
    checks: list | None = None,
    rows: list | None = None,
    state: str = "",
) -> str:
    """판정자가 읽을 블록. 사실만 적고 해석은 안 적는다."""
    where = "the last verdict (turn %d)" % turn if turn else "the quest opening"
    # 구간을 자를 수 있는 것은 기록에 시각이 있을 때뿐이다. Cursor 는 안 적으므로 "이후"라고 쓰면
    # 안 자른 목록에 잘랐다는 딱지를 붙이는 것이 된다.
    span = "since %s" % where if depth != INVOCATIONS else "for this session"
    lines = [
        "<asgard-verifier-input>",
        "Harness-observed record %s. The harness watched these; this is not the Worker's" % span,
        "account of them. Compare what the Worker says it did against what actually ran.",
        "",
        "Diff anchor: %s — run your own diff against it (git diff %s)." % (ref or "(none)", ref or "<ref>"),
    ]
    lines.append("")
    lines.append("Changed files (%d):" % len(files))
    lines.extend("  " + row for row in files[:MAX_FILES])
    if len(files) > MAX_FILES:
        lines.append("  … %d more — read them with git diff --name-status" % (len(files) - MAX_FILES))
    # 기록을 못 읽는 호스트에서도 채점 기준은 그대로 유효하다 — BLANK_REASON 의 이른 반환보다 앞에 둔다.
    render_commitments(lines, turn, contracts or [], checks or [], rows or [], state, len(files))
    if depth in BLANK_REASON:
        # 침묵보다 나쁜 것은 없는 사실을 주는 것이다 — 빈 목록은 "안 돌렸다"로 읽힌다.
        lines.append("")
        lines.append(BLANK_REASON[depth])
        lines.append(BLANK_DETAIL[depth])
        lines.append("No claim can be made about what did or did not run. Ask the Worker to show its")
        lines.append("commands, and re-run the verification commands yourself.")
        lines.append("</asgard-verifier-input>")
        return "\n".join(lines)
    if depth == INVOCATIONS:
        lines.append("")
        lines.append("This host records which tool calls were made, not what came back, and stamps no times.")
        lines.append("So the lists below cover the whole session rather than only what followed the anchor,")
        lines.append("and every command is marked `ran`: the call was made, and the record says nothing about")
        lines.append("whether it succeeded. Run the verification commands yourself before you rule on them.")
    if writes:
        lines.append("")
        lines.append("Write-tool calls (%d) — every file this session edited, in order:" % len(writes))
        lines.extend("  %-13s %s" % (tool, path) for tool, path in writes[:MAX_WRITES])
        if len(writes) > MAX_WRITES:
            lines.append("  … %d more" % (len(writes) - MAX_WRITES))
    lines.append("")
    lines.append("Commands (%d):" % len(commands))
    lines.extend("  %-9s %s" % (mark, cmd[:CMD_CHARS]) for cmd, mark in commands[:MAX_COMMANDS])
    if len(commands) > MAX_COMMANDS:
        lines.append("  … %d more" % (len(commands) - MAX_COMMANDS))
    stuck = unresolved(commands)
    if stuck:
        lines.append("")
        lines.append("Never re-run after failing (%d) — a non-zero exit nobody resolved:" % len(stuck))
        lines.extend("  %-9s %s" % (mark, cmd[:CMD_CHARS]) for cmd, mark in stuck[:MAX_COMMANDS])
        if len(stuck) > MAX_COMMANDS:
            lines.append("  … %d more" % (len(stuck) - MAX_COMMANDS))
    if depth == FULL:
        lines.append("")
        lines.append("A command that never ran cannot support a claim. `blocked` means a guard refused it")
        lines.append("before execution — neither evidence of failure nor of success. `ran` means the host")
        lines.append("recorded the call but not its outcome.")
    lines.append("</asgard-verifier-input>")
    return "\n".join(lines)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        if agent(data) != AGENT:
            sys.exit(0)  # 매처가 좁히지만 호스트마다 다르므로 여기서도 확인한다
        root = os.environ.get("CLAUDE_PROJECT_DIR") or str(data.get("cwd") or "") or os.getcwd()
        qid = active_quest(root, str(data.get("session_id") or "") or None)
        if not qid:
            sys.exit(0)  # 퀘스트가 없으면 판정 구간도 없다
        events = quest_events(root, qid)
        ref, stamp, turn = anchor(events)
        commands, writes, depth = collect({**data, "_since": stamp})
        files = changed_files(root, ref)
        if not (files or commands or writes):
            sys.exit(0)  # 실을 것이 없으면 아무 말도 안 한다
        contracts, checks, rows, state = commitments(root, events)
        emit_context(
            client(),
            render(ref, turn, files, commands, writes, depth, contracts, checks, rows, state),
            "SubagentStart",
        )
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    run("verifier-context", main)
