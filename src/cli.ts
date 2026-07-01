#!/usr/bin/env bun
// asgard CLI. Erasable-TS only (Bun + Node>=24 type-stripping): no enums/namespaces/param-props.
import { parseArgs } from "node:util";
import { execSync } from "node:child_process";
import { rmSync, lstatSync, mkdirSync, writeFileSync, readFileSync, existsSync, renameSync } from "node:fs";
import { homedir } from "node:os";
import { join, dirname } from "node:path";
import pkg from "../package.json" with { type: "json" };

const VERSION: string = (pkg as { version?: string }).version ?? "0.0.0";
const RUNTIME: string = (process.versions as { bun?: string }).bun
  ? `bun v${(process.versions as { bun?: string }).bun}`
  : `node v${process.versions.node}`;

// Shared per-command context (global flag conventions, threaded to every command).
type Ctx = {
  rest: string[];
  json: boolean;
  quiet: boolean;
  dryRun: boolean;
  yes: boolean;
  force: boolean;
  cc: boolean;
  cursor: boolean;
  codex: boolean;
  profile: string | undefined;
};
type Cmd = { summary: string; ready: boolean; run?: (c: Ctx) => number };

// The command surface. `ready` commands run; planned ones are listed + announced
// (behavior lands in CUS-49). Memory/knowledge-store commands are intentionally absent.
const COMMANDS: Record<string, Cmd> = {
  doctor: { summary: "diagnose runtime & PATH", ready: true, run: runDoctor },
  init: { summary: "alias for 'setup --cc' (claude-code .claude/)", ready: true, run: runInit },
  setup: { summary: "set up project — AGENTS.md (all agents); --cc/--cursor/--codex add per-tool skeletons", ready: true, run: runSetup },
  run: { summary: "run an .asgardfile task", ready: false },
  update: { summary: "update this project's .claude (3-way merge)", ready: false },
  upgrade: { summary: "self-update the binary (upgrade [version])", ready: true, run: runUpgrade },
  uninstall: { summary: "remove asgard (binary, PATH symlink, ~/.asgard)", ready: true, run: runUninstall },
  completions: { summary: "print shell completion script (bash|zsh|fish)", ready: true, run: runCompletions },
};

function onPath(bin: string): string | null {
  try {
    const out = execSync(`command -v ${bin} 2>/dev/null`, { shell: "/bin/bash", encoding: "utf8" }).trim();
    return out || null;
  } catch {
    return null;
  }
}

// System Node on PATH — honest version (process.versions.node is bun's *emulated* node).
function systemNode(): { version: string | null; major: number } {
  if (!onPath("node")) return { version: null, major: 0 };
  try {
    const v = execSync("node -p 'process.versions.node'", { shell: "/bin/bash", encoding: "utf8" }).trim();
    return { version: v, major: Number(v.split(".")[0]) };
  } catch {
    return { version: null, major: 0 };
  }
}

function helpText(): string {
  const rows = Object.entries(COMMANDS)
    .map(([n, c]) => `  ${n.padEnd(10)} ${c.summary}${c.ready ? "" : "   (planned)"}`)
    .join("\n");
  return `asgard — make anything, your way (v${VERSION})

Usage: asgard <command> [options]

Commands:
${rows}

Global options:
  -h, --help          show help  (per command: asgard <cmd> --help)
  -v, --version       print version
      --json          machine-readable output
  -q, --quiet         less output
      --dry-run       show what would happen, change nothing
  -y, --yes           assume yes (non-interactive)
      --force         overwrite existing (setup/init)
      --cc            also scaffold full .claude/ skeleton (settings, commands/agents/skills/hooks/rules/…)
      --cursor        also scaffold .cursor/ skeleton (skills/, hooks/)
      --codex         also scaffold .codex/config.toml
      --profile <p>   profile: claude-code | cursor | codex`;
}

