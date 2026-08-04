"""Obsidian vault 계층 — 개인 위키를 사람과 에이전트가 둘 다 스스로 돌아다닐 수 있게 만든다.

정본은 이미 Obsidian이 읽는 형식이다 (md + frontmatter + [[wikilink]]). 모자란 건 두 가지였다.

① 첫 열기의 마찰. `.obsidian/`이 없으면 폴더는 vault가 아니고, URI로 열 수도 없다.
   그래서 최소 설정을 심는다 — 사람이 고른 값은 절대 덮지 않되, 없는 키는 채운다
   (`_merged_keys`). 불가침의 단위가 파일이 아니라 키인 이유가 거기 적혀 있다.

② 길잡이. 주입 카탈로그는 kind 별 칸 예산에 묶여 있어 전부를 실을 수 없다 (칸이 차면 최신부터
   살아남고 나머지는 잘린다). 그래서 전체 목차는 maps/ 로 뺀다. maps/ 는 파생물이다 —
   pages/ 에서 다시 만들어지고, 백업·동기화 대상이 아니며, 지워도 지식은 죽지 않는다.
   예산이 걸린 주입면과 역할이 갈린다.

maps/ 안의 링크는 전부 [[slug]] 다. Obsidian의 그래프·백링크·아웃라인이 그대로 살아나고,
파일을 직접 읽는 에이전트에게도 같은 문서가 목차로 동작한다 — 두 독자에게 형식이 하나다.

정본 pages/ 는 한 겹으로 고정돼 있다. 페이지를 세는 자리 여섯(store._pages·
store._pages_fingerprint·backup.canonical_members·sync.digest_map·store.ensure_home 의 chmod·
index.reindex)이 전부 os.listdir 한 번이라, pages/ 아래 하위 폴더는 오류 없이 목록에서
빠진다 — 백업에서 빠진 채로 backup.restore 의 rmtree 를 만나면 되돌릴 수 없다. 그래서 사람이
쓰는 폴더 구분은 정본이 아니라 이 파생 계층이 맡는다: maps/kind/<kind>.md 가 Obsidian 파일
탐색기에 접히는 트리로 표시되고, pages/ 는 저장소로 남는다.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import re

from .store import _atomic_write, _chmod, _desc, _kind, _pages, _read_all, ensure_home, poisoned

_WIKILINK = re.compile(r"\[\[([^\]|#]+)")

MAPS_DIR = "maps"
OBSIDIAN_DIR = ".obsidian"
# 종류별 목록은 파일 하나가 아니라 폴더 하나다. Obsidian 파일 탐색기는 폴더만 접고 펴므로,
# 한 장짜리 `by-kind.md` 는 페이지가 늘어도 계속 한 줄로만 보인다 — 종류가 트리에 뜨지 않는다.
KIND_DIR = "kind"
MAP_FILES = ("index.md", "recent.md", "loose-ends.md")
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


def _merged_keys(path: str, payload: dict) -> dict | None:
    """기존 설정에 우리 키 중 **없는 것만** 얹은 값 — 얹을 게 없거나 못 읽으면 None.

    파일 단위로 건너뛰면 안 되는 이유: Obsidian은 첫 열기에 이 파일들을 스스로 만든다. 그래서
    "있으면 안 건드린다"는 사람이 고른 적 없는 기본값을 지키게 되고, 우리가 나중에 추가하는
    어떤 키도 이미 열어 본 vault 에는 영원히 닿지 못한다. 실측(26-08-04, ~/.asgard/memory):
    Obsidian이 app.json 을 `{}` 로 다시 써서 attachmentFolderPath 가 사라졌고, 스캐폴드는
    그 뒤로 한 번도 그 값을 되돌리지 못했다.

    사람이 고른 값은 그대로 둔다 — 키가 이미 있으면 값이 무엇이든 손대지 않는다. 객체가 아닌
    설정(core-plugins.json 은 판 버전에 따라 배열이거나 객체다)은 형태를 모르므로 건너뛴다."""
    try:
        with open(path, encoding="utf-8") as handle:
            current = json.load(handle)
    except OSError, ValueError:
        return None  # 손상·권한 문제로 못 읽는 설정을 우리 기본값으로 덮지 않는다
    if not isinstance(current, dict):
        return None
    missing = {key: value for key, value in payload.items() if key not in current}
    return {**current, **missing} if missing else None


def scaffold_obsidian(d: str | None = None) -> list[str]:
    """vault 최소 설정을 심는다. 사람이 고른 키는 건드리지 않는다. 반환 = 새로 쓴 파일들."""
    d = ensure_home(d)
    root = os.path.join(d, OBSIDIAN_DIR)
    if os.path.islink(root):
        raise ValueError("vault config directory must not be a symlink")
    os.makedirs(root, exist_ok=True)
    _chmod(root, 0o700)
    written: list[str] = []
    for name, payload in (
        ("app.json", _APP_JSON),
        ("appearance.json", _APPEARANCE_JSON),
        ("core-plugins.json", _CORE_PLUGINS),
    ):
        path = os.path.join(root, name)
        if os.path.exists(path):
            if os.path.islink(path) or not isinstance(payload, dict):
                continue
            payload = _merged_keys(path, payload)
            if payload is None:
                continue
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        written.append(os.path.join(OBSIDIAN_DIR, name))
    return written


# ── 목차 (파생) ───────────────────────────────────────────────────────────────


def _rows(d: str, loaded: list[tuple[str, dict, str]] | None = None) -> list[dict]:
    """살아 있는 페이지의 표시용 사실. 오염 페이지는 목차에도 넣지 않는다.

    목차는 페이지를 저장할 때마다 다시 만들어지므로 파일은 한 번만 읽는다 — 나가는 링크까지
    여기서 같이 뽑아 둔다 (본문을 두 번 읽으면 쓰기 한 번이 읽기 2N 번이 된다). loaded 를 주면
    그 한 번도 아낀다: 카탈로그(`index.write_index`)가 이미 읽어 둔 것을 그대로 받는다."""
    rows: list[dict] = []
    for slug, meta, body in _read_all(d) if loaded is None else loaded:
        if poisoned(meta, body):
            continue
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


def _map_header(title: str, note: str, *, home: bool = False) -> list[str]:
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    lines = [f"# {title}", "", f"> {note}", f"> 파생 목차 — pages/ 에서 재생성된다 ({stamp})."]
    if not home:
        lines.append(f"> [[{MAPS_DIR}/index|← 메모리 지도]]")
    return [*lines, ""]


def build_maps(d: str, loaded: list[tuple[str, dict, str]] | None = None) -> dict[str, str]:
    """maps/ 파일 내용 전체를 만든다 (쓰기 없음). 반환 = {파일명: 본문}."""
    rows = _rows(d, loaded)
    outgoing = {row["slug"]: row["outgoing"] for row in rows}
    pointed = set().union(*outgoing.values()) if outgoing else set()
    by_kind: dict[str, list[dict]] = {}
    for row in rows:
        by_kind.setdefault(row["kind"], []).append(row)

    ordered_kinds = sorted(by_kind, key=lambda k: (-len(by_kind[k]), k))

    home = _map_header("메모리 지도", "이 vault를 돌아다니는 출발점.", home=True)
    home += [
        f"- [[{MAPS_DIR}/recent|최근순]] — 최근에 고친 것부터",
        f"- [[{MAPS_DIR}/loose-ends|끊어진 곳]] — 아무도 가리키지 않는 페이지와 죽은 링크",
        "",
        f"페이지 {len(rows)}장 · 종류 {len(by_kind)}가지",
        "",
        f"## 종류별 — `{MAPS_DIR}/{KIND_DIR}/`",
        "",
    ]
    for kind in ordered_kinds:
        title = _KIND_TITLES.get(kind, kind)
        home.append(f"- [[{MAPS_DIR}/{KIND_DIR}/{kind}|{title}]] `{kind}` — {len(by_kind[kind])}장")

    kind_maps = {}
    for kind in ordered_kinds:
        title = _KIND_TITLES.get(kind, kind)
        page = _map_header(f"{title} `{kind}`", f"같은 종류로 묶인 기억 {len(by_kind[kind])}장.")
        page += [f"- [[{row['slug']}|{row['title']}]] — {row['desc']}" for row in sorted(by_kind[kind], key=_by_title)]
        kind_maps[f"{KIND_DIR}/{kind}.md"] = "\n".join(page) + "\n"

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
        "recent.md": "\n".join(recent) + "\n",
        "loose-ends.md": "\n".join(loose) + "\n",
        **kind_maps,
    }


def _by_title(row: dict) -> tuple:
    return (str(row["title"]).lower(), row["slug"])


def write_maps(d: str | None = None, *, loaded: list[tuple[str, dict, str]] | None = None) -> list[str]:
    """maps/ 재생성. 반환 = 쓴 상대경로들. 실패는 조용히 넘어간다 (파생물이 지식을 막지 않는다).

    loaded 를 주면 페이지를 다시 읽지 않고, 스캐폴드 점검도 건너뛴다 — 그 값을 들고 온 쪽이
    이미 홈을 세우고 페이지를 훑은 것이라, 여기서 또 훑으면 쓰기 한 번에 chmod 가 N 번 더 붙는다."""
    if loaded is None or not d:
        d = ensure_home(d)
    written: list[str] = []
    try:
        contents = build_maps(d, loaded)
        root = maps_dir(d)
        for name, text in contents.items():
            path = os.path.join(root, *name.split("/"))
            parent = os.path.dirname(path)
            if parent != root:
                os.makedirs(parent, exist_ok=True)
                _chmod(parent, 0o700)
            _atomic_write(path, text)
            written.append(f"{MAPS_DIR}/{name}")
        _prune_stale(root, contents)
    except Exception:
        return written
    return written


def _prune_stale(root: str, contents: dict[str, str]) -> None:
    """이번에 쓴 것이 아닌 `.md` 와 그 뒤에 남는 빈 폴더를 치운다.

    종류가 사라지면 `kind/<kind>.md` 도 사라져야 한다. 훑기가 한 겹이면 하위 폴더 안의 그 파일이
    영원히 남아, 없는 종류를 있다고 말하는 목차가 된다. `topdown=False` 는 자식을 먼저 비운 뒤
    부모를 지우기 위한 것이다."""
    keep = {os.path.join(root, *name.split("/")) for name in contents}
    for base, _dirs, files in os.walk(root, topdown=False):
        for name in files:
            path = os.path.join(base, name)
            if name.endswith(".md") and path not in keep:
                with contextlib.suppress(OSError):
                    os.remove(path)
        if base != root:
            with contextlib.suppress(OSError):
                os.rmdir(base)  # 비어 있을 때만 성공한다 — 사용자 파일이 남아 있으면 그대로 둔다


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
    "KIND_DIR",
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
