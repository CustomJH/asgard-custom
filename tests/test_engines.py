import json
import os

from asgard import engines
from asgard.providers import PROVIDERS, ResolvedProvider


def _resolved(name: str, *, missing: tuple[str, ...] = ()) -> ResolvedProvider:
    profile = PROVIDERS[name]
    return ResolvedProvider(
        profile=profile,
        model=profile.default_model,
        base_url=profile.base_url,
        api_key="test-key",
        missing=list(missing),
    )


def test_api_catalog_and_fallback_are_distinct_reachability(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(engines.providers, "resolve", lambda _root, provider: _resolved(provider))

    def catalog(_resolved, *, timeout, on_fallback):
        assert timeout == 1.5
        return ["model-a", "model-b"]

    monkeypatch.setattr(engines.providers, "provider_models", catalog)
    live = engines.probe(str(tmp_path), names=("openai",), timeout=1.5, force=True, now=10.0)[0]
    assert live.reachable
    assert live.models == ("model-a", "model-b")
    assert "모델 카탈로그" in live.detail

    def fallback(_resolved, *, timeout, on_fallback):
        on_fallback("live catalog request failed")
        return ["fallback-model"]

    monkeypatch.setattr(engines.providers, "provider_models", fallback)
    offline = engines.probe(str(tmp_path), names=("openai",), force=True, now=11.0)[0]
    assert not offline.reachable
    assert offline.models == ()
    assert "live catalog request failed" in offline.detail


def test_anthropic_uses_its_existing_catalog_probe(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(engines.providers, "resolve", lambda _root, provider: _resolved(provider))
    monkeypatch.setattr("asgard.model_tiers.catalog_models", lambda api_key, timeout: ["claude-opus-5"])
    monkeypatch.setattr(
        engines.providers,
        "provider_models",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("wrong catalog probe")),
    )

    row = engines.probe(str(tmp_path), names=("anthropic",), timeout=2.0, force=True, now=15.0)[0]
    assert row.reachable
    assert row.models == ("claude-opus-5",)


def test_unconfigured_engine_never_calls_catalog(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        engines.providers,
        "resolve",
        lambda _root, provider: _resolved(provider, missing=("API 키 없음",)),
    )
    monkeypatch.setattr(
        engines.providers,
        "provider_models",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network called")),
    )

    row = engines.probe(str(tmp_path), names=("openai",), force=True, now=20.0)[0]
    assert not row.configured
    assert not row.reachable
    assert "API 키 없음" in row.detail


def test_cli_and_codex_use_their_native_readiness_checks(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(engines.providers, "resolve", lambda _root, provider: _resolved(provider))
    monkeypatch.setattr(engines.shutil, "which", lambda name: "/usr/local/bin/claude" if name == "claude" else None)
    monkeypatch.setattr("asgard.openai_codex.login_status", lambda: (True, "logged in"))
    monkeypatch.setattr(
        engines.providers,
        "provider_models",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("catalog called")),
    )

    cli, codex = engines.probe(str(tmp_path), names=("claude-native", "openai-native"), force=True, now=30.0)
    assert cli.reachable and "/usr/local/bin/claude" in cli.detail
    assert codex.reachable and "OAuth" in codex.detail


def test_cache_ttl_boundary_and_cached_never_probe(monkeypatch, tmp_path) -> None:
    calls = []
    monkeypatch.setattr(engines.providers, "resolve", lambda _root, provider: _resolved(provider))

    def catalog(*_args, **_kwargs):
        calls.append(1)
        return ["model-a"]

    monkeypatch.setattr(engines.providers, "provider_models", catalog)
    root = str(tmp_path)
    first = engines.probe(root, names=("openai",), now=100.0)[0]
    boundary = engines.probe(root, names=("openai",), now=100.0 + engines.CACHE_TTL)[0]
    expired = engines.probe(root, names=("openai",), now=100.0 + engines.CACHE_TTL + 0.001)[0]

    assert len(calls) == 2
    assert first.checked == boundary.checked == 100.0
    assert expired.checked > boundary.checked

    monkeypatch.setattr(engines, "_probe_one", lambda *_args: (_ for _ in ()).throw(AssertionError("probed")))
    assert engines.cached(root)[0].checked == expired.checked


def test_corrupt_cache_fails_open_and_probe_never_raises(monkeypatch, tmp_path) -> None:
    path = tmp_path / engines.CACHE_REL
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    assert engines.cached(str(tmp_path)) == []

    monkeypatch.setattr(
        engines.providers, "resolve", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("bad config"))
    )
    row = engines.probe(str(tmp_path), names=("openai",), now=200.0)[0]
    assert not row.configured
    assert not row.reachable
    assert "OSError: bad config" in row.detail

    with open(os.path.join(tmp_path, engines.CACHE_REL), encoding="utf-8") as handle:
        assert json.load(handle)["engines"][0]["name"] == "openai"
