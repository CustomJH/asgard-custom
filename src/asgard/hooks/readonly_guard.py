#!/usr/bin/env python3
"""Read-only Bash policy shared by native execution and Claude Code role hooks.

The policy is deliberately allowlist-based. Unknown commands are mutating until proven
otherwise. This does not try to understand arbitrary shell programs; it only admits
inspection commands and bounded verification runners without shell write syntax.
"""

from __future__ import annotations

import json
import os
import shlex
import sys

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass

# 판정 본체는 훅과 함께 깔리는 공용 라이브러리에 있다. 여기 남은 것은 훅 표면이다 — 호스트
# 프로토콜(차단 응답)과 거부 사유 문장. `F401` 이 붙은 줄은 이 파일이 안 쓰지만 밖에서
# `asgard.hooks.readonly_guard.<이름>` 으로 집는 이름이다 (네이티브 tool_kernel·REPL·시험).
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.firing import run  # noqa: E402
from asgard_hooklib.policy import READ_ONLY_ROLES  # noqa: E402
from asgard_hooklib.readonly import (  # noqa: E402
    READONLY_BASH_HINT,
    READONLY_WRITE_HINT,
    is_index_only_git,
    is_readonly_bash_safe,
)
from asgard_hooklib.session import unattended  # noqa: E402
from asgard_hooklib.shell import (  # noqa: E402
    _DISCARD_REDIRECTION,
    command_targets_control,
    drop_inert_operands,
    first_escaping_operand,
    lex,
    mutation_signal,
    scannable_text,
    without_heredoc_bodies,
)
from asgard_hooklib.shell import (  # noqa: E402
    segments as _segments,
)
from asgard_hooklib.workspace import (  # noqa: E402
    _BOUNDARY_FILES,
    _CONTROL_PATHS,
    _PRIVATE_CONTROL_PATHS,
    _resolve_token,
    _within_host_state,
    _within_unit_workspace,
    _without_workspace,
    enclosing_project,
    path_token_targets_control,
    path_token_within_root,
    within_managed_map,
    work_roots,
)

_READONLY_AGENTS = READ_ONLY_ROLES  # 정본은 공용 라이브러리 하나다 — 훅마다 사본을 들지 않는다

# 이 호스트에서 오딘에게 묻는 방법. 거부문이 "물어보라"고만 하면 물을 채널이 있는 모드에서도
# 에이전트가 묻지 않고 멈추거나 혼자 넘어간다 — 무엇으로 묻는지까지 말해야 실행 가능한 처방이다.
_ASK_CHANNELS = {"claude": "Ask Odin with the AskUserQuestion tool"}
_ASK_DEFAULT = "Ask Odin in your reply and wait for the answer"


def _deny(protocol: str, message: str) -> None:
    """차단 응답 — Cursor는 permission JSON, Claude Code/Codex는 exit 2 + stderr (git-guard와 동일 규약)."""
    if protocol == "cursor":
        sys.stdout.write(
            json.dumps({"permission": "deny", "user_message": message, "agent_message": message}, ensure_ascii=False)
        )
        raise SystemExit(0)
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _escape_refusal(tool_name: str, target: str, path: str, roots: tuple[str, ...], protocol: str, alone: bool) -> str:
    """뿌리 밖 차단의 문장 — 실행할 명령만으로는 처방이 안 끝나는 유일한 사유다.

    어느 디렉터리를 열지(`enclosing_project`), 무엇으로 물을지(`_ASK_CHANNELS`), 물을 사람이 없을
    때 어떻게 할지(Canon 8), 그리고 그 자리가 아직 없으면 먼저 만들라는 것까지 한 문장에 담아야
    읽는 쪽이 왕복 한 번으로 끝낸다. 지목하는 자리는 `commands.workroots.run_root_add` 가 받아
    주는 자리여야 한다 — 어긋나면 오딘의 승인을 받아 낸 뒤에 명령이 실패한다 (26-08-11 판정이
    두 형상에서 재현했다: 세션 뿌리를 품는 조상, 아직 없는 디렉터리)."""
    listed = ", ".join(roots[:4]) or "(none)"
    opening = f"Asgard workspace policy blocked {tool_name} on a path outside every work root: {target}\n"
    directory = enclosing_project(path, roots)
    if not directory:
        return (
            f"{opening}Work roots in force: {listed}. No declaration reaches that path: every directory "
            "containing it also contains this session's root (or is your home directory), and opening one "
            "of those would pull in every repository beside it. Open that project as its own session — "
            "start Asgard with it as the working directory — and do the work there."
        )
    decide = (
        f"Nobody is in the approval loop here, so Canon 8 applies: run it yourself and say in your "
        f"report that you opened {directory}"
        if alone
        else f"{_ASK_CHANNELS.get(protocol, _ASK_DEFAULT)} — may agents edit files under {directory}? — then run it"
    )
    # 아직 없는 자리는 `run_root_add` 가 거절한다 — 만드는 줄이 처방에 없으면 승인을 받아 낸
    # 뒤에 명령이 exit 2 로 끊긴다.
    declaration = f"asgard root add {directory} --yes"
    if not os.path.isdir(directory):
        declaration = f"mkdir -p {directory} && {declaration}"
    return (
        f"{opening}Work roots in force: {listed}. Widening them is Odin's call. {decide}:\n"
        f"  {declaration}\n"
        'That writes {"paths": {"additional_roots": [...]}} into .asgard/asgard-setting-project.json, '
        "the file all four modes read. Do not write that file or .claude/settings.json by hand — the "
        "control-surface rule blocks both, so this command is the only way in. A blocked path never "
        "changed — declare the root instead of retrying a variant."
    )


