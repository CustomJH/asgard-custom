"""Obsidian vault 계층 — 개인 위키를 사람과 에이전트가 둘 다 스스로 돌아다닐 수 있게 만든다.

정본은 이미 Obsidian이 읽는 형식이다 (md + frontmatter + [[wikilink]]). 모자란 건 두 가지였다.

① 첫 열기의 마찰. `.obsidian/`이 없으면 폴더는 vault가 아니고, URI로 열 수도 없다.
   그래서 최소 설정을 심는다 — 이미 있는 파일은 절대 덮지 않는다 (사용자 설정이 정본).

② 길잡이. 주입 카탈로그는 kind 별 칸 예산에 묶여 있어 전부를 실을 수 없다 (칸이 차면 최신부터
   살아남고 나머지는 잘린다). 그래서 전체 목차는 maps/ 로 뺀다. maps/ 는 파생물이다 —
   pages/ 에서 다시 만들어지고, 백업·동기화 대상이 아니며, 지워도 지식은 죽지 않는다.
   예산이 걸린 주입면과 역할이 갈린다.

maps/ 안의 링크는 전부 [[slug]] 다. Obsidian의 그래프·백링크·아웃라인이 그대로 살아나고,
파일을 직접 읽는 에이전트에게도 같은 문서가 목차로 동작한다 — 두 독자에게 형식이 하나다.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import re

from .store import _atomic_write, _chmod, _desc, _kind, _pages, _read, ensure_home, poisoned

_WIKILINK = re.compile(r"\[\[([^\]|#]+)")

MAPS_DIR = "maps"
OBSIDIAN_DIR = ".obsidian"
MAP_FILES = ("index.md", "by-kind.md", "recent.md", "loose-ends.md")
RECENT_LIMIT = 60

# 최소 vault 설정. Obsidian은 나머지를 스스로 만든다 — 여기서는 "폴더가 vault 다"라고
# 말하는 데 필요한 것과, 위키 링크가 이 저장소 규약대로 동작하게 하는 것만 심는다.
_APP_JSON = {
    "alwaysUpdateLinks": True,
    "newLinkFormat": "shortest",
    "useMarkdownLinks": False,
    "attachmentFolderPath": "attachments",
    "showUnsupportedFiles": False,
}
_CORE_PLUGINS = [
    "file-explorer",
    "global-search",
    "switcher",
    "graph",
    "backlink",
    "outgoing-link",
    "tag-pane",
    "page-preview",
    "outline",
    "word-count",
]
_APPEARANCE_JSON = {"accentColor": "", "theme": "system"}

_KIND_TITLES = {
    "user": "오딘에 대한 것",
    "insight": "통찰",
    "decision": "결정",
    "reference": "레퍼런스",
    "feedback": "피드백",
    "note": "노트",
}


def maps_dir(d: str) -> str:
    path = os.path.join(d, MAPS_DIR)
    os.makedirs(path, exist_ok=True)
    _chmod(path, 0o700)
    return path


def is_vault(d: str) -> bool:
    return os.path.isdir(os.path.join(d, OBSIDIAN_DIR))


def scaffold_obsidian(d: str | None = None) -> list[str]:
    """vault 최소 설정을 심는다. 이미 있는 파일은 건드리지 않는다. 반환 = 새로 만든 파일들."""
    d = ensure_home(d)
    root = os.path.join(d, OBSIDIAN_DIR)
    if os.path.islink(root):
        raise ValueError("vault config directory must not be a symlink")
    os.makedirs(root, exist_ok=True)
    _chmod(root, 0o700)
    created: list[str] = []
    for name, payload in (
        ("app.json", _APP_JSON),
        ("appearance.json", _APPEARANCE_JSON),
        ("core-plugins.json", _CORE_PLUGINS),
    ):
        path = os.path.join(root, name)
        if os.path.exists(path):
            continue  # 사용자 설정이 정본 — 우리 기본값으로 되돌리지 않는다
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        created.append(os.path.join(OBSIDIAN_DIR, name))
    return created


# ── 목차 (파생) ───────────────────────────────────────────────────────────────


def _rows(d: str) -> list[dict]:
    """살아 있는 페이지의 표시용 사실. 오염 페이지는 목차에도 싣지 않는다.

    목차는 페이지를 저장할 때마다 다시 만들어지므로 파일은 한 번만 읽는다 — 나가는 링크까지
    여기서 같이 뽑아 둔다 (본문을 두 번 읽으면 쓰기 한 번이 읽기 2N 번이 된다)."""
    rows: list[dict] = []
    for slug in _pages(d):
        page = _read(d, slug)
        if not page or poisoned(*page):
            continue
        meta, body = page
        links = [part.strip() for part in str(meta.get("links", "")).split(",") if part.strip()]
        targets = {target.strip() for target in [*links, *_WIKILINK.findall(body)] if target.strip()}
        rows.append(
            {
                "slug": slug,
                "title": meta.get("title", slug),
                "kind": _kind(meta),
                "updated": meta.get("updated", meta.get("created", "")),
                "desc": _desc(meta, body),
                "links": links,
                "outgoing": targets,
            }
        )
    return rows


def _map_header(title: str, note: str) -> list[str]:
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    return [f"# {title}", "", f"> {note}", f"> 파생 목차 — pages/ 에서 재생성된다 ({stamp}).", ""]


def build_maps(d: str) -> dict[str, str]:
    """maps/ 파일 내용 전체를 만든다 (쓰기 없음). 반환 = {파일명: 본문}."""
    rows = _rows(d)
    outgoing = {row["slug"]: row["outgoing"] for row in rows}
    pointed = set().union(*outgoing.values()) if outgoing else set()
    by_kind: dict[str, list[dict]] = {}
    for row in rows:
        by_kind.setdefault(row["kind"], []).append(row)

    home = _map_header("메모리 지도", "이 vault를 돌아다니는 출발점.")
    home += [
        f"- [[{MAPS_DIR}/by-kind|종류별]] — 무엇에 대한 기억인지로 묶은 목록",
        f"- [[{MAPS_DIR}/recent|최근순]] — 최근에 고친 것부터",
        f"- [[{MAPS_DIR}/loose-ends|끊어진 곳]] — 아무도 가리키지 않는 페이지와 죽은 링크",
        "",
        f"페이지 {len(rows)}장 · 종류 {len(by_kind)}가지",
        "",
        "## 종류별 요약",
        "",
    ]
    for kind in sorted(by_kind, key=lambda k: (-len(by_kind[k]), k)):
        home.append(f"- **{_KIND_TITLES.get(kind, kind)}** ({kind}) — {len(by_kind[kind])}장")

    kinds = _map_header("종류별", "같은 성격의 기억끼리 모아 둔 목록.")
    for kind in sorted(by_kind, key=lambda k: (-len(by_kind[k]), k)):
        kinds += ["", f"## {_KIND_TITLES.get(kind, kind)} `{kind}`", ""]
        kinds += [f"- [[{row['slug']}|{row['title']}]] — {row['desc']}" for row in sorted(by_kind[kind], key=_by_title)]

    recent = _map_header("최근순", "마지막으로 손댄 순서. 지금 무엇을 다루고 있었는지가 여기 보인다.")
    for row in sorted(rows, key=lambda r: (r["updated"], r["slug"]), reverse=True)[:RECENT_LIMIT]:
        recent.append(f"- `{row['updated'] or '----------'}` [[{row['slug']}|{row['title']}]] `{row['kind']}`")

    known = {row["slug"] for row in rows}
    orphans = sorted((row for row in rows if row["slug"] not in pointed), key=_by_title)
    dead = sorted(
        (slug, target)
        for slug, targets in outgoing.items()
        for target in targets
        if target not in known and not target.startswith(f"{MAPS_DIR}/")
    )

    loose = _map_header("끊어진 곳", "고립된 페이지와 가리키는 곳이 없는 링크. 이어 붙일 자리다.")
    loose += ["", "## 아무도 가리키지 않는 페이지", ""]
    loose += [f"- [[{row['slug']}|{row['title']}]] `{row['kind']}`" for row in orphans] or ["- 없음"]
    loose += ["", "## 죽은 링크", ""]
    loose += [f"- [[{source}]] → `{target}`" for source, target in dead] or ["- 없음"]

    return {
        "index.md": "\n".join(home) + "\n",
        "by-kind.md": "\n".join(kinds) + "\n",
        "recent.md": "\n".join(recent) + "\n",
        "loose-ends.md": "\n".join(loose) + "\n",
    }


def _by_title(row: dict) -> tuple:
    return (str(row["title"]).lower(), row["slug"])


def write_maps(d: str | None = None) -> list[str]:
    """maps/ 재생성. 반환 = 쓴 상대경로들. 실패는 조용히 넘어간다 (파생물이 지식을 막지 않는다)."""
    d = ensure_home(d)
    written: list[str] = []
    try:
        contents = build_maps(d)
        root = maps_dir(d)
        for name, text in contents.items():
            _atomic_write(os.path.join(root, name), text)
            written.append(f"{MAPS_DIR}/{name}")
        for stale in os.listdir(root):
            if stale.endswith(".md") and stale not in contents:
                with contextlib.suppress(OSError):
                    os.remove(os.path.join(root, stale))
    except Exception:
        return written
    return written


def refresh(d: str | None = None) -> dict:
    """vault 준비 한 번 — 설정 스캐폴드 + 목차 재생성."""
    d = ensure_home(d)
    return {"directory": d, "scaffolded": scaffold_obsidian(d), "maps": write_maps(d), "pages": len(_pages(d))}


def vault_note(d: str | None = None) -> str:
    """vault 상태 한 줄 — doctor/표면용."""
    d = ensure_home(d)
    count = len(_pages(d))
    ready = "ready" if is_vault(d) else "not opened as a vault yet"
    return f"{d} · {count} page(s) · {ready}"


__all__ = [
    "MAPS_DIR",
    "OBSIDIAN_DIR",
    "build_maps",
    "is_vault",
    "maps_dir",
    "refresh",
    "scaffold_obsidian",
    "vault_note",
    "write_maps",
]
