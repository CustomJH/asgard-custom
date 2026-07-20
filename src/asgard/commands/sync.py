"""sync — 레지스트리(~/.asgard/projects.json)에 등록된 모든 asgard 프로젝트의 코어 스캐폴드를
현재 엔진 버전으로 갱신한다. `asgard update` 가 엔진 설치 후 자동 호출; 단독 실행도 가능.

파일별 갱신 정책 (사용자 편집 보존이 원칙 — force 덮어쓰기가 아니다):
  overwrite   asgard 소유 파일 (훅·역할 에이전트·스킬·캐논·브릿지·README 시드) — 항상 최신으로.
  markers     AGENTS.md — `<!-- >>> asgard:* >>>` 마커 블록만 교체, 밖(Conventions 등)은 보존.
              마커가 하나도 없으면 사용자 소유 파일로 보고 건너뛴다.
  json-merge  .claude/settings.json — hooks/statusLine 배선은 재계산, 사용자 permissions·기타 키 보존.
  keep        .asgard/trinity-policy.json — 사용자 튜닝 존중, 없을 때만 생성.
  gitignore   루트 .gitignore — 기존 merge_gitignore (asgard 블록만 교체)."""

import json
import os
import re

from .. import registry, ui
from ..skill_registry import show_skill, skills
from ..templates.skill_router import direct_skill, openai_skill_metadata, routed_skill
from .setup import merge_gitignore, plan_files

# AGENTS.md 관리 블록 — <!-- >>> asgard:xxx >>> --> … <!-- <<< asgard:xxx <<< -->
_BLOCK_RE = re.compile(r"<!-- >>> (asgard:[a-z-]+) >>> -->\n.*?<!-- <<< \1 <<< -->", re.S)


def merge_agents_md(existing: str | None, new: str) -> str | None:
    """AGENTS.md 병합 — 마커 블록은 새 템플릿으로 교체, 블록 밖 사용자 내용은 보존.
    기존에 없는 새 블록(버전업으로 추가된 섹션)은 마지막 asgard 블록 뒤에 삽입.
    기존 파일에 마커가 전혀 없으면 None (사용자 소유 — 건드리지 않는다)."""
    if existing is None:
        return new
    new_blocks = {m.group(1): m.group(0) for m in _BLOCK_RE.finditer(new)}  # 템플릿 순서 보존
    found: set[str] = set()

    def repl(m: re.Match) -> str:
        found.add(m.group(1))
        return new_blocks.get(m.group(1), m.group(0))

    merged = _BLOCK_RE.sub(repl, existing)
    if not found:
        return None
    missing = [block for key, block in new_blocks.items() if key not in found]
    if missing:
        last = None
        for last in _BLOCK_RE.finditer(merged):  # noqa: B007 — 마지막 매치만 필요
            pass
        assert last is not None  # found 가 비어있지 않으므로 반드시 존재
        at = last.end()
        merged = merged[:at] + "\n\n" + "\n\n".join(missing) + merged[at:]
    return merged


# settings.json 에서 asgard 가 소유(재계산)하는 최상위 키 — 나머지는 사용자 몫으로 보존
_SETTINGS_OWNED = ("hooks", "statusLine")


def merge_cc_settings(existing: str | None, new: str) -> str:
    """.claude/settings.json 병합 — 훅 배선·statusLine 은 항상 최신 템플릿, permissions 는
    템플릿(바닥) + 사용자 추가분 합집합, 그 외 사용자 키는 그대로. 기존이 JSON 파손이면 템플릿."""
    if existing is None:
        return new
    tmpl = json.loads(new)
    try:
        cur = json.loads(existing)
        assert isinstance(cur, dict)
    except Exception:
        return new
    for key in _SETTINGS_OWNED:
        cur[key] = tmpl[key]
    perms = cur.get("permissions")
    if not isinstance(perms, dict):
        perms = {}
    for kind, floor in tmpl["permissions"].items():
        mine = perms.get(kind)
        if not isinstance(mine, list):
            mine = []
        perms[kind] = floor + [x for x in mine if x not in floor]
    cur["permissions"] = perms
    return json.dumps(cur, indent=2, ensure_ascii=False) + "\n"


def _policy(root: str, path: str) -> str:
    rel = os.path.relpath(path, root)
    if rel == "AGENTS.md":
        return "markers"
    if rel == ".gitignore":
        return "gitignore"
    if rel == os.path.join(".claude", "settings.json"):
        return "json-merge"
    if rel == os.path.join(".asgard", "asgard-setting-project.json"):
        return "keep"  # 사용자 튜닝(정책·project-memory backend·배치) 존중 — 없을 때만 시드
    return "overwrite"