def _refusal(
    reason: str,
    tool_name: str,
    command: str,
    path: str,
    roots: tuple[str, ...] = (),
    protocol: str = "claude",
    alone: bool = False,
) -> str:
    """거부 사유 문장 — 실제 규칙과 도구에 맞아야 가르친다.

    통제 표면 차단에 "읽기전용 역할" 문장을 붙이면 쓰기 권한이 있는 역할이 자기 신원을 의심하며
    턴을 태우고, Edit 차단에 Bash 허용목록을 붙이면 없는 레인을 찾는다 (26-07-26 실측).
    하네스 상태 차단과 뿌리 밖 차단도 사유가 다르다: 전자는 아무도 못 고치는 자리라 처방이
    `asgard init/sync`고, 후자는 선언 한 줄로 열리는 자리라 처방이 그 선언이다. 둘을 한 문장으로
    묶어 두면 열 수 있는 차단이 못 여는 차단처럼 읽힌다 (26-08-04 실측).

    처방은 **여기서 실행할 수 있는 것**이어야 한다. 뿌리 밖 차단이 설정 파일 편집만 지목하던
    동안 그 파일은 바로 아래 통제 표면 규칙이 막고 있었고, 둘이 맞물려 교착이 됐다 (26-08-07
    실측: 짝 저장소 편집 차단 → 처방대로 연 설정 파일 편집도 차단). 그래서 두 사유 모두
    `asgard root add` 를 지목한다.

    뿌리 밖 차단은 나머지 셋과 달리 **오딘이 정할 일**을 담고 있어 문장이 따로 산다 —
    `_escape_refusal`."""
    target = command[:160] if tool_name == "Bash" else (path[:160] or "(no path)")
    if reason == "escape":
        return _escape_refusal(tool_name, target, path, roots, protocol, alone)
    if reason == "control":
        return (
            f"Asgard control-surface policy blocked {tool_name}: {target}\n"
            "Harness state (.asgard/, except the shared map .asgard/map/*.md) and the two files "
            "that define this guard's work roots (.claude/settings.json, .claude/settings.local.json) "
            "are not work targets: the verdict's physical diff does not cover them, so a write there "
            "leaves no evidence. Change them through Asgard's own commands: `asgard init` / `asgard sync`, "
            "and `asgard root add <dir> --yes` to declare a work root outside this repo. "
            "Staging and committing them is allowed (git add / git commit) — that is what puts them "
            "inside the diff. The rest of .claude/.cursor/.codex/.agents is an ordinary work target — "
            "edit it directly."
        )
    if tool_name == "Bash":
        return f"Asgard read-only role policy blocked mutating or unclassified Bash: {target}\n{READONLY_BASH_HINT}"
    return f"Asgard read-only role policy blocked a file write via {tool_name}: {target}\n{READONLY_WRITE_HINT}"


def _allow(protocol: str) -> None:
    """Cursor는 침묵을 허용으로 안 본다 — 명시적 allow가 프로토콜 요구사항 (git-guard와 동일)."""
    if protocol == "cursor":
        sys.stdout.write(json.dumps({"permission": "allow"}, separators=(",", ":")))
    raise SystemExit(0)


_WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}


