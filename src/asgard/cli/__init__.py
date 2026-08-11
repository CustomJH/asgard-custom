"""asgard CLI (Python 3.14) — Typer 진입.

명령 표면은 그룹별 모듈이 나눠 지고, 이 파일은 그것들을 등록 차례대로 불러 모은다.
차례가 데이터(`_GROUPS`)인 것이 요점이다 — 임포트 문으로 적으면 정렬기가 알파벳순으로
바꿔 놓고, 그 순간 사용자가 보는 `--help` 목록이 조용히 뒤섞인다.

`app`·`main`은 여기서 다시 내보낸다: `from asgard.cli import app`이 파일 하나였을 때와
똑같이 닿아야 한다."""

from importlib import import_module

from ._app import _agent, _main, _version, app, main

# 등록 차례 = `asgard --help` 차례.
_GROUPS = (
    "root",
    "roots",
    "review",
    "agent",
    "map",
    "role",
    "siege",
    "skills",
    "memory",
    "ticket",
    "evolve",
    "office",
    "k6",
)
_loaded = {name: import_module(f".{name}", __name__) for name in _GROUPS}

# 하위 앱을 이름으로 쥐는 시험이 있다 (tests/test_k6.py) — 그 자리만 다시 내보낸다.
k6_app = _loaded["k6"].k6_app
k6_baseline_app = _loaded["k6"].k6_baseline_app

__all__ = ["app", "main", "_main", "_version", "_agent", "k6_app", "k6_baseline_app"]
