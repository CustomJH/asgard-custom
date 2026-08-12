"""세션 기록 읽기 — 호스트가 훅을 부르든 말든 디스크에 남는 정본.

훅 페이로드에는 호스트가 주기로 한 것만 들어 있다. 무엇이 **실제로 돌았는지**는 세션 기록 파일에
있다: 도구 호출과 그 결과가 한 줄씩 쌓이고, 페이로드가 비거나 훅이 아예 안 불린 자리도 여기서는
관측된다 — 26-08-12 에 failure-tracker 의 Canon 9 레인을 되살린 근거가 그것이고, budget-guard 가
토큰을 재는 근거도 같은 파일이다.

호스트 셋이 그 파일을 서로 다른 모양으로 적는다. 셋 다 실측으로 확인한 것만 적는다.

- **Claude Code** — `~/.claude/projects/<slug>/<session-id>.jsonl`. 행마다 `message.content` 블록이
  있고 `tool_use`(이름·인자·id)와 `tool_result`(id·본문·`is_error`)가 짝을 이룬다. 호출과 결과가
  다 남는다.
- **Codex** — `~/.codex/sessions/<년>/<월>/<일>/rollout-<시각>-<uuid>.jsonl`. 훅 페이로드가
  `transcript_path` 로 그 경로를 직접 준다 (`subagent-start.command.input` 스키마의 필수 필드).
  행은 `{timestamp, type, payload}` 이고 호출은 `payload.type` 이 `function_call`(인자가 JSON 문자열)
  이거나 `custom_tool_call`(인자가 JS 한 토막), 결과는 각각 `*_output` 이다. 종료 코드는 본문 머리의
  `Process exited with code N` 으로만 온다 — `is_error` 같은 표식이 없다.
- **Cursor** — `~/.cursor/projects/<슬러그>/agent-transcripts/<대화-id>/<대화-id>.jsonl`. 페이로드에는
  경로가 없어서 대화 id 와 작업 디렉터리로 짚는다. 이 기록에는 **호출만** 남는다: 실측 21개 파일
  318행에서 나온 `tool_use` 블록 654개가 전부 `{type, name, input}` 이고 `tool_result` 도 id 도
  시각도 하나도 없다. 그래서 Cursor 기록은 무엇을 불렀는지 말할 수 있고 그것이 어떻게 끝났는지는
  말할 수 없다.

`read()` 가 내는 둘째 값이 그 차이를 진다. 결과를 못 읽는 호스트에서 성패를 주장하면 판정자에게
없는 사실을 주는 것이고, 그것은 기록을 아예 안 주는 것보다 나쁘다.

소비자가 둘이다. failure-tracker 는 실패한 호출만 골라 세고, verifier-context 는 판정자에게
"마지막 판정 이후 무엇이 돌았는가"를 넘긴다. 짝짓기와 파싱은 같은 일이라 여기 한 곳에만 둔다.
"""

from __future__ import annotations

import collections
import json
import os
import re
from typing import NamedTuple

TAIL = 4000  # 꼬리에서 볼 줄 수 — 한 턴이 아니라 판정 구간(워커 여러 턴)을 덮어야 한다

# 기록이 판정자에게 말해 줄 수 있는 깊이. 셋을 뭉치면 "안 돌렸다"와 "못 읽었다"가 같은 빈 목록이 된다.
MISSING = "missing"  # 파일이 없거나 못 열었다
UNKNOWN = "unknown"  # 열어서 JSON 은 읽혔는데 아는 호스트의 모양이 아니다
INVOCATIONS = "invocations"  # 무엇을 불렀는지만 남는다 (Cursor)
FULL = "full"  # 호출과 그 결과가 다 남는다 (Claude Code·Codex)

