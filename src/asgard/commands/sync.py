"""sync — 레지스트리(~/.asgard/projects.json)에 등록된 모든 asgard 프로젝트의 코어 스캐폴드를
현재 엔진 버전으로 갱신한다. `asgard update`가 엔진 설치 후 자동 호출; 단독 실행도 가능.

파일별 갱신 정책 (사용자 편집 보존이 원칙 — force 덮어쓰기가 아니다):
  overwrite   asgard 소유 파일 (훅·역할 에이전트·스킬·캐논·브릿지·README 시드) — 항상 최신으로.
  markers     AGENTS.md — `<!-- >>> asgard:* >>>` 마커 블록만 교체, 밖(Conventions 등)은 보존.
              마커가 하나도 없으면 사용자 소유 파일로 보고 건너뛴다.
  json-merge  .claude/settings.json — hooks 배선은 재계산, 사용자 permissions·기타 키 보존.
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
        assert last is not None  # found가 비어있지 않으므로 반드시 존재
        at = last.end()
        merged = merged[:at] + "\n\n" + "\n\n".join(missing) + merged[at:]
    return merged


# settings.json에서 asgard가 소유(재계산)하는 최상위 키 — 나머지는 사용자 몫으로 보존
_SETTINGS_OWNED = ("hooks",)

# 0.10.5까지 스캐폴드가 기록하던 statusLine 값. Claude Code 는 프로젝트 설정이 사용자 설정보다
# 우선하므로, 이 키가 남아 있으면 사용자가 ~/.claude/settings.json에 지정한 상태줄이 asgard
# 프로젝트마다 무시된다. 정확히 이 값일 때만 제거한다 — 다른 값이 된 statusLine 은 사용자 소유다.
_PLANTED_STATUSLINE = {
    "type": "command",
    "command": 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/lagom-statusline.sh"',
}


def merge_cc_settings(existing: str | None, new: str) -> str:
    """.claude/settings.json 병합 — 훅 배선은 항상 최신 템플릿, permissions는
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
    if cur.get("statusLine") == _PLANTED_STATUSLINE:
        del cur["statusLine"]  # 호스트 상태줄은 사용자 설정이 정한다
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
    if rel == os.path.join(".asgard", ".gitignore"):
        # 커밋 경계는 저장소마다 다르게 정한 결정이다. 스캐폴드의 예외는 팀 공유를 넓게 뚫는
        # 쪽인데, 어떤 저장소는 map/·설정·binding 을 이 기계의 상태로 두고 닫는다. 덮어쓰면
        # 그 결정이 조용히 뒤집히고 런타임 상태가 팀 저장소로 샌다 — 되돌릴 정본도 없다
        # (이 파일 자신이 추적 대상이 아니다). 없을 때만 시드한다.
        return "keep"
    if rel == "MANUAL.md" or rel == os.path.join(".asgard", "MANUAL.md"):
        return "keep"  # 오딘이 쓴 규칙 — 재스캐폴드가 덮으면 그건 Canon 3 급 데이터 손실이다
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
            routed_skill(body, agent) for agent in ("worker", "freyja", "thor", "thor-lead", "eitri", "mimir")
        }
        for scope in scopes:
            path = os.path.join(scope, name, "SKILL.md")
            if path in expected_paths:
                continue
            try:
                with open(path, encoding="utf-8") as handle:
                    if handle.read() not in generated:
                        continue
            except OSError:
                continue
            removed += 1
            if not dry_run:
                os.unlink(path)
                metadata = os.path.join(os.path.dirname(path), "agents", "openai.yaml")
                expected = openai_skill_metadata(direct_skill(body, implicit=False))
                try:
                    with open(metadata, encoding="utf-8") as handle:
                        stale = bool(expected) and handle.read() == expected
                    if stale:
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
                with open(path, encoding="utf-8") as handle:
                    prev = handle.read()
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
                ui.warn(f"건너뜀 {os.path.relpath(path, root)} — asgard 마커가 없어서 사용자 파일로 두고 갈게요")
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
    # A scaffold refresh must leave both map contract and managed projection current. Previously
    # sync could create INDEX.md while PROJECT.md stayed missing or stale until verification.
    from ..code_map import refresh_map
    from ..map_graph import scan_graph

    mapped = refresh_map(root, dry_run=dry_run)
    if mapped.changed or mapped.index_changed:
        counts["updated"] += int(mapped.changed) + int(mapped.index_changed)
    else:
        counts["kept"] += 1
    graphed = scan_graph(root, dry_run=dry_run)
    if graphed.changed:
        counts["updated"] += 1
    else:
        counts["kept"] += 1
    return counts


def _detect_flags(root: str) -> tuple[bool, bool, bool]:
    return (
        os.path.isdir(os.path.join(root, ".claude")),
        os.path.isdir(os.path.join(root, ".cursor")),
        os.path.isdir(os.path.join(root, ".codex")),
    )


def _emit(payload: dict, code: int) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


def _autoregister_cwd() -> None:
    """레지스트리 도입 전에 셋업된 프로젝트 흡수 — cwd가 asgard 배선(AGENTS.md 마커)인데
    미등록이면 디렉토리 존재로 프로필을 추정해 등록한다."""
    root = os.path.realpath(os.getcwd())
    if any(os.path.realpath(str(p["root"])) == root for p in registry.load()):
        return
    agents = os.path.join(root, "AGENTS.md")
    try:
        with open(agents, encoding="utf-8") as handle:
            txt = handle.read()
    except OSError:
        return
    if "asgard:" not in txt:
        return
    cc, cursor, codex = _detect_flags(root)
    if cc or cursor or codex:
        registry.record(root, cc, cursor, codex)


