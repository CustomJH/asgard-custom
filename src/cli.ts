#!/usr/bin/env bun
// asgard CLI. Erasable-TS only (Bun + Node>=24 type-stripping): no enums/namespaces/param-props.
import { parseArgs } from "node:util";
import { execSync } from "node:child_process";
import { rmSync, lstatSync, mkdirSync, writeFileSync, readFileSync, existsSync, renameSync } from "node:fs";
import { homedir } from "node:os";
import { join, dirname } from "node:path";
import pkg from "../package.json" with { type: "json" };
import { agentsMd, ccSettings, gitGuard, secretGuard, CC_FOLDERS, cursorRule, cursorGitGuard, cursorHooksJson, CURSOR_FOLDERS, codexConfig, codexRules } from "./templates.ts";

const VERSION: string = (pkg as { version?: string }).version ?? "0.0.0";
const RUNTIME: string = (process.versions as { bun?: string }).bun
  ? `bun v${(process.versions as { bun?: string }).bun}`
  : `node v${process.versions.node}`;

// ── terminal UX (mirrors install.sh): branded + colored on a tty; plain otherwise ──
// `--quiet` suppresses decorative head/step lines (results still print). NO_COLOR / non-tty → no ANSI.
let QUIET = false;
const COLOR = process.stdout.isTTY && !process.env.NO_COLOR;
const paint = (code: string, s: string): string => (COLOR ? `\x1b[${code}m${s}\x1b[0m` : s);
const bold = (s: string): string => paint("1", s);
const dim = (s: string): string => paint("2", s);
function uiHead(action: string): void { if (!QUIET) process.stdout.write(`\n  ${paint("1;35", "ᛞ")} ${bold("asgard")} ${dim(action)}\n\n`); }
function uiStep(msg: string): void { if (!QUIET) process.stdout.write(`  ${paint("36", "→")} ${msg}\n`); }
function uiOk(msg: string): void { process.stdout.write(`  ${paint("32", "✔")} ${msg}\n`); }
function uiWarn(msg: string): void { process.stdout.write(`  ${paint("33", "!")} ${msg}\n`); }
function uiFail(msg: string): void { process.stderr.write(`  ${paint("31", "✗")} ${msg}\n`); }

// Blocking sleep (ms). Synchronous so the progress bar can animate without making every command
// async — a timed wait on a throwaway SharedArrayBuffer. tty-only path, so it never stalls scripts.
function sleep(ms: number): void { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms); }

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
    uiHead("uninstall");
    uiWarn("nothing to remove (not installed here).");
    return 0;
  }
  if (c.dryRun || !c.yes) {
    uiHead("uninstall");
    for (const t of files) uiStep(`would remove ${dim(t)}`);
    for (const t of rcs) uiStep(`would clean ${dim(t)}  ${dim("(asgard PATH block)")}`);
    process.stdout.write(`\n  ${dim("run 'asgard uninstall --yes' to remove.")}\n`);
    return 0;
  }
  uiHead("uninstall");
  let failed = 0;
  for (const t of files) {
    try {
      rmSync(t, { recursive: true, force: true });
      uiOk(`removed ${dim(t)}`);
    } catch (e) {
      failed++;
      uiFail(`${t}: ${(e as Error).message}`);
    }
  }
  for (const rc of rcs) {
    try {
      writeFileSync(rc, readFileSync(rc, "utf8").replace(ASGARD_BLOCK, "\n"));
      uiOk(`cleaned ${dim(rc)}  ${dim("(PATH block)")}`);
    } catch (e) {
      failed++;
      uiFail(`${rc}: ${(e as Error).message}`);
    }
  }
  process.stdout.write(failed ? `\n  ${paint("33", "!")} uninstall incomplete.\n` : `\n  ${paint("32", "✔")} asgard removed.\n`);
  return failed ? 1 : 0;
}

// ── setup / init (CUS-49): scaffold a project ────────────────────────────────
// setup       → AGENTS.md canonical, shared by codex / claude-code / cursor
// setup --cc  → same + .claude/settings.json   (init = alias for setup --cc)
type File = { path: string; content: string };
// A setup stage — a titled group of files, rendered as one install-like step ("STEP 2/4 · Claude Code").
type Stage = { title: string; note?: string; files: File[] };

// ── Bifröst progress bar — a pinned bottom bar fills in place (percentage climbing, stage caption
// morphing) while ✔ lines scroll above it. Mirrors the asgard installer's rainbow bar so setup and
// install feel like one tool. tty-only; non-tty/quiet/dry take the plain staged path below.
const BAR_CELLS = 22;
const BIFROST = ["31", "38;5;208", "33", "32", "36", "34", "35"]; // R O Y G C B M — the rainbow bridge