def _prune_stale_skill_adapters(
    root: str,
    cc: bool,
    cursor: bool,
    codex: bool,
    expected_paths: set[str],
    dry_run: bool,
) -> int:
    """Remove only byte-identical generated adapters no longer exposed by current policy."""
    scopes = []
    if cc:
        scopes.append(os.path.join(root, ".claude", "skills"))
    if cursor or codex:
        scopes.append(os.path.join(root, ".agents", "skills"))
    removed = 0
    for row in skills(root):
        name = row["name"]
        body = show_skill(root, name)
        if not body:
            continue
        generated = {direct_skill(body), direct_skill(body, implicit=False)} | {
            routed_skill(body, agent)
            for agent in ("worker", "freyja", "freyja-lead", "thor", "thor-lead", "eitri", "mimir")
        }
        for scope in scopes:
            path = os.path.join(scope, name, "SKILL.md")
            if path in expected_paths:
                continue
            try:
                if open(path, encoding="utf-8").read() not in generated:
                    continue
            except OSError:
                continue
            removed += 1
            if not dry_run:
                os.unlink(path)
                metadata = os.path.join(os.path.dirname(path), "agents", "openai.yaml")
                expected = openai_skill_metadata(direct_skill(body, implicit=False))
                try:
                    if expected and open(metadata, encoding="utf-8").read() == expected:
                        os.unlink(metadata)
                        os.rmdir(os.path.dirname(metadata))
                except OSError:
                    pass
                try:
                    os.rmdir(os.path.dirname(path))
                except OSError:
                    pass
    return removed


def sync_project(root: str, cc: bool, cursor: bool, codex: bool, dry_run: bool = False) -> dict[str, int]:
    """한 프로젝트의 스캐폴드 갱신 — {"updated": n, "kept": n, "skipped": n} 집계를 돌려준다."""
    # 설정 통합 마이그레이션 (26-07-15) — 구 config.toml/trinity-policy.json/memory-server.json →
    # asgard-setting-project.json, 런타임 잔재 → state/. 멱등이라 매 sync 선행해도 무해.
    if not dry_run:
        from ..settings import migrate_global, migrate_project

        for msg in migrate_global() + migrate_project(root):
            ui.step(f"migrate {ui.dim(msg)}")
    files, _ = plan_files(cc, cursor, codex, root)
    counts = {
        "updated": _prune_stale_skill_adapters(root, cc, cursor, codex, {path for path, _ in files}, dry_run),
        "kept": 0,
        "skipped": 0,
    }
    for path, content in files:
        prev = None
        if os.path.exists(path):
            try:
                prev = open(path, encoding="utf-8").read()
            except Exception:
                counts["skipped"] += 1
                continue
        policy = _policy(root, path)
        if policy == "keep" and prev is not None:
            counts["kept"] += 1
            continue
        if policy == "markers":
            merged = merge_agents_md(prev, content)
            if merged is None:  # 사용자 소유 AGENTS.md — 관리 마커 없음
                ui.warn(f"skip {os.path.relpath(path, root)} — asgard 마커 없음 (사용자 소유로 보존)")
                counts["skipped"] += 1
                continue
            content = merged
        elif policy == "gitignore":
            content = merge_gitignore(prev)
        elif policy == "json-merge":
            content = merge_cc_settings(prev, content)
        if prev == content:
            counts["kept"] += 1
            continue
        counts["updated"] += 1
        if not dry_run:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
    return counts


def _detect_flags(root: str) -> tuple[bool, bool, bool]:
    return (
        os.path.isdir(os.path.join(root, ".claude")),
        os.path.isdir(os.path.join(root, ".cursor")),
        os.path.isdir(os.path.join(root, ".codex")),
    )


def _autoregister_cwd() -> None:
    """레지스트리 도입 전에 셋업된 프로젝트 흡수 — cwd 가 asgard 배선(AGENTS.md 마커)인데
    미등록이면 디렉토리 존재로 프로필을 추정해 등록한다."""
    root = os.path.realpath(os.getcwd())
    if any(os.path.realpath(str(p["root"])) == root for p in registry.load()):
        return
    agents = os.path.join(root, "AGENTS.md")
    try:
        txt = open(agents, encoding="utf-8").read()
    except OSError:
        return
    if "asgard:" not in txt:
        return
    cc, cursor, codex = _detect_flags(root)
    if cc or cursor or codex:
        registry.record(root, cc, cursor, codex)


def run_sync(dry_run: bool = False, list_only: bool = False) -> int:
    _autoregister_cwd()
    projects = registry.load()
    ui.head(f"sync · {len(projects)} project(s)" + (" · dry-run" if dry_run else ""))
    if not projects:
        ui.warn("등록된 프로젝트 없음 — `asgard init` 을 실행한 프로젝트가 여기 기록됩니다.")
        return 0
    if list_only:
        ui.phase("registered projects")
        for p in projects:
            profile = "+".join(k for k in ("cc", "cursor", "codex") if p.get(k)) or "universal"
            ui.step(f"{p['root']} {ui.dim('(' + profile + ')')}")
        return 0
    ui.phase("refresh scaffolds")
    failed = 0
    for p in projects:
        root = str(p["root"])
        if not os.path.isdir(root):
            ui.warn(f"{root} — 디렉토리 없음, 레지스트리에서 제거")
            registry.forget(root)
            continue
        try:
            c = sync_project(root, bool(p.get("cc")), bool(p.get("cursor")), bool(p.get("codex")), dry_run=dry_run)
        except Exception as e:
            ui.fail(f"{root} — {e}")
            failed += 1
            continue
        summary = f"updated {c['updated']} · kept {c['kept']}" + (f" · skipped {c['skipped']}" if c["skipped"] else "")
        ui.ok(f"{root} {ui.dim('(' + summary + ')')}")
    if failed:
        ui.fail(f"{failed} project(s) failed")
        return 1
    ui.done("all projects on the latest core · make anything, your way")
    return 0
