#!/usr/bin/env python3
"""Search Aceternity UI's public, machine-readable free-component catalog."""

from __future__ import annotations

import argparse
import html.parser
import json
import re
import sys
import urllib.error
import urllib.request

CATALOG_URL = "https://ui.aceternity.com/ai-recommendations"
REGISTRY_URL = "https://ui.aceternity.com/registry/{name}.json"


class _PreBlocks(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._current: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "pre":
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre" and self._current is not None:
            self.blocks.append("".join(self._current))
            self._current = None


def _fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Asgard Aceternity skill/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8")


def _catalog() -> list[dict]:
    parser = _PreBlocks()
    parser.feed(_fetch(CATALOG_URL))
    found: dict[str, dict] = {}
    for block in parser.blocks:
        try:
            rows = json.loads(block.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or row.get("isPro") or row.get("isTemplate"):
                continue
            name = str(row.get("name") or "")
            command = str(row.get("installCommand") or "")
            if name and command.startswith("npx shadcn@latest add @aceternity/"):
                found[name] = row
    if not found:
        raise ValueError("Aceternity free-component catalog was not found in the live page")
    return [found[name] for name in sorted(found)]


def _search(rows: list[dict], query: str, limit: int) -> list[dict]:
    phrase = query.strip().lower()
    terms = re.findall(r"[a-z0-9.+-]+", phrase)
    ranked: list[tuple[int, str, dict]] = []
    for row in rows:
        name = str(row.get("name") or "").lower()
        title = str(row.get("title") or "").lower()
        description = str(row.get("description") or "").lower()
        categories = " ".join(map(str, row.get("categories") or [])).lower()
        dependencies = " ".join(map(str, row.get("dependencies") or [])).lower()
        text = " ".join((name, title, description, categories, dependencies))
        score = (8 if phrase and phrase in text else 0) + sum(
            4 if term in name or term in title else 2 if term in categories else 1 if term in text else 0
            for term in terms
        )
        if score:
            ranked.append((-score, name, row))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [row for _, _, row in ranked[:limit]]


def _summary(row: dict, registry: dict | None = None) -> dict:
    result = {
        "name": row.get("name"),
        "title": row.get("title"),
        "description": row.get("description"),
        "categories": row.get("categories") or [],
        "dependencies": row.get("dependencies") or [],
        "registryDependencies": row.get("registryDependencies") or [],
        "documentationUrl": row.get("documentationUrl"),
        "registryUrl": REGISTRY_URL.format(name=row.get("name")),
        "installCommand": row.get("installCommand"),
    }
    if registry:
        result["dependencies"] = registry.get("dependencies") or result["dependencies"]
        result["registryDependencies"] = registry.get("registryDependencies") or result["registryDependencies"]
        result["files"] = [item.get("target") or item.get("path") for item in registry.get("files") or []]
    return result


def _print(rows: list[dict], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("No matching free Aceternity components.")
        return
    for row in rows:
        dependencies = ", ".join(row.get("dependencies") or []) or "none"
        print(f"{row['name']} — {row.get('title') or row['name']}")
        print(f"  {row.get('description') or ''}")
        print(f"  dependencies: {dependencies}")
        print(f"  docs: {row.get('documentationUrl')}")
        print(f"  install: {row.get('installCommand')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--json", action="store_true")
    show = subparsers.add_parser("show")
    show.add_argument("name")
    show.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        rows = _catalog()
        if args.command == "search":
            if not 1 <= args.limit <= 50:
                parser.error("--limit must be between 1 and 50")
            result = [_summary(row) for row in _search(rows, args.query, args.limit)]
            _print(result, as_json=args.json)
            return 0
        row = next((item for item in rows if item.get("name") == args.name), None)
        if row is None:
            print(f"Free Aceternity component not found: {args.name}", file=sys.stderr)
            return 1
        registry = json.loads(_fetch(REGISTRY_URL.format(name=args.name)))
        _print([_summary(row, registry)], as_json=args.json)
        return 0
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        print(f"Aceternity catalog error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
