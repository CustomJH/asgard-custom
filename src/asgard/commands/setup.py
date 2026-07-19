"""setup / init — scaffold a project. AGENTS.md is always canonical; a tool flag scopes the setup to
that tool (nothing for the others); no flag wires every agent (universal). Flags combine. Generated
content is byte-identical to the TS version; hooks are Python (.py) wired via python3."""

import os
import sys
from pathlib import Path

from .. import ui
from ..hooks import script as hook  # hook("git-guard") → the hook's source, scaffolded verbatim
from ..skill_registry import client_skill_bodies, skill_catalog
from ..templates import (
    BRIDGE_SKILL_MD,
    CC_FOLDERS,
    CURSOR_FOLDERS,
    LAGOM_CANON,
    MAP_INDEX_MD,
    SEAL_SKILL_MD,
    SELFTEST_MD,
    agents_md,
    cc_settings,
    codex_config,
    codex_rules,
    cursor_hooks_json,
    cursor_rule,
    project_settings,
)
from ..templates.freyja import (
    freyja_core_skill,  # 모드 A 코어 계약 스킬 — role 파일에서 파생 (단일 소스)
)
from ..templates.lagom import (
    LAGOM_SKILLS,  # (스킬명, SKILL.md 본문) — review/debt/compress
    LAGOM_STATUSLINE_SH,
)
from ..templates.memory import MEMORY_SKILL_MD  # memory v3 — 읽기/저장(승인 게이트) 계약
from ..templates.mimir import (
    mimir_core_skill,  # 모드 A 코어 계약 스킬 — role 파일에서 파생 (단일 소스)
)
from ..templates.roles import ROLE_AGENTS  # real .md files, scaffolded verbatim (same pattern as hooks)
from ..templates.skill_router import ROUTER_SKILL_MD, direct_skill
from ..templates.thor import (
    eitri_core_skill,  # 모드 A 코어 계약 스킬 — role 파일에서 파생 (단일 소스)
    thor_core_skill,
)

# 루트 .gitignore 마커 블록 (AGENTS.md 와 같은 idempotent 마커 패턴). 런타임 상태·로컬 설정만
# 무시한다 — .claude 스캐폴드(훅·에이전트·settings.json)는 커밋해 팀과 공유하는 것이 asgard 사상.
# .asgard/.gitignore 가 이미 자가 무시하지만, 루트에도 명시해 `git status` 를 처음부터 깨끗하게.
# `.asgard/` (디렉토리 패턴)이 아니라 `.asgard/*` + negation 인 이유: 디렉토리째 무시하면 git 이
# 하위로 내려가지 않아 map/ 재포함이 불가능하다 — 지도는 팀 공유(추적) 자산.
_GITIGNORE_BEGIN = "# >>> asgard >>>"
_GITIGNORE_END = "# <<< asgard <<<"
_GITIGNORE_BLOCK = (
    f"{_GITIGNORE_BEGIN}\n"
    "# Asgard 런타임 상태·로컬 설정 (스캐폴드 훅·에이전트·settings.json 은 커밋 — 팀 공유)\n"
    "!.asgard/\n"
    ".asgard/*\n"
    "!.asgard/map/\n"
    "!.asgard/map/**\n"
    "!.asgard/.gitignore\n"
    "!.asgard/asgard-setting-project.json\n"
    ".claude/settings.local.json\n"
    ".claude/**/*.local.*\n"
    f"{_GITIGNORE_END}\n"
)

# .asgard 내부 자가 무시 — 런타임 상태(quest/·config·priors)는 전부 무시, 지도만 추적.
# 루트 블록과 합의돼야 한다 (둘 중 하나라도 map 을 막으면 추적 불가 — smoke 가 실추적 검증).
# asgard-setting-project.json = 팀 공유 설정 (trinity 정책·project-memory backend 선택, 비밀 없음) — 커밋 대상.
# state/·quest/ 등 런타임은 "*" 가 전부 무시한다.
_ASGARD_GITIGNORE = "*\n!.gitignore\n!map/\n!map/**\n!asgard-setting-project.json\n"


