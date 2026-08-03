"""컨테이너 하나 = 에이전트 하나 — 명령줄 조립을 재는 판정기.

도커 없이 도는 시험이 본체다: `run_container`가 만든 argv 안에 (1) 컨테이너 안 경로로 옮긴
ASGARD_HOME과 (2) 에이전트 홈 마운트가 들어 있는지, (3) 활성 에이전트가 바뀌면 그 둘이 따라
바뀌는지, (4) 기본 에이전트에서도 기존 계약이 그대로인지를 잰다. 마지막 한 건만 실제 기동을
재고, 이미지가 없으면 skip한다 (CI에 도커가 없어도 안 깨진다).
"""

import json
import os
import shutil
import subprocess
from unittest import mock

import pytest

from asgard import __version__, profiles, sandbox

IMAGE = f"asgard-runtime:{__version__}"
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COMPOSE = os.path.join(_REPO, "docker", "compose.agents.yml")


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """이 시험만의 기계 뿌리 — profiles.root()가 HOME을 보므로 HOME을 옮긴다."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for key in ("ASGARD_HOME", "ASGARD_PROFILE", "ASGARD_CONTAINER_CREDENTIALS"):
        monkeypatch.delenv(key, raising=False)
    os.makedirs(tmp_path / ".asgard", exist_ok=True)
    return tmp_path


def _argv(monkeypatch, tmp_path, root=None):
    """run_container를 도커 없이 돌려 실제로 실행됐을 argv를 돌려준다."""
    workspace = tmp_path / "private"
    workspace.mkdir(exist_ok=True)
    monkeypatch.setattr(sandbox, "_container_engine", lambda: "/usr/bin/docker")
    monkeypatch.setattr(sandbox, "_private_workspace", lambda _root, _name: workspace)
    monkeypatch.setattr(sandbox.sys.stdin, "isatty", lambda: False)
    calls = [mock.Mock(returncode=0), mock.Mock(returncode=0)]
    with mock.patch("asgard.sandbox.subprocess.run", side_effect=calls) as run:
        assert sandbox.run_container(root or str(tmp_path / "demo"), name="safe-box") == 0
    return run.call_args_list[1].args[0]


def _env_values(argv, key):
    """argv에서 `--env KEY=...` 로 실린 값들 — 순서나 이웃 인자에 기대지 않는다."""
    return [item.split("=", 1)[1] for item in argv if isinstance(item, str) and item.startswith(f"{key}=")]


# ── 1·2. ASGARD_HOME과 에이전트 홈 마운트가 argv에 들어간다 ─────────────────────────


def test_container_gets_the_agent_home_as_a_container_path(machine, monkeypatch):
    profiles.create("loki")
    monkeypatch.setenv("ASGARD_PROFILE", "loki")

    argv = _argv(monkeypatch, machine)

    assert _env_values(argv, "ASGARD_HOME") == ["/agent/loki"]


def test_container_mounts_the_agent_home(machine, monkeypatch):
    home = profiles.create("loki")
    monkeypatch.setenv("ASGARD_PROFILE", "loki")

    argv = _argv(monkeypatch, machine)

    assert f"type=bind,src={home},dst=/agent/loki" in argv


def test_host_path_never_leaks_into_the_container_env(machine, monkeypatch):
    """호스트 경로를 그대로 넘기면 컨테이너 안에서 없는 경로가 된다 — 그 사고를 막는다."""
    home = profiles.create("loki")
    monkeypatch.setenv("ASGARD_PROFILE", "loki")

    argv = _argv(monkeypatch, machine)

    assert f"ASGARD_HOME={home}" not in argv


def test_profile_name_does_not_ride_along(machine, monkeypatch):
    """ASGARD_PROFILE은 안 넘긴다 — 컨테이너 안에는 `profiles/<id>` 자리가 없다."""
    profiles.create("loki")
    monkeypatch.setenv("ASGARD_PROFILE", "loki")

    argv = _argv(monkeypatch, machine)

    assert _env_values(argv, "ASGARD_PROFILE") == []


# ── 3. 활성 에이전트가 바뀌면 argv도 따라 바뀐다 ───────────────────────────────────


def test_argv_follows_the_active_agent(machine, monkeypatch):
    loki_home = profiles.create("loki")
    mimir_home = profiles.create("mimir")

    monkeypatch.setenv("ASGARD_PROFILE", "loki")
    loki = _argv(monkeypatch, machine)
    monkeypatch.setenv("ASGARD_PROFILE", "mimir")
    mimir = _argv(monkeypatch, machine)

    assert _env_values(loki, "ASGARD_HOME") == ["/agent/loki"]
    assert _env_values(mimir, "ASGARD_HOME") == ["/agent/mimir"]
    assert f"type=bind,src={loki_home},dst=/agent/loki" in loki
    assert f"type=bind,src={mimir_home},dst=/agent/mimir" in mimir


def test_sticky_active_agent_reaches_the_container(machine, monkeypatch):
    """`asgard agent use`로 고정한 에이전트도 컨테이너까지 간다 (env가 비어도)."""
    profiles.create("loki")
    profiles.set_active("loki")

    argv = _argv(monkeypatch, machine)

    assert _env_values(argv, "ASGARD_HOME") == ["/agent/loki"]


def test_unnamed_home_is_labelled_by_its_directory(machine, monkeypatch):
    """이름 없는 홈(`custom`)은 홈 디렉터리 이름으로 불린다 — 컨테이너 여럿을 가르는 이름."""
    volume = machine / "opt" / "agent-data"
    volume.mkdir(parents=True)
    monkeypatch.setenv("ASGARD_HOME", str(volume))

    argv = _argv(monkeypatch, machine)

    assert profiles.active() == profiles.CUSTOM
    assert _env_values(argv, "ASGARD_HOME") == ["/agent/agent-data"]
    assert f"type=bind,src={volume},dst=/agent/agent-data" in argv


def test_label_folds_characters_that_cannot_be_a_path_segment(machine, monkeypatch):
    volume = machine / "opt" / "agent data (qa)"
    volume.mkdir(parents=True)
    monkeypatch.setenv("ASGARD_HOME", str(volume))

    assert sandbox.agent_label() == "agent-data-qa"


# ── 4. 기본 에이전트에서도 안 깨진다 (회귀 0) ──────────────────────────────────────


def test_default_agent_still_boots(machine, monkeypatch):
    argv = _argv(monkeypatch, machine)

    assert _env_values(argv, "ASGARD_HOME") == ["/agent/default"]
    assert f"type=bind,src={machine / '.asgard'},dst=/agent/default" in argv


def test_existing_container_contract_is_untouched(machine, monkeypatch):
    """workspace 마운트·격리 플래그·로그인 없음 — 이 패치 전의 계약 그대로."""
    workspace = machine / "private"

    argv = _argv(monkeypatch, machine)

    assert argv[:5] == ["/usr/bin/docker", "run", "--rm", "--name", mock.ANY]
    assert argv[5:9] == ["--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    assert f"type=bind,src={workspace},dst=/workspace" in argv
    assert "ASGARD_EXECUTION=local" in argv and "ASGARD_ISOLATION=oci-container" in argv
    assert argv[-1] == IMAGE
    assert "sbx" not in argv and "login" not in argv


# ── 자격증명은 기본으로 안 넘어간다 ────────────────────────────────────────────────


def test_shared_credentials_stay_on_the_host_by_default(machine, monkeypatch):
    cred = machine / ".asgard" / "credentials.json"
    cred.write_text("{}", encoding="utf-8")

    argv = _argv(monkeypatch, machine)

    assert not [item for item in argv if isinstance(item, str) and "credentials.json" in item]


def test_shared_credentials_are_read_only_when_opted_in(machine, monkeypatch):
    cred = machine / ".asgard" / "credentials.json"
    cred.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ASGARD_CONTAINER_CREDENTIALS", "1")

    argv = _argv(monkeypatch, machine)

    assert f"type=bind,src={cred},dst={sandbox.CONTAINER_CRED_PATH},readonly" in argv


def test_agent_owned_credentials_ride_the_home_mount(machine, monkeypatch):
    """에이전트 전용 키는 따로 배선하지 않는다 — 에이전트 홈 안에 있어 마운트에 이미 포함된다."""
    home = profiles.create("loki")
    with open(os.path.join(home, "credentials.json"), "w", encoding="utf-8") as handle:
        handle.write("{}")
    monkeypatch.setenv("ASGARD_PROFILE", "loki")

    argv = _argv(monkeypatch, machine)

    assert f"type=bind,src={home},dst=/agent/loki" in argv


# ── 이미지와 실행측이 같은 자리를 가리킨다 ──────────────────────────────────────────


def test_image_and_launcher_agree_on_the_agent_home_root():
    """한쪽만 바꾸면 실행측이 마운트한 자리와 이미지가 읽는 자리가 어긋난다."""
    from importlib.resources import files

    dockerfile = files("asgard").joinpath("assets", "container_kit", "Dockerfile").read_text(encoding="utf-8")

    assert f'VOLUME ["{sandbox.CONTAINER_AGENT_ROOT}"]' in dockerfile
    assert f"ENV ASGARD_HOME={sandbox.CONTAINER_AGENT_ROOT}/{profiles.DEFAULT}" in dockerfile


def test_compose_example_uses_the_image_the_launcher_builds():
    """compose가 딴 이미지를 구우면 예시가 도는 것과 `asgard start`가 도는 것이 갈린다.

    태그는 `${ASGARD_VERSION:?...}`라 고정 숫자가 없다 — 판 대신 값을 안 주면 멈추게 해서,
    릴리스마다 이 파일이 낡아 조용히 옛 이미지를 쓰는 경우를 없앴다."""
    body = open(_COMPOSE, encoding="utf-8").read()

    assert "image: asgard-runtime:${ASGARD_VERSION:?" in body
    for agent in ("freyja", "loki", "mimir"):
        assert f"ASGARD_HOME: {sandbox.CONTAINER_AGENT_ROOT}/{agent}" in body
        assert f"- {agent}-home:{sandbox.CONTAINER_AGENT_ROOT}/{agent}" in body


# ── 실제 기동 (이미지가 있을 때만) ─────────────────────────────────────────────────


def _engine():
    return shutil.which("docker") or shutil.which("podman")


def _image_present():
    engine = _engine()
    if not engine:
        return False
    return subprocess.run([engine, "image", "inspect", IMAGE], capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(not _image_present(), reason=f"{IMAGE} 이미지가 없어요 — 도커 없는 CI에서는 건너뜁니다")
def test_container_really_boots_as_its_own_agent(tmp_path):
    """컨테이너가 마운트된 홈을 자기 에이전트로 읽는다 — 조립이 아니라 기동을 잰다."""
    engine = _engine()
    home = tmp_path / "muninn"
    home.mkdir()

    out = subprocess.run(
        [
            engine,
            "run",
            "--rm",
            "--mount",
            f"type=bind,src={home},dst=/agent/muninn",
            "--env",
            "ASGARD_HOME=/agent/muninn",
            "--entrypoint",
            "asgard",
            IMAGE,
            "agent",
            "where",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        encoding="utf-8",
        errors="replace",
    )

    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    assert payload["process"] == profiles.CUSTOM
    assert payload["home"] == "/agent/muninn"