def _unregistered_cwd_note(projects: list[dict]) -> str:
    """지금 서 있는 폴더가 갱신 목록 밖이면 그 사실. 목록 안이거나 프로젝트 형상이 아니면 빈 문자열.

    sync 는 등록된 프로젝트만 만지는데, 성공 줄은 등록된 것들만 세어 보고한다 — 배선이 없는
    저장소에서 이 명령을 치면 "all projects on the latest core" 를 읽고 고쳐졌다고 믿은 채로
    떠난다. `_autoregister_cwd` 는 AGENTS.md 의 `asgard:` 마커를 요구하므로, 다른 도구가 만든
    AGENTS.md 를 가진 저장소는 흡수 대상도 아니다 (26-08-07 실측: helios-application, 마커 0개)."""
    root = os.path.realpath(os.getcwd())
    if any(os.path.realpath(str(p["root"])) == root for p in projects):
        return ""
    if not any(os.path.isdir(os.path.join(root, d)) for d in (".asgard", ".claude", ".cursor", ".codex")):
        return ""
    return f"{root} 는 이 목록에 없어서 아무것도 안 깔렸어요 — 여기에 깔려면 `asgard init` 을 먼저 돌려 주세요"


def _profile(project: dict) -> str:
    return "+".join(k for k in ("cc", "cursor", "codex") if project.get(k)) or "universal"


def run_sync(dry_run: bool = False, list_only: bool = False, json_out: bool = False, here: bool = False) -> int:
    """등록된 프로젝트의 코어를 갱신한다.

    `--json`은 프로젝트별 결과를 그대로 낸다 — 설치 스크립트와 CI가 "몇 개가 어떻게 됐나"로
    분기한다. `ui.ok`·`warn`·`fail`·`done`은 `--quiet`을 안 보므로 그 넷은 따로 막는다.

    `here=True` 는 지금 있는 프로젝트 하나만 본다. 훅이나 템플릿을 고친 사람이 그 변경을 자기
    저장소에서 확인하려면 등록된 전부(이 기계는 72개, 대부분 시험이 남긴 임시 폴더)를 건드려야
    했고, 그래서 사람은 안 돌리거나 내부 함수를 직접 부르게 된다 — 어느 쪽도 정본 통로가
    아니다 (26-08-05)."""
    ui.set_quiet(ui._QUIET or json_out)
    _autoregister_cwd()
    projects = registry.load()
    if here:
        cwd = os.path.realpath(os.getcwd())
        projects = [p for p in projects if os.path.realpath(str(p["root"])) == cwd]
        if not projects:
            if json_out:
                return _emit({"projects": [], "failed": 0, "dry_run": dry_run, "here": True}, 0)
            ui.warn("여기는 등록된 프로젝트가 아니에요 — 먼저 `asgard init` 을 돌려 주세요.")
            return 0
    ui.head(f"sync · {len(projects)} project(s)" + (" · dry-run" if dry_run else ""))
    if not projects:
        if json_out:
            return _emit({"projects": [], "failed": 0, "dry_run": dry_run}, 0)
        ui.warn("등록된 프로젝트가 없어요 — `asgard init`을 돌린 프로젝트가 여기 쌓여요.")
        return 0
    if list_only:
        rows = [{"root": str(p["root"]), "profile": _profile(p)} for p in projects]
        if json_out:
            return _emit({"projects": rows, "listed_only": True, "dry_run": dry_run}, 0)
        ui.phase("registered projects")
        for row in rows:
            ui.step(f"{row['root']} {ui.dim('(' + row['profile'] + ')')}")
        return 0
    if not json_out and (note := _unregistered_cwd_note(projects)):
        ui.warn(note)
    ui.phase("refresh scaffolds")
    failed = 0
    rows: list[dict] = []
    for p in projects:
        root = str(p["root"])
        if not os.path.isdir(root):
            rows.append({"root": root, "state": "forgotten"})
            if not json_out:
                ui.warn(f"{root} — 폴더가 없어져서 목록에서 뺄게요")
            registry.forget(root)
            continue
        try:
            c = sync_project(root, bool(p.get("cc")), bool(p.get("cursor")), bool(p.get("codex")), dry_run=dry_run)
        except Exception as e:
            rows.append({"root": root, "state": "failed", "error": f"{type(e).__name__}: {e}"})
            if not json_out:
                ui.fail(f"{root} — {e}")
            failed += 1
            continue
        rows.append({"root": root, "state": "synced", **{k: c[k] for k in ("updated", "kept", "skipped")}})
        if not json_out:
            summary = f"updated {c['updated']} · kept {c['kept']}" + (
                f" · skipped {c['skipped']}" if c["skipped"] else ""
            )
            ui.ok(f"{root} {ui.dim('(' + summary + ')')}")
    if json_out:
        return _emit({"projects": rows, "failed": failed, "dry_run": dry_run}, 1 if failed else 0)
    if failed:
        ui.fail(f"{failed} project(s) failed")
        return 1
    ui.done("all projects on the latest core · make anything, your way")
    return 0