def _writer_reaches(command: str, roots: tuple[str, ...], markers: tuple[str, ...]) -> bool:
    """이 표식의 경로를 인자로 받는 조각 중 읽기로 인정되지 않는 것이 있는가.

    판정 단위가 명령 전체가 아니라 **조각**인 것이 요점이다. 여는 것은 그 경로를 받는 한
    조각이고, 뒤에 붙은 필터는 아무것도 안 연다 — 파이프 끝의 `sort` 한 마디 때문에 기장을
    세는 `grep` 이 위조 시도로 읽히던 자리다 (26-08-13).

    "무엇이 쓰기인가"를 이름 목록으로 물으면 목록 밖의 제자리 편집기가 그대로 지나간다:
    `sed -i` 는 막히고 `gsed -i` 는 통과하는 갈림이 실제로 났다 (26-08-13 판정). 그래서 묻는
    방향을 뒤집는다 — 읽기로 **증명된** 조각만 놓아주고 나머지는 여는 것으로 본다. 그 증명은
    이 저장소의 허용목록 판정기(`is_readonly_bash_safe`) 하나가 쥔다.

    조각을 자르는 어휘는 `command_targets_control` 과 같아야 한다 — 히어독을 못 벗기는 분해기로
    자르면 본문에 스친 한 마디 때문에 명령 전체가 미분류로 떨어진다.

    폐기 리다이렉션은 자르기 **전에** 뗀다. `lex` 는 `2>/dev/null` 을 세 토큰으로 내고, 그것을
    `shlex.join` 으로 다시 붙이면 꺾쇠가 인용돼 안쪽 판정기가 리다이렉션으로 못 읽는다 —
    `/dev/null` 이 뿌리 밖 경로 인자로 남아, 원문이면 읽기로 인정될 조각이 재조립 뒤 미분류가
    된다 (26-08-13 2차 판정이 잡은 반례). 버리는 리다이렉션은 파일을 만들지 않으므로 떼도
    판정이 달라지지 않고, 실제로 파일을 만드는 `> path` 는 그대로 남아 미분류로 떨어진다."""
    try:
        tokens = drop_inert_operands(lex(without_heredoc_bodies(_DISCARD_REDIRECTION.sub("", command))))
    except ValueError:
        return True  # 못 읽는 글은 좁히지 않는다
    for part in _segments(tokens):
        if not any(path_token_targets_control(roots, token, markers) for token in part[1:]):
            continue
        if not is_readonly_bash_safe(shlex.join(part), roots=roots):
            return True
    return False


def _reaches_foreign_harness_state(command: str, roots: tuple[str, ...]) -> bool:
    """남의 저장소의 하네스 상태를 만지는가 — 뿌리 밖 이탈로 진단할 자리.

    종전에는 이 진단이 통제 표면 갈래를 타고 나왔는데, 그 갈래가 쓰기 신호를 요구하게 되면서
    읽기 형태가 아무 진단 없이 통과하게 됐다 (26-08-13). 통제 표면 이름이 보이는 명령으로만
    좁힌다 — 뿌리 밖 경로 전부를 여기서 막으면 호스트 세션 디렉터리를 읽는 것까지 끊긴다."""
    scannable = _without_workspace(scannable_text(command).replace("\\", "/"))
    if not any(marker in scannable for marker in _CONTROL_PATHS + _PRIVATE_CONTROL_PATHS):
        return False
    return bool(first_escaping_operand(roots, command))


def _forgery_surface_access(
    tool_name: str, command: str, normalized_path: str, path: str, roots: tuple[str, ...], readonly_shell: bool
) -> bool:
    """기장·영수증·상태(`_PRIVATE_CONTROL_PATHS`)에 닿는가 — **위조를 막는 자리**라 넓은 표식보다
    그물이 촘촘하다.

    경로 인자로 안 풀리는 토큰도 나중에 실행돼 기장을 쓸 수 있어서 (`python -c "$PAYLOAD"`)
    명령문 텍스트까지 본다. 그 텍스트에서 실행되지 않는 자리만 뺀다 — `scannable_text`.
    읽기 전용 레인은 먼저 빠진다: 여기를 지키는 것은 위조 방지이지 열람 금지가 아닌데, 예외가
    없던 판에서는 `ls .asgard/quest/` 한 줄도 막혔다 (26-08-04 실측 4회)."""
    if any(marker in normalized_path for marker in _PRIVATE_CONTROL_PATHS):
        return True
    if path_token_targets_control(roots, path, _PRIVATE_CONTROL_PATHS):
        return True
    if tool_name != "Bash" or readonly_shell:
        return False
    # 기장 경로를 인자로 받는 **세그먼트가 읽기인가**를 본다. 명령 전체가 읽기 전용으로
    # 인정되는지만 보면, 파이프 끝에 `sort` 한 마디가 붙었다는 이유로 기장을 세는 `grep` 이
    # 위조 시도로 읽힌다 (26-08-13 평가에서 재현). 반대로 미지의 프로그램이 그 경로를 인자로
    # 받는 형태(`./w -m .asgard/quest/f.jsonl`)는 여기서 그대로 걸린다.
    if _writer_reaches(command, roots, _PRIVATE_CONTROL_PATHS):
        return True
    # 글자로만 보이는 자리는 **고칠 수 있는 연산이 있을 때만** 막는다. 여기는 위조를 막는
    # 자리이지 열람을 막는 자리가 아닌데, 그 구분이 없던 판에서는 기장을 세기만 하는 스크립트가
    # 차단됐다 (26-08-13 평가에서 재현).
    if not mutation_signal(command):
        return False
    scannable = _without_workspace(scannable_text(command).replace("\\", "/"))
    return any(marker in scannable for marker in _PRIVATE_CONTROL_PATHS)