_EXIT = re.compile(r"^\s*(?:<tool_use_error>)?\s*(?:Error:\s*)?Exit code (\d+)")
# Codex 는 종료 코드를 본문 **머리말**에 한 줄로 적는다 (`Chunk ID`·`Wall time` 다음). 실측 4,572건
# 에서 이 줄은 전부 앞 200자 안에 있었고, 명령이 뱉은 글에서 우연히 같은 줄이 나오는 것을 피하려고
# 아래 `exit_code` 가 찾는 범위를 머리 400자로 묶는다.
_CODEX_EXIT = re.compile(r"^(?:Process|Script) exited with code (\d+)", re.M)
_CODEX_HEAD = 400


class Call(NamedTuple):
    """도구 호출 하나와 그 결과.

    `output` 은 결과 본문, `failed` 는 이 호출이 실패로 끝났다는 표식이다. `outcome_known` 이
    거짓이면 **결과 자체가 기록에 없다** — 그때 `failed=False` 는 "성공했다"가 아니라 "실패라고
    적힌 것이 없다"이고, 소비자는 성패를 주장하면 안 된다."""

    id: str
    tool: str
    request: dict
    output: str
    failed: bool
    ts: str
    outcome_known: bool = True


def _cursor_slug(path: str) -> str:
    """Cursor 가 작업 디렉터리로 짓는 프로젝트 폴더 이름.

    규칙은 cursor-agent 번들의 `workspace-paths.js` 에 있는 그대로다: 영숫자가 아닌 글자를 전부
    `-` 로 바꾸고, 이어진 `-` 를 하나로 줄이고, 양끝의 `-` 를 뗀다."""
    return re.sub(r"-+", "-", re.sub(r"[^a-zA-Z0-9]", "-", path)).strip("-")


def _cursor_file(data: dict, base: str) -> str:
    """Cursor 대화 기록의 경로 — 없으면 빈 문자열.

    subagentStart 페이로드는 `conversation_id` 와 `parent_conversation_id` 를 둘 다 들고 오고,
    어느 쪽이 판정 대상 세션인지는 페이로드만 봐서는 안 갈린다. 그래서 둘을 차례로 짚어 **실제로
    있는 파일**을 쓴다 — 값은 stat 두 번이다."""
    cwd = str(data.get("cwd") or "").strip() or os.getcwd()
    folder = os.path.join(base, ".cursor", "projects", _cursor_slug(cwd), "agent-transcripts")
    for key in ("conversation_id", "parent_conversation_id"):
        chat = str(data.get(key) or "").strip()
        if chat:
            path = os.path.join(folder, chat, chat + ".jsonl")
            if os.path.exists(path):
                return path
    return ""


def session_file(data: dict, home: str = "") -> str:
    """이 세션의 기록 경로 — 페이로드가 주면 그것, 없으면 세션 id 로 짚는다.

    SubagentStart 페이로드의 `session_id` 는 **부모 세션**의 것이다 (영수증 6건 실측:
    한 런의 worker·verifier 배차가 전부 같은 id 를 들고 있었다). 그래서 서브에이전트로 뜬
    판정자도 이 경로로 메인 세션 기록에 닿는다 — 자기 기록이 아니라 자기가 판정할 세션의 기록이
    필요하므로, 그것이 맞는 방향이다.

    Claude Code 와 Codex 는 `transcript_path` 를 직접 준다. Cursor 만 안 줘서 대화 id 로 짚는다.
    폴더 이름은 호스트가 작업 디렉터리로 만드는데 규칙이 서로 다르다: Claude Code 는 `/` 와 `_` 를
    `-` 로 바꾸고 (`/Users/y/develop/work_space/vn_onm/x` → `-Users-y-develop-work-space-vn-onm-x`,
    실측), Cursor 는 영숫자가 아닌 글자를 전부 `-` 로 바꾼 뒤 줄인다."""
    given = str(data.get("transcript_path") or "").strip()
    if given:
        return given
    base = home or os.path.expanduser("~")
    cursor = _cursor_file(data, base)
    if cursor:
        return cursor
    session = str(data.get("session_id") or "").strip()
    cwd = str(data.get("cwd") or "").strip()
    if not session or not cwd:
        return ""
    slug = cwd.replace("/", "-").replace("_", "-")
    return os.path.join(base, ".claude", "projects", slug, session + ".jsonl")


