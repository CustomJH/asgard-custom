"""창이 살아 있는 동안 드는 것 — 이 패키지에서 **변하는 값은 전부 여기 하나에** 있다.

여기저기에 모듈 전역을 두면 두 가지가 샌다. 하나는 재바인딩이다: 다른 모듈이
`from .state import _CURRENT_ROOT`로 가져가면 그건 그때의 **값**이라, 여기서 바꿔도
저쪽은 옛 값을 계속 든다. 그래서 밖에서는 늘 `state._CURRENT_ROOT`로 모듈을 통해 읽는다.
다른 하나는 테스트다 — 자리를 되돌릴 곳이 하나여야 판마다 깨끗한 상태에서 시작한다.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from ... import profiles

if TYPE_CHECKING:  # pragma: no cover - 타입 전용
    from .server import _RootServer


def _task_owner(value: object = None) -> str:
    return profiles.normalize(str(value or profiles.DEFAULT))


class _ProfileTasks(dict[tuple[str, str], dict]):
    """같은 서버의 프로파일 창들이 같은 작업 ID를 써도 상태를 공유하지 않는다."""

    @staticmethod
    def _key(key: object) -> tuple[str, str]:
        if isinstance(key, tuple) and len(key) == 2:
            return str(key[0]), str(key[1])
        return _task_owner(profiles.active()), str(key)

    def __getitem__(self, key: object) -> dict:
        return super().__getitem__(self._key(key))

    def __setitem__(self, key: object, value: dict) -> None:
        owner = _task_owner(value.get("agent")) if not isinstance(key, tuple) else str(key[0])
        super().__setitem__((owner, str(key if not isinstance(key, tuple) else key[1])), value)

    def __contains__(self, key: object) -> bool:
        return super().__contains__(self._key(key))

    # 반환이 Any 인 이유는 dict.get 이 오버로드 셋이기 때문이다 — 기본값의 타입이 반환 타입을
    # 정한다. 단일 시그니처로 그 셋을 다 덮으려면 이 자리 말고는 적을 곳이 없다.
    def get(self, key: object, default: object = None) -> Any:
        return super().get(self._key(key), default)


_TASKS = _ProfileTasks()
_TASK_LOCK = threading.Lock()
_MAX_RUNNING = 4
_PROMPT_CAP = 20_000
_LOG_CAP = 200_000
_ARTIFACT_CAP = 400_000  # 뷰어가 읽는 최대 바이트 — 창은 편집기가 아니다

# 어느 프로젝트를 보고 있는가. 프로세스가 뜰 때는 서버가 잡은 root 지만, 사용자가 창 안에서
# 프로젝트를 바꾸면 이 값이 정본이 된다. 서버 객체가 아니라 모듈에 두는 이유: dispatch_post는
# 핸들러를 안 받는데 전환은 POST 이고, 전환 직후의 GET도 같은 답을 해야 하기 때문이다.
_CURRENT_ROOT: str | None = None
_ROOT_LOCK = threading.Lock()
_LOADED_ROOTS: set[tuple[str, str]] = set()
_SERVER: "_RootServer | None" = None

_SETTING_KEYS = {
    "provider": {"name", "model", "base_url", "api_key_env", "context_window", "rpm"},
    "ui": {"lang", "theme", "density", "studio_permission"},
    "memory": {"directory", "inject", "providers", "auto_retain_turns", "autosave"},
    "lagom": {"mode"},
    "bridge": {"claude-code", "cursor", "codex"},
}


def trim(text: str) -> str:
    """기록에 남길 만큼만 — 상한을 아는 자리가 자르는 자리다."""
    return text[-_LOG_CAP:]