def refusal_reason(tool_name: str, command: str, path: str, roots: tuple[str, ...], agent: str) -> str:
    """이 호출을 막는다면 무엇 때문인가 — `control` · `escape` · `readonly`, 통과면 빈 문자열.

    정책 전부가 여기 한 자리에 있다 (`main`은 프로토콜만 다룬다). 규율은 세션이 아니라
    **역할**에 붙는다 (tool_kernel.ROLE_CAPABILITIES가 정본): worker 계열은 mutate를 갖고,
    thinker/verifier/loki/ullr/mimir은 안 갖는다. 신원이 없는 호출은 메인 세션이 전이 함수가
    배정한 역할을 직접 수행하는 자리(MAIN_WORKER)라 쓰기가 그 역할의 몫이다 — 신원 부재를
    읽기전용으로 읽으면 조율자가 자기 배정을 수행하지 못하고, 단위 티켓이 선언된 퀘스트에서는
    subagent-gate가 `[ASGARD_UNIT:<id>]` 없는 asgard-worker 디스패치도 거부하므로 우회로가
    남지 않는다 (양쪽 차단 = 교착). 퀘스트 없는 쓰기는 이 훅의 소관이 아니다 — write-sentinel이 기록하고 Stop의
    verifier-gate가 물리 대조로 잡는다. 같은 것을 두 시점에 재판하면 교착이 된다."""
    # 표식 부분문자열 검사는 스튜디오 작업 공간 접두사를 뺀 형태로 한다 — 그 폴더는 `.asgard`
    # 아래 있지만 하네스 상태가 아니라 작업 대상이다 (`_studio_workspace`).
    normalized_path = _without_workspace(os.path.normpath(path).replace("\\", "/"))
    # 하네스가 이 세션·이 프로젝트 몫으로 내준 자리와 공유 지도는 통제 표면이 아니라 작업
    # 대상이다. 경로에 `.claude` 가 들어 있다는 이유로 여기를 막으면 에이전트가 자기 기억과
    # 계측 산출물을 한 줄도 못 남긴다.
    harness_owned = bool(path) and (
        _within_host_state(os.path.realpath(os.path.expanduser(path)), roots)
        or _within_unit_workspace(os.path.expanduser(path), roots)
        or within_managed_map(roots, _resolve_token(roots, path) if roots else "")
    )
    # 넓은 표식이 `.asgard` 하나로 좁아졌으므로 `.claude/settings*.json` 은 여기서 따로 본다 —
    # 그 파일이 `work_roots()` 를 정하고, 정하는 자리를 열면 나머지 판정이 통째로 무의미해진다.
    control_write = (
        tool_name in _WRITE_TOOLS
        and not harness_owned
        and (
            any(marker in normalized_path for marker in _CONTROL_PATHS)
            or any(name in normalized_path for name in _BOUNDARY_FILES)
            or path_token_targets_control(roots, path, _CONTROL_PATHS)
        )
    )
    readonly_shell = tool_name == "Bash" and is_readonly_bash_safe(command, roots=roots, agent=agent)
    # 색인에만 닿는 git 호출은 이 갈래에서 뺀다 — 담는 것은 쓰기가 아니라 그 반대이고, 팀이
    # 함께 읽는 `.asgard` 자산은 커밋돼야 판정의 물리 대조가 덮는다. 뿌리를 정하는 파일도 같이
    # 뺀다: 색인에 담는 것은 그 파일을 고치는 것이 아니다. 기장·영수증·상태는 그대로 막힌다
    # (`_forgery_surface_access` 는 이 완화를 안 본다).
    index_only_git = tool_name == "Bash" and not readonly_shell and is_index_only_git(command, roots)
    # 통제 표면에 닿는 길이 둘이라 판정도 둘이다.
    #
    # ① **경로 인자로 풀린 자리** — 그 경로를 받는 조각이 읽기로 증명되는가로 가른다. 명령
    #    전체를 한 덩어리로 물으면 파이프 끝의 `sort` 한 마디가 기장을 세는 `grep` 을 쓰기로
    #    만들고, 반대로 "무엇이 쓰기인가"를 이름 목록으로 물으면 목록 밖 편집기가 그대로
    #    지나간다 — `sed -i` 는 막히고 `gsed -i` 는 통과했다 (26-08-13 판정이 잡은 반례).
    # ② **글자로만 보이는 자리** — 히어독 본문이나 인용 안 문자열. 경계 파일 셋만 여기서도
    #    찾는다: 그 파일들이 이 가드의 뿌리를 정하므로, 열리면 뒤이은 판정이 무엇을 기준으로
    #    했는지부터 무의미해진다. 이쪽은 고칠 수 있는 연산이 함께 보일 때만 막는다 — 이름을
    #    입에 올리는 것은 여는 것이 아닌데, 그 구분이 없던 판에서는 외부 도구에 넘긴 프롬프트가
    #    통제 표면 쓰기로 읽혔다 (같은 날 네 번 재현).
    boundary_text = tool_name == "Bash" and any(
        name in _without_workspace(scannable_text(command).replace("\\", "/")) for name in _BOUNDARY_FILES
    )
    control_shell_write = (
        tool_name == "Bash"
        and not readonly_shell
        and not index_only_git
        and (
            _writer_reaches(command, roots, _CONTROL_PATHS + _BOUNDARY_FILES)
            or (boundary_text and mutation_signal(command))
        )
    )
    if (
        _forgery_surface_access(tool_name, command, normalized_path, path, roots, readonly_shell)
        or control_write
        or control_shell_write
    ):
        # 통제 표면 차단은 **뿌리 안**의 자리를 두고 하는 말이다. 뿌리 밖 경로는 읽기 레인에서
        # 먼저 떨어지고, 그러면 위조 방지 그물의 글자 검사가 남의 저장소 경로에 스친 `.asgard`
        # 를 잡아 이 갈래로 흘려보낸다 — 사유도 처방도 틀린 차단이다. 경로 인자 판정으로도,
        # 경계 파일 글자로도 안 걸렸는데 뿌리 밖 경로가 있다면 그것이 진짜 사유다.
        if (
            tool_name == "Bash"
            and not boundary_text
            and not command_targets_control(roots, command, _CONTROL_PATHS + _PRIVATE_CONTROL_PATHS)
            and first_escaping_operand(roots, command)
        ):
            return "escape"
        return "control"
    if tool_name == "Bash" and not readonly_shell and _reaches_foreign_harness_state(command, roots):
        return "escape"
    if bool(path) and not path_token_within_root(roots, path):
        return "escape"
    if agent in _READONLY_AGENTS and (tool_name in _WRITE_TOOLS or (tool_name == "Bash" and not readonly_shell)):
        return "readonly"
    return ""