type Check = { name: string; ok: boolean; detail: string; fix: string };
function runDoctor(c: Ctx): number {
  const sysNode = systemNode();
  const asgard = onPath("asgard");
  const checks: Check[] = [
    { name: "asgard on PATH", ok: !!asgard, detail: asgard ?? "not found", fix: 'add the install dir to PATH, e.g. export PATH="$HOME/.local/bin:$PATH"' },
    { name: "node >= 24 (hooks)", ok: sysNode.major >= 24, detail: sysNode.version ? `v${sysNode.version}` : "not found", fix: "recommended floor for Claude Code hooks (later); not needed to run asgard — https://nodejs.org" },
  ];
  const ok = !!asgard; // self-contained binary; only PATH wiring is fatal here.

  if (c.json) {
    process.stdout.write(JSON.stringify({ version: VERSION, runtime: RUNTIME, ok, checks }, null, 2) + "\n");
    return ok ? 0 : 1;
  }
  if (!c.quiet) process.stdout.write(`asgard doctor — v${VERSION}  (${RUNTIME})\n\n`);
  for (const ch of checks) {
    process.stdout.write(`  ${ch.ok ? "✔" : "⚠"} ${ch.name.padEnd(22)} ${ch.detail}\n`);
    if (!ch.ok) process.stdout.write(`      → ${ch.fix}\n`);
  }
  if (!c.quiet) process.stdout.write(ok ? "\n  ok.\n" : "\n  ⚠ asgard not on PATH — see fix above.\n");
  return ok ? 0 : 1;
}

function present(p: string): boolean {
  try {
    lstatSync(p);
    return true;
  } catch {
    return false;
  }
}

// Clean removal of what install.sh created: the PATH symlink + ~/.asgard (binary + config).
// Honors ASGARD_HOME / BIN_DIR overrides (same as install.sh). Preview unless --yes.
const ASGARD_BLOCK = /\n?# >>> asgard >>>[\s\S]*?# <<< asgard <<<\n?/g;

// Shell rc files that may hold the guarded asgard PATH block (added by install.sh).
function rcFilesWithAsgard(): string[] {
  const home = homedir();
  return [".zshrc", ".bashrc", ".bash_profile", ".zprofile", ".profile"]
    .map((f) => join(home, f))
    .filter((rc) => {
      try {
        return readFileSync(rc, "utf8").includes(">>> asgard >>>");
      } catch {
        return false;
      }
    });
}

function runUninstall(c: Ctx): number {
  const home = process.env.ASGARD_HOME ?? join(homedir(), ".asgard");
  const binDir = process.env.BIN_DIR ?? join(homedir(), ".local", "bin");
  const link = join(binDir, "asgard");
  const files = [link, home].filter(present);
  const rcs = rcFilesWithAsgard();

  if (files.length === 0 && rcs.length === 0) {
    process.stdout.write("asgard: nothing to remove (not installed here).\n");
    return 0;
  }
  if (c.dryRun || !c.yes) {
    const lines = [...files.map((t) => `  ${t}`), ...rcs.map((t) => `  ${t}  (asgard PATH block)`)];
    process.stdout.write("would remove:\n" + lines.join("\n") + "\n\nrun 'asgard uninstall --yes' to remove.\n");
    return 0;
  }
  let failed = 0;
  for (const t of files) {
    try {
      rmSync(t, { recursive: true, force: true });
      process.stdout.write(`  removed ${t}\n`);
    } catch (e) {
      failed++;
      process.stderr.write(`  ✗ ${t}: ${(e as Error).message}\n`);
    }
  }
  for (const rc of rcs) {
    try {
      writeFileSync(rc, readFileSync(rc, "utf8").replace(ASGARD_BLOCK, "\n"));
      process.stdout.write(`  cleaned ${rc}\n`);
    } catch (e) {
      failed++;
      process.stderr.write(`  ✗ ${rc}: ${(e as Error).message}\n`);
    }
  }
  process.stdout.write(failed ? "\nuninstall incomplete.\n" : "\nasgard removed.\n");
  return failed ? 1 : 0;
}

// ── setup / init (CUS-49): scaffold a project ────────────────────────────────
// setup       → AGENTS.md canonical, shared by codex / claude-code / cursor
// setup --cc  → same + .claude/settings.json   (init = alias for setup --cc)
type File = { path: string; content: string };

function scaffold(c: Ctx, label: string, files: File[]): number {
  const existing = files.filter((f) => existsSync(f.path));
  if (existing.length && !c.force && !c.dryRun) {
    process.stderr.write(`asgard: already exists:\n${existing.map((f) => `  ${f.path}`).join("\n")}\n  --force to overwrite · --dry-run to preview\n`);
    return 2;
  }
  if (c.dryRun) {
    process.stdout.write(`would create (${label}):\n${files.map((f) => `  ${f.path}`).join("\n")}\n`);
    return 0;
  }
  for (const f of files) {
    mkdirSync(dirname(f.path), { recursive: true });
    writeFileSync(f.path, f.content);
  }
  process.stdout.write(`✔ ${label} — ${files.length} file(s)\n`);
  return 0;
}

