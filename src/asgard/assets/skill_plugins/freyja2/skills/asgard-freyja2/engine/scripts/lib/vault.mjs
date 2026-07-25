/**
 * Freyja 2's artifact vault — Fólkvangr, Freyja's field, where the judged
 * gather and nothing is meant to stay once the judging is done.
 *
 * Every artifact this engine writes about a project — the design sidecar,
 * live-session journals, critique snapshots, hook caches, surface briefs,
 * questions — lands under
 *
 *   <project root>/.asgard/.vanadis/engine2/
 *
 * `.asgard/.vanadis/` is the shared roof for Freyja's design engines — engine 1
 * writes beside this under `engine1/` — so a project running both keeps two
 * `config.json`s apart instead of one overwriting the other.
 *
 * `asgard init` creates `.asgard/` and Asgard's own setup keeps it out of git,
 * so the vault inherits that and owes no gitignore entry of its own. Nothing
 * here writes, reads, or repairs an ignore file; the directory simply exists
 * where Asgard's runtime state already lives.
 *
 * The engine used to write a dotted `.impeccable/` directory at the project
 * root — visible to git, named after the upstream tool, and outliving the run
 * that produced it. Reads still fall back to that location so an existing
 * project keeps its sidecar and config; writes only ever go to the vault.
 *
 * This module is deliberately pure: every entry point takes an already
 * resolved root. `context.mjs` owns project-root resolution and must be able
 * to import from here without a cycle.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

/** Vault location relative to the project root, as path segments. */
export const VAULT_SEGMENTS = Object.freeze(['.asgard', '.vanadis', 'engine2']);

/** Vault location relative to the project root, in posix form. */
export const VAULT_REL = VAULT_SEGMENTS.join('/');

/**
 * Retired artifact roots, newest first. Read-only: resolvers fall back to
 * these so a project written by an older engine still loads, and the doctor
 * pass reports them as drift. Nothing writes here.
 */
export const LEGACY_VAULT_RELS = Object.freeze(['.impeccable']);

/**
 * Absolute vault path for a project root. `FREYJA_VAULT_DIR` overrides it
 * outright (absolute, or resolved against the root) for tests and for hosts
 * that keep build output somewhere unusual.
 */
export function vaultDirFor(root, env = process.env) {
  const override = env?.FREYJA_VAULT_DIR?.trim();
  if (override) return path.isAbsolute(override) ? override : path.resolve(root, override);
  return path.join(root, ...VAULT_SEGMENTS);
}

/** Absolute path to `rel` inside the vault. */
export function vaultPath(root, ...rel) {
  return path.join(vaultDirFor(root), ...rel);
}

/** Retired artifact roots for a project root, in read precedence order. */
export function legacyVaultDirsFor(root) {
  return LEGACY_VAULT_RELS.map((rel) => path.join(root, rel));
}

/**
 * Every location `rel` may live for this root, canonical first. Callers that
 * write use `[0]`; callers that read walk the list.
 */
export function vaultCandidates(root, ...rel) {
  return [
    vaultPath(root, ...rel),
    ...legacyVaultDirsFor(root).map((dir) => path.join(dir, ...rel)),
  ];
}

/**
 * First existing location of `rel`, or the canonical one when none exists so
 * the return value is always a usable path.
 */
export function resolveVaultFile(root, ...rel) {
  const candidates = vaultCandidates(root, ...rel);
  return candidates.find((candidate) => existsQuiet(candidate)) || candidates[0];
}

/**
 * Create the vault, or any subdirectory of it. `root` is accepted so callers
 * read the same at every site, but it is not needed: `.asgard/` is Asgard's
 * own runtime directory and is already out of git, so there is no marker to
 * stamp and no ignore file to repair.
 */
export function ensureVaultDir(dir, _root = null) {
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

/** Create the parent directory of `filePath` as vault space, then return it. */
export function ensureVaultFileDir(filePath, root = null) {
  ensureVaultDir(path.dirname(filePath), root);
  return filePath;
}

function existsQuiet(filePath) {
  try {
    return fs.existsSync(filePath);
  } catch {
    return false;
  }
}

// ─── Global (per-user) cache ───────────────────────────────────────────────

/**
 * Machine-wide caches — update polling, staleness throttling — are not project
 * artifacts and have no project root to live under. They sit beside Asgard's
 * other per-user state instead of in a tool-named dotfile of their own.
 */
export function userCachePath(name, env = process.env, homedir = os.homedir()) {
  const override = env?.FREYJA_CACHE_DIR?.trim();
  const dir = override
    ? (path.isAbsolute(override) ? override : path.resolve(override))
    : path.join(homedir, '.asgard', 'freyja2');
  return path.join(dir, name);
}

// ─── Sweeping the field ────────────────────────────────────────────────────

/**
 * Vault entries that exist only for the duration of a judging run. `sweep`
 * removes these and leaves the durable record (design sidecar, config,
 * critique snapshots, surface briefs) in place; `purge` removes the vault
 * outright.
 */
export const TRANSIENT_ENTRIES = Object.freeze([
  'live',
  'questions',
  'hook.cache.json',
  'hook.pending.json',
]);

/**
 * Remove the run-scoped entries. Returns the relative paths actually removed
 * so callers can report what they cleared rather than claiming a clean field
 * they never touched.
 */
export function sweepVault(root, { entries = TRANSIENT_ENTRIES } = {}) {
  const removed = [];
  for (const dir of [vaultDirFor(root), ...legacyVaultDirsFor(root)]) {
    for (const entry of entries) {
      const target = path.join(dir, entry);
      if (!existsQuiet(target)) continue;
      try {
        fs.rmSync(target, { recursive: true, force: true });
        removed.push(path.relative(root, target).split(path.sep).join('/'));
      } catch {
        // A live server still holding a lock keeps its file; the next sweep gets it.
      }
    }
  }
  return removed;
}

/**
 * Remove the vault entirely, along with any retired artifact root. Returns the
 * relative paths removed.
 */
export function purgeVault(root, { includeLegacy = true } = {}) {
  const removed = [];
  const targets = includeLegacy
    ? [vaultDirFor(root), ...legacyVaultDirsFor(root)]
    : [vaultDirFor(root)];
  for (const target of targets) {
    if (!existsQuiet(target)) continue;
    try {
      fs.rmSync(target, { recursive: true, force: true });
      removed.push(path.relative(root, target).split(path.sep).join('/'));
    } catch {
      // Reported as not-removed rather than swallowed as success.
    }
  }
  return removed;
}
