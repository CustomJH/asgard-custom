"""작업 뿌리와 통제면 — 어디가 이 세션의 일감이고 어디가 하네스의 상태인가.

두 물음을 판정한다. ① 이 경로가 선언된 작업 뿌리 안인가 (프로젝트 설정의 `paths.additional_roots`
와 호스트의 `permissions.additionalDirectories` 가 정본) ② 이 경로가 하네스 통제면인가
(`.asgard/` 상태·훅 폴더·이 가드의 뿌리를 정하는 설정 파일 자신).

통제면을 따로 세는 이유는 증거다: 그 자리의 쓰기는 판정 diff 에 안 실려서, 고쳐도 아무 판정에도
안 나타난다. 뿌리 밖 쓰기와 통제면 쓰기는 다른 실패라 사유도 따로 낸다.
"""

from __future__ import annotations

import json
import os
import tempfile

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


def has_project_marker(directory: str) -> bool:
    """여기가 프로젝트 뿌리인가 — 마커 둘을 다르게 센다.

    `.git` 은 어디서든 세고, 디렉터리인지는 안 본다: 연결된 worktree 에서는 그것이 파일이라
    `isdir` 로만 보면 그 뿌리를 지나쳐 올라간다. `.asgard` 는 홈에서만 안 센다 — `~/.asgard` 는
    전역 에이전트 홈이라 아스가르드를 깐 기계라면 반드시 있고, 그것을 프로젝트로 세면 홈 아래
    모든 프로젝트가 "홈이라는 바깥 프로젝트 안에 있다"고 판정된다."""
    if os.path.exists(os.path.join(directory, ".git")):
        return True
    return directory != os.path.realpath(os.path.expanduser("~")) and os.path.isdir(os.path.join(directory, ".asgard"))


def declarable_root(roots: tuple[str, ...], directory: str) -> bool:
    """이 디렉터리를 작업 뿌리로 선언할 수 있는가 — `commands.workroots._reject_target` 의 거절 갈래 셋.

    기계 뿌리, 홈 그 자체, 그리고 이미 서 있는 작업 뿌리를 품는 조상. 마지막 것을 열면 그 뿌리의
    이웃 저장소와 하네스 상태까지 한꺼번에 딸려 온다. 거부문이 지목하는 자리와 명령이 받아 주는
    자리는 같아야 한다 — 어긋나면 처방이 실패하는 명령이 되고, 그 전에 오딘의 승인 한 번이 이미
    소모된다 (26-08-11 판정이 중첩 프로젝트에서 재현했다).

    세 번째 갈래를 **작업 뿌리 전부**에 대해 본다. 저쪽은 `_project_root` 하나만 보므로 이 판정이
    더 엄격하다 — 여기서 통과한 자리는 저기서도 통과하고, 반대는 보장하지 않는다. 처방이 거절될
    일만 없으면 되는 관계라 이 방향이 맞다."""
    if directory in ("", os.path.dirname(directory)) or directory == os.path.realpath(os.path.expanduser("~")):
        return False
    return not any(root == directory or root.startswith(directory + os.sep) for root in roots)


def enclosing_project(path: str, roots: tuple[str, ...] = ()) -> str:
    """막힌 경로를 담는 가장 가까운 프로젝트 뿌리 — 선언할 자리가 없으면 빈 문자열.

    거부문이 `<dir>` 자리표시자를 내면 어디를 열지 읽는 쪽이 고른다. 좁게 고르면 다음 파일에서
    또 막히고, 넓게 고르면 이웃한 저장소까지 딸려 온다. 막힌 경로가 하나면 답도 하나라서
    가드가 직접 센다: 그 파일이 든 디렉터리에서 위로 올라가며 첫 마커를 찾는다.

    올라가기는 `declarable_root` 가 거절하는 자리에서 멈춘다. 거기까지 갔다는 것은 이 경로를
    담는 **선언 가능한** 프로젝트가 없다는 뜻이라, 그 파일이 든 디렉터리로 물러선다 — 마커가
    없어도 선언은 되는 자리다. 그것마저 거절될 자리면(홈에 놓인 파일, 또는 세션의 뿌리보다
    위에 있는 파일) 빈 문자열이고, 그때는 선언으로 열 수 있는 경로가 아예 아니다.

    물러선 자리는 아직 없는 디렉터리일 수 있다 — 저장소 옆에 새 폴더를 만들며 쓰는 형상이다.
    `run_root_add` 는 없는 자리를 거절하므로 부르는 쪽이 먼저 만들라고 말해야 한다
    (`hooks.readonly_guard._refusal`). 여기서 조상으로 더 올라가지는 않는다: 올라가면 세션 뿌리를
    품는 자리가 나와 이웃 저장소까지 딸려 온다."""
    resolved = os.path.realpath(os.path.expanduser(path))
    base = resolved if os.path.isdir(resolved) else os.path.dirname(resolved)
    current = base
    while declarable_root(roots, current):
        if has_project_marker(current):
            return current
        current = os.path.dirname(current)
    return base if declarable_root(roots, base) else ""


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


