#!/usr/bin/env node
// critique_store — 3D 판정 스냅샷의 저장·회귀. 엔진 2(critique-storage)의 규약을 3D 금고로 이식했다.
// 스냅샷은 .asgard/.vanadis/3d/critique/<타임스탬프>__<슬러그>.md 에 쌓이고, 대상당 최근 5개만 남는다.
// 슬러그는 해석된 산출물 경로(파일·URL)에서 기계적으로 만든다 — 자연어 표현을 슬러그로 만들지 않는다.
// 사용: node critique_store.mjs slug <대상>
//       FREYJA3D_CRITIQUE_META='{"total_score":N,...}' node critique_store.mjs write <대상> <본문파일>
//       node critique_store.mjs latest <대상>          # 없으면 종료 코드 2
//       node critique_store.mjs trend <대상> [개수]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const SLUG_MAX = 50;
/** 대상당 보존 스냅샷 수 — 추세가 5개를 읽고, 그 이상은 아무도 읽지 않는다. */
export const SNAPSHOT_RETENTION = 5;

export function critiqueDir(cwd = process.cwd()) {
  return path.join(cwd, ".asgard", ".vanadis", "3d", "critique");
}

export function kebab(value) {
  const slug = String(value || "")
    .toLowerCase()
    .replace(/[/\\.]+/g, "-")
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  if (!slug) return null;
  return slug.length <= SLUG_MAX ? slug : slug.slice(slug.length - SLUG_MAX).replace(/^-/, "");
}

/** 해석된 경로·URL 하나에서 클론 간 안정적인 슬러그를 만든다. 루트·빈 입력은 null. */
export function slugFromTarget(resolved, { cwd = process.cwd() } = {}) {
  if (!resolved || typeof resolved !== "string") return null;
  const trimmed = resolved.trim();
  if (!trimmed) return null;
  if (/^https?:\/\//i.test(trimmed)) {
    let url;
    try {
      url = new URL(trimmed);
    } catch {
      return null;
    }
    return kebab(`${url.hostname}${url.pathname}`);
  }
  const abs = path.isAbsolute(trimmed) ? trimmed : path.resolve(cwd, trimmed);
  let rel = path.relative(cwd, abs);
  if (rel.startsWith("..") || path.isAbsolute(rel)) rel = path.basename(abs);
  if (!rel || rel === ".") return null;
  return kebab(rel);
}

/** 파일명에 쓸 수 있는 UTC 타임스탬프 — 콜론은 Windows 파일계에서 금지 문자다. */
export function nowFilenameStamp(date = new Date()) {
  return date.toISOString().replace(/[:.]/g, "-").replace(/-\d+Z$/, "Z");
}

function serializeFrontmatter(obj) {
  const lines = ["---"];
  for (const [key, value] of Object.entries(obj)) {
    if (value === undefined || value === null) continue;
    const str = typeof value === "string" ? value : String(value);
    const needsQuotes = typeof value === "string" && /[:#]/.test(str);
    lines.push(`${key}: ${needsQuotes ? JSON.stringify(str) : str}`);
  }
  lines.push("---");
  return lines.join("\n");
}

function parseFrontmatter(text) {
  const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!match) return {};
  const out = {};
  for (const line of match[1].split(/\r?\n/)) {
    const colon = line.indexOf(":");
    if (colon < 0) continue;
    const key = line.slice(0, colon).trim();
    let value = line.slice(colon + 1).trim();
    if (/^".*"$/.test(value)) {
      try {
        value = JSON.parse(value);
      } catch {
        /* 따옴표째 남긴다 */
      }
    } else if (/^-?\d+$/.test(value)) {
      value = Number(value);
    }
    out[key] = value;
  }
  return out;
}

function listSnapshotsForSlug(slug, cwd) {
  const dir = critiqueDir(cwd);
  if (!fs.existsSync(dir)) return [];
  const suffix = `__${slug}.md`;
  return fs
    .readdirSync(dir)
    .filter((file) => file.endsWith(suffix))
    .sort()
    .map((file) => path.join(dir, file));
}

