#!/usr/bin/env python3
"""Template registry: list, inspect, scaffold, adopt, check, and render.

    asgard skills run asgard-office -- template list
    asgard skills run asgard-office -- template show report-ko
    asgard skills run asgard-office -- template new my-proposal --kind docx --genre proposal
    asgard skills run asgard-office -- template adopt my-form --from ~/Downloads/form.docx
    asgard skills run asgard-office -- template check my-proposal --values v.json
    asgard skills run asgard-office -- template render my-proposal --values v.json -o out.docx

`new` scaffolds a Markdown-backed template from a genre skeleton. `adopt` takes a
document somebody already made — a letterhead, an employer's form — and turns it
into a template by scanning its `{{placeholders}}` into a field schema. Both write
into the project by default (`.asgard/office/templates/`); `--global` writes into
`~/.asgard/office/templates/` so it follows the user across projects.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from officelib import specs, templates  # noqa: E402

SUFFIX_KIND = {".docx": "docx", ".dotx": "docx", ".pptx": "pptx", ".potx": "pptx", ".xlsx": "xlsx", ".xlsm": "xlsx"}


def _destination(name: str, use_global: bool, root: Path) -> Path:
    base = specs.home() / "office" / "templates" if use_global else root / ".asgard" / "office" / "templates"
    return base / name


def _manifest(name: str, kind: str, *, title: str, description: str, genre: str, language: str, fields) -> str:
    """fields is a list of (key, type, required, note)."""
    lines = [
        "schema = 1",
        f'name = "{name}"',
        f'kind = "{kind}"',
        f'title = "{title}"',
        f'description = "{description}"',
    ]
    if genre:
        lines.append(f'genre = "{genre}"')
    if language:
        lines.append(f'language = "{language}"')
    lines += [
        "",
        "# Theme and page defaults a spec can override key by key.",
        "[theme]",
        'primary = "1F2933"',
        'accent = "9A3412"',
        'font_body = "Calibri"',
        "",
        "[page]",
        'size = "a4"',
        "",
        "# Defaults merged into every spec built from this template.",
        "[defaults]",
        "toc = false",
        "",
        "# The field schema. `required` blocks a render; every other entry is",
        "# documentation the author of a values file reads.",
    ]
    for key, kind_name, required, note in fields:
        lines += [
            "",
            "[[fields]]",
            f'key = "{key}"',
            f'label = "{key}"',
            f'type = "{kind_name}"',
            f"required = {str(required).lower()}",
        ]
        if note:
            lines.append(f'description = "{note}"')
        if kind_name in ("text", "multiline", "date"):
            lines.append('example = "…"')
    return "\n".join(line for line in lines if line is not None) + "\n"


def scaffold(name: str, kind: str, *, genre: str, language: str, use_global: bool, root: Path, force: bool) -> Path:
    from outline import SKELETONS, skeleton

    destination = _destination(name, use_global, root)
    if destination.exists() and not force:
        raise ValueError(f"template already exists: {destination} (pass --force to overwrite)")
    if genre and genre not in SKELETONS:
        raise ValueError(f"unknown genre {genre!r} — try one of: {', '.join(sorted(SKELETONS))}")
    body = skeleton(genre or ("deck" if kind == "pptx" else "report"), kind)
    fields = [(key, "text", index == 0, "") for index, key in enumerate(templates.placeholders(body))]
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "template.toml").write_text(
        _manifest(
            name,
            kind,
            title=name.replace("-", " ").title(),
            description=f"{genre or kind} template",
            genre=genre,
            language=language,
            fields=fields,
        ),
        encoding="utf-8",
    )
    (destination / "body.md").write_text(body, encoding="utf-8")
    (destination / "values.example.json").write_text(
        json.dumps({key: f"<{key}>" for key, *_ in fields}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def adopt(name: str, source: Path, *, use_global: bool, root: Path, force: bool) -> tuple[Path, list[str]]:
    """Turn an existing office file into a template by reading its placeholders."""
    from fill import scan_typed

    if not source.is_file():
        raise ValueError(f"source file not found: {source}")
    kind = SUFFIX_KIND.get(source.suffix.lower())
    if not kind:
        raise ValueError(f"cannot adopt {source.suffix} — expected docx, pptx, or xlsx")
    destination = _destination(name, use_global, root)
    if destination.exists() and not force:
        raise ValueError(f"template already exists: {destination} (pass --force to overwrite)")
    found = scan_typed(source)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination / f"base{source.suffix.lower()}")
    (destination / "template.toml").write_text(
        _manifest(
            name,
            kind,
            title=name.replace("-", " ").title(),
            description=f"adopted from {source.name}",
            genre="",
            language="",
            fields=[
                (key, field_kind, False, f"one entry per repeated row; keys: {', '.join(keys)}" if keys else "")
                for key, field_kind, keys in found
            ],
        ),
        encoding="utf-8",
    )
    example = {
        key: ([{inner: f"<{inner}>" for inner in keys}] if field_kind == "table" else f"<{key}>")
        for key, field_kind, keys in found
    }
    (destination / "values.example.json").write_text(
        json.dumps(example, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination, [key for key, _, _ in found]


def render_template(name: str, values_path: Path, out: Path, root: Path) -> dict:
    template = templates.resolve(name, root)
    values = specs.load_data(values_path)
    problems = templates.check(template, values)
    if problems:
        raise ValueError("values do not satisfy the template:\n  - " + "\n  - ".join(problems))
    if template.base:
        from fill import fill

        return fill(template.base, values, out)
    if not template.body:
        raise ValueError(f"template {name!r} has neither body.md nor a base file — nothing to render")
    import build_docx
    import build_pptx
    import build_xlsx

    builder = {"docx": build_docx.build, "md": build_docx.build, "pptx": build_pptx.build, "xlsx": build_xlsx.build}
    return builder[template.kind](template.body, out, template_name=name, values_path=values_path, root=root)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="template", description="Office template registry")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    # `--json` reads naturally on either side of the subcommand. SUPPRESS is what
    # stops the subparser's default from clobbering a flag given before it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--root", type=Path, default=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=lambda **kw: argparse.ArgumentParser(**kw))

    sub.add_parser("list", help="every template visible from here", parents=[common])
    show = sub.add_parser("show", help="one template's manifest and field schema", parents=[common])
    show.add_argument("name")

    new = sub.add_parser("new", help="scaffold a Markdown-backed template", parents=[common])
    new.add_argument("name")
    new.add_argument("--kind", default="docx", choices=templates.KINDS)
    new.add_argument("--genre", default="")
    new.add_argument("--language", default="")
    new.add_argument("--global", dest="use_global", action="store_true")
    new.add_argument("--force", action="store_true")

    adopt_parser = sub.add_parser("adopt", help="turn an existing office file into a template", parents=[common])
    adopt_parser.add_argument("name")
    adopt_parser.add_argument("--from", dest="source", type=Path, required=True)
    adopt_parser.add_argument("--global", dest="use_global", action="store_true")
    adopt_parser.add_argument("--force", action="store_true")

    check = sub.add_parser("check", help="validate a values file against a template's field schema", parents=[common])
    check.add_argument("name")
    check.add_argument("--values", type=Path, required=True)

    render_parser = sub.add_parser("render", help="build a document from a template plus values", parents=[common])
    render_parser.add_argument("name")
    render_parser.add_argument("--values", type=Path, required=True)
    render_parser.add_argument("-o", "--output", type=Path, required=True)

    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "list":
            found, problems = templates.discover(root)
            if args.json:
                print(json.dumps({"templates": [item.summary() for item in found], "problems": problems},
                                 ensure_ascii=False, indent=2))
            else:
                if not found:
                    print("no templates yet — scaffold one with `template new <name> --genre report`")
                for item in found:
                    required = sum(1 for entry in item.fields if entry.required)
                    print(
                        f"{item.name:<24} {item.kind:<5} {item.origin:<8} "
                        f"{len(item.fields)} fields ({required} required)  {item.title}"
                    )
                for problem in problems:
                    print(f"  unreadable: {problem}", file=sys.stderr)
            return 0
        if args.command == "show":
            template = templates.resolve(args.name, root)
            if args.json:
                print(json.dumps(template.summary(), ensure_ascii=False, indent=2))
            else:
                print(f"{template.name}  [{template.kind}, {template.origin}]  {template.title}")
                print(f"  {template.description}")
                print(f"  path:    {template.root}")
                print(f"  backing: {'file ' + template.base.name if template.base else 'body.md'}")
                for entry in template.fields:
                    mark = "*" if entry.required else " "
                    print(f"   {mark} {entry.key:<20} {entry.type:<10} {entry.description or entry.label}")
                print("\n  (* required)")
            return 0
        if args.command == "new":
            destination = scaffold(
                args.name, args.kind, genre=args.genre, language=args.language,
                use_global=args.use_global, root=root, force=args.force,
            )
            print(f"created {destination}")
            print(f"  edit body.md, then: template render {args.name} --values values.example.json -o out.{args.kind}")
            return 0
        if args.command == "adopt":
            destination, found = adopt(
                args.name, args.source, use_global=args.use_global, root=root, force=args.force
            )
            print(f"created {destination} from {args.source.name}")
            print(f"  placeholders found: {', '.join(found) if found else '(none — add {{field}} markers to the file)'}")
            return 0
        if args.command == "check":
            template = templates.resolve(args.name, root)
            problems = templates.check(template, specs.load_data(args.values))
            if args.json:
                print(json.dumps({"template": args.name, "problems": problems}, ensure_ascii=False, indent=2))
            else:
                for problem in problems:
                    print(f"  - {problem}")
                print(f"{args.name}: {'ok' if not problems else str(len(problems)) + ' problem(s)'}")
            return 1 if problems else 0
        if args.command == "render":
            report = render_template(args.name, args.values, args.output, root)
            print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else f"wrote {report['output']}")
            return 0
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"template command failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
