"""asgard CLI (Python 3.14) — Typer 진입.

명령 표면은 그룹별 모듈이 나눠 지고, 이 파일은 그것들을 등록 차례대로 불러 모은다.
차례가 데이터(`_GROUPS`)인 것이 요점이다 — 임포트 문으로 적으면 정렬기가 알파벳순으로
바꿔 놓고, 그 순간 사용자가 보는 `--help` 목록이 조용히 뒤섞인다.

그룹은 **물어볼 때 등록한다.** 한 번 열 때마다 그룹을 다 등록하면 typer 가 명령 표면 전체를
매 호출마다 Click 객체로 다시 짓는다 — `asgard map context` 하나가 나머지 그룹의 명령까지
짓고 버린다는 뜻이고, 훅 넷이 매 턴 그 값을 각각 낸다. `_LazyCommands` 가 루트 명령표를
대신 들어서, 이름 하나를 물으면 그 이름을 매다는 모듈까지만 등록한다. 명령표를 통째로 훑는
쪽(`--help`, `completions` 스크립트, 표면 시험)은 훑는 순간 전부 등록되므로 예전과
똑같은 것을 본다.

`app`·`main`은 여기서 다시 내보낸다: `from asgard.cli import app`이 파일 하나였을 때와
똑같이 닿아야 한다."""

from importlib import import_module
from typing import Any

import typer.main
from typer.core import TyperGroup

from ._app import _agent, _main, _version, app, main

# 등록 차례 = `asgard --help` 차례.
_GROUPS = (
    "root",
    "roots",
    "review",
    "agent",
    "map",
    "just",
    "role",
    "siege",
    "skills",
    "memory",
    "ticket",
    "evolve",
    "office",
    "k6",
)

# 그룹 모듈이 등록한 명령·하위그룹 — 등록 차례를 `_GROUPS` 로 되돌릴 때 쓴다.
# 키는 `_GROUPS` 의 이름뿐이라 그 길이를 넘지 않는다. 값은 typer 가 `app` 에 이미 매달아 둔
# 등록 정보를 가리키므로, 이 표가 무엇의 수명도 늘리지 않는다.
_REGISTERED: dict[str, tuple[list[Any], list[Any]]] = {}


def _load(name: str) -> None:
    """그룹 모듈 하나를 등록한다. 이미 등록됐거나 그런 그룹이 없으면 아무 일도 안 한다."""
    if name not in _GROUPS or name in _REGISTERED:
        return
    commands, groups = len(app.registered_commands), len(app.registered_groups)
    import_module(f".{name}", __name__)
    _REGISTERED[name] = (app.registered_commands[commands:], app.registered_groups[groups:])


def _load_all() -> None:
    """`_GROUPS` 를 전부 등록하고 등록 차례를 그 차례로 되돌린다.

    되돌리는 자리가 필요한 이유는 한 프로세스가 명령을 두 번 지나는 경우다(시험의 CliRunner).
    먼저 지나간 `asgard memory ...`가 memory 를 아홉째가 아니라 첫째로 등록해 두면, 뒤이은
    `--help`는 같은 그룹을 다른 차례로 낸다. 차례를 정하는 것은 `_GROUPS`지 무엇을 먼저
    불렀느냐가 아니다. 바깥에서 직접 매단 명령(시험이 `@app.command()`로 붙이는 것)은
    어느 그룹의 것도 아니므로 뒤에 그대로 남긴다."""
    for name in _GROUPS:
        _load(name)
    for attribute, index in (("registered_commands", 0), ("registered_groups", 1)):
        registry = getattr(app, attribute)
        ordered = [info for name in _GROUPS for info in _REGISTERED[name][index]]
        known = {id(info) for info in ordered}
        registry[:] = ordered + [info for info in registry if id(info) not in known]