def _within_unit_workspace(candidate: str, roots: tuple[str, ...] = ()) -> bool:
    """하네스가 만든 격리 배정 작업공간 판정 — 프로젝트 밖이지만 하네스 소유 경로다.

    26-07-26 실측: wave 단위가 격리 워크스페이스($TMPDIR/asgard-unit-*)에서 뛸 때, 그 안의
    자기 파일을 절대경로로 가리키는 `node --test <ws>/tests/...`·`git -C <ws> status`가 경로
    이탈로 차단됐다 — 격리 레인과 경로 레인이 서로를 막아 관측 자체가 불가능해진다."""
    resolved = os.path.realpath(candidate)
    if _within_host_scratchpad(resolved, roots):
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


def _within_host_scratchpad(resolved: str, roots: tuple[str, ...]) -> bool:
    """호스트가 이 프로젝트에 내준 임시 자리인가 — 시스템 프롬프트가 "여기를 쓰라"고 지정하는 그 폴더다.

    프로젝트 밖이라 경로 이탈로 막혔는데, 막힌 쪽은 임시 계측 스크립트와 분석 산출물이라
    역할이 그것을 저장소 안에 쓰거나 아예 포기했다 (26-08-04 실측).

    좁히는 열쇠는 프로젝트 슬러그다 — `_within_host_state` 와 같은 열쇠이고, 호스트가 임시 뿌리
    아래에 만드는 칸 이름이 그 슬러그다 (`<임시뿌리>/claude-501/-Users-…-asgard-custom/<세션>/scratchpad`).
    세션 id 로 좁히던 판은 이어받은 세션에서 통째로 닫혔다: 호스트는 이어받기마다 새 id 를
    내주는데 문맥에 남아 다시 쓰이는 경로는 처음 세션의 것이라 두 값이 어긋난다 (26-08-12 실측,
    스크래치패드 하나를 세션 넷이 물려받아 셋이 차단당했다). 같은 프로젝트의 다른 세션 자리가
    열리는 것은 받아들인 값이다 — 임시 뿌리 전체와 다른 프로젝트의 자리는 그대로 막힌다."""
    parts = resolved.split(os.sep)
    if "scratchpad" not in parts:
        return False
    temp_roots = {os.path.realpath(tempfile.gettempdir()), os.path.realpath("/tmp")}
    if not any(_within(base, resolved) for base in temp_roots):
        return False
    slugs = {root.replace(os.sep, "-").replace("_", "-") for root in roots}
    return bool(slugs.intersection(parts[: parts.index("scratchpad")]))


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


def path_token_within_root(roots: tuple[str, ...], token: str) -> bool:
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
    if _within_unit_workspace(candidate, roots) or _within_host_state(candidate, roots):
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


def within_managed_map(roots: tuple[str, ...], candidate: str) -> bool:
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


def path_token_targets_control(roots: tuple[str, ...], token: str, markers: tuple[str, ...]) -> bool:
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
        or within_managed_map(roots, candidate)
    ):
        return False  # 작업 공간·이 프로젝트 몫 상태 폴더·공유 지도는 작업 대상이다
    return any(_within(anchor, candidate) for anchor in _control_anchors(roots, markers))