def main() -> None:
    protocol = sys.argv[1] if len(sys.argv) > 1 else "claude"
    try:
        data = json.load(sys.stdin)
        agent = str(data.get("agent_type") or data.get("agent_name") or data.get("subagent_type") or "")
        # Cursor beforeShellExecution은 command를 최상위에 싣고 tool_input이 없다 — git-guard와
        # 같은 판별자로 셸 페이로드를 Bash 호출로 정규화한다.
        if "tool_input" not in data and data.get("command") is not None:
            tool_name, tool_input = "Bash", {"command": data.get("command")}
        else:
            tool_name = str(data.get("tool_name") or "Bash")
            tool_input = data.get("tool_input") or {}
        command = str(tool_input.get("command") or "")
    except Exception:
        _allow(protocol)
        return
    root = str(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    roots = work_roots(root)
    path = str(tool_input.get("file_path") or tool_input.get("path") or tool_input.get("notebook_path") or "")
    reason = refusal_reason(tool_name, command, path, roots, agent)
    if reason == "escape" and not path:
        # Bash 호출의 payload 에는 경로 인자가 없다 — 이탈 문장이 지목할 디렉터리를 명령에서 뽑는다.
        path = first_escaping_operand(roots, command)
    if reason:
        _deny(protocol, _refusal(reason, tool_name, command, path, roots, protocol, unattended(data)))
    _allow(protocol)


if __name__ == "__main__":
    run("readonly-guard", main)