/** 보존 수를 넘는 오래된 스냅샷을 지운다 — 추가하는 유일한 자리에서 바로 묶는다. */
export function pruneSnapshots(slug, cwd = process.cwd()) {
  const all = listSnapshotsForSlug(slug, cwd);
  const stale = all.slice(0, Math.max(0, all.length - SNAPSHOT_RETENTION));
  const removed = [];
  for (const filePath of stale) {
    try {
      fs.unlinkSync(filePath);
      removed.push(filePath);
    } catch {
      /* 잠긴 파일은 다음 실행의 몫 */
    }
  }
  return removed;
}

/** 스냅샷을 쓰고 절대 경로를 돌려준다. timestamp·slug 는 내부 계산값이 항상 이긴다. */
export function writeSnapshot({ slug, meta = {}, body, cwd = process.cwd(), now = new Date() }) {
  if (!slug) throw new Error("writeSnapshot 은 슬러그가 필요하다");
  const dir = critiqueDir(cwd);
  fs.mkdirSync(dir, { recursive: true });
  const timestamp = nowFilenameStamp(now);
  const filePath = path.join(dir, `${timestamp}__${slug}.md`);
  const front = serializeFrontmatter({ ...meta, timestamp, slug });
  fs.writeFileSync(filePath, `${front}\n${String(body).trim()}\n`, "utf-8");
  pruneSnapshots(slug, cwd);
  return filePath;
}

export function readLatestSnapshot(slug, { cwd = process.cwd() } = {}) {
  const all = listSnapshotsForSlug(slug, cwd);
  if (!all.length) return null;
  const latest = all[all.length - 1];
  const body = fs.readFileSync(latest, "utf-8");
  return { path: latest, body, meta: parseFrontmatter(body) };
}

export function readTrend(slug, { limit = 5, cwd = process.cwd() } = {}) {
  return listSnapshotsForSlug(slug, cwd)
    .slice(-limit)
    .map((file) => parseFrontmatter(fs.readFileSync(file, "utf-8")));
}

// ---- CLI ---------------------------------------------------------------

// 슬러그와 대상(경로·URL)을 어디서나 함께 받는다 — 호출자가 slug 단계를 따로 돌 필요가 없다.
function coerceSlug(value) {
  if (!value) return null;
  if (/^[a-z0-9-]+$/.test(value) && !value.includes("/")) return value;
  return slugFromTarget(value);
}

function main(argv) {
  const [cmd, ...args] = argv;
  switch (cmd) {
    case "slug": {
      const slug = slugFromTarget(args[0]);
      if (!slug) {
        process.stderr.write("안정적인 슬러그를 만들 수 없는 입력이다\n");
        process.exit(1);
      }
      process.stdout.write(`${slug}\n`);
      return;
    }
    case "write": {
      const [slugArg, bodyFile] = args;
      const slug = coerceSlug(slugArg);
      if (!slug || !bodyFile) {
        process.stderr.write("사용법: write <슬러그|대상> <본문파일>\n");
        process.exit(1);
      }
      let meta = {};
      const metaArg = process.env.FREYJA3D_CRITIQUE_META;
      if (metaArg) {
        try {
          meta = JSON.parse(metaArg);
        } catch {
          /* 깨진 메타는 버리고 본문만 남긴다 */
        }
      }
      const out = writeSnapshot({ slug, meta, body: fs.readFileSync(bodyFile, "utf-8") });
      process.stdout.write(`${out}\n`);
      return;
    }
    case "latest": {
      const latest = readLatestSnapshot(coerceSlug(args[0]));
      if (!latest) process.exit(2);
      process.stdout.write(latest.body);
      return;
    }
    case "trend": {
      const rows = readTrend(coerceSlug(args[0]), { limit: args[1] ? Number(args[1]) : 5 });
      process.stdout.write(`${JSON.stringify(rows, null, 2)}\n`);
      return;
    }
    default:
      process.stderr.write("사용법: critique_store.mjs <slug|write|latest|trend> [인자]\n");
      process.exit(1);
  }
}

function isMainModule() {
  if (!process.argv[1]) return false;
  try {
    return fs.realpathSync(fileURLToPath(import.meta.url)) === fs.realpathSync(process.argv[1]);
  } catch {
    return import.meta.url === pathToFileURL(process.argv[1]).href;
  }
}

// 심링크로 실행돼도 조용한 no-op 이 되지 않게 정규화 경로로 비교한다.
if (isMainModule()) {
  main(process.argv.slice(2));
}
