"""작업 뿌리 선언 — 저장소 밖인데 이 작업의 대상인 자리를 설정에 적는다.

`hooks.readonly_guard` 는 선언된 뿌리 밖 경로를 막고, 처방으로 `paths.additional_roots` 선언을
지목한다. 그런데 그 선언이 사는 `.asgard/` 는 같은 가드의 통제 표면이라 손으로 못 고친다 —
처방과 금지가 한 가드 안에서 맞물려 교착이 된다 (26-08-07 실측: 짝 저장소의 파일 편집이 막히고,
이어서 그 처방대로 연 설정 파일 편집도 막혔다). 이 명령이 그 교착을 여는 자리다. 가드가 이미
비워 둔 "아스가르드 자신의 명령" 갈래로 들어가므로 새 예외를 뚫지 않는다.

선언은 에이전트가 고칠 수 있는 범위를 넓힌다. 그래서 확인 없이는 안 적는다: 터미널에서 부르면
그 자리에서 묻고, 물을 데가 없는 비대화형에서는 `--yes` 를 요구한다. 그 플래그가 오딘의 승인을
적는 자리이고, 에이전트가 스스로 넘길 수도 있다 — 막지는 못하되 선언은 Git 이 따라가는 파일에
한 줄로 남는다.
"""

from __future__ import annotations

import json
import os
import sys
from importlib import import_module

from .. import ui

_SECTION = "paths"
_KEY = "additional_roots"


def _has_marker(directory: str) -> bool:
    """여기가 프로젝트 뿌리인가 — 판정은 훅 라이브러리가 쥔다.

    가드가 거부문에서 "이 디렉터리를 열어라"라고 지목할 때 쓰는 것과 같은 판정이어야 한다
    (`asgard_hooklib.workspace.enclosing_project`). 갈라지면 가드가 지목한 자리를 이 명령이
    다른 뿌리로 읽고, 선언은 적혔는데 여전히 막히는 상태가 된다."""
    import asgard.hooks  # noqa: F401 — 임포트 부작용이 목적이다

    return import_module("asgard_hooklib.workspace").has_project_marker(directory)


def _project_root(start: str) -> str:
    """설정이 실제로 읽히는 자리 — 프로젝트가 아니면 빈 문자열.

    가드는 호스트가 넘긴 세션 뿌리의 `.asgard/asgard-setting-project.json` 만 읽는다. 그래서
    호스트가 그 뿌리를 알려 줬으면(`CLAUDE_PROJECT_DIR`) 그것이 정본이다 — 마커로 되짚어
    올라가면 하위 프로젝트의 설정 파일에 적고, 선언은 적혔는데 바깥 세션에서는 여전히 막히는
    상태가 된다. 알려 준 게 없으면 마커를 가진 가장 가까운 조상으로 물러서고, 그것도 없으면
    선언할 프로젝트가 없다고 답한다: 아무 데나 설정 파일을 만들면 아무도 안 읽는 자리에 적고도
    열렸다고 말하게 된다."""
    declared = os.environ.get("CLAUDE_PROJECT_DIR")
    if declared and os.path.isdir(declared):
        return os.path.realpath(declared)
    current = os.path.realpath(start)
    while True:
        if _has_marker(current):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return ""
        current = parent


def _outer_marker(root: str) -> str:
    """이 뿌리를 품는 또 다른 프로젝트 마커 — 없으면 빈 문자열.

    중첩 프로젝트에서 부르면 선언은 안쪽 설정에 적히는데, 바깥에서 연 세션의 가드는 바깥 설정을
    읽는다. 막을 일은 아니지만(안쪽에서 일하는 중일 수 있다) 말은 해 줘야 한다."""
    current = os.path.dirname(root)
    while True:
        if _has_marker(current):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return ""
        current = parent


