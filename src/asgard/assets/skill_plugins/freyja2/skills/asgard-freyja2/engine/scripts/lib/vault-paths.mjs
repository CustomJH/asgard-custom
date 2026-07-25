/**
 * Project-root-aware layer over the Fólkvangr vault (see `vault.mjs`).
 *
 * Everything the engine persists about a project resolves through here, so
 * `.asgard/.vanadis/engine2/` is stated once and the retired `.impeccable/` root stays
 * readable without any caller knowing it existed.
 */

import fs from 'node:fs';
import path from 'node:path';
import { resolveProjectRoot } from '../context.mjs';
import { designSidecarCandidatesFor } from './staleness.mjs';
import {
  VAULT_REL,
  ensureVaultDir,
  ensureVaultFileDir,
  purgeVault,
  resolveVaultFile,
  sweepVault,
  vaultCandidates,
  vaultDirFor,
  vaultPath,
} from './vault.mjs';
export { FREYJA2_COMMAND_PREFIX } from './provider.mjs';
export {
  VAULT_REL,
  VAULT_SEGMENTS,
  LEGACY_VAULT_RELS,
  TRANSIENT_ENTRIES,
  ensureVaultDir,
  ensureVaultFileDir,
  purgeVault,
  sweepVault,
  userCachePath,
} from './vault.mjs';

/** Vault location relative to the project root, kept for message text. */
export const VAULT_DIR = VAULT_REL;
export const LIVE_DIR = 'live';
export const CRITIQUE_DIR = 'critique';

export function getVaultDir(cwd = process.cwd(), options = {}) {
  return vaultDirFor(resolveProjectRoot(cwd, options));
}

export function getDesignSidecarPath(cwd = process.cwd(), options = {}) {
  return vaultPath(resolveProjectRoot(cwd, options), 'design.json');
}

export function getDesignSidecarCandidates(cwd = process.cwd(), contextDir = cwd, options = {}) {
  return designSidecarCandidatesFor(resolveProjectRoot(cwd, options), contextDir);
}

export function resolveDesignSidecarPath(cwd = process.cwd(), contextDir = cwd, options = {}) {
  return firstExisting(getDesignSidecarCandidates(cwd, contextDir, options));
}

export function getLiveDir(cwd = process.cwd(), options = {}) {
  return path.join(getVaultDir(cwd, options), LIVE_DIR);
}

export function getLiveConfigPath(cwd = process.cwd(), options = {}) {
  return path.join(getLiveDir(cwd, options), 'config.json');
}

export function getLegacyLiveConfigPath(scriptsDir) {
  return path.join(scriptsDir, 'config.json');
}

export function resolveLiveConfigPath({ cwd = process.cwd(), scriptsDir, env = process.env, targetPath } = {}) {
  if (env.FREYJA2_LIVE_CONFIG && env.FREYJA2_LIVE_CONFIG.trim()) {
    const configured = env.FREYJA2_LIVE_CONFIG.trim();
    return path.isAbsolute(configured) ? configured : path.resolve(cwd, configured);
  }
  const primary = getLiveConfigPath(cwd, { targetPath });
  if (fs.existsSync(primary)) return primary;
  // A project set up by an older engine keeps its live config under the
  // retired artifact root; adopt it rather than demanding a fresh setup.
  for (const candidate of vaultCandidates(resolveProjectRoot(cwd, { targetPath }), LIVE_DIR, 'config.json')) {
    if (fs.existsSync(candidate)) return candidate;
  }
  if (scriptsDir) {
    const legacy = getLegacyLiveConfigPath(scriptsDir);
    if (fs.existsSync(legacy)) return legacy;
  }
  return primary;
}

export function getLiveServerPath(cwd = process.cwd(), options = {}) {
  return path.join(getLiveDir(cwd, options), 'server.json');
}

export function getLegacyLiveServerPath(cwd = process.cwd(), options = {}) {
  return path.join(resolveProjectRoot(cwd, options), '.freyja2-live.json');
}