def tail_rows(path: str, limit: int = TAIL) -> list[dict]:
    """기록 꼬리의 행 목록 — 못 읽거나 찢어진 줄은 조용히 빠진다.

    부분 관측이 무관측보다 낫다: 한 줄이 깨졌다고 나머지를 버리면 그 세션의 실행 기록이 통째로
    사라지고, 이 층의 소비자는 전부 fail-open 이라 그 사실조차 안 보인다."""
    if not path:
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = list(collections.deque(handle, maxlen=limit))
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _blocks(row: dict) -> list:
    message = row.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, list) else []


def block_text(content: object) -> str:
    """결과 본문에서 사람이 읽는 글만 — 문자열이면 그대로, 블록 목록이면 이어 붙인다."""
    if isinstance(content, str):
        return content.strip()
    parts = [str(b.get("text") or "") for b in (content if isinstance(content, list) else []) if isinstance(b, dict)]
    return " ".join(p for p in parts if p).strip()


def host_of(rows: list[dict]) -> str:
    """이 행 묶음을 적은 호스트 — 못 알아보면 빈 문자열.

    셋을 가르는 것은 행의 최상위 모양이지 도구 블록이 아니다. 도구를 한 번도 안 부른 기록도
    호스트는 알아봐야 하고, 그때 블록으로 재면 "형식을 모른다"가 나와 못 읽은 것과 뭉쳐진다.

    `payload` 가 딕셔너리인 행은 Codex 뿐이고(`{timestamp, type, payload}`), 최상위에 `role` 이 있는
    행은 Cursor 뿐이다 — Claude Code 의 `role` 은 `message` 안에 있다. 남는 것이 Claude Code 다.

    Cursor 는 턴이 끝날 때 `turn_ended` 한 줄을 더 적는데, 한 번도 도구를 못 부르고 끝난 세션은
    그 줄만 남는다 (실측: 사용량 상한에 걸려 끝난 기록 하나가 그 모양이다). 그 줄을 안 세면 그런
    기록이 "형식을 모른다"로 떨어져, 아무것도 안 돌린 사실이 판독기 탓으로 보고된다."""
    for row in rows:
        if isinstance(row.get("payload"), dict):
            return "codex"
        if isinstance(row.get("role"), str) and isinstance(row.get("message"), dict):
            return "cursor"
        if row.get("type") == "turn_ended":
            return "cursor"
        if isinstance(row.get("message"), dict):
            return "claude-code"
    return ""


def _claude_calls(rows: list[dict]) -> list[Call]:
    """Claude Code 기록의 짝지어진 호출 목록 — 기록 순서 그대로.

    이름과 인자는 assistant 의 `tool_use` 에, 결과는 뒤따르는 `tool_result` 에 있고 둘을 잇는 것은
    `tool_use_id` 다. 짝을 못 찾은 결과는 뺀다 — 이름 없는 호출은 어느 쪽 소비자에게도 못 쓴다."""
    requested: dict[str, tuple[str, dict]] = {}
    found: list[Call] = []
    for row in rows:
        stamp = str(row.get("timestamp") or "")
        for block in _blocks(row):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("id"):
                payload = block.get("input")
                requested[str(block["id"])] = (
                    str(block.get("name") or ""),
                    payload if isinstance(payload, dict) else {},
                )
            elif block.get("type") == "tool_result":
                use_id = str(block.get("tool_use_id") or "")
                name, request = requested.get(use_id, ("", {}))
                if use_id and name:
                    found.append(
                        Call(
                            use_id, name, request, block_text(block.get("content")), bool(block.get("is_error")), stamp
                        )
                    )
    return found