def merge_gitignore(existing: str | None) -> str:
    """루트 .gitignore 내용 계산 — 기존 있으면 asgard 마커 블록만 갱신(사용자 내용 보존), 없으면 신규.
    idempotent: 재실행 시 블록을 교체하되 블록 밖 사용자 규칙은 건드리지 않는다."""
    if not existing:
        return _GITIGNORE_BLOCK
    # Legacy installs commonly ignored the whole directory. Git will not descend into an ignored
    # parent, so later `!.asgard/map/` cannot revive the shared map. Migrate only these exact broad
    # rules; scoped user rules and every unrelated line remain untouched.
    lines = [
        line for line in existing.splitlines() if line.strip() not in (".asgard", ".asgard/", "/.asgard", "/.asgard/")
    ]
    base = "\n".join(lines) + ("\n" if lines else "")
    if _GITIGNORE_BEGIN in lines and _GITIGNORE_END in lines:  # 기존 블록 교체
        b = lines.index(_GITIGNORE_BEGIN)
        e = lines.index(_GITIGNORE_END)
        if b < e:
            merged = lines[:b] + _GITIGNORE_BLOCK.rstrip("\n").splitlines() + lines[e + 1 :]
            return "\n".join(merged) + "\n"
    # 블록 없음 → 끝에 append (기존이 개행으로 안 끝나면 하나 넣는다)
    return base + ("\n" if base else "") + _GITIGNORE_BLOCK


def _scaffold(files: list[tuple[str, str]], label: str, force: bool, dry_run: bool) -> int:
    cwd = os.getcwd()

    def rel(p: str) -> str:
        return p[len(cwd) + 1 :] if p.startswith(cwd + os.sep) else p

    def _is_root_gitignore(p: str) -> bool:  # 루트 .gitignore 는 병합 대상 — existing 거부·덮어쓰기 예외
        return os.path.basename(p) == ".gitignore" and os.path.dirname(p) in (cwd, os.getcwd())

    existing = [p for p, _ in files if os.path.lexists(p) and not _is_root_gitignore(p)]
    if existing and not force and not dry_run:
        ui.head(label)
        ui.phase("check · existing files")
        for p in existing:
            ui.fail(f"exists {ui.dim(rel(p))}")
        sys.stderr.write(f"  {ui.dim('--force to overwrite · --dry-run to preview')}\n")
        return 2

    ui.head(label)
    if dry_run:
        ui.phase(f"preview · {len(files)} file(s)")
        for p, _ in files:
            ui.step(f"would create {ui.dim(rel(p))}")
        return 0

    ui.phase(f"scaffold · {len(files)} file(s)")
    for p, content in files:
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        if _is_root_gitignore(p):  # 병합 — 기존 사용자 규칙 보존, asgard 블록만 갱신
            prev = Path(p).read_text(encoding="utf-8") if os.path.exists(p) else None
            Path(p).write_text(merge_gitignore(prev))
            ui.ok(ui.dim(rel(p)) + ("" if prev is None else ui.dim(" (asgard 블록 갱신)")))
            continue
        Path(p).write_text(content)
        ui.ok(ui.dim(rel(p)))
    ui.done(f"{len(files)} file(s) · make anything, your way")
    ui.phase("next steps")
    ui.step(f"asgard start   {ui.dim('— open the Heimdall terminal (native Trinity loop)')}")
    ui.step(f"asgard doctor  {ui.dim('— verify the wiring')}")
    ui.step(
        f"role placement {ui.dim('— /trinity set in the terminal, or trinity.<role> in asgard-setting-project.json')}"
    )
    ui.step(f"tool bridge    {ui.dim('— /bridge <tool> on lets Claude Code/Codex/Cursor delegate placed roles')}")
    ui.step(f"               {ui.dim('  via `asgard role` (asgard-provider skill) · default off = internal model')}")
    return 0