export function readLiveServerInfo(cwd = process.cwd(), options = {}) {
  for (const filePath of [getLiveServerPath(cwd, options), getLegacyLiveServerPath(cwd, options)]) {
    try {
      const info = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
      if (info && typeof info.pid === 'number' && !isLiveServerPidReachable(info.pid)) {
        try { fs.unlinkSync(filePath); } catch {}
        continue;
      }
      return { info, path: filePath };
    } catch {
      /* try next */
    }
  }
  return null;
}

export function isLiveServerPidReachable(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    // ESRCH means "no such process". EPERM means the process exists but this
    // user cannot signal it, so the live server info is still valid.
    return err?.code !== 'ESRCH';
  }
}

export function writeLiveServerInfo(cwd = process.cwd(), info, options = {}) {
  const filePath = getLiveServerPath(cwd, options);
  ensureVaultFileDir(filePath, resolveProjectRoot(cwd, options));
  fs.writeFileSync(filePath, JSON.stringify(info));
  return filePath;
}

export function removeLiveServerInfo(cwd = process.cwd(), options = {}) {
  for (const filePath of [getLiveServerPath(cwd, options), getLegacyLiveServerPath(cwd, options)]) {
    try { fs.unlinkSync(filePath); } catch {}
  }
}

/**
 * Session IDs become path segments (journals, snapshots, accept receipts,
 * preview manifests, generated component dirs). They arrive from CLI `--id`
 * arguments and HTTP payloads, so anything containing a separator or `..` must
 * be rejected before it reaches path.join, which would happily escape
 * `.asgard/.vanadis/engine2/live/`. Real IDs are 8 hex chars; the tests use short slugs.
 */
export function safeSessionId(id) {
  if (typeof id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(id)) {
    throw new Error('invalid session id: ' + id);
  }
  return id;
}

export function getLiveSessionsDir(cwd = process.cwd(), options = {}) {
  return path.join(getLiveDir(cwd, options), 'sessions');
}

export function getLegacyLiveSessionsDir(cwd = process.cwd(), options = {}) {
  return path.join(resolveProjectRoot(cwd, options), '.freyja2-live', 'sessions');
}

export function getLiveAnnotationsDir(cwd = process.cwd(), options = {}) {
  return path.join(getLiveDir(cwd, options), 'annotations');
}

export function getCritiqueDir(cwd = process.cwd(), options = {}) {
  return path.join(getVaultDir(cwd, options), CRITIQUE_DIR);
}

/** Every location the critique record may live, canonical first. */
export function getCritiqueDirCandidates(cwd = process.cwd(), options = {}) {
  return vaultCandidates(resolveProjectRoot(cwd, options), CRITIQUE_DIR);
}

export function getLegacyLiveAnnotationsDir(cwd = process.cwd(), options = {}) {
  return path.join(resolveProjectRoot(cwd, options), '.freyja2-live', 'annotations');
}

/** Ensure a vault subdirectory exists, for a given cwd. */
export function ensureVaultDirFor(dir, cwd = process.cwd(), options = {}) {
  return ensureVaultDir(dir, resolveProjectRoot(cwd, options));
}

/** Ensure a vault file's parent directory exists. */
export function ensureVaultFileDirFor(filePath, cwd = process.cwd(), options = {}) {
  return ensureVaultFileDir(filePath, resolveProjectRoot(cwd, options));
}

/** Resolve a vault-relative file for a given cwd, retired roots included. */
export function resolveVaultFileFor(rel, cwd = process.cwd(), options = {}) {
  return resolveVaultFile(resolveProjectRoot(cwd, options), ...(Array.isArray(rel) ? rel : [rel]));
}

/** Clear the run-scoped vault entries for a given cwd. */
export function sweepVaultFor(cwd = process.cwd(), options = {}) {
  return sweepVault(resolveProjectRoot(cwd, options));
}

/** Remove the vault outright for a given cwd. */
export function purgeVaultFor(cwd = process.cwd(), options = {}) {
  return purgeVault(resolveProjectRoot(cwd, options));
}

function firstExisting(paths) {
  return paths.find((filePath) => fs.existsSync(filePath)) || null;
}