# 패치 한 덩이가 건드리는 파일과 그 동작. Codex 의 `apply_patch` 와 Cursor 의 `ApplyPatch` 가 같은
# 문법을 쓰므로 판독기 하나가 둘을 다 본다.
_PATCH_VERBS = {"Add File": "Write", "Update File": "Edit", "Delete File": "Delete"}
_PATCH_LINE = re.compile(r"^\*\*\* (Add File|Update File|Delete File): (.+)$", re.M)


def _patch_targets(body: str) -> list[tuple[str, str]]:
    """`*** Begin Patch` 본문이 건드리는 `(도구, 경로)` 목록."""
    return [(_PATCH_VERBS[verb], path.strip()) for verb, path in _PATCH_LINE.findall(body or "")]


# 호스트마다 셸 도구 이름이 다르다. 소비자는 Claude Code 의 어휘(`Bash`·`Write`·`Edit`)로 읽으므로
# 번역은 판독기가 진다 — 그래야 소비자가 호스트를 몰라도 된다.
_CODEX_SHELL = {"exec_command", "shell", "local_shell", "container.exec"}
# Cursor 의 `AwaitShell` 은 여기 없다 — 이미 띄운 셸을 기다리는 호출이라 `{block_until_ms, shell_id}`
# 만 들고 명령문이 없다. 셸로 세면 판정자의 명령 목록에 빈 줄이 생긴다 (실측 5건).
_CURSOR_SHELL = {"Shell"}


def _codex_command(name: str, body: str) -> str:
    """Codex 호출 인자에서 실제로 돌린 명령문 — 못 뽑으면 빈 문자열.

    `exec_command` 는 인자가 JSON 이라 `cmd` 를 그대로 읽는다. 압도적으로 많은 `exec`(실측
    12,922건)는 인자가 JS 한 토막이고 명령은 그 안의 `tools.exec_command({...})` 인자에 있다 —
    여는 중괄호부터 JSON 을 한 덩이 떼어 읽는다 (정규식으로 긁지 않는다: 명령문 안의 중괄호가
    그대로 들어 있다). 못 떼면 스크립트 전체를 명령으로 남긴다. 그것이 실제로 돌아간 것이다."""
    if name in _CODEX_SHELL:
        try:
            args = json.loads(body)
        except ValueError:
            return body
        return str(args.get("cmd") or args.get("command") or "") if isinstance(args, dict) else body
    head = body.find("exec_command(")
    if head < 0:
        return body
    brace = body.find("{", head)
    if brace < 0:
        return body
    try:
        args, _ = json.JSONDecoder().raw_decode(body[brace:])
    except ValueError:
        return body
    return str(args.get("cmd") or args.get("command") or "") if isinstance(args, dict) else body


def _codex_output(payload: dict) -> str:
    """`*_output` 행의 본문 — 문자열이거나 텍스트 블록 목록이다."""
    out = payload.get("output")
    return out.strip() if isinstance(out, str) else block_text(out)


def _codex_calls(rows: list[dict]) -> list[Call]:
    """Codex rollout 의 호출 목록.

    `is_error` 에 해당하는 표식이 없어서 성패는 본문 머리의 종료 코드로만 안다. 그 줄이 없으면
    `outcome_known=False` 로 남긴다 — `exec` 는 JS 래퍼가 안쪽 종료 코드를 안 실어서 실측
    13,090건이 이 자리에 온다. 여기서 성공으로 접으면 판정자가 안 확인된 초록을 읽는다."""
    requested: dict[str, tuple[str, str, str]] = {}
    found: list[Call] = []
    for row in rows:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        kind, call_id = payload.get("type"), str(payload.get("call_id") or "")
        stamp = str(row.get("timestamp") or "")
        if not call_id:
            continue
        if kind == "function_call":
            requested[call_id] = (str(payload.get("name") or ""), str(payload.get("arguments") or ""), stamp)
        elif kind == "custom_tool_call":
            requested[call_id] = (str(payload.get("name") or ""), str(payload.get("input") or ""), stamp)
        elif kind in ("function_call_output", "custom_tool_call_output"):
            name, body, when = requested.get(call_id, ("", "", ""))
            if not name:
                continue
            output = _codex_output(payload)
            code = exit_code(output)
            known = code is not None or never_ran(output)
            when = when or stamp
            targets = _patch_targets(body) if name == "apply_patch" else []
            if targets:
                found.extend(
                    Call("%s#%d" % (call_id, i), tool, {"file_path": path}, output, bool(code), when, known)
                    for i, (tool, path) in enumerate(targets)
                )
                continue
            tool = "Bash" if name in _CODEX_SHELL or name == "exec" else name
            request = {"command": _codex_command(name, body)} if tool == "Bash" else {"body": body}
            found.append(Call(call_id, tool, request, output, bool(code), when, known))
    return found


