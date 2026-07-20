from importlib.resources import files
from pathlib import Path
from unittest import mock

import pytest

from asgard import sandbox


def test_container_runtime_installs_with_curl_without_git_auth():
    dockerfile = files("asgard").joinpath("assets", "container_kit", "Dockerfile").read_text()

    assert "curl -fsSL" in dockerfile
    assert "ASGARD_VERSION=" in dockerfile
    assert "pip install" not in dockerfile
    assert "git clone" not in dockerfile


def test_sandbox_reuses_existing_name(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox.shutil, "which", lambda _name: "/usr/bin/sbx")
    name = sandbox.sandbox_name(str(tmp_path / "demo"))
    calls = [
        mock.Mock(returncode=0, stdout=str(tmp_path / "demo") + "\n"),
        mock.Mock(returncode=0, stdout=""),
        mock.Mock(returncode=0, stdout=name + "\n"),
        mock.Mock(returncode=7),
    ]
    with mock.patch("asgard.sandbox.subprocess.run", side_effect=calls) as run:
        assert sandbox.run(str(tmp_path / "demo")) == 7

    assert run.call_args_list[3].args[0] == ["/usr/bin/sbx", "run", "--name", name]


def test_private_sandbox_uses_clone_and_kit(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox.shutil, "which", lambda _name: "/usr/bin/sbx")
    calls = [
        mock.Mock(returncode=0, stdout=str(tmp_path / "demo") + "\n"),
        mock.Mock(returncode=0, stdout=""),
        mock.Mock(returncode=0, stdout=""),
        mock.Mock(returncode=0),
    ]
    with mock.patch("asgard.sandbox.subprocess.run", side_effect=calls) as run:
        assert sandbox.run(str(tmp_path / "demo")) == 0

    command = run.call_args_list[3].args[0]
    assert command[:4] == ["/usr/bin/sbx", "run", "--name", sandbox.sandbox_name(str(tmp_path / "demo"))]
    assert "--clone" in command
    assert command[-2:] == ["asgard", str(tmp_path / "demo")]


def test_shared_sandbox_skips_git_and_clone(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox.shutil, "which", lambda _name: "/usr/bin/sbx")
    calls = [mock.Mock(returncode=0, stdout=""), mock.Mock(returncode=0)]
    with mock.patch("asgard.sandbox.subprocess.run", side_effect=calls) as run:
        assert sandbox.run(str(tmp_path / "demo"), shared=True) == 0

    command = run.call_args_list[1].args[0]
    assert "--clone" not in command
    assert command[-2:] == ["asgard", str(tmp_path / "demo")]


def test_container_uses_docker_compatible_engine_without_sbx_login(monkeypatch, tmp_path):
    root = str(tmp_path / "demo")
    workspace = tmp_path / "private"
    monkeypatch.setattr(sandbox, "_container_engine", lambda: "/usr/bin/docker")
    monkeypatch.setattr(sandbox, "_private_workspace", lambda _root, _name: workspace)
    monkeypatch.setattr(sandbox.sys.stdin, "isatty", lambda: False)
    calls = [mock.Mock(returncode=0), mock.Mock(returncode=0)]

    with mock.patch("asgard.sandbox.subprocess.run", side_effect=calls) as run:
        assert sandbox.run_container(root, name="safe-box") == 0

    command = run.call_args_list[1].args[0]
    assert command[:5] == ["/usr/bin/docker", "run", "--rm", "--name", mock.ANY]
    assert command[5:9] == ["--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    assert f"type=bind,src={workspace},dst=/workspace" in command
    assert "sbx" not in command
    assert "login" not in command


def test_container_preserves_windows_mount_path(monkeypatch):
    workspace = Path(r"C:\Users\yun\project")
    monkeypatch.setattr(sandbox, "_container_engine", lambda: r"C:\Program Files\Docker\docker.exe")
    monkeypatch.setattr(sandbox, "_private_workspace", lambda _root, _name: workspace)
    monkeypatch.setattr(sandbox.sys.stdin, "isatty", lambda: False)

    with mock.patch(
        "asgard.sandbox.subprocess.run", side_effect=[mock.Mock(returncode=0), mock.Mock(returncode=0)]
    ) as run:
        assert sandbox.run_container(str(workspace), name="windows-box") == 0

    assert f"type=bind,src={workspace},dst=/workspace" in run.call_args_list[1].args[0]


def test_private_workspace_rejects_path_like_name(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with pytest.raises(ValueError):
        sandbox._private_workspace(str(tmp_path), "../escape")


def test_private_workspace_rejects_symlink_target(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    target = tmp_path / ".asgard" / "sandboxes" / "linked"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(ValueError):
        sandbox._private_workspace(str(tmp_path), "linked")


def test_private_workspace_fallback_does_not_copy_git_credentials(tmp_path, monkeypatch):
    source = tmp_path / "source"
    (source / ".git").mkdir(parents=True)
    (source / ".git" / "config").write_text("token=secret")
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(sandbox.shutil, "which", lambda _name: None)

    workspace = sandbox._private_workspace(str(source), "safe-copy")

    assert not (workspace / ".git").exists()
