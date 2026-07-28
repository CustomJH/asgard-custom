"""테스트 전역 전제 — 스위트는 밀폐돼야 한다.

개인 메모리의 시맨틱 스트림이 26-07-27 부터 기본으로 켜진다. 그대로 두면 메모리를 건드리는
모든 테스트가 **489MB 임베딩 모델을 실제로 내려받아 로드한다** — 스위트가 네트워크에 묶이고,
같은 판정이 캐시 유무에 따라 다른 시간을 쓰고, 오프라인 CI 에서는 아예 다르게 돈다.

그래서 기본을 끈 채로 돌린다. 시맨틱 경로를 검증하는 테스트는 `set_embedder()` 주입 시임을
쓰는데, 그 시임은 mode 보다 먼저 판정되므로(memory_semantic.embedder) 여기 영향을 받지 않는다.
실제 모델이 필요한 테스트가 생기면 그 테스트만 env 를 직접 세우면 된다.
"""

import os

import pytest

_ENV = "ASGARD_MEMORY_SEMANTIC"


@pytest.fixture(autouse=True)
def _hermetic_semantic_stream():
    previous = os.environ.get(_ENV)
    os.environ[_ENV] = "off"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(_ENV, None)
        else:
            os.environ[_ENV] = previous
