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
from ..hooks.asgard_hooklib import seen
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


_RETIRED_WORKFLOW_ADAPTERS = {
    name: f"""---
name: {name}
description: {description}
disable-model-invocation: true
allowed-tools: Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show {name}` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
"""
    for name, description in {
        "grill-me": "Relentlessly clarify a plan or design, one decision at a time.",
        "to-spec": "Turn the current discussion into a durable implementation spec.",
        "to-tickets": "Split a spec or plan into dependency-aware tracer-bullet tickets.",
        "wayfinder": "Map a decision-heavy effort that cannot fit in one agent session.",
    }.items()
}


def _is_generated_direct_adapter(content: str, directory_name: str) -> bool:
    """Recognize exact retired Asgard adapters while preserving every user-modified byte."""
    return content == _RETIRED_WORKFLOW_ADAPTERS.get(directory_name)


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
    generated: set[str] = set()
    for row in skills(root):
        name = row["name"]
        body = show_skill(root, name)
        if not body:
            continue
        generated.update((direct_skill(body), direct_skill(body, implicit=False)))
        generated.update(
            routed_skill(body, agent) for agent in ("worker", "freyja", "thor", "thor-lead", "eitri", "mimir")
        )
    removed = 0
    for scope in scopes:
        try:
            entries = os.scandir(scope)
        except OSError:
            continue
        with entries:
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                path = os.path.join(entry.path, "SKILL.md")
                if path in expected_paths:
                    continue
                try:
                    with open(path, encoding="utf-8") as handle:
                        content = handle.read()
                except OSError:
                    continue
                if content not in generated and not _is_generated_direct_adapter(content, entry.name):
                    continue
                removed += 1
                if dry_run:
                    continue
                os.unlink(path)
                metadata = os.path.join(entry.path, "agents", "openai.yaml")
                expected = openai_skill_metadata(content)
                try:
                    with open(metadata, encoding="utf-8") as handle:
                        stale = bool(expected) and handle.read() == expected
                    if stale:
                        os.unlink(metadata)
                        os.rmdir(os.path.dirname(metadata))
                except OSError:
                    pass
                try:
                    os.rmdir(entry.path)
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
    # 이미 Justfile 을 쓰는 저장소만 실행 표면도 같이 갱신한다 — 매니페스트가 움직이면
    # `just test` 가 도는 명령도 같이 움직여야 한다. `create=False` 라 파일이 없으면 아무 일도
    # 안 한다: 실행 표면을 들일지는 `asgard just init` 으로 저장소가 고른다.
    from ..justfile import sync as sync_justfile

    counts["updated" if sync_justfile(root, dry_run=dry_run, create=False).changed else "kept"] += 1
    # 어느 판이 이 사본들을 썼는지 남긴다. 진단이 깔린 훅과 패키지 템플릿의 차이를 볼 때, 이
    # 도장이 없으면 어느 쪽이 새 판인지 알 방법이 없어 되감는 조언을 낸다 (settings 의
    # `read_scaffold_version` 주석에 그 사고가 적혀 있다).
    if not dry_run:
        from .. import __version__
        from ..settings import write_scaffold_version

        write_scaffold_version(root, __version__)
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


def _absorb_seen() -> None:
    """훅이 남긴 흔적을 등록부로 옮긴다 — 사용자가 프로젝트마다 `init` 을 다시 돌지 않게.

    `_autoregister_cwd` 는 지금 서 있는 폴더 하나만 흡수한다. 그래서 clone 해 온 저장소나
    `~/.asgard` 를 잃은 기계의 프로젝트는 업그레이드가 아무리 돌아도 영영 목록 밖이었고,
    그 상태가 화면에서는 초록으로 보였다. 훅은 셋업된 프로젝트에서만 도니, 훅이 남긴 흔적
    (`asgard_hooklib.seen`)은 "이 기계에서 실제로 쓰이는 Asgard 프로젝트"의 목록이다.

    흔적은 경로일 뿐이고 등록할 만한지는 여기서 정한다 — 폴더가 남아 있고 호스트 배선
    디렉토리가 하나라도 있어야 한다. `_autoregister_cwd` 와 달리 AGENTS.md 의 `asgard:`
    마커를 요구하지 않는다: 그 마커는 "다른 도구가 만든 AGENTS.md"를 걸러내려는 것인데,
    훅이 돌았다는 사실이 그보다 강한 증거다. 판정이 끝난 흔적은 지운다 — 등록됐거나,
    프로젝트가 아니거나, 폴더가 사라졌거나 셋 중 하나다.
    """
    known = {os.path.realpath(str(p["root"])) for p in registry.load()}
    for root in seen.roots():
        real = os.path.realpath(root)
        if real in known:
            seen.clear(root)
            continue
        if not os.path.isdir(real):
            seen.clear(root)
            continue
        cc, cursor, codex = _detect_flags(real)
        if not (cc or cursor or codex):
            seen.clear(root)
            continue
        registry.record(real, cc, cursor, codex)
        known.add(real)
        seen.clear(root)


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
    _absorb_seen()
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
