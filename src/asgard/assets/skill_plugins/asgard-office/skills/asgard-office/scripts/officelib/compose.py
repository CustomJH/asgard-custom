"""Spec composition: front matter + template merge + placeholder expansion.

The document and deck lanes both start here. Keeping it out of either builder is
what stops one lane from importing the other just to share a template contract.
"""

from __future__ import annotations

from pathlib import Path

from . import specs, templates


def resolve_spec(
    spec_path: Path, template_name: str, values_path: Path | None, root: Path | None, kinds: tuple[str, ...]
) -> tuple[dict, str, "templates.Template | None", list[str]]:
    """Front matter + body with the template merged in and placeholders expanded.

    Both the document and the deck lane call this, so a template behaves
    identically in either — which is the point of keeping it out of both.
    """
    front, body = specs.split_frontmatter(spec_path.read_text(encoding="utf-8"))
    name = template_name or str(front.get("template") or "")
    template = None
    if name:
        template = templates.resolve(name, root)
        if template.kind not in kinds:
            raise ValueError(f"template {name!r} builds {template.kind}, not {kinds[0]}")
        # The spec wins over the template, key by key — except theme and page,
        # which merge, so a spec can override one colour without restating the set.
        merged = {**template.defaults, **{key: value for key, value in front.items() if key not in ("theme", "page")}}
        theme = {**template.theme, **(front.get("theme") or {})}
        page = {**template.page, **(front.get("page") or {})}
        if theme:
            merged["theme"] = theme
        if page:
            merged["page"] = page
        front = merged
        if template.body and not body.strip():
            body = specs.split_frontmatter(template.body.read_text(encoding="utf-8"))[1]

    missing: list[str] = []
    if values_path is not None:
        values = specs.load_data(values_path)
        if template is not None:
            problems = templates.check(template, values)
            if problems:
                raise ValueError("values do not satisfy the template:\n  - " + "\n  - ".join(problems))
        body, missing = templates.render(body, values)
        for key, value in list(front.items()):
            if isinstance(value, str) and "{{" in value:
                front[key], gap = templates.render(value, values)
                missing.extend(gap)
    return front, body, template, sorted(set(missing))
