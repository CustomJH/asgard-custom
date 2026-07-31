"""테스트 전역 전제 — 스위트는 밀폐돼야 한다.

개인 메모리의 시맨틱 스트림이 26-07-27 부터 기본으로 켜진다. 그대로 두면 메모리를 건드리는
모든 테스트가 **489MB 임베딩 모델을 실제로 내려받아 로드한다** — 스위트가 네트워크에 묶이고,
같은 판정이 캐시 유무에 따라 다른 시간을 쓰고, 오프라인 CI 에서는 아예 다르게 돈다.

그래서 기본을 끈 채로 돌린다. 시맨틱 경로를 검증하는 테스트는 `set_embedder()` 주입 시임을
쓰는데, 그 시임은 mode 보다 먼저 판정되므로(memory_semantic.embedder) 여기 영향을 받지 않는다.
실제 모델이 필요한 테스트가 생기면 그 테스트만 env 를 직접 세우면 된다.
"""

import os
import tempfile

import pytest

_ENV = "ASGARD_MEMORY_SEMANTIC"
_DESKTOP_HOME = "ASGARD_DESKTOP_HOME"
_STUDIO_HOME = "ASGARD_STUDIO_HOME"


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


@pytest.fixture(autouse=True)
def _hermetic_studio_home(tmp_path_factory):
    """티켓 워크스페이스를 스위트 밖으로 뺀다 — 그리고 **테스트마다** 새 자리를 준다.

    자리를 옮기는 것만으로는 모자란다: 워크스페이스는 이제 폴더가 아니라 기계 단위라, 한
    자리를 세션 내내 함께 쓰면 앞 테스트가 만든 팀과 티켓이 뒤 테스트의 목록에 그대로 뜬다
    (폴더마다 파일이 갈리던 시절엔 임시 디렉터리가 그 격리를 대신해 줬다).

    실측: 이 문이 없던 첫 판에서 손상 판정용 쓰레기 파일이 사용자의 실제
    `~/.asgard/studio/workspace.db` 로 그대로 나갔다."""
    previous = os.environ.get(_STUDIO_HOME)
    home = tmp_path_factory.mktemp("asgard-studio-home")
    os.environ[_STUDIO_HOME] = str(home)
    try:
        yield str(home)
    finally:
        if previous is None:
            os.environ.pop(_STUDIO_HOME, None)
        else:
            os.environ[_STUDIO_HOME] = previous


@pytest.fixture(autouse=True, scope="session")
def _hermetic_desktop_home():
    """Desktop 등록부를 스위트 밖으로 뺀다.

    이 변수가 안 서 있으면 desktop_store 는 `~/.asgard/desktop/` 을 쓴다 — 즉 테스트가
    만든 임시 디렉터리들이 **사용자의 실제 프로젝트 목록에 그대로 쌓인다**. 실측: 등록
    29개 중 27개가 이미 사라진 `/var/folders/.../T/tmpXXXX` 였다."""
    previous = os.environ.get(_DESKTOP_HOME)
    with tempfile.TemporaryDirectory(prefix="asgard-desktop-home-") as home:
        os.environ[_DESKTOP_HOME] = home
        try:
            yield home
        finally:
            if previous is None:
                os.environ.pop(_DESKTOP_HOME, None)
            else:
                os.environ[_DESKTOP_HOME] = previous
