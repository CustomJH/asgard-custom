"""선택형 외부 상호운용 어댑터 — 개인 메모리를 OKF v0.1 bundle로 복사한다.

도입 이유: 향후 Obsidian·MkDocs·다른 에이전트처럼 Asgard SDK를 모르는 소비자에게
개인 지식을 공유하거나 이식할 때, 벤더 중립 Markdown/YAML 묶음으로 내보내기 위해서다.

이 모듈은 Asgard 메모리 코어가 아니다. 1차 메모리의 저장·검색·recall에도, 2차
프로젝트 메모리의 `.asgard/memory/records/` 정본·backend 검색·rehydrate에도 참여하지
않는다. 원본을 수정하거나 동기화하지 않는 단방향 snapshot이며, 외부 공유가 필요할
때만 `asgard memory export-okf`로 명시 실행한다.
"""

from __future__ import annotations

import os
import re

import yaml

from .policy import memory_dir
from .store import _atomic_write, _desc, _kind, _pages, _read, poisoned, slugify


def _link_label(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def _markdown_links(text: str, slugs: set[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        target, _, alias = raw.partition("|")
        resolved = target if target in slugs else slugify(target)
        label = _link_label(alias or target)
        return f"[{label}](/pages/{resolved}.md)"

    return re.sub(r"\[\[([^\]]+)\]\]", replace, text)


def export_okf(destination: str, d: str | None = None) -> int:
    """개인 pages를 OKF bundle로 복사한다. 기존 비어 있지 않은 목적지는 덮어쓰지 않는다."""
    source = os.path.realpath(d or memory_dir())
    destination = os.path.abspath(os.path.expanduser(destination))
    if os.path.islink(destination):
        raise ValueError("OKF export destination must not be a symlink")
    target = os.path.realpath(destination)
    try:
        inside_source = os.path.commonpath([source, target]) == source
    except ValueError:  # Windows의 서로 다른 drive는 공통 경로가 없다.
        inside_source = False
    if inside_source:
        raise ValueError("OKF export destination must be outside the personal memory directory")
    if os.path.isdir(target) and os.listdir(target):
        raise ValueError("OKF export destination is not empty")
    if os.path.exists(target) and not os.path.isdir(target):
        raise ValueError("OKF export destination must be a directory")

    slugs = set(_pages(source))
    rendered: list[tuple[str, str, str, str]] = []
    for slug in sorted(slugs):
        page = _read(source, slug)
        if page is None:
            raise ValueError(f"cannot export unreadable memory page: {slug}")
        meta, body = page
        if threat := poisoned(meta, body):
            raise ValueError(f"cannot export quarantined memory page {slug}: {threat}")

        front = {key: value for key, value in meta.items() if key not in {"kind", "links", "updated"}}
        front = {
            "type": _kind(meta),
            "title": meta.get("title") or slug,
            "description": _markdown_links(str(meta.get("description") or _desc(meta, body)), slugs),
            "timestamp": meta.get("updated") or meta.get("created"),
            **front,
        }
        source_ref = str(meta.get("source") or "").strip()
        if source_ref and not front.get("resource"):
            front["resource"] = source_ref

        converted = _markdown_links(body, slugs).rstrip()
        links = [link.strip() for link in str(meta.get("links") or "").split(",") if link.strip()]
        if links:
            converted += "\n\n# Links\n\n" + "\n".join(f"- {_markdown_links(f'[[{link}]]', slugs)}" for link in links)
        if source_ref and not re.search(r"^# Citations\s*$", converted, re.MULTILINE):
            converted += f"\n\n# Citations\n\n- [Source]({source_ref})"

        yaml_text = yaml.safe_dump(front, allow_unicode=True, sort_keys=False).rstrip()
        document = f"---\n{yaml_text}\n---\n\n{converted}\n"
        rendered.append((slug, str(front["title"]), str(front["description"]), document))

    os.makedirs(os.path.join(target, "pages"), exist_ok=True)
    for slug, _title, _description, document in rendered:
        _atomic_write(os.path.join(target, "pages", f"{slug}.md"), document)
    index_rows = [
        "# Personal Memory",
        "",
        *(f"* [{_link_label(title)}](pages/{slug}.md) - {description}" for slug, title, description, _ in rendered),
    ]
    _atomic_write(os.path.join(target, "index.md"), "\n".join(index_rows).rstrip() + "\n")
    return len(rendered)