def plan_files(cc: bool, cursor: bool, codex: bool, root: str | None = None) -> tuple[list[tuple[str, str]], str]:
    """Compute (files, label) a setup would write — pure, no IO. Shared by run_setup and the TUI
    preview so what the onboarding screen shows is exactly what gets scaffolded."""
    universal = not cc and not cursor and not codex
    if universal:  # universal = the full cross-tool Canon setup — every agent wired AND enforced.
        cc = cursor = codex = True
    root = root or os.getcwd()
    name = os.path.basename(root)
    j = os.path.join

    def discovery_bodies() -> list[tuple[str, str]]:
        merged: dict[str, str] = {}
        for agent in ("worker", "freyja", "freyja-lead", "thor", "thor-lead", "eitri", "mimir"):
            for skill, body in client_skill_bodies(agent, root):
                merged.setdefault(skill, body)
        return sorted(merged.items())

    files: list[tuple[str, str]] = [
        (j(root, "AGENTS.md"), agents_md(name)),
        # 루트 .gitignore — 없으면 생성, 있으면 asgard 마커 블록만 병합 (write 시점, merge_gitignore).
        # 런타임 상태(.asgard/)·로컬 설정만 무시; 스캐폴드는 커밋해 팀과 공유.
        (j(root, ".gitignore"), _GITIGNORE_BLOCK),
    ]

    # Trinity — 정책은 툴 중립 .asgard/ (크로스툴 공유), 통합 설정 파일의 trinity_policy
    # 섹션으로 (26-07-15 설정 통합). .gitignore 를 함께 심는 이유: 훅이 첫 실행 때 lazy 로 만들지만,
    # setup 직후 커밋하면 정책·상태가 사용자 repo 에 섞인다.
    files += [
        (j(root, ".asgard", "asgard-setting-project.json"), project_settings()),
        (j(root, ".asgard", ".gitignore"), _ASGARD_GITIGNORE),
        # 코드베이스 지도 시드 — INDEX 는 규칙 문서(asgard 소유), 영역 지도는 에이전트가 그린다.
        (j(root, ".asgard", "map", "INDEX.md"), MAP_INDEX_MD),
    ]

    # Claude Code — bridge import + settings (permission floor + hook wiring) + Canon guards.
    # 의도적으로 standalone(비-플러그인) 배치다. CC 플러그인으로 묶으면 에이전트명이 네임스페이스돼
    # (`asgard:asgard-thinker`) settings.json 매처와 훅 내부의 이름 등식(readonly/subagent/memory/
    # charter)이 조용히 fail-open 하고, readonly-guard 의 `.claude/hooks/` allowlist·lagom-canon
    # sibling 읽기도 깨진다. 배포·버전·팀 공유는 init/sync/update 가 이미 담당 — 스킬의 승인
    # 완화는 프론트매터 allowed-tools 로, 강제는 훅으로 (승인과 강제는 별 계층).
    if cc:
        files += [
            (j(root, ".claude", "CLAUDE.md"), "@../AGENTS.md\n"),
            (j(root, ".claude", "settings.json"), cc_settings()),
            (
                j(root, ".claude", ".gitignore"),
                "settings.local.json\n",
            ),  # shared hook state lives in root .asgard/ (self-ignored)
        ]
        for d, desc in CC_FOLDERS:
            files.append((j(root, ".claude", d, "README.md"), f"# .claude/{d}/\n\n{desc}\n"))
        files += [
            (j(root, ".claude", "hooks", "git-guard.py"), hook("git-guard")),
            (j(root, ".claude", "hooks", "release-guard.py"), hook("release-guard")),  # 외부 부작용 승인 게이트
            (j(root, ".claude", "hooks", "readonly-guard.py"), hook("readonly-guard")),
            (j(root, ".claude", "hooks", "secret-guard.py"), hook("secret-guard")),
            (j(root, ".claude", "hooks", "failure-tracker.py"), hook("failure-tracker")),
            (j(root, ".claude", "hooks", "quest-log.py"), hook("quest-log")),  # Trinity 로그+전이 CLI
            (j(root, ".claude", "hooks", "verifier-gate.py"), hook("verifier-gate")),  # Canon 10 Stop 게이트
            (j(root, ".claude", "hooks", "write-sentinel.py"), hook("write-sentinel")),  # quest 미개설 write 봉합
            (j(root, ".claude", "hooks", "unattended-context.py"), hook("unattended-context")),  # Canon 8 무인 감지
            (j(root, ".claude", "hooks", "subagent-gate.py"), hook("subagent-gate")),  # 역할 로그 규율 (SubagentStop)
            # Lagom — 훅 3종 + 캐논 단일 소스 (훅이 모드 필터해 주입)
            (j(root, ".claude", "hooks", "lagom-activate.py"), hook("lagom-activate")),
            (j(root, ".claude", "hooks", "lagom-tracker.py"), hook("lagom-tracker")),
            (j(root, ".claude", "hooks", "lagom-subagent.py"), hook("lagom-subagent")),
            (j(root, ".claude", "hooks", "lagom-canon.md"), LAGOM_CANON),
            (j(root, ".claude", "hooks", "lagom-statusline.sh"), LAGOM_STATUSLINE_SH),  # CC statusLine 스크립트
            # Memory v3 — 개인 위키 스냅샷 주입 (SessionStart + Thinker 한정 SubagentStart)
            (j(root, ".claude", "hooks", "memory-activate.py"), hook("memory-activate")),
            # Charter — 프로젝트 북극성 주입 (Session/UserPrompt=through_line, Subagent=역할별)
            (j(root, ".claude", "hooks", "charter-activate.py"), hook("charter-activate")),
        ]
        # Trinity 역할 서브에이전트 3종 (모드 B 디스패치 대상) — 직관명, 신화명은 딜리버리 계층 전용.
        for fname, content in ROLE_AGENTS:
            agent = fname.removeprefix("asgard-").removesuffix(".md")
            catalog = skill_catalog(root, agent, loader="cli")
            files.append((j(root, ".claude", "agents", fname), content + catalog))
        # /asgard-test — 사용자가 세션 안에서 셋업을 자가 테스트 (배선·하니스·라이브 3계층).
        files.append((j(root, ".claude", "skills", "asgard-skills", "SKILL.md"), ROUTER_SKILL_MD))
        files.append((j(root, ".claude", "skills", "asgard-test", "SKILL.md"), direct_skill(SELFTEST_MD)))
        # asgard-provider — Trinity 역할 브릿지. 항상 스캐폴드, 게이트는 런타임([bridge] 기본 꺼짐).
        files.append((j(root, ".claude", "skills", "asgard-provider", "SKILL.md"), direct_skill(BRIDGE_SKILL_MD)))
        # Lagom 스킬 — review(양축 diff 검토) / debt(lagom: 마커 감사) / compress(문서 압축)
        files += [(j(root, ".claude", "skills", sname, "SKILL.md"), direct_skill(body)) for sname, body in LAGOM_SKILLS]
        # /asgard-seal — gitmoji 사건 봉인 (한 봉인 한 사건 + 품질 게이트)
        files.append((j(root, ".claude", "skills", "asgard-seal", "SKILL.md"), direct_skill(SEAL_SKILL_MD)))
        # asgard-memory — 개인 메모리 읽기/저장 계약 (직접 파일 편집 금지, ingest 승인 게이트)
        files.append((j(root, ".claude", "skills", "asgard-memory", "SKILL.md"), direct_skill(MEMORY_SKILL_MD)))
        # Claude가 각 description으로 스킬을 고르고, 선택된 얇은 어댑터만 중앙 정본을 로드한다.
        files += [
            (j(root, ".claude", "skills", sname, "SKILL.md"), direct_skill(body)) for sname, body in discovery_bodies()
        ]

    # Cursor — rule bridge + skeleton + beforeShellExecution guard + postToolUseFailure tracker.
    if cursor:
        files.append((j(root, ".cursor", "rules", "000-agents.mdc"), cursor_rule()))
        for d, desc in CURSOR_FOLDERS:
            files.append((j(root, ".cursor", d, "README.md"), f"# .cursor/{d}/\n\n{desc}\n"))
        files += [
            (j(root, ".cursor", "hooks.json"), cursor_hooks_json()),
            (j(root, ".cursor", "hooks", "git-guard.py"), hook("git-guard")),  # same script, auto-detects Cursor
            (j(root, ".cursor", "hooks", "release-guard.py"), hook("release-guard")),
            (j(root, ".cursor", "hooks", "failure-tracker.py"), hook("failure-tracker")),
            (j(root, ".cursor", "hooks", "quest-log.py"), hook("quest-log")),  # Trinity 모드 A 로그 CLI
        ]

    # Codex reads root AGENTS.md natively — add config + Pre/PostToolUse hooks + native rules.
    # Codex shares Claude's stdin schema, so it reuses the same git-guard / failure-tracker scripts.
    if codex:
        files += [
            (j(root, ".codex", "config.toml"), codex_config()),
            (j(root, ".codex", "hooks", "git-guard.py"), hook("git-guard")),
            (j(root, ".codex", "hooks", "release-guard.py"), hook("release-guard")),
            (j(root, ".codex", "hooks", "failure-tracker.py"), hook("failure-tracker")),
            (j(root, ".codex", "hooks", "quest-log.py"), hook("quest-log")),  # Trinity 모드 A 로그 CLI
            (j(root, ".codex", "rules", "canon.rules"), codex_rules()),
        ]

    # asgard-test 자가 테스트 스킬 — .agents/skills/ 는 Cursor·Codex 공용 네이티브 스코프
    # (cursor.com/docs/skills · developers.openai.com/codex/skills), Claude Code 만 .claude/skills/.
    # 같은 SKILL.md 포맷이라 본문은 하나다.
    if cursor or codex:
        files.append((j(root, ".agents", "skills", "asgard-skills", "SKILL.md"), ROUTER_SKILL_MD))
        files.append((j(root, ".agents", "skills", "asgard-test", "SKILL.md"), direct_skill(SELFTEST_MD)))
        files.append((j(root, ".agents", "skills", "asgard-provider", "SKILL.md"), direct_skill(BRIDGE_SKILL_MD)))
        files += [(j(root, ".agents", "skills", sname, "SKILL.md"), direct_skill(body)) for sname, body in LAGOM_SKILLS]
        files.append((j(root, ".agents", "skills", "asgard-seal", "SKILL.md"), direct_skill(SEAL_SKILL_MD)))
        # 딜리버리 코어 계약 — 모드 A 는 서브에이전트가 없으므로 코어 계약을 스킬로 배치한다.
        files.append((j(root, ".agents", "skills", "asgard-freyja", "SKILL.md"), direct_skill(freyja_core_skill())))
        files.append((j(root, ".agents", "skills", "asgard-thor", "SKILL.md"), direct_skill(thor_core_skill())))
        files.append((j(root, ".agents", "skills", "asgard-eitri", "SKILL.md"), direct_skill(eitri_core_skill())))
        files.append((j(root, ".agents", "skills", "asgard-mimir", "SKILL.md"), direct_skill(mimir_core_skill())))
        # 각 클라이언트가 이름·설명만 색인하고, 선택된 어댑터가 중앙 정본을 지연 로드한다.
        files += [
            (j(root, ".agents", "skills", sname, "SKILL.md"), direct_skill(body)) for sname, body in discovery_bodies()
        ]

    tools = [t for t, on in (("claude-code", cc), ("cursor", cursor), ("codex", codex)) if on]
    label = "init · universal (all agents, enforced)" if universal else f"init · AGENTS.md + {', '.join(tools)}"
    return files, label