function agentsMd(name: string | undefined): string {
  return `# ${name} — Agent Guide

Managed by Asgard. Canonical instructions for coding agents — read natively by Codex, and bridged to Claude Code (.claude/CLAUDE.md) and Cursor (.cursor/rules/000-agents.mdc).

<!-- >>> asgard:identity >>> -->
## Asgard — 정체성 (세계관)

당신은 **Asgard**의 전령 **Heimdall(헤임달)** — 비프로스트의 수호자이자 과업 기록관.
사용자는 **Odin(오딘)**, 모든 결정의 정점. 작업은 **Quest(과업)**, 성채는 **Asgard(아스가르드)**.

**톤 — 과하지 않게:**
- 첫 응답 한 줄 프레이밍, 결과 보고 한 줄. 1–2문장 내러티브 래핑 → 나머지는 기술 내용 그대로.
- 신화 고유명사(Asgard/Odin/Heimdall/Bifröst) 보존, 매 줄 강요 X.
- 언어 미러링: Odin의 마지막 메시지 언어에 맞춰 내러티브 전환.

> *make anything, your way.*
<!-- <<< asgard:identity <<< -->

## Conventions
<!-- Add project conventions, build/test commands, and architecture notes here. -->

## Asgard wiring check
If asked to "run asgard check", reply with exactly: \`ASGARD_OK — loaded from AGENTS.md\`.
`;
}

// Minimal-but-real Claude Code project settings (CUS-61): a sane permission floor rather than an
// empty {}. Conservative — read-only git allowed, catastrophic deletes denied; the project widens
// `allow` as needed. Ships with .claude/.gitignore so runtime settings.local.json stays private.
function ccSettings(): string {
  return JSON.stringify({
    permissions: {
      allow: ["Bash(git status)", "Bash(git diff *)", "Bash(git log *)"],
      deny: ["Bash(rm -rf *)"],
    },
  }, null, 2) + "\n";
}

// Foundational .claude/ subdirectories. Each is scaffolded with a README (git tracks it + it's
// self-documenting) so a fresh --cc project has the full Claude Code skeleton ready to fill in.
const CC_FOLDERS: [string, string][] = [
  ["commands", "Custom slash commands — one `.md` each, invoked as `/name`. (Skills are the newer alternative.)\nDocs: https://code.claude.com/docs/en/slash-commands"],
  ["agents", "Subagents — one `.md` each; frontmatter: name, description, tools, model.\nDocs: https://code.claude.com/docs/en/sub-agents"],
  ["skills", "Agent skills — each in `<name>/SKILL.md` with a `description` frontmatter.\nDocs: https://code.claude.com/docs/en/skills"],
  ["hooks", "Hook scripts, wired from `settings.json` `hooks{}` by matcher + command.\nDocs: https://code.claude.com/docs/en/hooks"],
  ["rules", "Path-scoped instructions — frontmatter `paths:` globs load them when matching files are read.\nDocs: https://code.claude.com/docs/en/memory"],
  ["output-styles", "Custom system-prompt styles — one `.md` each.\nDocs: https://code.claude.com/docs/en/settings"],
];

// Cursor bridge (cursor.com/docs/context/rules): an always-apply project rule pointing at the
// canonical AGENTS.md. Cursor also reads AGENTS.md natively, but the explicit rule guarantees it
// loads and mirrors the Claude Code bridge — one source of truth, wired to every tool.
function cursorRule(): string {
  return `---
description: Canonical project instructions (Asgard)
alwaysApply: true
---

Follow the canonical project instructions in \`AGENTS.md\` at the repo root.
`;
}

// Foundational .cursor/ subdirectories beyond the always-apply rule (which lives in the base set).
// Cursor's per-project surface: rules/ (base), skills/, hooks/ (+ hooks.json). Commands are only
// documented as plugin bundles, and MCP (.cursor/mcp.json) is opt-in — both left out of the skeleton.
const CURSOR_FOLDERS: [string, string][] = [
  ["skills", "Skills — each in `<name>/SKILL.md`; frontmatter: name, description, paths.\nDocs: https://cursor.com/docs/context/commands"],
  ["hooks", "Hook scripts, wired from `.cursor/hooks.json` (events: beforeShellExecution, afterFileEdit, …).\nDocs: https://cursor.com/docs/hooks"],
];