def _work_roots(root: str) -> tuple[str, ...]:
    """가드가 세는 것과 같은 뿌리 목록 — 판정의 단일 출처는 훅 라이브러리다.

    임포트가 함수 안에 있고 모듈을 이름으로 집는 이유는 순서다. `asgard.hooks` 를 임포트해야 훅
    폴더가 `sys.path` 에 올라 배포 이름(`asgard_hooklib`)이 서고, 그 이름으로 불러야 라이브러리
    정체가 하나로 남는다 (`asgard.hooks.asgard_hooklib` 은 두 번째 정체다). 두 줄을 `from … import`
    로 나란히 적으면 정렬기가 차례를 뒤집어 부작용보다 사용이 먼저 온다."""
    import asgard.hooks  # noqa: F401 — 임포트 부작용이 목적이다

    return import_module("asgard_hooklib.workspace").work_roots(root)


def _resolve(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def _declared_paths(root: str, entries: list[str]) -> list[str]:
    """선언 문자열을 가드와 같은 규칙으로 편 절대 경로 — 상대 경로는 뿌리 기준이다."""
    out = []
    for entry in entries:
        expanded = os.path.expanduser(entry)
        out.append(_resolve(expanded if os.path.isabs(expanded) else os.path.join(root, expanded)))
    return out


def _section(root: str) -> dict:
    from ..settings import load_project

    section = load_project(root).get(_SECTION)
    return dict(section) if isinstance(section, dict) else {}  # `"paths": "x"` 는 섹션이 아니다


def _declared(root: str) -> list[str]:
    values = _section(root).get(_KEY)
    return [v.strip() for v in values if isinstance(v, str) and v.strip()] if isinstance(values, list) else []


def _guard_readable(root: str) -> None:
    """설정을 덮어써도 되는 상태인지 먼저 본다.

    `save_project` 는 파일 전체를 다시 쓰고, `load_project` 는 못 읽으면 빈 dict 로 물러선다.
    둘을 그대로 이으면 쉼표 하나 때문에 trinity_policy·agents·budget 이 한 번에 사라진다.
    같은 일이 섹션 층에서도 난다: `paths` 가 객체가 아니면 `_section` 이 그것을 `{}` 로 삼키고
    그 안에 있던 값이 말없이 증발한다. 그래서 최상위와 이 섹션을 둘 다 본다."""
    from ..settings import project_path

    path = project_path(root)
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 가 JSON 객체가 아니에요 — 고친 뒤 다시 불러 주세요")
    if _SECTION in data and not isinstance(data[_SECTION], dict):
        raise ValueError(f"{path} 의 `{_SECTION}` 가 객체가 아니에요 — 고친 뒤 다시 불러 주세요")


def _reject_target(root: str, target: str) -> str:
    """이 자리를 열어도 되는가 — 열면 안 되는 것만 이름을 대고 막는다. 통과면 빈 문자열.

    선언은 가드의 경계 그 자체라, 넓은 자리 하나를 열면 남은 판정이 통째로 무의미해진다. 막는
    것은 셋이다: 기계 뿌리, 홈 디렉터리 그 자체, 그리고 이 프로젝트를 품는 조상 — 조상을 열면
    이웃한 다른 저장소와 그 하네스 상태까지 한꺼번에 딸려 온다. 신뢰 경계 입력 검증이라
    lagom 의 안전 예외다."""
    hint = " — 열어야 하는 디렉터리를 직접 짚어 주세요"
    if target == os.path.dirname(target):
        return "기계 뿌리 전체는 못 열어요" + hint
    if target == _resolve("~"):
        return "홈 디렉터리 전체는 못 열어요" + hint
    if root == target or root.startswith(target + os.sep):
        return f"{target} 는 이 프로젝트를 품는 자리예요 — 열면 이웃한 저장소까지 다 딸려와요" + hint
    return ""


def _entry_text(root: str, target: str, absolute: bool) -> str:
    """설정에 적을 형태 — 기본은 뿌리 기준 상대 경로.

    이 파일은 팀이 함께 읽는 Git 자산이라 `/Users/<이름>/…` 을 적으면 다른 사람 기계에서 아무
    자리도 안 가리킨다. 짝 저장소는 대개 형제 폴더여서 `../helios-application` 로 적힌다.
    두 단계 이상 거슬러 올라가는 꼴(`../../../..`)은 상대 경로로 안 적는다 — 디프를 읽는 사람이
    그 점 여덟 개가 어디를 가리키는지 셀 수 없다. 그 자리를 절대 경로로 메우면 위에 적은 이유가
    그대로 되살아나므로, 홈 아래라면 `~/…` 로 적는다: 사용자 이름이 안 들어가고, 이 선언을 읽는
    두 자리가 모두 `expanduser` 를 거친다 (`settings.declared_roots` — 프로젝트 메모리도 여기로
    들어온다 — 와 훅 쪽 `asgard_hooklib.workspace.work_roots`). 홈 밖이거나 드라이브가
    다르면(Windows) 남는 길은 절대 경로뿐이다."""
    if absolute:
        return target
    try:
        relative = os.path.relpath(target, root)
    except ValueError:
        relative = ""
    climbing = os.pardir + os.sep + os.pardir
    if relative and not relative.startswith(climbing):
        return relative
    home = os.path.realpath(os.path.expanduser("~"))
    if target == home or target.startswith(home + os.sep):
        return "~" + target[len(home) :].replace(os.sep, "/")
    return target


def _fail(message: str, json_out: bool) -> int:
    print(json.dumps({"error": message}, ensure_ascii=False)) if json_out else ui.warn(message)
    return 2


_NO_PROJECT = "여기는 아스가르드 프로젝트가 아니에요 — 프로젝트 안에서 부르거나 `asgard init` 을 먼저 돌려 주세요"


def _can_ask() -> bool:
    """물을 데가 있는가 — 두 흐름이 다 터미널일 때만.

    `input()` 의 물음은 stdout 으로 나간다. stdout 이 파일이나 파이프로 가 있으면 사용자는 물음을
    못 본 채 멈춘 화면만 본다."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _consent(target: str, json_out: bool, assume_yes: bool) -> str:
    """승인을 받았는가 — 빈 문자열이면 통과, 아니면 거절 사유.

    터미널에서 부르면 그 자리에서 묻는다. 에이전트의 Bash 는 TTY 가 아니라 물을 데가 없으므로
    `--yes` 를 요구한다: 오딘에게 먼저 묻고 그 답을 플래그로 적으라는 뜻이다."""
    if assume_yes:
        return ""
    if json_out or not _can_ask():
        return (
            f"{target} 를 열면 에이전트가 그 안의 파일을 고칠 수 있어요. 오딘에게 먼저 물어보고, "
            "승인받았으면 `--yes` 를 붙여 다시 불러 주세요"
        )
    try:
        answer = input(f"{target} 를 작업 대상으로 열까요? 에이전트가 그 안을 고칠 수 있어요 [y/N] ")
    except EOFError, KeyboardInterrupt:
        return "취소했어요"
    return "" if answer.strip().lower() in ("y", "yes") else "취소했어요"


def run_root_list(*, json_out: bool = False) -> int:
    """`asgard root list` — 지금 힘을 쓰는 작업 뿌리와, 그중 이 프로젝트가 선언한 것.

    프로젝트 밖에서도 답한다 — 읽기라 만들 파일이 없고, "여기서 무엇이 열려 있나"는 어디서든
    물을 수 있는 물음이다."""
    root = _project_root(os.getcwd()) or os.path.realpath(os.getcwd())
    ui.set_quiet(json_out)
    roots = _work_roots(root)
    declared = _declared(root)
    if json_out:
        payload = {"root": root, "work_roots": list(roots), "declared": declared}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    ui.head("root · 이 작업이 만져도 되는 자리")
    for entry in roots:
        ui.step(entry + (ui.dim("  ← 이 프로젝트") if entry == root else ""))
    if declared:
        from ..settings import project_path

        ui.step(ui.dim(f"    선언: {', '.join(declared)}"))
        ui.step(ui.dim(f"    {project_path(root)}"))
    ui.done()
    return 0


def run_root_add(directory: str, *, assume_yes: bool = False, absolute: bool = False, json_out: bool = False) -> int:
    """`asgard root add <dir>` — 저장소 밖 디렉터리를 작업 대상으로 선언한다."""
    from ..settings import save_project

    root = _project_root(os.getcwd())
    ui.set_quiet(json_out)
    if not root:
        return _fail(_NO_PROJECT, json_out)
    target = _resolve(directory)
    if not os.path.isdir(target):
        return _fail(f"{target} 는 디렉터리가 아니에요 — 열 자리를 먼저 확인해 주세요", json_out)
    if any(target == entry or target.startswith(entry + os.sep) for entry in _work_roots(root)):
        if json_out:
            print(json.dumps({"root": root, "directory": target, "added": False}, ensure_ascii=False, indent=2))
        else:
            ui.ok(f"{target} 는 이미 작업 대상이에요")
            ui.done()
        return 0
    for refusal in (_reject_target(root, target), _consent(target, json_out, assume_yes)):
        if refusal:
            return _fail(refusal, json_out)
    try:
        _guard_readable(root)
        values = _section(root)
        values[_KEY] = list(dict.fromkeys([*_declared(root), _entry_text(root, target, absolute)]))
    except json.JSONDecodeError as error:
        return _fail(f"프로젝트 설정을 JSON 으로 못 읽었어요 — {error}", json_out)
    except (ValueError, OSError) as error:
        return _fail(
            str(error) if isinstance(error, ValueError) else f"프로젝트 설정을 못 읽었어요 — {error}", json_out
        )
    path = save_project(root, _SECTION, values)
    # 기록이 실제로 남았는지 되읽는다. 이 확인이 증명하는 것은 거기까지다 — 이 뿌리에서 읽으면
    # 열린다는 것이지, 세션의 가드가 **이** 설정 파일을 읽는다는 것이 아니다. 그 축은 위의
    # `_project_root` 와 아래 `_outer_marker` 가 진다.
    if not any(target == entry or target.startswith(entry + os.sep) for entry in _work_roots(root)):
        return _fail(f"{path} 에 적었는데 {target} 가 여전히 뿌리 밖이에요 — 그 설정을 읽는 자리가 아니에요", json_out)
    outer = _outer_marker(root)
    if json_out:
        payload = {"root": root, "directory": target, "added": True, "declared": values[_KEY], "path": path}
        print(json.dumps({**payload, "outer_project": outer} if outer else payload, ensure_ascii=False, indent=2))
        return 0
    ui.head("root · 작업 대상을 열었어요")
    ui.ok(f"{target}")
    ui.step(ui.dim(f"    {path}"))
    if outer:
        ui.warn(f"{outer} 안에 있는 프로젝트예요 — 거기서 연 세션은 이 선언을 안 읽어요")
    ui.done()
    return 0


def run_root_remove(directory: str, *, json_out: bool = False) -> int:
    """`asgard root remove <dir>` — 선언을 도로 거둔다."""
    from ..settings import save_project

    root = _project_root(os.getcwd())
    ui.set_quiet(json_out)
    if not root:
        return _fail(_NO_PROJECT, json_out)
    target = _resolve(directory)
    entries = _declared(root)
    kept = [text for text, path in zip(entries, _declared_paths(root, entries), strict=True) if path != target]
    if len(kept) == len(entries):
        return _fail(
            f"{target} 는 이 프로젝트가 선언한 자리가 아니에요 — `asgard root list` 로 어디서 왔는지 확인해 주세요",
            json_out,
        )
    try:
        _guard_readable(root)
        values = _section(root)
        values[_KEY] = kept
    except json.JSONDecodeError as error:
        return _fail(f"프로젝트 설정을 JSON 으로 못 읽었어요 — {error}", json_out)
    except (ValueError, OSError) as error:
        return _fail(
            str(error) if isinstance(error, ValueError) else f"프로젝트 설정을 못 읽었어요 — {error}", json_out
        )
    path = save_project(root, _SECTION, values)
    if json_out:
        print(json.dumps({"root": root, "directory": target, "declared": kept, "path": path}, ensure_ascii=False))
        return 0
    ui.head("root · 선언을 거뒀어요")
    ui.ok(f"{target}")
    ui.step(ui.dim(f"    {path}"))
    ui.done()
    return 0