def _declares(cmd_name: str) -> bool:
    """등록된 것 중에 이 이름이 있는가 — Click 객체를 짓지 않고 본다.

    지어 보고 확인하면 그룹을 하나 더 등록할 때마다 표면 전체를 다시 짓게 된다. 그래서 typer 가
    이름을 정하는 규칙(`name`, 없으면 함수 이름의 밑줄을 하이픈으로)만 여기서 따라 읽는다.
    이 판정이 틀려서 없다고 답하면 다음 모듈을 등록할 뿐이고, 전부 등록하면 예전 동작과
    같아진다 — 틀리는 방향이 안전한 쪽이다."""
    for info in app.registered_groups:
        if info.name == cmd_name:
            return True
    for info in app.registered_commands:
        declared = info.name or (info.callback and typer.main.get_command_name(info.callback.__name__))
        if declared == cmd_name:
            return True
    return False


class _LazyGroup(TyperGroup):
    """루트 그룹 — 이름 하나를 물으면 그 그룹만, 명령표를 통째로 달라면 전부 등록한다.

    갈림은 `commands` 를 속성으로 감싼 자리다. 표면 전체를 읽는 쪽은 typer 든 click 이든
    우리 시험이든 전부 이 하나를 지나므로(`--help`의 list_commands, `completions`가 읽는
    표면, 표면 시험의 `commands["completions"]`), 여기서 다 등록하면 훑는 쪽은 예전과
    똑같은 표를 본다. 명령 하나를 실행하는 경로만 `_table` 을 직접 봐서 자기 그룹까지만
    짓는다 — 매핑 연산을 하나씩 세어 가로채면 세다 빠뜨린 하나가 그대로 구멍이 된다."""

    _complete = False

    @property
    def commands(self) -> dict[str, Any]:
        self._fill()
        return self._table

    @commands.setter
    def commands(self, table: dict[str, Any]) -> None:
        self._table = table

    def _fill(self) -> None:
        """`_GROUPS` 를 등록하고 표를 통째로 다시 짓는다 — 차례까지 등록 차례 그대로.

        새로 지은 그룹은 `commands`가 아니라 `_table`로 읽는다. 속성으로 읽으면 그쪽이 다시
        여기로 들어와 짓기를 되풀이한다."""
        if self._complete:
            return
        self._complete = True  # 아래 재구축이 이 속성을 다시 읽어도 되돌아오지 않게 먼저 세운다
        _load_all()
        self._table = typer.main.get_command(app)._table

    def get_command(self, ctx: Any, cmd_name: str) -> Any:
        command = self._table.get(cmd_name)
        return command if command is not None else self._register(cmd_name)

    def _register(self, cmd_name: str) -> Any:
        """이 이름을 매다는 모듈이 나올 때까지 등록하고, 그 명령 하나를 지어 돌려준다.

        먼저 이름과 같은 모듈을 본다 — `memory`·`map`·`skills`처럼 대개 그 자리에서 끝난다.
        아니면 `_GROUPS` 차례로 훑는다: 최상위 명령(`tutor`·`doctor`)은 전부 첫째인 root 가
        매달고, `setup`처럼 이름과 모듈이 다른 자리는 그 모듈까지만 등록하고 멈춘다."""
        for name in (cmd_name, *_GROUPS):
            _load(name)
            if _declares(cmd_name):
                break
        else:
            return None
        command = typer.main.get_command(app)._table.get(cmd_name)
        if command is not None:
            self._table[cmd_name] = command
        return command


# 루트 그룹만 지연 로딩한다. `Typer(cls=...)`가 아니라 여기서 세우는 이유는 층이다 — `_app`은
# 이 파일보다 아래이고, 아래가 위를 부르면 순환이 된다(`_app` 모듈 docstring).
app.info.cls = _LazyGroup


def __getattr__(name: str) -> Any:
    """하위 앱을 이름으로 쥐는 시험이 있다 (tests/test_k6.py) — 물을 때 그 모듈을 등록한다."""
    if name in ("k6_app", "k6_baseline_app"):
        _load("k6")
        return getattr(import_module(".k6", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["app", "main", "_main", "_version", "_agent", "k6_app", "k6_baseline_app"]