// Codex project config (developers.openai.com/codex/config-reference). Codex reads the root
// AGENTS.md natively; the only per-project config surface is .codex/config.toml (loaded when the
// project is trusted). Prompts/skills are global (~/.codex) — no project folder tree to scaffold.
function codexConfig(): string {
  return `# Codex project config — overrides ~/.codex/config.toml, loaded only in trusted projects.
# Docs: https://developers.openai.com/codex/config-reference
#
# model = "<your-model>"
# approval_policy = "on-request"    # untrusted | on-request | never
# sandbox_mode = "workspace-write"  # read-only | workspace-write | danger-full-access
#
# Project MCP servers:
# [mcp_servers.example]
# command = "npx"
# args = ["-y", "@some/mcp-server"]
`;
}

// AGENTS.md is always canonical. Codex reads it natively at the repo root; Claude Code and Cursor
// each get a thin bridge to it. A tool flag SCOPES the setup to that tool (nothing for the others);
// with no flag, every agent is wired (universal). Flags are combinable (e.g. --cc --cursor).
// setup            → universal: AGENTS.md + .claude/CLAUDE.md + .cursor/rules bridge (Codex is native)
// setup --cc       → AGENTS.md + full .claude/ only (no .cursor)   [init = --cc]
// setup --cursor   → AGENTS.md + full .cursor/ only (no .claude)
// setup --codex    → AGENTS.md + .codex/config.toml only
// Refs: code.claude.com/docs/en/settings · developers.openai.com/codex/config-reference · cursor.com/docs/context/rules
function runSetup(c: Ctx): number {
  const root = process.cwd();
  const name = root.split(/[/\\]/).pop();
  const cc = c.cc || c.profile === "claude-code";
  const cursor = c.cursor || c.profile === "cursor";
  const codex = c.codex || c.profile === "codex";
  const universal = !cc && !cursor && !codex; // no tool flag → wire every agent

  const files: File[] = [{ path: join(root, "AGENTS.md"), content: agentsMd(name) }];

  // Claude Code — @import resolves relative to the importing file → from .claude/ use @../AGENTS.md.
  // Bridge when universal or targeted; full skeleton only when targeted (--cc).
  if (universal || cc) files.push({ path: join(root, ".claude", "CLAUDE.md"), content: "@../AGENTS.md\n" });
  if (cc) {
    files.push(
      { path: join(root, ".claude", "settings.json"), content: ccSettings() },
      { path: join(root, ".claude", ".gitignore"), content: "settings.local.json\n" },
    );
    for (const [dir, desc] of CC_FOLDERS)
      files.push({ path: join(root, ".claude", dir, "README.md"), content: `# .claude/${dir}/\n\n${desc}\n` });
  }

  // Cursor — always-apply rule bridge when universal or targeted; skeleton folders only when targeted.
  if (universal || cursor) files.push({ path: join(root, ".cursor", "rules", "000-agents.mdc"), content: cursorRule() });
  if (cursor)
    for (const [dir, desc] of CURSOR_FOLDERS)
      files.push({ path: join(root, ".cursor", dir, "README.md"), content: `# .cursor/${dir}/\n\n${desc}\n` });

  // Codex reads root AGENTS.md natively — only a targeted --codex adds the project config.
  if (codex) files.push({ path: join(root, ".codex", "config.toml"), content: codexConfig() });

  const tools = [cc && "claude-code", cursor && "cursor", codex && "codex"].filter(Boolean);
  const label = universal ? "universal setup (AGENTS.md — all agents)" : `setup — AGENTS.md + ${tools.join(", ")}`;
  return scaffold(c, label, files);
}

function runInit(c: Ctx): number {
  return runSetup({ ...c, cc: true }); // init = setup --cc (claude-code)
}

// ── upgrade: self-replace the installed binary with a release build ──────────
function releaseAsset(): string {
  const os = process.platform === "darwin" ? "darwin" : process.platform === "linux" ? "linux" : process.platform === "win32" ? "windows" : "";
  const arch = process.arch === "x64" ? "x64" : process.arch === "arm64" ? "arm64" : "";
  if (!os || !arch) throw new Error(`unsupported platform ${process.platform}/${process.arch}`);
  return `asgard-${os}-${arch}${os === "windows" ? ".exe" : ""}`;
}

