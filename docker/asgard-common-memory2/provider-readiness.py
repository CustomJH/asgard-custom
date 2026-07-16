#!/usr/bin/env python3
"""Check the configured Cognee LLM from inside its network namespace.

Supports native Ollama and OpenAI-compatible LiteLLM proxy endpoints. It never
prints API keys and never selects a fallback provider.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def get_json(url: str, api_key: str | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def main() -> int:
    provider = os.getenv("LLM_PROVIDER", "").lower()
    endpoint = os.getenv("LLM_ENDPOINT", "").rstrip("/")
    model = os.getenv("LLM_MODEL", "")
    api_key = os.getenv("LLM_API_KEY")

    if provider == "ollama":
        # Cognee/LiteLLM needs Ollama's OpenAI-compatible /v1 endpoint, while
        # model discovery remains on the native /api/tags route.
        native_endpoint = endpoint.removesuffix("/v1")
        payload = get_json(f"{native_endpoint}/api/tags")
        installed = {item.get("name") for item in payload.get("models", [])}
        wanted = model.removeprefix("ollama/")
        ready = wanted in installed
        mode = "ollama"
    elif provider == "custom":
        # Cognee's custom adapter is backed by LiteLLM. A LiteLLM proxy exposes
        # OpenAI-compatible /v1/models and model aliases.
        payload = get_json(f"{endpoint}/models", api_key)
        installed = {item.get("id") for item in payload.get("data", [])}
        candidates = {model, model.removeprefix("openai/")}
        ready = bool(candidates & installed)
        mode = "litellm-proxy"
    else:
        print(json.dumps({"provider": provider, "ready": False, "mode": "unverified"}))
        return 2

    print(json.dumps({"provider": provider, "model": model, "ready": ready, "mode": mode}))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