def _cursor_calls(rows: list[dict]) -> list[Call]:
    """Cursor 기록의 호출 목록 — 결과 없이 호출만.

    이 기록에는 `tool_result` 도 호출 id 도 시각도 없다 (실측 21개 파일 318행 전수). 그래서 모든
    호출이 `outcome_known=False` 이고 `ts` 가 비어 있다. id 는 순번으로 짓는다 — 소비자가 중복
    제거에 쓰는 자리라 비워 두면 서로 다른 호출이 한 호출로 뭉친다.

    인자는 두 모양뿐이다: 도구 605건은 JSON 객체로 오고, `ApplyPatch` 49건만 `*** Begin Patch`
    본문이 날 문자열로 온다 (실측 tool_use 블록 654건 전수)."""
    found: list[Call] = []
    for row in rows:
        for block in _blocks(row):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name, raw = str(block.get("name") or ""), block.get("input")
            request = raw if isinstance(raw, dict) else {}
            index = len(found)
            if name == "ApplyPatch":
                found.extend(
                    Call("cursor-%d-%d" % (index, i), tool, {"file_path": path}, "", False, "", False)
                    for i, (tool, path) in enumerate(_patch_targets(raw if isinstance(raw, str) else ""))
                )
                continue
            if name in _CURSOR_SHELL:
                tool, args = "Bash", {"command": str(request.get("command") or "")}
            elif name in ("Write", "Delete"):
                tool, args = name, {"file_path": str(request.get("path") or "")}
            else:
                tool, args = name, request
            found.append(Call("cursor-%d" % index, tool, args, "", False, "", False))
    return found


_READERS = {"claude-code": _claude_calls, "codex": _codex_calls, "cursor": _cursor_calls}


def calls(rows: list[dict]) -> list[Call]:
    """짝지어진 도구 호출 목록 — 기록 순서 그대로, 호스트를 가려 읽는다."""
    reader = _READERS.get(host_of(rows))
    return reader(rows) if reader else []


def read(path: str, limit: int = TAIL) -> tuple[list[Call], str]:
    """`(호출 목록, 이 기록이 말해 줄 수 있는 깊이)`.

    둘째 값이 있는 이유: 못 읽은 것·형식을 모르는 것·결과가 안 남는 것·다 남는 것 넷이 전부 빈
    목록이나 표식 없는 목록으로 뭉개지는데, 판정자에게는 서로 완전히 다른 사실이다. `Commands (0)`
    은 "안 돌렸다"로 읽히므로 나머지 셋을 그렇게 보여 주면 없는 사실을 주는 것이다."""
    rows = tail_rows(path, limit)
    if not rows:
        return [], MISSING
    host = host_of(rows)
    if not host:
        return [], UNKNOWN
    return _READERS[host](rows), INVOCATIONS if host == "cursor" else FULL