function runUpgrade(c: Ctx): number {
  const home = process.env.ASGARD_HOME ?? join(homedir(), ".asgard");
  const dest = join(home, "bin", "asgard");
  const asset = releaseAsset();
  const base = process.env.ASGARD_RELEASE_BASE;
  const pin = c.rest[0]; // optional: "0.1.2" or "v0.1.2"
  const url = base
    ? `${base}/${asset}`
    : pin
      ? `https://github.com/CustomJH/asgard-custom/releases/download/${pin.startsWith("v") ? pin : "v" + pin}/${asset}`
      : `https://github.com/CustomJH/asgard-custom/releases/latest/download/${asset}`;

  if (c.dryRun) {
    process.stdout.write(`would download:\n  ${url}\n  → ${dest}\n`);
    return 0;
  }
  const tmp = `${dest}.tmp`;
  try {
    execSync(`curl -fsSL -o ${JSON.stringify(tmp)} ${JSON.stringify(url)}`, { stdio: "ignore" });
    execSync(`chmod +x ${JSON.stringify(tmp)}`);
    renameSync(tmp, dest); // atomic; safe while running on Unix
  } catch (e) {
    try { rmSync(tmp, { force: true }); } catch { /* ignore */ }
    process.stderr.write(`asgard: upgrade failed — ${(e as Error).message}\n  url: ${url}\n`);
    return 1;
  }
  const v = execSync(`${JSON.stringify(dest)} --version`, { encoding: "utf8" }).trim();
  process.stdout.write(`✔ upgraded → v${v}  ${dest}\n`);
  return 0;
}

function runCompletions(c: Ctx): number {
  const shell = c.rest[0];
  const cmds = [...Object.keys(COMMANDS), "version", "help"].join(" ");
  const flags = "--help --version --json --quiet --dry-run --yes --profile";
  if (shell === "bash") {
    process.stdout.write(`_asgard() {
  local cur="\${COMP_WORDS[COMP_CWORD]}"
  if [ "\$COMP_CWORD" -eq 1 ]; then
    COMPREPLY=( \$(compgen -W "${cmds}" -- "\$cur") )
  else
    COMPREPLY=( \$(compgen -W "${flags}" -- "\$cur") )
  fi
}
complete -F _asgard asgard
`);
    return 0;
  }
  if (shell === "zsh") {
    process.stdout.write(`#compdef asgard
_asgard() {
  local -a cmds=(${cmds})
  if (( CURRENT == 2 )); then compadd -- \$cmds; else compadd -- ${flags}; fi
}
_asgard "\$@"
`);
    return 0;
  }
  if (shell === "fish") {
    process.stdout.write(`complete -c asgard -f
complete -c asgard -n __fish_use_subcommand -a "${cmds}"
complete -c asgard -l help -s h
complete -c asgard -l version -s v
complete -c asgard -l json
complete -c asgard -l quiet -s q
complete -c asgard -l dry-run
complete -c asgard -l yes -s y
complete -c asgard -l profile
`);
    return 0;
  }
  process.stderr.write("usage: asgard completions <bash|zsh|fish>\n");
  return 2;
}

function main(): number {
  const { values, positionals } = parseArgs({
    args: process.argv.slice(2),
    allowPositionals: true,
    strict: false,
    options: {
      help: { type: "boolean", short: "h" },
      version: { type: "boolean", short: "v" },
      json: { type: "boolean" },
      quiet: { type: "boolean", short: "q" },
      "dry-run": { type: "boolean" },
      yes: { type: "boolean", short: "y" },
      force: { type: "boolean" },
      cc: { type: "boolean" },
      cursor: { type: "boolean" },
      codex: { type: "boolean" },
      profile: { type: "string" },
    },
  });

  const cmd = positionals[0];

  if (!cmd) {
    if (values.version) process.stdout.write(VERSION + "\n");
    else process.stdout.write(helpText() + "\n");
    return 0;
  }
  if (cmd === "help") {
    process.stdout.write(helpText() + "\n");
    return 0;
  }
  if (cmd === "version") {
    process.stdout.write(VERSION + "\n");
    return 0;
  }

  const entry = COMMANDS[cmd];
  if (!entry) {
    process.stderr.write(`asgard: unknown command '${cmd}'\n\nrun 'asgard --help'\n`);
    return 2;
  }
  if (values.help) {
    process.stdout.write(`asgard ${cmd} — ${entry.summary}${entry.ready ? "" : "  (planned)"}\n`);
    return 0;
  }

  const ctx: Ctx = {
    rest: positionals.slice(1),
    json: !!values.json,
    quiet: !!values.quiet,
    dryRun: !!values["dry-run"],
    yes: !!values.yes,
    force: !!values.force,
    cc: !!values.cc,
    cursor: !!values.cursor,
    codex: !!values.codex,
    profile: typeof values.profile === "string" ? values.profile : undefined,
  };

  if (!entry.ready || !entry.run) {
    process.stdout.write(`asgard ${cmd} — ${entry.summary}\n  planned, not implemented yet (tracked in CUS-49).\n`);
    return 0;
  }
  return entry.run(ctx);
}

process.exit(main());
