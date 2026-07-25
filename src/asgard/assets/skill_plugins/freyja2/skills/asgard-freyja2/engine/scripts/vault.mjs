#!/usr/bin/env node
/**
 * Fólkvangr — inspect and clear the artifact vault.
 *
 * The vault (`.asgard/.vanadis/engine2/`) is scratch for a judging run: sidecar,
 * critique snapshots, live-session journals, hook caches, questions. It sits
 * inside `.asgard/`, which `asgard init` creates and Asgard already keeps out
 * of git — so nothing here reaches a commit. But "not committed" is not the
 * same as "not there", and a field left full is a field that goes stale. This
 * is the command that clears it.
 *
 *   node vault.mjs status                 what exists, and how big
 *   node vault.mjs sweep                  drop run-scoped state, keep the record
 *   node vault.mjs purge                  drop the vault entirely
 *   node vault.mjs purge --legacy-only    drop only the retired `.impeccable/` root
 *
 * `sweep` is the one to run when a command finishes: live sessions, questions,
 * and hook caches are meaningless once the run that made them is over, while
 * the design sidecar, config, critique snapshots, and surface briefs are the
 * record the next run reads. `purge` is the one to run when the work is
 * delivered and nothing should outlive it.
 *
 * Refuses to purge under a running live server unless `--force`: removing
 * `live/server.json` out from under a live process leaves it unreachable and
 * unkillable by `live.mjs stop`.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { resolveProjectRoot } from './context.mjs';
import { parseTargetOptions } from './lib/target-args.mjs';
import { readLiveServerInfo } from './lib/vault-paths.mjs';
import {
  LEGACY_VAULT_RELS,
  TRANSIENT_ENTRIES,
  VAULT_REL,
  legacyVaultDirsFor,
  purgeVault,
  sweepVault,
  vaultDirFor,
} from './lib/vault.mjs';

const ACTIONS = new Set(['status', 'sweep', 'purge']);

function rel(target, root) {
  const out = path.relative(root, target);
  return out && !out.startsWith('..') ? out.split(path.sep).join('/') : target;
}

/** Recursive byte total and file count. Returns null when `dir` is absent. */
function measure(dir) {
  let bytes = 0;
  let files = 0;
  const walk = (current) => {
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        continue;
      }
      files += 1;
      try { bytes += fs.statSync(full).size; } catch { /* vanished mid-walk */ }
    }
  };
  if (!fs.existsSync(dir)) return null;
  walk(dir);
  return { bytes, files };
}

function human(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function liveServerRunning(root) {
  try {
    const live = readLiveServerInfo(root);
    return live?.info?.pid ? live : null;
  } catch {
    return null;
  }
}

export function statusReport(root) {
  const lines = [];
  const vault = vaultDirFor(root);
  const size = measure(vault);
  lines.push(`Fólkvangr — Freyja 2 artifact vault`);
  lines.push(`  vault:  ${rel(vault, root)}${size ? ` (${size.files} files, ${human(size.bytes)})` : ' (absent)'}`);

  if (size) {
    let entries = [];
    try { entries = fs.readdirSync(vault).sort(); } catch { /* unreadable */ }
    if (entries.length) {
      for (const entry of entries) {
        const entrySize = measure(path.join(vault, entry));
        const scope = TRANSIENT_ENTRIES.includes(entry) ? 'run-scoped' : 'record';
        lines.push(`    ${entry}  —  ${scope}${entrySize ? `, ${human(entrySize.bytes)}` : ''}`);
      }
    } else {
      lines.push('    (empty)');
    }
  }

  for (const legacy of legacyVaultDirsFor(root)) {
    if (!fs.existsSync(legacy)) continue;
    const legacySize = measure(legacy);
    lines.push(`  retired: ${rel(legacy, root)} still present (${legacySize.files} files, ${human(legacySize.bytes)}) — \`purge --legacy-only\` removes it`);
  }

  const live = liveServerRunning(root);
  if (live) lines.push(`  live:   a live server is running (pid ${live.info.pid}); purge needs --force`);

  return lines.join('\n');
}

function main(argv) {
  const options = parseTargetOptions(argv);
  const flags = new Set(argv.filter((arg) => arg.startsWith('--')));
  const action = argv.find((arg) => !arg.startsWith('--')) || 'status';

  if (!ACTIONS.has(action)) {
    process.stderr.write(`usage: vault.mjs <${[...ACTIONS].join('|')}> [--legacy-only] [--force]\n`);
    process.exit(1);
  }

  const root = resolveProjectRoot(process.cwd(), options);

  if (action === 'status') {
    process.stdout.write(`${statusReport(root)}\n`);
    return;
  }

  if (action === 'sweep') {
    const removed = sweepVault(root);
    process.stdout.write(removed.length
      ? `Swept the field: removed ${removed.join(', ')}. The record (design.json, config, critique, surfaces) is untouched.\n`
      : `Nothing run-scoped to sweep under ${VAULT_REL}/.\n`);
    return;
  }

  const legacyOnly = flags.has('--legacy-only');
  if (!legacyOnly && !flags.has('--force')) {
    const live = liveServerRunning(root);
    if (live) {
      process.stderr.write(
        `Refusing to purge: a live server is running (pid ${live.info.pid}). `
        + `Stop it with \`node live.mjs stop\` first, or pass --force.\n`,
      );
      process.exit(2);
    }
  }

  const removed = legacyOnly
    ? purgeLegacyOnly(root)
    : purgeVault(root);
  process.stdout.write(removed.length
    ? `Cleared: ${removed.join(', ')}.\n`
    : `Nothing to clear${legacyOnly ? ` (no ${LEGACY_VAULT_RELS.join(', ')})` : ` under ${VAULT_REL}/`}.\n`);
}

function purgeLegacyOnly(root) {
  const removed = [];
  for (const dir of legacyVaultDirsFor(root)) {
    if (!fs.existsSync(dir)) continue;
    try {
      fs.rmSync(dir, { recursive: true, force: true });
      removed.push(rel(dir, root));
    } catch { /* reported by omission */ }
  }
  return removed;
}

function isMainModule() {
  if (!process.argv[1]) return false;
  try {
    return fs.realpathSync(fileURLToPath(import.meta.url)) === fs.realpathSync(process.argv[1]);
  } catch {
    return import.meta.url === pathToFileURL(process.argv[1]).href;
  }
}

if (isMainModule()) {
  main(process.argv.slice(2));
}
