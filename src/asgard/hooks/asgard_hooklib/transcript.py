"""세션 기록 읽기 — 호스트가 훅을 부르든 말든 디스크에 남는 정본.

훅 페이로드에는 호스트가 주기로 한 것만 들어 있다. 무엇이 **실제로 돌았는지**는 이 파일에 있다:
Claude Code 가 세션마다 JSONL 을 한 줄씩 적고, 도구 호출(`tool_use`)과 그 결과(`tool_result`)가
짝으로 들어간다. 그래서 페이로드가 비거나 아예 안 불린 자리도 여기서는 관측된다 — 26-08-12 에
failure-tracker 의 Canon 9 레인을 되살린 근거가 그것이고, budget-guard 가 토큰을 재는 근거도
같은 파일이다.

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

_EXIT = re.compile(r"^\s*(?:<tool_use_error>)?\s*(?:Error:\s*)?Exit code (\d+)")


class Call(NamedTuple):
    """도구 호출 하나와 그 결과. `output` 은 결과 본문, `failed` 는 호스트가 붙인 오류 표식이다."""

    id: str
    tool: str
    request: dict
    output: str
    failed: bool
    ts: str


def session_file(data: dict, home: str = "") -> str:
    """이 세션의 기록 경로 — 페이로드가 주면 그것, 없으면 세션 id 로 짚는다.

    SubagentStart 페이로드의 `session_id` 는 **부모 세션**의 것이다 (영수증 6건 실측:
    한 런의 worker·verifier 배차가 전부 같은 id 를 들고 있었다). 그래서 서브에이전트로 뜬
    판정자도 이 경로로 메인 세션 기록에 닿는다 — 자기 기록이 아니라 자기가 판정할 세션의 기록이
    필요하므로, 그것이 맞는 방향이다.

    폴더 이름은 호스트가 작업 디렉터리로 만든다: `/` 와 `_` 가 전부 `-` 가 된다
    (`/Users/y/develop/work_space/vn_onm/x` → `-Users-y-develop-work-space-vn-onm-x`, 실측)."""
    given = str(data.get("transcript_path") or "").strip()
    if given:
        return given
    session = str(data.get("session_id") or "").strip()
    cwd = str(data.get("cwd") or "").strip()
    if not session or not cwd:
        return ""
    slug = cwd.replace("/", "-").replace("_", "-")
    base = home or os.path.expanduser("~")
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


def calls(rows: list[dict]) -> list[Call]:
    """짝지어진 도구 호출 목록 — 기록 순서 그대로.

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


# 호스트의 권한 층이 실행 전에 거절할 때 쓰는 문구. 우리 코드가 아니라 늘어날 수 있다 —
# 실측 기록 3,512건에서 관측된 것이 전부이고, 호스트가 문구를 바꾸면 여기서 새 것이 빠진다.
_HOST_REFUSALS = (
    "This command requires approval",
    "This Bash command contains multiple operations",  # 부분 승인 요구 — 실측 20건
    "The user doesn't want to proceed",
    "Blocked:",
    "Permission to use ",
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
    """본문 머리의 `Exit code N` — 없으면 None.

    호스트는 **비영 종료일 때만** 이 머리말을 붙인다. 그래서 None 은 "성공"이 아니라 "종료 코드를
    이 본문에서 읽을 수 없다"는 뜻이고, 성공 여부는 `Call.failed` 가 따로 진다."""
    hit = _EXIT.match(output or "")
    return int(hit.group(1)) if hit else None
