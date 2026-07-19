"""`asgard start` terminal entrypoint regression tests."""

from unittest import mock

from asgard.commands.start import run_start


def test_start_uses_terminal_repl():
    rp = object()
    with (
        mock.patch("asgard.providers.resolve", return_value=rp) as resolve,
        mock.patch("asgard.agent.repl.run", return_value=7) as run,
    ):
        assert run_start(provider="anthropic", model="model", cont=True) == 7

    resolve.assert_called_once_with(mock.ANY, provider="anthropic", model="model")
    run.assert_called_once_with(mock.ANY, rp, cont=True)
