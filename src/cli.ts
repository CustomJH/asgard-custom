#!/usr/bin/env bun
// asgard CLI. Erasable-TS only (Bun + Node>=24 type-stripping): no enums/namespaces/param-props.
import { parseArgs } from "node:util";
import { execSync } from "node:child_process";
import { rmSync, lstatSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
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
  profile: string | undefined;
};
type Cmd = { summary: string; ready: boolean; run?: (c: Ctx) => number };

// The command surface. `ready` commands run; planned ones are listed + announced
// (behavior lands in CUS-49). Memory/knowledge-store commands are intentionally absent.
const COMMANDS: Record<string, Cmd> = {
  doctor: { summary: "diagnose runtime & PATH", ready: true, run: runDoctor },
  init: { summary: "install Asgard's .claude into this project", ready: false },
  setup: { summary: "compose project config (.asgardfile)", ready: false },
  run: { summary: "run an .asgardfile task", ready: false },
  update: { summary: "update this project's .claude (3-way merge)", ready: false },
  upgrade: { summary: "upgrade the asgard binary itself", ready: false },
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
      --profile <p>   target profile (e.g. claude-code)`;
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
function runUninstall(c: Ctx): number {
  const home = process.env.ASGARD_HOME ?? join(homedir(), ".asgard");
  const binDir = process.env.BIN_DIR ?? join(homedir(), ".local", "bin");
  const link = join(binDir, "asgard");
  const targets = [link, home].filter(present);

  if (targets.length === 0) {
    process.stdout.write("asgard: nothing to remove (not installed here).\n");
    return 0;
  }
  if (c.dryRun || !c.yes) {
    process.stdout.write("would remove:\n" + targets.map((t) => `  ${t}`).join("\n") + "\n\nrun 'asgard uninstall --yes' to remove.\n");
    return 0;
  }
  let failed = 0;
  for (const t of targets) {
    try {
      rmSync(t, { recursive: true, force: true });
      process.stdout.write(`  removed ${t}\n`);
    } catch (e) {
      failed++;
      process.stderr.write(`  ✗ ${t}: ${(e as Error).message}\n`);
    }
  }
  process.stdout.write(failed ? "\nuninstall incomplete.\n" : "\nasgard removed.\n");
  return failed ? 1 : 0;
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
    profile: typeof values.profile === "string" ? values.profile : undefined,
  };

  if (!entry.ready || !entry.run) {
    process.stdout.write(`asgard ${cmd} — ${entry.summary}\n  planned, not implemented yet (tracked in CUS-49).\n`);
    return 0;
  }
  return entry.run(ctx);
}

process.exit(main());
