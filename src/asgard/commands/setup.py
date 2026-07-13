"""setup / init — scaffold a project. AGENTS.md is always canonical; a tool flag scopes the setup to
that tool (nothing for the others); no flag wires every agent (universal). Flags combine. Generated
content is byte-identical to the TS version; hooks are Python (.py) wired via python3."""

import os
import sys
from pathlib import Path

from .. import ui
from ..hooks import script as hook  # hook("git-guard") → the hook's source, scaffolded verbatim
from ..templates import (
    BRIDGE_SKILL_MD,
    CC_FOLDERS,
    CURSOR_FOLDERS,
    SELFTEST_MD,
    agents_md,
    cc_settings,
    codex_config,
    codex_rules,
    cursor_hooks_json,
    cursor_rule,
    trinity_policy,
)
from ..templates.roles import ROLE_AGENTS  # real .md files, scaffolded verbatim (same pattern as hooks)

# 루트 .gitignore 마커 블록 (AGENTS.md 와 같은 idempotent 마커 패턴). 런타임 상태·로컬 설정만
# 무시한다 — .claude 스캐폴드(훅·에이전트·settings.json)는 커밋해 팀과 공유하는 것이 asgard 사상.
# .asgard/.gitignore="*" 가 이미 자가 무시하지만, 루트에도 명시해 `git status` 를 처음부터 깨끗하게.
_GITIGNORE_BEGIN = "# >>> asgard >>>"
_GITIGNORE_END = "# <<< asgard <<<"
_GITIGNORE_BLOCK = (
    f"{_GITIGNORE_BEGIN}\n"
    "# Asgard 런타임 상태·로컬 설정 (스캐폴드 훅·에이전트·settings.json 은 커밋 — 팀 공유)\n"
    ".asgard/\n"
    ".claude/settings.local.json\n"
    ".claude/**/*.local.*\n"
    f"{_GITIGNORE_END}\n"
)