# 호스트의 권한 층이 실행 전에 거절할 때 쓰는 문구. 우리 코드가 아니라 늘어날 수 있다 —
# 실측 기록 3,512건에서 관측된 것이 전부이고, 호스트가 문구를 바꾸면 여기서 새 것이 빠진다.
_HOST_REFUSALS = (
    "This command requires approval",
    "This Bash command contains multiple operations",  # 부분 승인 요구 — 실측 20건
    "The user doesn't want to proceed",
    "Blocked:",
    "Permission to use ",
    "Command blocked by PreToolUse hook",  # Codex — 가드 문구를 자기 머리말 뒤에 붙인다
)

# 아스가르드 가드 여섯이 전부 이것으로 자기를 밝힌다. 근거는 소스 전수 확인이다 (readonly_guard
# :83·142·153·154, secret_guard:355·363·372, git_guard:368, budget_guard:437, subagent_gate:184,
# release_guard:197). 시험은 그중 readonly_guard 의 뿌리 밖 거절 하나만 실물로 잡는다 —
# 나머지 다섯이 여는 말을 바꾸면 시험은 통과하고 그 거절이 도구 실패로 세어진다.
GUARD_OPENER = "Asgard "


def never_ran(text: str) -> bool:
    """실행되기 전에 거절된 호출인가 — 그렇다면 도구 실패가 아니다.

    가드가 막은 호출은 기록에 실패한 호출과 똑같은 모양(`is_error` tool_result)으로 남는다.
    그런데 가드 자신의 문구가 말하듯 그 명령은 **한 번도 실행되지 않았다**. 그것을 Canon 9 로
    세면 없는 루프를 신고한다 — 26-08-12 에 failure-tracker 가 배포 15분 만에 실제로 그렇게 했다:
    16분에 걸쳐 서로 다른 명령이 세 번 막혔고(막힐 때마다 접근을 바꿨다) 거절문의 앞 80자가 같은
    상용구라 시그니처가 셋을 한 키로 뭉쳐 THINKER_REPLAN 이 걸렸다. 실물 기록 3,512건 중 1,525건
    (43%)이 이런 거절이다 — 거르지 않으면 세는 것의 절반 가까이가 안 돈 호출이다.

    저자는 둘뿐이다. **아스가르드 가드**는 여섯 훅이 전부 `Asgard ` 로 열고, 근거는 소스 전수
    확인이다. **호스트의 권한 층**은 우리 코드가 아니라 닫을 수 없다 — `_HOST_REFUSALS` 는
    실측에서 뽑은 것이고 호스트가 문구를 바꾸면 새 모양이 빠진다. 어느 쪽이든 값은 거짓 신고다.

    판정자 쪽 소비자는 이것을 "세지 않을 이유"가 아니라 **표식**으로 쓴다 — 막힌 호출은 실패가
    아니지만 판정자는 그것이 있었다는 사실을 알아야 한다 (워커가 무엇을 시도했는지의 일부다)."""
    body = text.lstrip()
    if body.startswith("<tool_use_error>"):
        body = body[len("<tool_use_error>") :].lstrip()
    if body.startswith("PreToolUse:") and "hook error" in body:
        return True  # 호스트가 훅 거절에 붙이는 머리말
    return body.startswith(GUARD_OPENER) or body.startswith(_HOST_REFUSALS)


def exit_code(output: str) -> int | None:
    """본문에서 읽히는 종료 코드 — 없으면 None.

    Claude Code 는 **비영 종료일 때만** 본문 머리에 `Exit code N` 을 붙이고, Codex 는 성패와 무관
    하게 머리말에 `Process exited with code N` 을 적는다. 그래서 None 은 "성공"이 아니라 "종료
    코드를 이 본문에서 읽을 수 없다"는 뜻이고, 그 뜻이 `Call.outcome_known` 으로 따로 나간다."""
    body = output or ""
    hit = _EXIT.match(body)
    if hit:
        return int(hit.group(1))
    hit = _CODEX_EXIT.search(body[:_CODEX_HEAD])
    return int(hit.group(1)) if hit else None
