#!/usr/bin/env node
import { readdir } from "node:fs/promises";
import { basename, extname, join } from "node:path";
import exifr from "exifr";
import sharp from "sharp";

const dir = process.argv[2];
if (!dir) {
  console.error("usage: build-manifest.mjs <photos-directory>");
  process.exit(2);
}

const extensions = new Set([".jpg", ".jpeg", ".png", ".heic", ".webp"]);
const files = (await readdir(dir))
  .filter((file) => extensions.has(extname(file).toLowerCase()))
  .sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }));

const photos = [];
for (const file of files) {
  const path = join(dir, file);
  const metadata = await sharp(path).metadata();
  const exif = await exifr.parse(path, ["DateTimeOriginal"]).catch(() => null);
  const date = exif?.DateTimeOriginal ?? null;
  photos.push({
    src: path,
    width: metadata.width,
    height: metadata.height,
    caption: basename(file, extname(file)).replace(/^[\d\-_ ]+/, "").trim() || null,
    date: date ? new Date(date).toISOString() : null,
  });
}

photos.sort((a, b) => (a.date ?? "").localeCompare(b.date ?? ""));
process.stdout.write(JSON.stringify({ photos }, null, 2));