def run_setup(
    cc: bool = False,
    cursor: bool = False,
    codex: bool = False,
    profile: str | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    cc = cc or profile == "claude-code"
    cursor = cursor or profile == "cursor"
    codex = codex or profile == "codex"
    from ..code_map import MapError, refresh_map

    try:
        refresh_map(os.getcwd(), dry_run=True)  # map 경로/소유권 preflight — scaffold가 링크를 따라 쓰기 전 차단.
    except MapError as exc:
        ui.fail(str(exc))
        return 2
    files, label = plan_files(cc, cursor, codex)
    rc = _scaffold(files, label, force, dry_run)
    if rc == 0 and not dry_run:  # 레지스트리 기록 — `asgard sync` 가 세팅된 프로젝트를 찾는 근거
        from .. import registry

        refresh_map(os.getcwd())  # 초기 프로젝트 방향을 즉시 그린다; 이후 Verifier가 구조 변경 때 갱신.
        universal = not cc and not cursor and not codex
        registry.record(os.getcwd(), cc or universal, cursor or universal, codex or universal)
    return rc


# ── init — interactive onboarding. TTY: full-screen Textual picker (init_tui.py), with a Rich prompt
# as the fallback when Textual can't run; non-TTY / --yes: default to claude-code (back-compat with
# the old `init` = `setup --cc`).
_PROFILES: list[tuple[str, str]] = [
    ("universal", "every agent — AGENTS.md + full .claude/.cursor/.codex, Canon enforced"),
    ("claude-code", ".claude/ full skeleton + hooks"),
    ("cursor", ".cursor/ rules + hooks"),
    ("codex", ".codex/ config + rules + guard"),
]
_DEFAULT_PROFILE = "claude-code"
_FLAG_OF = {"claude-code": "cc", "cursor": "cursor", "codex": "codex"}


def profile_flags(profile: str) -> dict[str, bool]:
    """Profile name → setup flags. 'universal' = all False (bridges every agent)."""
    return {"cc": profile == "claude-code", "cursor": profile == "cursor", "codex": profile == "codex"}


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _choose_profile() -> str:
    from rich.console import Console
    from rich.prompt import Prompt

    c = Console()
    c.print("\n  [bold]asgard init[/bold] [dim]— choose a setup profile[/dim]")
    for i, (key, desc) in enumerate(_PROFILES, 1):
        c.print(f"    [bold cyan]{i}[/bold cyan]  {key:<12} [dim]{desc}[/dim]")
    default_idx = str(next(i for i, (k, _) in enumerate(_PROFILES, 1) if k == _DEFAULT_PROFILE))
    choice = Prompt.ask("  select", choices=[str(i) for i in range(1, len(_PROFILES) + 1)], default=default_idx)
    return _PROFILES[int(choice) - 1][0]


def _run_profile(profile: str, force: bool, dry_run: bool) -> int:
    if profile == "universal":
        return run_setup(force=force, dry_run=dry_run)
    return run_setup(**{_FLAG_OF[profile]: True}, force=force, dry_run=dry_run)  # ty: ignore[invalid-argument-type] — 동적 kwargs 디스패치


def _apply_lagom(lagom: str | None, dry_run: bool, rc: int) -> int:
    """init --lagom <mode> — 스캐폴드 성공 후 프로젝트 [lagom].mode 영속 (기본 full 은 무기록,
    resolve 기본값이 이미 full — 사다리 1단: 필요 없는 설정은 만들지 않는다)."""
    if rc != 0 or dry_run or not lagom:
        return rc
    from ..lagom import normalize
    from ..providers import save_config_section

    mode = normalize(lagom)
    if mode is None:
        ui.warn(f"--lagom {lagom}: 유효 모드 아님 (off|lite|full) — 기본 full 유지")
        return rc
    save_config_section(None, "lagom", {"mode": mode})
    ui.step(f"lagom mode   {ui.dim('— lagom.mode = ' + mode + ' (asgard-setting-project.json)')}")
    return rc


def run_init(
    cc: bool = False,
    cursor: bool = False,
    codex: bool = False,
    profile: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    yes: bool = False,
    lagom: str | None = None,
) -> int:
    # Explicit target (flags/--profile) → scaffold it directly, no picker.
    if cc or cursor or codex or profile:
        rc = run_setup(cc=cc, cursor=cursor, codex=codex, profile=profile, force=force, dry_run=dry_run)
        return _apply_lagom(lagom, dry_run, rc)
    # No target given: default on non-TTY/--yes; else the full-screen picker.
    if yes or not _interactive():
        return _apply_lagom(lagom, dry_run, _run_profile(_DEFAULT_PROFILE, force, dry_run))
    # TTY: full-screen Textual onboarding. Textual missing/broken → Rich prompt. None = user cancelled.
    try:
        from .init_tui import run_init_tui

        chosen = run_init_tui()
    except Exception:
        chosen = _choose_profile()
    if chosen is None:
        ui.warn("cancelled — nothing written.")
        return 0
    return _apply_lagom(lagom, dry_run, _run_profile(chosen, force, dry_run))


if __name__ == "__main__":  # lagom: profile→setup mapping self-check (no framework)
    assert _FLAG_OF["cursor"] == "cursor" and set(_FLAG_OF) == {"claude-code", "cursor", "codex"}
    assert _DEFAULT_PROFILE in dict(_PROFILES)
    print("setup self-check ok")
