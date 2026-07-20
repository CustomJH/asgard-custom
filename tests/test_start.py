"""`asgard start` terminal entrypoint regression tests."""

from unittest import mock

from asgard.commands.start import run_start


def test_start_uses_terminal_repl():
    rp = object()
    with (
        mock.patch("asgard.providers.resolve", return_value=rp) as resolve,
        mock.patch("asgard.agent.repl.run", return_value=7) as run,
        mock.patch("asgard.sandbox.choose_mode", return_value="local"),
    ):
        assert run_start(provider="anthropic", model="model", cont=True) == 7

    resolve.assert_called_once_with(mock.ANY, provider="anthropic", model="model")
    run.assert_called_once_with(mock.ANY, rp, cont=True)


def test_start_routes_to_private_docker_sandbox():
    with (
        mock.patch("asgard.sandbox.choose_mode", return_value="sandbox"),
        mock.patch("asgard.sandbox.run", return_value=9) as run,
    ):
        assert run_start(execution="sandbox", sandbox_name="safe-box") == 9

    run.assert_called_once_with(mock.ANY, shared=False, name="safe-box")


def test_start_routes_to_cross_platform_container():
    with (
        mock.patch("asgard.sandbox.choose_mode", return_value="container"),
        mock.patch("asgard.sandbox.run_container", return_value=8) as run,
    ):
        assert run_start(execution="container", sandbox_name="safe-box") == 8

    run.assert_called_once_with(mock.ANY, shared=False, name="safe-box")
