"""테스트 전역 전제 — 스위트는 밀폐돼야 한다.

개인 메모리의 시맨틱 스트림이 26-07-27부터 기본으로 켜진다. 그대로 두면 메모리를 건드리는
모든 테스트가 **489MB 임베딩 모델을 실제로 내려받아 로드한다** — 스위트가 네트워크에 묶이고,
같은 판정이 캐시 유무에 따라 다른 시간을 쓰고, 오프라인 CI 에서는 아예 다르게 돈다.

그래서 기본을 끈 채로 돌린다. 시맨틱 경로를 검증하는 테스트는 `set_embedder()` 주입 시임을
쓰는데, 그 시임은 mode보다 먼저 판정되므로(memory_semantic.embedder) 여기 영향을 받지 않는다.
실제 모델이 필요한 테스트가 생기면 그 테스트만 env를 직접 세우면 된다.
"""

import os
import tempfile

import pytest

# 훅의 공용 라이브러리는 배포 이름(`asgard_hooklib`)으로 산다 — 훅이 자기 폴더를 sys.path 에
# 얹어 그 이름을 세우고, 배포본에서는 스크립트 폴더가 곧 그 자리다. 스위트도 같은 이름을 써야
# 한다: `asgard.hooks.asgard_hooklib` 로 임포트하면 모듈 정체가 둘이 되고, 시험이 그쪽을
# 패치하면 훅이 쓰는 쪽은 그대로라 패치가 조용히 빗나간다. import 시점에 세우는 이유는 순서다 —
# 훅을 먼저 임포트한 시험만 성립하는 규칙은 규칙이 아니다.
import asgard.hooks  # noqa: F401 — sys.path 에 훅 폴더를 얹는 부작용이 목적이다

_ENV = "ASGARD_MEMORY_SEMANTIC"
_STUDIO_STATE = "ASGARD_STUDIO_STATE"
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
def _surface_state_is_not_shared():
    """`--json` 표면 상태는 그 테스트 안에서 끝난다.

    명령은 진입에서 `ui.set_quiet(json_out)`·`errors.set_json_surface(json_out)`를 켜고 끄지
    않는다 — 프로세스가 그 명령 하나를 위해 살다 끝나기 때문이다. 테스트는 한 프로세스에서
    명령 수십 개를 부르므로, 켠 채로 끝난 테스트 뒤의 테스트는 `ui.step`이 통째로 사라진 화면을
    본다. 그런데 `ui.warn`·`ok`는 조용해지지 않아서, 실패는 "출력이 없다"가 아니라 "문구가
    바뀌었다"로 보인다 — 원인과 증상이 어긋나 있어 화면 테스트가 무작위로 빨개진다.

    실측(26-08-03): `test_health_gate` 또는 `test_tutor` 뒤에 `test_memory_human_surface`가
    같은 워커에 놓이면 7건이 실패한다. 릴리스 파이프라인이 여기서 멈췄고, 같은 짝은
    b62d0dd에서도 똑같이 재현된다 — 워커 분배가 바뀔 때만 드러나던 오염이다."""
    from asgard import errors, ui

    try:
        yield
    finally:
        ui.set_quiet(False)
        errors.set_json_surface(False)


@pytest.fixture(autouse=True)
def _hermetic_studio_home(tmp_path_factory):
    """티켓 워크스페이스를 스위트 밖으로 뺀다 — 그리고 **테스트마다** 새 자리를 준다.

    자리를 옮기는 것만으로는 모자란다: 워크스페이스는 이제 폴더가 아니라 기계 단위라, 한
    자리를 세션 내내 함께 쓰면 앞 테스트가 만든 팀과 티켓이 뒤 테스트의 목록에 그대로 뜬다
    (폴더마다 파일이 갈리던 시절엔 임시 디렉터리가 그 격리를 대신해 줬다).

    실측: 이 문이 없던 첫 판에서 손상 판정용 쓰레기 파일이 사용자의 실제
    `~/.asgard/studio/workspace.db`로 그대로 나갔다."""
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
def _hermetic_studio_state():
    """Studio 등록부를 스위트 밖으로 뺀다.

    이 변수가 안 서 있으면 studio_store는 `~/.asgard/studio/`을 쓴다 — 즉 테스트가
    만든 임시 디렉터리들이 **사용자의 실제 프로젝트 목록에 그대로 쌓인다**. 실측: 등록
    29개 중 27개가 이미 사라진 `/var/folders/.../T/tmpXXXX` 였다."""
    previous = os.environ.get(_STUDIO_STATE)
    with tempfile.TemporaryDirectory(prefix="asgard-studio-home-") as home:
        os.environ[_STUDIO_STATE] = home
        try:
            yield home
        finally:
            if previous is None:
                os.environ.pop(_STUDIO_STATE, None)
            else:
                os.environ[_STUDIO_STATE] = previous
