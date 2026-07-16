#!/usr/bin/env -S uv run --script
"""Probe and benchmark Ollama models without logging generated content."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from typing import Any


def request_json(url: str, payload: dict[str, Any] | None = None, timeout: int = 300) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def rate(count: int, duration_ns: int) -> float | None:
    return round(count / (duration_ns / 1_000_000_000), 2) if duration_ns else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="*")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--num-predict", type=int, default=64)
    args = parser.parse_args()

    endpoint = args.endpoint.rstrip("/")
    tags = request_json(f"{endpoint}/api/tags", timeout=15)
    installed = [model.get("name") for model in tags.get("models", []) if model.get("name")]
    models = args.models or installed
    missing = sorted(set(models) - set(installed))
    if missing:
        print(json.dumps({"missing": missing}))
        return 2

    failed = False
    for model in models:
        payload = {
            "model": model,
            "prompt": (
                "Return one JSON object with keys status and summary. "
                "The status must be ok. Summarize: project memory uses "
                "Markdown as canonical source."
            ),
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0, "num_predict": args.num_predict},
        }
        started = time.monotonic()
        try:
            result = request_json(f"{endpoint}/api/generate", payload, timeout=300)
            generated = json.loads(result.get("response", ""))
            valid = generated.get("status") == "ok" and bool(generated.get("summary"))
            prompt_count = result.get("prompt_eval_count", 0)
            prompt_duration = result.get("prompt_eval_duration", 0)
            eval_count = result.get("eval_count", 0)
            eval_duration = result.get("eval_duration", 0)
            report = {
                "model": model,
                "wall_s": round(time.monotonic() - started, 2),
                "load_s": round(result.get("load_duration", 0) / 1_000_000_000, 2),
                "prompt_tokens": prompt_count,
                "prompt_tps": rate(prompt_count, prompt_duration),
                "output_tokens": eval_count,
                "output_tps": rate(eval_count, eval_duration),
                "done_reason": result.get("done_reason"),
                "structured_json_valid": valid,
            }
            failed = failed or not valid
        except Exception as error:  # report all runtime/provider failures uniformly
            failed = True
            report = {"model": model, "error": f"{type(error).__name__}: {error}"}
        print(json.dumps(report, ensure_ascii=False), flush=True)

    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