def merge_gitignore(existing: str | None) -> str:
    """루트 .gitignore 내용 계산 — 기존 있으면 asgard 마커 블록만 갱신(사용자 내용 보존), 없으면 신규.
    idempotent: 재실행 시 블록을 교체하되 블록 밖 사용자 규칙은 건드리지 않는다."""
    if not existing:
        return _GITIGNORE_BLOCK
    lines = existing.splitlines()
    if _GITIGNORE_BEGIN in lines and _GITIGNORE_END in lines:  # 기존 블록 교체
        b = lines.index(_GITIGNORE_BEGIN)
        e = lines.index(_GITIGNORE_END)
        if b < e:
            merged = lines[:b] + _GITIGNORE_BLOCK.rstrip("\n").splitlines() + lines[e + 1 :]
            return "\n".join(merged) + "\n"
    # 블록 없음 → 끝에 append (기존이 개행으로 안 끝나면 하나 넣는다)
    sep = "" if existing.endswith("\n") else "\n"
    return existing + sep + "\n" + _GITIGNORE_BLOCK


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
    ui.step(f"role placement {ui.dim('— /trinity set in the terminal, or [trinity.<role>] in .asgard/config.toml')}")
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
    files: list[tuple[str, str]] = [
        (j(root, "AGENTS.md"), agents_md(name)),
        # 루트 .gitignore — 없으면 생성, 있으면 asgard 마커 블록만 병합 (write 시점, merge_gitignore).
        # 런타임 상태(.asgard/)·로컬 설정만 무시; 스캐폴드는 커밋해 팀과 공유.
        (j(root, ".gitignore"), _GITIGNORE_BLOCK),
    ]

    # Trinity (CUS-125) — 정책은 툴 중립 .asgard/ (크로스툴 공유). .gitignore 를 함께 심는 이유:
    # 훅이 첫 실행 때 lazy 로 만들지만, setup 직후 커밋하면 정책·상태가 사용자 repo 에 섞인다.
    files += [
        (j(root, ".asgard", "trinity-policy.json"), trinity_policy()),
        (j(root, ".asgard", ".gitignore"), "*\n"),
    ]

    # Claude Code — bridge import + settings (permission floor + hook wiring) + Canon guards.
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
            (j(root, ".claude", "hooks", "secret-guard.py"), hook("secret-guard")),
            (j(root, ".claude", "hooks", "failure-tracker.py"), hook("failure-tracker")),
            (j(root, ".claude", "hooks", "quest-log.py"), hook("quest-log")),  # Trinity 로그+전이 CLI
            (j(root, ".claude", "hooks", "verifier-gate.py"), hook("verifier-gate")),  # Canon 10 Stop 게이트
            (j(root, ".claude", "hooks", "write-sentinel.py"), hook("write-sentinel")),  # quest 미개설 write 봉합
            (j(root, ".claude", "hooks", "unattended-context.py"), hook("unattended-context")),  # Canon 8 무인 감지
            (j(root, ".claude", "hooks", "subagent-gate.py"), hook("subagent-gate")),  # 역할 로그 규율 (SubagentStop)
        ]
        # Trinity 역할 서브에이전트 3종 (모드 B 디스패치 대상) — 직관명, 신화명은 딜리버리 계층 전용.
        files += [(j(root, ".claude", "agents", fname), content) for fname, content in ROLE_AGENTS]
        # /asgard-test — 사용자가 세션 안에서 셋업을 자가 테스트 (배선·하니스·라이브 3계층).
        files.append((j(root, ".claude", "skills", "asgard-test", "SKILL.md"), SELFTEST_MD))
        # asgard-provider — Trinity 역할 브릿지. 항상 스캐폴드, 게이트는 런타임([bridge] 기본 꺼짐).
        files.append((j(root, ".claude", "skills", "asgard-provider", "SKILL.md"), BRIDGE_SKILL_MD))

    # Cursor — rule bridge + skeleton + beforeShellExecution guard + postToolUseFailure tracker.
    if cursor:
        files.append((j(root, ".cursor", "rules", "000-agents.mdc"), cursor_rule()))
        for d, desc in CURSOR_FOLDERS:
            files.append((j(root, ".cursor", d, "README.md"), f"# .cursor/{d}/\n\n{desc}\n"))
        files += [
            (j(root, ".cursor", "hooks.json"), cursor_hooks_json()),
            (j(root, ".cursor", "hooks", "git-guard.py"), hook("git-guard")),  # same script, auto-detects Cursor
            (j(root, ".cursor", "hooks", "failure-tracker.py"), hook("failure-tracker")),
            (j(root, ".cursor", "hooks", "quest-log.py"), hook("quest-log")),  # Trinity 모드 A 로그 CLI
        ]

    # Codex reads root AGENTS.md natively — add config + Pre/PostToolUse hooks + native rules.
    # Codex shares Claude's stdin schema, so it reuses the same git-guard / failure-tracker scripts.
    if codex:
        files += [
            (j(root, ".codex", "config.toml"), codex_config()),
            (j(root, ".codex", "hooks", "git-guard.py"), hook("git-guard")),
            (j(root, ".codex", "hooks", "failure-tracker.py"), hook("failure-tracker")),
            (j(root, ".codex", "hooks", "quest-log.py"), hook("quest-log")),  # Trinity 모드 A 로그 CLI
            (j(root, ".codex", "rules", "canon.rules"), codex_rules()),
        ]

    # asgard-test 자가 테스트 스킬 — .agents/skills/ 는 Cursor·Codex 공용 네이티브 스코프
    # (cursor.com/docs/skills · developers.openai.com/codex/skills), Claude Code 만 .claude/skills/.
    # 같은 SKILL.md 포맷이라 본문은 하나다.
    if cursor or codex:
        files.append((j(root, ".agents", "skills", "asgard-test", "SKILL.md"), SELFTEST_MD))
        files.append((j(root, ".agents", "skills", "asgard-provider", "SKILL.md"), BRIDGE_SKILL_MD))

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
    files, label = plan_files(cc, cursor, codex)
    return _scaffold(files, label, force, dry_run)


# ── init — interactive onboarding (CUS-49, minimal slice). TTY: pick a profile; non-TTY / --yes:
# default to claude-code (back-compat with the old `init` = `setup --cc`). Uses Rich (already a dep);
# no heavy TUI framework yet — the full OpenCode/Hermes-style editor stays scoped to CUS-49.
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


def run_init(
    cc: bool = False,
    cursor: bool = False,
    codex: bool = False,
    profile: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    yes: bool = False,
) -> int:
    # Explicit target (flags/--profile) → scaffold it directly, no picker.
    if cc or cursor or codex or profile:
        return run_setup(cc=cc, cursor=cursor, codex=codex, profile=profile, force=force, dry_run=dry_run)
    # No target given: default on non-TTY/--yes; else the full-screen picker.
    if yes or not _interactive():
        return _run_profile(_DEFAULT_PROFILE, force, dry_run)
    # TTY: full-screen Textual onboarding. Textual missing/broken → Rich prompt. None = user cancelled.
    try:
        from .init_tui import run_init_tui

        chosen = run_init_tui()
    except Exception:
        chosen = _choose_profile()
    if chosen is None:
        ui.warn("cancelled — nothing written.")
        return 0
    return _run_profile(chosen, force, dry_run)


if __name__ == "__main__":  # ponytail: profile→setup mapping self-check (no framework)
    assert _FLAG_OF["cursor"] == "cursor" and set(_FLAG_OF) == {"claude-code", "cursor", "codex"}
    assert _DEFAULT_PROFILE in dict(_PROFILES)
    print("setup self-check ok")
