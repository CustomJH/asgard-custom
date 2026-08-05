#!/usr/bin/env python3
"""Read-only Bash policy shared by native execution and Claude Code role hooks.

The policy is deliberately allowlist-based. Unknown commands are mutating until proven
otherwise. This does not try to understand arbitrary shell programs; it only admits
inspection commands and bounded verification runners without shell write syntax.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import tempfile

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass


_READONLY_AGENTS = {"asgard-thinker", "asgard-verifier", "asgard-loki", "asgard-ullr", "asgard-mimir"}
_PYTHON = {"python", "python3", "pypy", "pypy3"}

# 차단이 가르치지 않으면 모델은 같은 명령의 변형으로 턴을 태운다 (26-07-21 실측: Verifier가
# python3 -c 차단 후 히어독·TMPDIR·py_compile 변형 10여 회 순차 시도). 거부 사유에 항상 동봉.
READONLY_BASH_HINT = (
    "Read-only role Bash allowlist: inspection (ls/cat/grep/rg/find/stat/tree/wc), git reads "
    "(status/diff/log/show/grep/ls-files), verification runners (pytest/mypy/pyright/ty/ruff check/tsc "
    "--noEmit — including via uv|poetry|pipenv run, with value-less flags such as --no-project/--isolated/"
    "--frozen/--locked/--offline in between), python -m pytest|unittest|compileall|py_compile, "
    "python -c '<one-line smoke with no writes>', node --check <file>, node [--test] <tests/ script>, "
    "npm|pnpm|yarn test|lint|check, tests/ scripts. "
    "sed/awk without in-place writes. Allowed commands may be chained with `|`, `&&`, `||`, `;` "
    "(each segment is judged on its own), and `2>/dev/null` / `2>&1` / `< /dev/null` are fine. "
    'Shell loops of read-only commands are fine (`for f in a b; do wc -c "$f"; done`). '
    "Blocked: file writes, redirection to a file, heredocs, $()/backticks, paths outside the "
    "project (the harness's own isolated unit workspace and this session's scratchpad are allowed). "
    "A `$VAR` is fine as an operand, but not as the script of `python -c` / sed / awk — there the "
    "judged text is not the text that runs, so those lanes abstain. "
    "Use python -c with a literal snippet instead of a scratch file, and for a uv project (uv.lock) "
    "use `uv run pytest -x -q`. "
    "A blocked command never ran — switch straight to an allowed lane instead of retrying a variant."
)

# 쓰기 도구 거부 — 읽기전용 역할에는 쓰기 레인 자체가 없다. Bash 허용목록을 보여 주면 오히려
# "다른 명령으로 쓰면 되나"로 오독된다: 소유자를 가리키는 것이 유일한 처방이다.
READONLY_WRITE_HINT = (
    "Read-only roles never write files. Hand the change to a write-capable role instead "
    "(Worker/Freyja/Thor/Eitri), or report the required change in your verdict/findings."
)

# python -c 스니펫의 쓰기 표면 휴리스틱 — 이미 허용된 pytest도 임의 프로젝트 코드를 실행하므로
# 이 분기가 그보다 넓지 않다. 적대 봉쇄가 아니라 실수 방지: 명시적 쓰기·프로세스·네트워크 API가
# 보이면 fail-closed. 없으면 Verifier 계약(대표 함수 호출 스모크)의 유일한 실행 통로로 허용.
_PY_SNIPPET_MUTATION = re.compile(
    r"subprocess|os\.(?:system|popen|remove|unlink|rename|replace|rmdir|mkdir|makedirs|chmod|chown|truncate)"
    r"|shutil\.(?:rmtree|move|copy\w*|chown|make_archive|unpack_archive|disk_usage)"
    r"|write_text|write_bytes|\.write\s*\(|pickle\.dump|\bexec\s*\(|\beval\s*\("
    r"|open\s*\([^)]*['\"](?:[wax]b?\+?|[rb]+\+b?)['\"]"
    r"|\bsocket\b|urllib|requests|httpx"
)
_INSPECT = {
    "cat",
    "diff",
    "echo",  # stdout 전용 — 파일 리다이렉션은 _shell_parts가 이미 막는다
    "fd",
    "file",
    "find",
    "grep",
    "head",
    "ls",
    "printf",
    "pwd",
    "rg",
    "stat",
    "tail",
    "tree",
    "wc",
}
# sed 스크립트의 파일 접근 명령 — w/W(쓰기)·r/R(읽기)는 경로 검사를 우회하는 표면이라 함께 막는다
# (`sed '1w /tmp/leak'`·`sed '1r /etc/passwd'`). 낱글자 경계로만 잡아 단어 속 w/r은 통과한다.
_SED_WRITE = re.compile(r"(?<![A-Za-z])[wWrR](?![A-Za-z])")
# 셸 변수 참조 — 스크립트나 스니펫 안에 있으면 그 자리의 실제 내용을 이 훅은 못 본다.
# 텍스트를 읽어 판정하는 레인(python -c · sed · awk)은 이것을 만나면 기권한다 (fail-closed).
_SHELL_EXPANSION = re.compile(r"\$\{?[A-Za-z_]")
# awk 프로그램의 쓰기·실행·파일읽기 표면. 비교 연산자 `>`까지 함께 걸리지만 관측용 awk는 쓰지 않는다.
_AWK_WRITE = re.compile(r">|\bsystem\s*\(|\bclose\s*\(|\bgetline\b|\bENVIRON\b|\|")
_VERIFY = {"pytest", "mypy", "pyright", "ty"}
_GIT_READ = {"diff", "status", "log", "show", "grep", "ls-files", "rev-parse"}
# 색인에만 닿는 git 하위명령 — 작업 트리의 파일을 한 바이트도 안 바꾼다. 아래 통제 표면이
# 닫혀 있는 이유는 "거기 쓴 것이 판정의 물리 대조에 안 잡힌다" 인데, 색인에 담는 것은 그
# 반대다: 커밋 경계 안으로 들여 Odin 이 diff 로 보게 만든다. 무엇이 담기는지는 `.asgard`
# 자신의 무시 규칙이 이미 정해서 (퀘스트 로그·상태·배차 DB 는 무시된 채 남는다) 가드가 그
# 경계를 다시 적지 않는다. `rm` 은 뺐다 — `--cached` 없이 부르면 파일을 지운다.
_GIT_INDEX_ONLY = {"add", "commit"}
# 통제 표면 = **판정의 물리 대조가 못 보는 자리**. `diff_state` 의 diff 범위는
# `[base, current, "--", ".", ":(exclude).asgard"]` 라 `.asgard/**` 에 쓴 것은 판정 해시에
# 한 바이트도 안 들어간다 (영역 지도 `.asgard/map/*.md` 만 따로 다시 읽어 넣는다). 그 자리만
# 하드 블록으로 닫는다.
#
# `.claude`·`.cursor`·`.codex`·`.agents` 는 뺐다. 스냅샷 안에 있어서 거기 쓴 것은 판정 해시에
# 묶이고 Odin 이 diff 로 본다 — 대가는 훅 본문도 고칠 수 있게 된다는 것이고, 얻는 것은 스캐폴드가
# 곧 산출물인 저장소에서 관측·편집이 통째로 막히지 않는다는 것이다 (26-08-05: 한 세션의 첫 세
# 명령이 `wc -l .claude/hooks/*.py` 형태로 연속 차단됐다). 되돌리려면 이 tuple 에 이름을 되돌린다.
_CONTROL_PATHS = (".asgard",)
_HOOK_DIRS = (".claude/hooks/", ".cursor/hooks/", ".codex/hooks/")
_PRIVATE_CONTROL_PATHS = (".asgard/quest", ".asgard/receipts", ".asgard/state")
# 이 가드 **자신의 경계를 정하는** 파일들 (`work_roots` 가 읽는 그 파일들이다). 여기에 쓸 수
# 있으면 뿌리가 다시 정해져 나머지 판정이 통째로 무의미해진다. 넓은 표식과 달리 인자가 아닌
# 글에서도 찾고, `.claude/settings*.json` 은 넓은 표식이 더는 안 덮으므로 쓰기 도구 갈래도
# 이 목록으로 판정한다 — 히어독 본문에 담아 넘긴 쓰기까지 본다.
#
# 한계는 분명하다: 글자를 찾는 검사라 런타임에 조립한 경로(`'.claude/'+'settings.json'`)는 못
# 본다. 실수와 곧이곧대로의 쓰기를 막는 그물이지 적대 봉쇄가 아니다. 경로 모양으로 적어 두는
# 것도 그래서다 — 맨 파일명만 보면 그 이름을 **설명하는** 문서 한 줄이 쓰기로 읽힌다.
_BOUNDARY_FILES = (".asgard/asgard-setting-project.json", ".claude/settings.json", ".claude/settings.local.json")


def _git_flags_safe(tokens: list[str], roots: tuple[str, ...]) -> bool:
    """git 전역 플래그가 임의 실행이나 뿌리 이탈로 이어지지 않는가 — 읽기 레인과 색인 레인이 함께 쓴다.

    이름만 읽기 전용인 git 명령도 설정으로 지정한 헬퍼를 실행할 수 있다. 실행 가능한 설정 키의
    목록을 불완전하게 유지하느니 명령별 설정 자체를 거부한다."""
    for index, token in enumerate(tokens[1:], 1):
        if token == "-c" or token.startswith("-c") or token == "--config-env" or token.startswith("--config-env="):
            return False
        if token in {"--ext-diff", "--textconv", "--paginate", "-p", "--open-files-in-pager"} or token.startswith(
            "--open-files-in-pager="
        ):
            return False
        if token == "-C" and (index + 1 >= len(tokens) or not _path_token_within_root(roots, tokens[index + 1])):
            return False
        if token.startswith(("--git-dir=", "--work-tree=")) and not _path_token_within_root(
            roots, token.split("=", 1)[1]
        ):
            return False
    return True


def _git_subcommand(tokens: list[str]) -> str:
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
            index += 2
            continue
        if token.startswith(("--git-dir=", "--work-tree=", "--namespace=")) or token in {
            "--no-pager",
            "--paginate",
            "--bare",
            "--literal-pathspecs",
            "--no-replace-objects",
        }:
            index += 1
            continue
        return token
    return ""


_SETTING_FILE = os.path.join(".asgard", "asgard-setting-project.json")
_CLAUDE_SETTINGS = (os.path.join(".claude", "settings.json"), os.path.join(".claude", "settings.local.json"))
_STUDIO_STATE_ENV = "ASGARD_STUDIO_STATE"


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _entries(section: object, key: str) -> list[str]:
    if not isinstance(section, dict):
        return []
    values = section.get(key)
    return [v.strip() for v in values if isinstance(v, str) and v.strip()] if isinstance(values, list) else []


def work_roots(root: str | None) -> tuple[str, ...]:
    """이 작업이 만져도 되는 자리 전부 — 세션의 뿌리 + **선언된** 추가 뿌리.

    프로젝트 하나가 곧 작업 경계라는 가정은 세 자리에서 깨진다: 스튜디오는 프로젝트를 안 열고도
    서야 해서 개인 작업 공간에서 돌고, 모노레포 밖의 짝 저장소(프런트/백엔드)는 한 작업이 두
    자리를 같이 만지고, 호스트가 `--add-dir`로 이미 들인 폴더는 호스트 쪽에서는 통과한 뒤
    훅에서 되돌아온다 (26-08-04 실측: 저장소 밖 파일 편집이 Edit 단계에서 전부 차단됐다).

    그래도 기본은 닫혀 있다 — 여는 것은 선언뿐이다. 정본은 `.asgard/asgard-setting-project.json`의
    `paths.additional_roots`(네 모드가 같이 읽는다), Claude Code의
    `permissions.additionalDirectories`는 그 호스트가 이미 적어 둔 같은 선언이라 함께 읽는다.
    설정을 캐시하지 않는다: 훅 프로세스는 한 판정마다 새로 뜨고, 네이티브 루프는 사람이 설정을
    고친 즉시 그 값으로 판정해야 한다 (JSON 네 개 읽기)."""
    if not root:
        return ()
    base = os.path.realpath(root)
    roots = [base]
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if project:
        roots.append(os.path.realpath(project))
    declared = _entries(_read_json(os.path.join(base, _SETTING_FILE)).get("paths"), "additional_roots")
    for name in (*(os.path.join(base, s) for s in _CLAUDE_SETTINGS), os.path.expanduser("~/.claude/settings.json")):
        declared += _entries(_read_json(name).get("permissions"), "additionalDirectories")
    for entry in declared:
        expanded = os.path.expanduser(entry)
        roots.append(os.path.realpath(expanded if os.path.isabs(expanded) else os.path.join(base, expanded)))
    return tuple(dict.fromkeys(roots))


def _studio_workspace() -> str:
    """스튜디오 개인 작업 공간 — `~/.asgard/studio/workspace`
    (`commands.studio_store.scratch_root()`와 같은 자리. 훅은 그 모듈을 임포트하지 못해 같은
    규칙을 내장한다 — 단일 출처는 저쪽이다).

    이 폴더는 `.asgard` 아래 있지만 하네스 상태가 아니라 **작업 대상**이다: 창은 프로젝트를 안
    열고도 서야 해서 아스가르드가 자기 소유 폴더를 하나 파고 거기서 돈다. 경로에 `.asgard`가
    들어 있다는 이유로 통제 표면 취급을 하면 스튜디오의 기본 자리에서는 쓰기가 한 건도 통하지
    않는다. 그 안의 `.asgard/…`는 아래 검사가 그대로 잡는다 — 지우는 것은 접두사뿐이다."""
    override = os.environ.get(_STUDIO_STATE_ENV)
    base = (
        os.path.abspath(os.path.expanduser(override))
        if override
        else os.path.join(os.path.expanduser("~"), ".asgard", "studio")
    )
    return os.path.join(base, "workspace")


def _without_workspace(text: str) -> str:
    """통제 표식 부분문자열 검사에 쓸 형태 — 스튜디오 작업 공간 접두사만 지운다.

    위로 거슬러 올라가는 꼬리(`<작업공간>/../..`)는 지우지 않는다: 그건 작업 공간 안이 아니라
    그 위의 하네스 상태를 가리키는 경로라, 접두사를 지워 주면 `.asgard` 표식이 같이 사라진다."""
    workspace = _studio_workspace()
    home = os.path.expanduser("~")
    forms = {workspace, os.path.realpath(workspace)}
    if workspace.startswith(home + os.sep):
        forms.add("~" + workspace[len(home) :])
    for form in forms:
        needle = form.replace("\\", "/")
        chunks = text.split(needle)
        text = chunks[0]
        for tail in chunks[1:]:
            text += (needle if tail.startswith("/..") else " ") + tail
    return text


_UNIT_WORKSPACE_PREFIX = "asgard-unit-"
_HOST_SESSION_ENV = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID", "CURSOR_SESSION_ID", "CODEX_SESSION_ID")


def _within_unit_workspace(candidate: str) -> bool:
    """하네스가 만든 격리 배정 작업공간 판정 — 프로젝트 밖이지만 하네스 소유 경로다.

    26-07-26 실측: wave 단위가 격리 워크스페이스($TMPDIR/asgard-unit-*)에서 뛸 때, 그 안의
    자기 파일을 절대경로로 가리키는 `node --test <ws>/tests/...`·`git -C <ws> status`가 경로
    이탈로 차단됐다 — 격리 레인과 경로 레인이 서로를 막아 관측 자체가 불가능해진다."""
    resolved = os.path.realpath(candidate)
    if _within_host_scratchpad(resolved):
        return True
    temp_root = os.path.realpath(tempfile.gettempdir())
    try:
        if os.path.commonpath((temp_root, resolved)) != temp_root:
            return False
    except ValueError:
        return False
    return any(part.startswith(_UNIT_WORKSPACE_PREFIX) for part in resolved.split(os.sep))


def _within_host_state(resolved: str, roots: tuple[str, ...]) -> bool:
    """호스트가 **이 프로젝트** 몫으로 내준 상태 폴더인가 — `~/.claude/projects/<슬러그>/…`.

    스크래치패드와 같은 부류다: 저장소 밖이지만 하네스가 에이전트에게 "여기에 쓰라"고 지정하는
    자리이고(세션 기록·자동 기억), 경로에 `.claude` 가 들어 있다는 이유로 통제 표면 취급을 하면
    에이전트가 자기 기억을 한 줄도 못 남긴다 (26-08-04 실측).

    슬러그로 좁힌다 — 호스트는 프로젝트 절대경로에서 구분자와 밑줄을 `-` 로 바꿔 폴더 이름을
    만든다 (`/Users/yun/…/personal_space/…` → `-Users-yun-…-personal-space-…`). 남의 프로젝트
    폴더나 `~/.claude` 전체가 열리지는 않는다."""
    base = os.path.realpath(os.path.join(os.path.expanduser("~"), ".claude", "projects"))
    if not _within(base, resolved):
        return False
    slugs = {root.replace(os.sep, "-").replace("_", "-") for root in roots}
    parts = [segment for segment in resolved[len(base) :].split(os.sep) if segment]
    # **첫 칸만** 본다. 어느 깊이에서나 맞추면 남의 프로젝트 폴더 안에 이 슬러그로 디렉터리를
    # 하나 만들어 두는 것만으로 그 아래가 열린다.
    return bool(parts) and parts[0] in slugs


def _within_host_scratchpad(resolved: str) -> bool:
    """호스트가 이 세션에 내준 임시 자리인가 — 시스템 프롬프트가 "여기를 쓰라"고 지정하는 그 폴더다.

    프로젝트 밖이라 경로 이탈로 막혔는데, 막힌 쪽은 임시 계측 스크립트와 분석 산출물이라
    역할이 그것을 저장소 안에 쓰거나 아예 포기했다 (26-08-04 실측). 세션 신원으로 좁힌다 —
    임시 뿌리 아래에서 **이 세션의 id 를 경로에 담은** `scratchpad` 만 연다. 남의 세션 자리나
    임시 뿌리 전체가 열리지는 않는다."""
    parts = resolved.split(os.sep)
    if "scratchpad" not in parts:
        return False
    session_ids = {value for name in _HOST_SESSION_ENV if (value := (os.environ.get(name) or "").strip())}
    if not session_ids:
        return False
    temp_roots = {os.path.realpath(tempfile.gettempdir()), os.path.realpath("/tmp")}
    if not any(_within(base, resolved) for base in temp_roots):
        return False
    return bool(session_ids.intersection(parts))


def _resolve_token(roots: tuple[str, ...], token: str) -> str:
    """토큰을 절대경로로 — 상대경로는 첫 뿌리(세션의 자리)를 기준으로 읽는다."""
    if token.startswith(("~", "/")):
        return os.path.realpath(os.path.expanduser(token))
    return os.path.realpath(os.path.join(roots[0], token))


def _within(base: str, candidate: str) -> bool:
    try:
        return os.path.commonpath((base, candidate)) == base
    except ValueError:
        return False


def _path_token_within_root(roots: tuple[str, ...], token: str) -> bool:
    """Reject explicit path escapes; resolve existing symlinks when a project root is known."""
    if not token or token == "-" or token.startswith("-"):
        return True
    normalized = token.replace("\\", "/")
    if normalized.startswith("~") or os.path.isabs(token) or normalized == ".." or normalized.startswith("../"):
        if not roots:
            return False
    if not roots:
        return True
    candidate = _resolve_token(roots, token)
    if _within_unit_workspace(candidate) or _within_host_state(candidate, roots):
        return True
    return any(_within(root, candidate) for root in roots)


def _control_anchors(roots: tuple[str, ...], markers: tuple[str, ...]) -> list[str]:
    """이 판정에서 통제 표면으로 치는 실제 디렉터리들.

    작업 뿌리마다의 표식 디렉터리에 **기계 전역 자리(`~/.asgard`)** 를 더한다. 스튜디오 작업
    공간이 `~/.asgard/studio/workspace` 라 한 칸만 올라가면 어느 작업 뿌리에도 안 걸리는 하네스
    상태에 닿는다 (`<작업공간>/../workspace.db`). `~/.claude/settings.json` 은 표식이 아니라
    `_BOUNDARY_FILES` 가 잡는다 — `work_roots()` 가 읽어 **이 가드의 경계를 정하는** 파일이라,
    거기에 쓸 수 있으면 나머지 판정이 전부 무의미해진다.

    읽기를 막지는 않는다. 이 목록을 쓰는 두 자리 모두 read-only 레인을 먼저 빼기 때문이다
    (`control_shell_write` 의 `not readonly_shell`), 그리고 하네스가 이 프로젝트 몫으로 내준
    폴더는 `_within_host_state` 가 아래에서 따로 뺀다."""
    anchors = [os.path.realpath(os.path.join(root, marker)) for root in roots for marker in markers]
    home = os.path.expanduser("~")
    anchors += [os.path.realpath(os.path.join(home, marker)) for marker in markers]
    return anchors


def _within_managed_map(roots: tuple[str, ...], candidate: str) -> bool:
    """팀이 함께 쓰는 영역 지도 파일인가 — `<뿌리>/.asgard/map/<이름>.md` 딱 하나의 깊이.

    `.asgard` 아래 있지만 하네스 상태가 아니라 **작업 대상**이다: Canon 이 역할에게 탐색하며
    알게 된 구조를 영역 지도에 반영하라고 시키는데, 통제 표면으로 묶어 두면 그 지시를 어느
    역할도 수행할 수 없다 (26-08-05: doctor 가 유령 경로를 손으로 지우라고 안내하는데 지울
    도구가 없었다).

    여는 폭은 **판정 해시가 묶는 폭과 같게** 잡는다. `diff_state` 는 지도 디렉터리 바로 아래의
    `*.md` 만 다시 읽어 해시에 넣는다 — 더 열면 증거로 안 묶이는 자리에 쓰기가 생긴다.

    **세션의 뿌리 하나만** 본다. `diff_state` 가 다시 읽는 것도 그 자리의 지도 하나뿐이라,
    선언된 추가 뿌리(`paths.additional_roots`)까지 열면 해시 밖에 쓰기 가능한 지도가 뿌리 수만큼
    생긴다 (26-08-05 2차 교차검토).

    지도 자리가 심링크면 열지 않는다. 기준을 `realpath` 로 구하던 판은 링크가 **기준 자체를**
    옮겼다: `.asgard/map` 을 `.asgard` 로 걸어 두면 기준이 `.asgard` 가 되어 기장·상태까지
    별칭으로 통과했다 (26-08-05 재현). `unsafe_map_links` 와 같은 판정이다. 아직 없는 자리는
    연다 — 닫아 두면 첫 영역 지도를 아무도 못 만들고 그 대가가 얻는 것보다 크다. 나중에
    링크로 바뀌면 그때 이 판정이 다시 돈다 (훅은 호출마다 새로 뜬다)."""
    if not roots:
        return False
    base = os.path.join(os.path.realpath(roots[0]), ".asgard", "map")
    if os.path.islink(base) or (os.path.exists(base) and not os.path.isdir(base)):
        return False
    return os.path.dirname(candidate) == base and candidate.endswith(".md")


def _path_token_targets_control(roots: tuple[str, ...], token: str, markers: tuple[str, ...]) -> bool:
    """Resolve symlink parents before comparing a path operand with protected directories."""
    if not roots or not token or token == "-":
        return False
    if token.startswith("-"):
        if "=" not in token:
            return False
        token = token.split("=", 1)[1]
        if not token:
            return False
    candidate = _resolve_token(roots, token)
    if (
        _within(os.path.realpath(_studio_workspace()), candidate)
        or _within_host_state(candidate, roots)
        or _within_managed_map(roots, candidate)
    ):
        return False  # 작업 공간·이 프로젝트 몫 상태 폴더·공유 지도는 작업 대상이다
    return any(_within(anchor, candidate) for anchor in _control_anchors(roots, markers))


# 히어독 여는 낱말 — `<<EOF` · `<<-'EOF'` · `<<\EOF` · `<<"EOF"` · `<<2EOF`. 본문은 다음
# 줄부터 그 낱말만 적힌 줄까지고, 그 사이는 셸이 인자로 넘기지 않는다 (표준 입력으로 간다).
# 낱말 문법을 좁게 잡으면 못 알아본 표기의 본문이 인자로 남아, 그 안에 스친 한 마디가 읽기만
# 하는 명령을 막는다 — 여는 쪽을 넓게 본다.
_HEREDOC_OPEN = re.compile(r"<<-?\s*\\?(['\"]?)([^\s'\"|&;<>]+)\1")


def _without_heredoc_bodies(command: str) -> str:
    """히어독 본문을 지운 형태 — **인자 후보를 뽑는 자리에서만** 쓴다.

    본문은 인자가 아니다 (셸이 표준 입력으로 흘려보낸다). 지우지 않으면 스크립트 안에 스친 한
    마디가 경로 인자로 읽혀 관측 명령 전체가 막힌다 (26-08-05 실측: 훅 사본 대조가 이 형태로
    거부됐다).

    본문이 **코드**일 수는 있다 — 그래서 사설 통제 경로의 텍스트 그물(`_scannable_text`)은
    본문을 그대로 본다. 여기서 지우는 것은 "이것이 경로 인자인가"라는 질문 하나뿐이다.
    종료 낱말을 못 찾으면 아무것도 안 지운다: 열기만 하고 안 닫은 히어독까지 지우면 그
    뒤의 진짜 인자(`cat <<EOF; rm -rf .claude/hooks`)가 통째로 안 보인다."""
    lines = command.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        out.append(line)
        index += 1
        for match in _HEREDOC_OPEN.finditer(line):
            terminator = match.group(2)
            end = index
            while end < len(lines) and lines[end].strip() != terminator:
                end += 1
            if end < len(lines):
                index = end + 1  # 종료 낱말 줄 자체도 인자가 아니다
    return "\n".join(out)


def _command_targets_control(roots: tuple[str, ...], command: str, markers: tuple[str, ...]) -> bool:
    try:
        tokens = _drop_inert_operands(_lex(_without_heredoc_bodies(command)))
    except ValueError:
        return True
    return any(_path_token_targets_control(roots, token, markers) for token in tokens[1:])


# 글을 글로만 받는 피연산자 — 그 자리의 문자열은 실행되지도, 열리지도 않는다. 지금은 커밋과
# 태그 메시지뿐이다 (`-F`는 파일을 받으므로 경로 그대로 검사한다). 짧은 플래그는 뭉쳐 오므로
# (`git commit -am "…"`) 낱글자 `m` 으로 끝나는 뭉치도 같은 자리로 본다.
#
# **하위 명령까지 봐야 한다.** `git` 만 보고 `-m` 을 메시지로 읽으면 `git checkout -m <경로>`
# 처럼 `-m` 이 피연산자를 안 받는 자리에서 바로 뒤 경로가 통째로 사라진다 — 그 한 자리가
# 통제 표면 쓰기를 통과시킨다 (26-08-05 2차 교차검토가 잡은 회귀).
_INERT_SUBCOMMANDS = {"git": {"commit", "tag"}}
_INERT_VALUE_FLAGS = re.compile(r"^(?:-[A-Za-z]*m|--message)$")
_INERT_INLINE_FLAG = "--message="
# 메시지 안의 명령 치환은 **실행된다** — `git commit -m "$(python3 -c '…')"`. 그 자리는
# 글이 아니라 코드라 빼지 않는다.
_SUBSTITUTION = re.compile(r"\$\(|`")


def _lex(command: str) -> list[str]:
    """명령을 토큰으로 — 구분자(`|` `&&` `;`)는 **자기 토큰**으로 남는다.

    줄바꿈을 `;` 로 바꾸는 것이 요점이다. `shlex.split` 은 줄바꿈을 그냥 공백으로 삼켜서, 여러
    줄로 적은 명령은 첫 줄의 프로그램 이름이 끝까지 따라다닌다 — 같은 명령이 `;` 로 적으면
    통과하고 줄바꿈으로 적으면 막히는, 이 패치가 없애려던 바로 그 표기 차별이 생긴다.
    인용 안의 줄바꿈도 함께 바뀌지만 그 자리는 글이라 판정이 안 달라진다. `_shell_parts` 와
    같은 어휘 규칙이다 (구분자 집합 하나만 쓴다)."""
    lexer = shlex.shlex(re.sub(r"\\\r?\n", " ", command).replace("\n", " ; "), posix=True, punctuation_chars="|&;<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _drop_inert_operands(tokens: list[str]) -> list[str]:
    """실행도 개방도 하지 않는 피연산자를 뺀 토큰들 — 지금은 커밋·태그 메시지뿐이다.

    거기 스친 한 마디 때문에 커밋이 막히면 규칙이 아니라 표기 요령을 가르치고, 실제로 3차
    세션은 매번 표기를 바꿔 우회했다 (26-08-05). 메시지에 든 명령 치환은 예외다 —
    `git commit -m "$(python3 -c '…')"` 의 그 자리는 글이 아니라 실행되는 코드다."""
    kept: list[str] = []
    program, subcommand, skip_next = "", "", False
    for index, token in enumerate(tokens):
        if not program or (kept and kept[-1] in _SEGMENT_SEPARATORS):
            program, subcommand = os.path.basename(token), ""
        elif not subcommand and program and token != tokens[0] and not token.startswith("-"):
            subcommand = token
        if skip_next:
            skip_next = False
            # 구분자는 메시지가 아니다. 삼키면 `git commit -m ; ./w -m <경로>` 처럼 앞이 망가진
            # 명령에서 프로그램 판정이 `git commit` 에 붙박여 뒤 세그먼트의 경로까지 사라진다.
            if _SUBSTITUTION.search(token) or token in _SEGMENT_SEPARATORS:
                kept.append(token)
            continue
        if subcommand in _INERT_SUBCOMMANDS.get(program, ()):
            if token.startswith(_INERT_INLINE_FLAG) and not _SUBSTITUTION.search(token):
                continue
            if _INERT_VALUE_FLAGS.fullmatch(token) and index + 1 < len(tokens):
                skip_next = True
                continue
        kept.append(token)
    return kept


def _scannable_text(command: str) -> str:
    """사설 통제 경로 표식을 찾을 글 — 실행도 개방도 하지 않는 자리를 뺀 나머지.

    이 검사는 **판정하는 글과 실행되는 글이 다를 때** 남는 마지막 그물이다. 인자로 푼 토큰이
    경로가 아닌데도 나중에 기장 파일을 쓰는 형태 — `python -c "$PAYLOAD"` ·
    `for P in "…write_text('.asgard/quest/x')…"` — 는 여기서만 잡힌다 (26-08-04 교차검증이
    그 형태로 기장을 실제로 위조했다). 그러니 그물은 남긴다.

    히어독 본문은 **안 뺀다**: 본문은 인자가 아니지만 코드일 수는 있어서, 인자를 뽑는
    자리(`_command_targets_control`)와 판단이 갈린다. 파싱이 안 되면 원문을 그대로 돌려준다 —
    못 읽는 글은 좁히지 않는다."""
    try:
        return " ".join(_drop_inert_operands(_lex(command)))
    except ValueError:
        return command


_STREAM_EDITORS = {"sed", "gsed", "awk", "gawk", "nawk", "mawk"}

_RUNNERS = {"uv", "poetry", "pipenv"}
# `run`과 본체 명령 사이에 낄 수 있는 플래그 중 **값을 따로 받지 않고 실행 노출도 넓히지 않는**
# 것만 벗긴다. `--with`(임의 패키지 설치) · `--python`/-p(런타임 내려받기) · `--script` ·
# `--module`/-m · `--env-file` 처럼 값이나 새 실행 통로를 동반하는 플래그는 목록 밖이고,
# 하나라도 보이면 판정은 fail-closed 로 떨어진다 (모르는 래퍼는 통과시키지 않는다).
_RUNNER_INERT_FLAGS = {
    "--no-project",
    "--isolated",
    "--frozen",
    "--locked",
    "--offline",
    "--no-sync",
    "--no-dev",
    "-q",
    "--quiet",
}


def _strip_runner(tokens: list[str]) -> list[str] | None:
    """`uv|poetry|pipenv run [무해 플래그…] <명령>`에서 래퍼를 벗겨 본체만 돌려준다.

    벗긴 뒤에는 맨 인터프리터와 **완전히 같은 판정 경로**를 탄다. 이게 요점이다: 래퍼를
    통째로 허용하면 `python3 -c` 에는 걸리는 쓰기 스니펫이 `uv run python -c` 로는 새어
    나가고, 반대로 래퍼를 통째로 막으면 정본 훅 명령(`uv run --no-project python
    <hooks>/quest-log.py append`)이 읽기전용 역할에서 차단돼 역할이 자기 이벤트를 못 남긴다 —
    subagent-gate 가 그 상태의 종료를 거부하므로 양쪽이 막히면 교착이다.

    래퍼가 아니거나 판정할 수 없는 형태면 None (호출자는 계속 진행 → 최종적으로 차단)."""
    if len(tokens) < 3 or os.path.basename(tokens[0]) not in _RUNNERS or tokens[1] != "run":
        return None
    rest = tokens[2:]
    while rest and rest[0].startswith("-"):
        if rest[0] not in _RUNNER_INERT_FLAGS:
            return None
        rest = rest[1:]
    return rest or None


def _safe_stream_editor(program: str, tokens: list[str], roots: tuple[str, ...]) -> bool:
    """sed/awk 판정 — 인플레이스와 스크립트 내 쓰기 표면만 제외하면 stdout 전용 관측이다.

    스크립트 인자는 경로가 아니므로 경로 이탈 검사에서 뺀다: 정규식이 `/`로 시작하면
    (`awk '/^\\.dark/,0'`) 절대경로로 오독돼 정당한 관측이 차단됐다 (26-07-26 실측)."""
    is_sed = program.endswith("sed")
    args = tokens[1:]
    if any(a == "-i" or a.startswith("-i") or a in {"--in-place", "--include"} for a in args):
        return False
    if is_sed and any(a in {"-f", "--file"} or a.startswith("--file=") for a in args):
        return False  # 스크립트를 파일로 받으면 내용을 판정할 수 없다 (fail-closed)
    write_pattern = _SED_WRITE if is_sed else _AWK_WRITE
    script_seen = False
    for arg in args:
        if arg.startswith("-"):
            continue
        if not script_seen:  # 첫 비플래그 인자 = 스크립트
            script_seen = True
            # 셸 변수가 든 스크립트는 판정 대상 텍스트가 실행 텍스트와 다르다 (`_SHELL_EXPANSION`)
            if _SHELL_EXPANSION.search(arg) or write_pattern.search(arg):
                return False
            continue
        if not _path_token_within_root(roots, arg):
            return False
    return script_seen


# 셸 제어문 낱말 — 그 자체로는 아무것도 실행하지 않는다. 없으면 읽기 전용 명령만 담은
# `for f in a b; do wc -c "$f"; done` 이 통째로 미분류가 돼 막힌다 (26-08-04 실측).
# 명령 치환(`$(…)`)은 여전히 `_shell_parts` 가 거부한다 — 그 안은 판정할 수 없다.
_BLOCK_OPENERS = {"do", "then", "else"}
_BLOCK_CLOSERS = {"done", "fi", "esac", ";;"}
_COMMAND_HEADERS = {"while", "until", "if", "elif"}  # 뒤에 오는 것이 명령이다
_WORDLIST_HEADERS = {"for", "select"}  # 뒤에 오는 것은 낱말 목록이다


def _safe_segment(segment: str, roots: tuple[str, ...] = ()) -> bool:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return False
    if not tokens:
        return False
    while tokens and tokens[0] in _BLOCK_OPENERS | _COMMAND_HEADERS:
        tokens = tokens[1:]
    if tokens and tokens[0] in _WORDLIST_HEADERS:
        # `for NAME in …` 는 목록 선언이라 실행은 do 뒤 본문이 하지만, **낱말이 곧 경로**다.
        # 본문은 그 경로를 변수로 읽으므로 여기서 안 보면 뿌리 밖 파일이 반복문 형태로만 열린다
        # (같은 파일을 평범한 명령으로 읽으면 막힌다 — 판정이 형태에 따라 갈리면 안 된다).
        return len(tokens) >= 2 and all(_path_token_within_root(roots, word) for word in tokens[3:])
    while tokens and tokens[-1] in _BLOCK_CLOSERS:
        tokens = tokens[:-1]
    if not tokens:
        return True  # 닫는 낱말만 남은 조각 (`done`) — 실행이 없다
    # 선행 환경 대입(VAR=x cmd / env VAR=x cmd)은 프로세스-로컬 — 판정은 본체 명령으로.
    # 터미널 폭 스모크(COLUMNS=130 python -c …) 같은 정당한 검증이 env 때문에 막히지 않게 한다.
    if os.path.basename(tokens[0]) == "env":
        tokens = tokens[1:]
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        # 대입만 남은 조각(`D=/some/path`)은 부를 명령이 없다 — 셸 변수 하나가 생길 뿐이다.
        # 이걸 미분류로 떨어뜨리면 조각 하나 때문에 명령 전체가 읽기 레인 밖으로 나가고,
        # 그 다음 통제 표면 그물이 인자에 스친 `.asgard`·`.claude` 를 잡아 순수 관측이 막힌다
        # (26-08-05 실측: `D=<경로>; ls "$D"` 형태가 그렇게 거부됐다). 값에 든 명령 치환은
        # `_shell_parts` 가 이미 앞에서 거부한다.
        return True
    program = os.path.basename(tokens[0])
    if program in _STREAM_EDITORS:
        return _safe_stream_editor(program, tokens, roots)  # 스크립트 인자는 경로 검사 대상이 아니다
    if any(not _path_token_within_root(roots, token) for token in tokens[1:]):
        return False
    if any(token == "--output" or token.startswith("--output=") for token in tokens[1:]):
        return False
    if program == "find" and any(token in {"-delete", "-exec", "-execdir", "-ok", "-okdir"} for token in tokens):
        return False
    if program in _INSPECT or program in _VERIFY:
        return True
    if program == "cd":
        # 디렉터리 이동은 쓰기가 아니다. 경로는 위에서 이미 root(또는 하네스 작업공간) 안으로
        # 검사됐다. `cd sub && <관측>`은 모노레포에서 가장 흔한 관측 형태다 — 이걸 막으면
        # 연결 허용의 이득이 절반은 사라진다 (26-07-26 실측: 재검증 런의 차단 2건이 전부 이 형태).
        return len(tokens) <= 2
    if _safe_asgard_hook(tokens, roots):
        return True  # 퀘스트 기장(記帳)은 파이프라인 안에서도 같은 허용 명령이다
    if program == "ruff":
        return len(tokens) >= 2 and (
            (tokens[1] == "check" and not any(t in {"--fix", "--unsafe-fixes"} for t in tokens[2:]))
            or (tokens[1] == "format" and "--check" in tokens[2:])
        )
    if program == "tsc":
        return "--noEmit" in tokens[1:]
    if program == "git":
        return _git_flags_safe(tokens, roots) and _git_subcommand(tokens) in _GIT_READ
    if (inner := _strip_runner(tokens)) is not None:
        return _safe_segment(shlex.join(inner), roots)
    if program in {"npm", "pnpm", "yarn"}:
        return len(tokens) >= 2 and tokens[1] in {"test", "lint", "check"}
    if program == "cargo":
        return len(tokens) >= 2 and (
            tokens[1] in {"test", "check", "clippy"} or (tokens[1] == "fmt" and "--check" in tokens[2:])
        )
    if program == "go":
        return len(tokens) >= 2 and tokens[1] in {"test", "vet"}
    if program == "node":
        # Python 레인과 대칭인 검증 통로. 이게 없으면 JS/TS 저장소에서 판정자가 **아무것도 실행할
        # 수 없어**, 배달물이 아무리 멀쩡해도 "실행 증거 없음 = FAIL" 로만 끝난다 (26-07-26 helios
        # 실측: node·npm·python -c subprocess 전 레인이 막혀 판정이 정적 읽기로 후퇴).
        # 임의 프로젝트 코드 실행은 이미 허용된 pytest와 같은 수준의 노출이다 — 새 구멍이 아니라
        # 같은 계약의 다른 런타임. 인라인 실행(-e/-p/--eval)은 쓰기 휴리스틱이 없어 제외한다.
        flags = [t for t in tokens[1:] if t.startswith("-")]
        operands = [t for t in tokens[1:] if not t.startswith("-")]
        if any(
            not (
                f in {"--check", "--test", "--test-only"} or f.startswith(("--test-reporter=", "--test-name-pattern="))
            )
            for f in flags
        ):
            return False
        if "--check" in flags:
            return len(operands) == 1
        if not operands:
            return "--test" in flags  # bare `node --test` = 프로젝트 테스트 전체 (pytest 무인자와 동형)
        # 여러 테스트 파일을 한 번에 — `pytest a b`와 동형. 단일 operand만 받으면 판정자가 파일마다
        # 턴을 나눠 써야 한다 (26-07-26 실측: 다중 형태 차단 후 한 파일씩 재시도).
        return all(_is_test_path(operand) for operand in operands)
    if program == "asgard" and len(tokens) >= 4 and tokens[1:3] == ["skills", "show"]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", tokens[3]):
            return False
        return len(tokens) == 4 or (
            len(tokens) == 6
            and tokens[4] == "--resource"
            and tokens[5] not in (".", "..")
            and not tokens[5].startswith(("/", "../"))
            and "/../" not in tokens[5]
        )
    if program == "make":
        return len(tokens) >= 2 and all(
            not t.startswith("-") and t in {"test", "check", "lint", "verify"} for t in tokens[1:]
        )
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", program):
        if tokens[1:2] in (["--version"], ["-V"], ["-VV"]):
            return True
        if len(tokens) >= 3 and tokens[1:3] in (
            ["-m", "pytest"],
            ["-m", "unittest"],
            ["-m", "compileall"],
            ["-m", "py_compile"],
        ):
            return True
        if len(tokens) >= 3 and tokens[1] == "-c":
            # Verifier 계약의 한 줄 스모크 레인 — 파일 작성 없이 대표 함수를 직접 호출한다.
            snippet = " ".join(tokens[2:])
            # 셸 변수가 들어 있으면 **판정하는 글과 실행되는 글이 다르다** — 아래 쓰기 휴리스틱이
            # 보는 것은 `$PAYLOAD` 라는 네 글자뿐이고, 셸이 그 자리에 넣는 것은 무엇이든 될 수
            # 있다. 26-08-04 에 그렇게 기장 파일이 만들어졌다:
            #   for PAYLOAD in "…write_text('forged')"; do python -c "$PAYLOAD"; done
            # 스니펫을 판정할 수 없으면 통과시키지 않는다 (fail-closed).
            if _SHELL_EXPANSION.search(snippet):
                return False
            return not _PY_SNIPPET_MUTATION.search(snippet)
        if len(tokens) >= 2:
            return tokens[1].replace("\\", "/").endswith(".py") and _is_test_path(tokens[1])
    return False


def _is_test_path(script: str) -> bool:
    """테스트 자산 경로 판정 — `tests/` 아래이거나 파일명이 test로 시작. 런타임 무관 (py·mjs·ts)."""
    normalized = script.replace("\\", "/")
    return os.path.basename(normalized).startswith("test") or "/tests/" in f"/{normalized}"


# 세그먼트 구분자 — 각 세그먼트를 독립 판정하므로 허용 명령끼리의 연결은 새 권한을 만들지 않는다.
# 반대로 이를 막으면 `git status --porcelain && git diff` 같은 순수 읽기가 통째로 차단되고, 모델은
# 같은 관측을 변형으로 재시도해 턴을 태운다 (26-07-26 helios 실측: 차단 39건의 최다 사유).
# 단일 `&`(백그라운드)는 구분자가 아니다 — 판정 밖에서 계속 도는 프로세스를 허용하지 않는다.
_SEGMENT_SEPARATORS = {"|", "||", "&&", ";"}
# 폐기 리다이렉션 — /dev/null로 버리거나 스트림을 합치는 형태는 프로젝트 파일을 만들지 않는다.
_DISCARD_REDIRECTION = re.compile(r"\s*(?:\d?>>?\s*/dev/null|\d?>&\s*[12]|<\s*/dev/null)")


def _shell_parts(command: str) -> tuple[list[list[str]], bool]:
    """Tokenize pipelines and command sequences, keeping metacharacters inside quotes as data."""
    command = _DISCARD_REDIRECTION.sub("", command)
    if "$(" in command or "`" in command:
        return [], False
    # 줄이음(`\` + 줄바꿈)은 셸이 통째로 지우는 것이지 구분자가 아니다. 먼저 안 지우면 아래
    # 치환이 `\ ; ` 를 만들고, posix shlex 가 그 백슬래시를 탈출부호로 읽어 공백 한 칸짜리
    # 토큰을 남긴 뒤 명령을 두 조각으로 쪼갠다. 그러면 여러 줄로 적은 정본 기장 명령이
    # 미분류로 떨어지고, 읽기 전용 레인이 꺼진 자리에서 `.claude/hooks/quest-log.py` 라는
    # 인자가 통제 표면 갈래에 걸려 퀘스트를 못 연다 (26-08-05 실측 — 이 세션의 첫 명령).
    command = re.sub(r"\\\r?\n", " ", command)
    # 줄바꿈은 `;`와 같은 구분자다 — 히어독(`<<`)은 아래 토큰 검사가 계속 막는다. 줄바꿈 자체를
    # 금지하면 모델이 관측 뒤에 `\necho "EXIT:$?"` 같은 한 줄을 붙였을 때 명령 전체가 죽는다
    # (26-07-26 실측: 프로토콜 기록 명령이 이 형태로 반복 차단됐다).
    command = command.replace("\n", " ; ")
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return [], False
    parts: list[list[str]] = [[]]
    for token in tokens:
        if token in _SEGMENT_SEPARATORS:
            if not parts[-1]:
                return [], False
            parts.append([])
        elif token and all(char in "|&;<>" for char in token):
            return [], False
        else:
            parts[-1].append(token)
    if len(parts) > 1 and not parts[-1]:
        parts.pop()  # 후행 구분자(`ls;`)는 빈 세그먼트가 아니다
    return parts, bool(parts[-1])


def _safe_asgard_hook(tokens: list[str], roots: tuple[str, ...] = ()) -> bool:
    # 훅 명령의 정본 표기는 `uv run --no-project python <hooks>/quest-log.py …`다
    # (platform.hook_python). 래퍼를 먼저 벗겨야 아래 인터프리터·스크립트 판정이 맨 형태와
    # 같은 자리를 본다 — 안 벗기면 정본대로 친 기장 명령이 통째로 차단된다.
    if (inner := _strip_runner(tokens)) is not None:
        tokens = inner
    if len(tokens) < 2 or os.path.basename(tokens[0]) not in _PYTHON:
        return False
    # The trusted hook must be Python's actual script argument. Scanning later
    # arguments would let `python -c ... quest-log.py open` smuggle arbitrary code.
    script = tokens[1].replace("\\", "/")
    if os.path.isabs(script) and roots:
        # 절대경로 형태도 같은 훅이다 — 호스트가 프로젝트 절대경로를 그대로 넘기는 일이 흔한데
        # 상대 형태만 인정하면 프로토콜 기록 명령이 막힌다 (26-07-26 실측: Worker가 quest를
        # 열지 못해 같은 명령을 형태만 바꿔 5회 재시도했다). 뿌리 안으로 환원해 판정한다.
        absolute = os.path.realpath(script)
        for candidate in roots:
            try:
                relative = os.path.relpath(absolute, candidate).replace("\\", "/")
            except ValueError:
                continue
            if not relative.startswith("../"):
                script = relative
                break
        else:
            return False
    script = os.path.normpath(script).replace("\\", "/")
    # 훅이 사는 디렉토리는 클라이언트마다 다르다 — `.claude/hooks/`만 인정하면 Cursor·Codex 세션의
    # 퀘스트 기장이 통째로 막혀 역할이 로그를 못 연다 (모드 간 같은 동작이 깨지는 자리).
    if not script.startswith(_HOOK_DIRS) or script.count("/") != 2:
        return False
    name = os.path.basename(script)
    if name == "quest-log.py":
        if len(tokens) < 3 or tokens[2] not in {
            "open",
            "attach",
            "append",
            "state",
            "replay",
            "next",
            "close",
            "ticket-claim",
            "ticket-heartbeat",
            "ticket-finish",
            "ticket-recover",
            "verify-baseline",
        }:
            return False
        # close --force는 검증 실패 상태의 관리적 해제(Odin 동의) — read-only 역할의 권한이 아니다.
        return not (tokens[2] == "close" and "--force" in tokens[3:])
    return name == "verifier-gate.py"


def is_readonly_bash_safe(command: str, root: str | None = None, roots: tuple[str, ...] | None = None) -> bool:
    """Return True only for Bash commands admitted in a read-only role.

    `roots`를 넘기면 그것이 정본이다 — 이미 뿌리를 구한 호출자(훅의 main)가 설정을 두 번 읽지
    않게 한다. 안 넘기면 `root` 하나에서 `work_roots`로 편다."""
    command = command.strip()
    if not command:
        return False
    if roots is None:
        roots = work_roots(root)
    parts, valid = _shell_parts(command)
    if not valid:
        return False
    if (
        len(parts) == 2
        and parts[0]
        and os.path.basename(parts[0][0]) in {"echo", "printf"}
        and _safe_asgard_hook(parts[1], roots)
        and "append" in parts[1]
    ):
        return True
    # Pipelines are safe only when every stage is independently read-only. 퀘스트 기장은 소스
    # 변경이 아니라 허용된 메타데이터 쓰기이므로 그 단계도 스스로 안전하다 — 단계별로 보지 않고
    # 명령 전체가 한 토막일 때만 인정하면, 계약이 안내하는 형태에 `| tail` 한 번만 붙어도
    # 판정이 뒤집힌다: 그 뒤 `.claude/hooks/quest-log.py` 라는 경로 인자가 통제 표면 갈래에
    # 걸려 기장 자체가 막힌다 (26-08-05 실측 2회 — open 과 사본 대조가 그렇게 거부됐다).
    # 한 토막일 때 되던 것이 파이프 뒤에서 되는 것뿐이라 열리는 권한은 없다.
    return all(_safe_asgard_hook(part, roots) or _safe_segment(shlex.join(part), roots) for part in parts)


def is_index_only_git(command: str, roots: tuple[str, ...]) -> bool:
    """모든 조각이 관측이거나 **색인에만 닿는 git 호출**인가 — 통제 표면 갈래에서만 쓴다.

    통제 표면이 닫혀 있는 이유는 거기 쓴 것이 판정의 물리 대조 밖에 남는다는 것이다. 색인에
    담는 연산은 그 반대다 — 그 자리를 커밋 경계 안으로 들여 Odin 이 diff 로 보게 만든다.
    무엇이 실제로 담기는지는 `.asgard` 자신의 무시 규칙이 정하므로 (런타임은 무시된 채 남는다)
    가드가 그 경계를 다시 적지 않는다.

    읽기 전용 레인(`is_readonly_bash_safe`)에는 안 넣는다. 넣으면 판정자·로키가 색인을 건드릴
    수 있게 되는데, 이 완화가 사려던 것은 그것이 아니다.

    뿌리 이탈·임의 실행은 읽기 레인과 같은 `_git_flags_safe` 로 거른다. 경로 인자를 뿌리 안으로
    다시 검사하지는 않는다 — git 이 작업 트리 밖 경로를 스스로 거부하고, 검사하면 커밋 메시지에
    적힌 경로 한 줄이 봉인을 막는다."""
    parts, valid = _shell_parts(command)
    if not valid or not parts:
        return False
    for part in parts:
        if not part:
            return False
        if _safe_segment(shlex.join(part), roots):
            continue
        if os.path.basename(part[0]) != "git" or not _git_flags_safe(part, roots):
            return False
        if _git_subcommand(part) not in _GIT_INDEX_ONLY:
            return False
        # `-f` 는 무시 규칙을 끄는 플래그다. 이 레인의 근거가 "무엇이 담기는지는 무시 규칙이
        # 정한다" 이므로, 그 규칙을 끄는 철자를 함께 열면 근거가 남지 않는다 — `git add -f
        # .asgard` 한 줄이 기장·상태·배차 DB 를 통째로 색인에 넣는다.
        if any(token == "-f" or token == "--force" for token in part[1:]):
            return False
    return True


def _deny(protocol: str, message: str) -> None:
    """차단 응답 — Cursor는 permission JSON, Claude Code/Codex는 exit 2 + stderr (git-guard와 동일 규약)."""
    if protocol == "cursor":
        sys.stdout.write(
            json.dumps({"permission": "deny", "user_message": message, "agent_message": message}, ensure_ascii=False)
        )
        raise SystemExit(0)
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _refusal(reason: str, tool_name: str, command: str, path: str, roots: tuple[str, ...] = ()) -> str:
    """거부 사유 문장 — 실제 규칙과 도구에 맞아야 가르친다.

    통제 표면 차단에 "읽기전용 역할" 문장을 붙이면 쓰기 권한이 있는 역할이 자기 신원을 의심하며
    턴을 태우고, Edit 차단에 Bash 허용목록을 붙이면 없는 레인을 찾는다 (26-07-26 실측).
    하네스 상태 차단과 뿌리 밖 차단도 사유가 다르다: 전자는 아무도 못 고치는 자리라 처방이
    `asgard init/sync`고, 후자는 선언 한 줄로 열리는 자리라 처방이 그 선언이다. 둘을 한 문장으로
    묶어 두면 열 수 있는 차단이 못 여는 차단처럼 읽힌다 (26-08-04 실측)."""
    target = command[:160] if tool_name == "Bash" else (path[:160] or "(no path)")
    if reason == "escape":
        listed = ", ".join(roots[:4]) or "(none)"
        return (
            f"Asgard workspace policy blocked {tool_name} on a path outside every work root: {target}\n"
            f"Work roots in force: {listed}. To make that directory a work target, declare it — "
            '.asgard/asgard-setting-project.json → {"paths": {"additional_roots": ["<dir>"]}} '
            "(read by all four modes), or Claude Code's permissions.additionalDirectories in "
            ".claude/settings.json. A blocked path never changed — declare the root instead of "
            "retrying a variant."
        )
    if reason == "control":
        return (
            f"Asgard control-surface policy blocked {tool_name}: {target}\n"
            "Harness state (.asgard/, except the shared map .asgard/map/*.md) and the two files "
            "that define this guard's work roots (.claude/settings.json, .claude/settings.local.json) "
            "are not work targets: the verdict's physical diff does not cover them, so a write there "
            "leaves no evidence. Change them through Asgard's own commands (asgard init/sync). "
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


def _forgery_surface_access(
    tool_name: str, command: str, normalized_path: str, path: str, roots: tuple[str, ...], readonly_shell: bool
) -> bool:
    """기장·영수증·상태(`_PRIVATE_CONTROL_PATHS`)에 닿는가 — **위조를 막는 자리**라 넓은 표식보다
    그물이 촘촘하다.

    경로 인자로 안 풀리는 토큰도 나중에 실행돼 기장을 쓸 수 있어서 (`python -c "$PAYLOAD"`)
    명령문 텍스트까지 본다. 그 텍스트에서 실행되지 않는 자리만 뺀다 — `_scannable_text`.
    읽기 전용 레인은 먼저 빠진다: 여기를 지키는 것은 위조 방지이지 열람 금지가 아닌데, 예외가
    없던 판에서는 `ls .asgard/quest/` 한 줄도 막혔다 (26-08-04 실측 4회)."""
    if any(marker in normalized_path for marker in _PRIVATE_CONTROL_PATHS):
        return True
    if _path_token_targets_control(roots, path, _PRIVATE_CONTROL_PATHS):
        return True
    if tool_name != "Bash" or readonly_shell:
        return False
    scannable = _without_workspace(_scannable_text(command).replace("\\", "/"))
    return any(marker in scannable for marker in _PRIVATE_CONTROL_PATHS) or _command_targets_control(
        roots, command, _PRIVATE_CONTROL_PATHS
    )


def refusal_reason(tool_name: str, command: str, path: str, roots: tuple[str, ...], agent: str) -> str:
    """이 호출을 막는다면 무엇 때문인가 — `control` · `escape` · `readonly`, 통과면 빈 문자열.

    정책 전부가 여기 한 자리에 있다 (`main`은 프로토콜만 다룬다). 규율은 세션이 아니라
    **역할**에 붙는다 (tool_kernel.ROLE_CAPABILITIES가 정본): worker 계열은 mutate를 갖고,
    thinker/verifier/loki/ullr/mimir은 안 갖는다. 신원이 없는 호출은 메인 세션이 전이 함수가
    배정한 역할을 직접 수행하는 자리(MAIN_WORKER)라 쓰기가 그 역할의 몫이다 — 신원 부재를
    읽기전용으로 읽으면 모드 B의 단일 변경이 통째로 막힌다: subagent-gate가
    `[ASGARD_UNIT:<id>]` 없는 asgard-worker 디스패치를 거부하므로 우회로도 없다 (양쪽 차단 =
    교착). 퀘스트 없는 쓰기는 이 훅의 소관이 아니다 — write-sentinel이 기록하고 Stop의
    verifier-gate가 물리 대조로 잡는다. 같은 것을 두 시점에 재판하면 교착이 된다."""
    # 표식 부분문자열 검사는 스튜디오 작업 공간 접두사를 뺀 형태로 한다 — 그 폴더는 `.asgard`
    # 아래 있지만 하네스 상태가 아니라 작업 대상이다 (`_studio_workspace`).
    normalized_path = _without_workspace(os.path.normpath(path).replace("\\", "/"))
    # 하네스가 이 세션·이 프로젝트 몫으로 내준 자리와 공유 지도는 통제 표면이 아니라 작업
    # 대상이다. 경로에 `.claude` 가 들어 있다는 이유로 여기를 막으면 에이전트가 자기 기억과
    # 계측 산출물을 한 줄도 못 남긴다.
    harness_owned = bool(path) and (
        _within_host_state(os.path.realpath(os.path.expanduser(path)), roots)
        or _within_unit_workspace(os.path.expanduser(path))
        or _within_managed_map(roots, _resolve_token(roots, path) if roots else "")
    )
    # 넓은 표식이 `.asgard` 하나로 좁아졌으므로 `.claude/settings*.json` 은 여기서 따로 본다 —
    # 그 파일이 `work_roots()` 를 정하고, 정하는 자리를 열면 나머지 판정이 통째로 무의미해진다.
    control_write = (
        tool_name in _WRITE_TOOLS
        and not harness_owned
        and (
            any(marker in normalized_path for marker in _CONTROL_PATHS)
            or any(name in normalized_path for name in _BOUNDARY_FILES)
            or _path_token_targets_control(roots, path, _CONTROL_PATHS)
        )
    )
    readonly_shell = tool_name == "Bash" and is_readonly_bash_safe(command, roots=roots)
    # 색인에만 닿는 git 호출은 이 갈래에서 뺀다 — 담는 것은 쓰기가 아니라 그 반대이고, 팀이
    # 함께 읽는 `.asgard` 자산은 커밋돼야 판정의 물리 대조가 덮는다. 뿌리를 정하는 파일도 같이
    # 뺀다: 색인에 담는 것은 그 파일을 고치는 것이 아니다. 기장·영수증·상태는 그대로 막힌다
    # (`_forgery_surface_access` 는 이 완화를 안 본다).
    index_only_git = tool_name == "Bash" and not readonly_shell and is_index_only_git(command, roots)
    # 넓은 통제 표식은 **뿌리 기준으로 푼 경로 인자**로만 판정한다. 명령문 전체를 부분문자열로
    # 훑던 종전 갈래는 경로가 아닌 언급까지 잡았다: 저장소 밖 호스트 세션 디렉터리나 히어독
    # 본문에 스친 한 마디가 읽기 전용 조사를 통째로 막았다. 인용 안쪽에 숨긴 쓰기가 이 갈래를
    # 빠져나가는 것은 받아들인 값이다 — 그쪽은 write-sentinel 이 적고 verifier-gate 가 물리
    # 대조로 잡는다. `_BOUNDARY_FILES` 만 글에서도 찾는다: 그 셋은 이 가드의 뿌리를 정하는
    # 파일이라, 열리면 뒤이은 판정이 무엇을 기준으로 했는지부터 무의미해진다.
    control_shell_write = (
        tool_name == "Bash"
        and not readonly_shell
        and not index_only_git
        and (
            _command_targets_control(roots, command, _CONTROL_PATHS)
            or any(name in _without_workspace(_scannable_text(command).replace("\\", "/")) for name in _BOUNDARY_FILES)
        )
    )
    if (
        _forgery_surface_access(tool_name, command, normalized_path, path, roots, readonly_shell)
        or control_write
        or control_shell_write
    ):
        return "control"
    if bool(path) and not _path_token_within_root(roots, path):
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
    if reason:
        _deny(protocol, _refusal(reason, tool_name, command, path, roots))
    _allow(protocol)


if __name__ == "__main__":
    main()