// Redraw the pinned bar in place: rainbow ▆ up to pct, dim ░ after, bold %, then the morphing caption.
// \x1b[K erases any leftover from a longer previous caption/frame.
function drawBar(pct: number, caption: string): void {
  const filled = Math.floor((BAR_CELLS * pct) / 100);
  let bar = "";
  for (let i = 0; i < BAR_CELLS; i++)
    bar += i < filled ? paint(BIFROST[Math.floor((i * BIFROST.length) / BAR_CELLS)], "▆") : dim("░");
  process.stdout.write(`\r  ${bar}  ${bold(String(pct).padStart(3) + "%")}  ${caption}\x1b[K`);
}

// Animate the fill from → to (small steps + short sleep = smooth climb), holding the caption.
function advance(from: number, to: number, caption: string): number {
  let p = from;
  while (p < to) { p = Math.min(p + 4, to); drawBar(p, caption); sleep(14); }
  return to;
}

// Emit a permanent line ABOVE the pinned bar: erase the bar, print the line, redraw the bar beneath.
function barLog(pct: number, caption: string, line: string): void {
  process.stdout.write(`\r\x1b[K${line}\n`);
  drawBar(pct, caption);
}

// Scaffold a project as an install-like progress flow. On a tty: a pinned Bifröst bar climbs while
// each written file scrolls up as a ✔ and the caption morphs per stage; then a done summary. Guards
// existing files (--force to overwrite) and previews under --dry-run. Non-tty/quiet/dry: plain steps.
function scaffoldStaged(c: Ctx, headline: string, stages: Stage[]): number {
  const cwd = process.cwd();
  const rel = (p: string): string => (p.startsWith(cwd + "/") ? p.slice(cwd.length + 1) : p);
  const all = stages.flatMap((s) => s.files);
  const existing = all.filter((f) => existsSync(f.path));
  if (existing.length && !c.force && !c.dryRun) {
    uiHead(headline);
    for (const f of existing) uiFail(`exists ${dim(rel(f.path))}`);
    process.stderr.write(`  ${dim("--force to overwrite · --dry-run to preview")}\n`);
    return 2;
  }
  uiHead(headline);
  const total = stages.length;
  const caption = (i: number): string =>
    `${dim(`STEP ${i + 1}/${total}`)} ${dim("·")} ${bold(stages[i].title)}${stages[i].note ? "  " + dim(stages[i].note) : ""}`;

  // Plain staged path — dry-run preview, non-tty (CI/pipe), or --quiet: one line per step, no bar.
  if (c.dryRun || !COLOR || QUIET) {
    stages.forEach((st, i) => {
      const label = st.note ? `${st.title}  ${dim("· " + st.note)}` : st.title;
      const tag = dim(`[${i + 1}/${total}]`);
      if (c.dryRun) uiStep(`${tag} ${label}`);
      for (const f of st.files) {
        if (!c.dryRun) { mkdirSync(dirname(f.path), { recursive: true }); writeFileSync(f.path, f.content); }
        process.stdout.write(`      ${dim((c.dryRun ? "+ " : "") + rel(f.path))}\n`);
      }
      if (!c.dryRun) uiOk(`${tag} ${label}`);
    });
    if (c.dryRun) { process.stdout.write(`\n  ${dim(`${all.length} file(s) — run without --dry-run to create.`)}\n`); return 0; }
    process.stdout.write(`\n  ${paint("32", "✔")} ${bold("done")} ${dim(`— ${all.length} file(s) · make anything, your way`)}\n`);
    return 0;
  }

  // Animated pinned-bar path (interactive tty).
  process.stdout.write("\x1b[?25l"); // hide cursor while the bar animates
  let pct = 0;
  let done = 0;
  drawBar(0, caption(0));
  stages.forEach((st, i) => {
    drawBar(pct, caption(i)); // morph caption at the stage boundary
    for (const f of st.files) {
      mkdirSync(dirname(f.path), { recursive: true });
      writeFileSync(f.path, f.content);
      pct = advance(pct, Math.round((++done / all.length) * 100), caption(i));
      barLog(pct, caption(i), `  ${paint("32", "✔")} ${dim(rel(f.path))}`);
    }
  });
  advance(pct, 100, caption(total - 1));
  process.stdout.write("\r\x1b[K\x1b[?25h"); // clear the bar, restore cursor
  process.stdout.write(`\n  ${paint("32", "✔")} ${bold("done")} ${dim(`— ${all.length} file(s) · make anything, your way`)}\n`);
  process.stdout.write(`  ${dim("next: edit")} ${bold("AGENTS.md")} ${dim("— your project's canonical agent guide")}\n`);
  return 0;
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

  // Each stage is one install-like step. Build only the stages this invocation actually writes.
  const stages: Stage[] = [
    { title: "AGENTS.md", note: "canonical agent guide", files: [{ path: join(root, "AGENTS.md"), content: agentsMd(name) }] },
  ];

  // Claude Code — @import resolves relative to the importing file → from .claude/ use @../AGENTS.md.
  // Bridge when universal or targeted; full skeleton only when targeted (--cc).
  const claude: File[] = [];
  if (universal || cc) claude.push({ path: join(root, ".claude", "CLAUDE.md"), content: "@../AGENTS.md\n" });
  if (cc) {
    claude.push(
      { path: join(root, ".claude", "settings.json"), content: ccSettings() },
      { path: join(root, ".claude", ".gitignore"), content: "settings.local.json\n" },
    );
    for (const [dir, desc] of CC_FOLDERS)
      claude.push({ path: join(root, ".claude", dir, "README.md"), content: `# .claude/${dir}/\n\n${desc}\n` });
    // Working Canon guards wired in settings.json hooks{} (Law 3/6 git, Law 4 secrets).
    claude.push(
      { path: join(root, ".claude", "hooks", "git-guard.mjs"), content: gitGuard() },
      { path: join(root, ".claude", "hooks", "secret-guard.mjs"), content: secretGuard() },
    );
  }
  if (claude.length) stages.push({ title: "Claude Code", note: cc ? ".claude/ — settings, skills, hooks, agents" : ".claude/ — bridge", files: claude });

  // Cursor — always-apply rule bridge when universal or targeted; skeleton folders only when targeted.
  const cursorFiles: File[] = [];
  if (universal || cursor) cursorFiles.push({ path: join(root, ".cursor", "rules", "000-agents.mdc"), content: cursorRule() });
  if (cursor) {
    for (const [dir, desc] of CURSOR_FOLDERS)
      cursorFiles.push({ path: join(root, ".cursor", dir, "README.md"), content: `# .cursor/${dir}/\n\n${desc}\n` });
    // Canon enforcement — Cursor's beforeShellExecution guard (different schema than Claude/Codex).
    cursorFiles.push(
      { path: join(root, ".cursor", "hooks.json"), content: cursorHooksJson() },
      { path: join(root, ".cursor", "hooks", "git-guard.mjs"), content: cursorGitGuard() },
    );
  }
  if (cursorFiles.length) stages.push({ title: "Cursor", note: cursor ? ".cursor/ — rules, skills, hooks" : ".cursor/ — rule bridge", files: cursorFiles });

  // Codex reads root AGENTS.md natively — --codex adds project config + a PreToolUse git-guard +
  // native command rules (defense-in-depth). Hooks share Claude Code's stdin schema (same script);
  // rules are Starlark (node-free), so the Canon holds even without node.
  if (codex) stages.push({ title: "Codex", note: ".codex/ — config, git-guard, rules", files: [
    { path: join(root, ".codex", "config.toml"), content: codexConfig() },
    { path: join(root, ".codex", "hooks", "git-guard.mjs"), content: gitGuard() },
    { path: join(root, ".codex", "rules", "canon.rules"), content: codexRules() },
  ] });

  const tools = [cc && "claude-code", cursor && "cursor", codex && "codex"].filter(Boolean);
  const headline = universal ? "setting up project — all agents" : `setting up project — ${tools.join(", ")}`;
  return scaffoldStaged(c, headline, stages);
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
    uiHead("upgrade");
    uiStep(`would download ${dim(url)}`);
    uiStep(`to ${dim(dest)}`);
    return 0;
  }
  uiHead("upgrade");
  let cur = "";
  try { cur = execSync(`${JSON.stringify(dest)} --version`, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim(); } catch { /* not installed yet */ }
  const tmp = `${dest}.tmp`;
  try {
    uiStep(`downloading ${bold(asset)}${pin ? dim(`  (${pin})`) : ""}`);
    // tty → curl's own progress bar streams to stderr; non-tty → silent.
    const prog = COLOR ? "--progress-bar" : "-s";
    execSync(`curl -fSL ${prog} -o ${JSON.stringify(tmp)} ${JSON.stringify(url)}`, { stdio: ["ignore", "ignore", COLOR ? "inherit" : "ignore"] });
    execSync(`chmod +x ${JSON.stringify(tmp)}`);
    renameSync(tmp, dest); // atomic; safe while running on Unix
  } catch (e) {
    try { rmSync(tmp, { force: true }); } catch { /* ignore */ }
    uiFail(`upgrade failed — ${(e as Error).message}`);
    process.stderr.write(`  ${dim("url: " + url)}\n`);
    return 1;
  }
  const v = execSync(`${JSON.stringify(dest)} --version`, { encoding: "utf8" }).trim();
  const verb = !cur ? "installed" : cur === v ? "reinstalled" : "upgraded";
  uiOk(`${verb} ${cur ? dim(cur) + " → " : ""}${bold("v" + v)}  ${dim(dest)}`);
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
  QUIET = ctx.quiet;

  if (!entry.ready || !entry.run) {
    process.stdout.write(`asgard ${cmd} — ${entry.summary}\n  planned, not implemented yet (tracked in CUS-49).\n`);
    return 0;
  }
  return entry.run(ctx);
}

process.exit(main());
