#!/usr/bin/env bash
# Asgard installer — curl entry point. Polished terminal UX; plain fallback when non-tty.
#   curl -fsSL <raw-url>/install.sh | bash
#
# Installs a self-contained `asgard` binary (bun build --compile): no Node/Bun/git needed to RUN.
# Node >= 24 is recommended for the full system (Claude Code hooks, later) — NOT required by the CLI.
#
# Binary source: ASGARD_DOWNLOAD_URL (prebuilt release) else local build (needs bun + source checkout).
# Env: ASGARD_HOME(~/.asgard) · BIN_DIR(~/.local/bin) · ASGARD_DOWNLOAD_URL · NO_COLOR
set -euo pipefail

ASGARD_HOME="${ASGARD_HOME:-$HOME/.asgard}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
DEST="$ASGARD_HOME/bin/asgard"
DL="${ASGARD_DOWNLOAD_URL:-}"

# ── palette — disabled when stdout is not a tty or NO_COLOR is set ─────────────
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  TTY=1; B=$'\033[1m'; D=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; M=$'\033[35m'; X=$'\033[0m'
else
  TTY=0; B=; D=; G=; Y=; R=; C=; M=; X=
fi

ok()   { printf '  %s✔%s %s\n' "$G" "$X" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$X" "$*"; }
die()  { printf '\n  %s✗%s %s\n\n' "$R" "$X" "$*" >&2; exit 1; }

banner() {
  printf '\n  %s%sᚨ  ᛋ  ᚷ  ᚨ  ᚱ  ᛞ%s\n' "$B" "$M" "$X"
  printf '  %sASGARD%s %s· Claude Code harness%s\n\n' "$B" "$X" "$D" "$X"
}

# spin <pid> <label> — braille spinner while pid runs (tty); one plain line otherwise.
# returns the awaited pid's exit code.
spin() {
  local pid=$1 label=$2 fr='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏' i=0 rc
  if [ "$TTY" != 1 ]; then
    printf '  %s∴%s %s\n' "$C" "$X" "$label"
    wait "$pid"; return $?
  fi
  while kill -0 "$pid" 2>/dev/null; do
    i=$(( (i + 1) % ${#fr} ))
    printf '\r  %s%s%s %s' "$C" "${fr:$i:1}" "$X" "$label"
    sleep 0.08
  done
  wait "$pid"; rc=$?
  printf '\r\033[K'
  return "$rc"
}

banner
mkdir -p "$ASGARD_HOME/bin" "$BIN_DIR"

# 1. obtain the self-contained binary
if [ -n "$DL" ]; then
  ( curl -fsSL -o "$DEST" "$DL" ) & spin $! "fetching binary" || die "download failed: $DL"
  chmod +x "$DEST"
else
  SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
  [ -f "$SRC_DIR/src/cli.ts" ] || die "no ASGARD_DOWNLOAD_URL set and no source checkout here. Point ASGARD_DOWNLOAD_URL at a release binary."
  command -v bun >/dev/null 2>&1 || die "local build needs bun → curl -fsSL https://bun.sh/install | bash , then re-run (or set ASGARD_DOWNLOAD_URL)."
  ( cd "$SRC_DIR" && bun build src/cli.ts --compile --outfile "$DEST" >/dev/null 2>&1 ) & spin $! "building binary (bun --compile)" || die "build failed."
fi
[ -x "$DEST" ] || die "binary missing at $DEST."
VERSION="$("$DEST" --version 2>/dev/null || echo 0.0.0)"
ok "asgard ${B}v$VERSION${X}  ${D}$DEST${X}"

# 2. link onto PATH
ln -sfn "$DEST" "$BIN_DIR/asgard"
ok "linked  ${D}$BIN_DIR/asgard${X}"
on_path=0; case ":$PATH:" in *":$BIN_DIR:"*) on_path=1 ;; esac
[ "$on_path" = 1 ] || warn "not on PATH yet — add:  ${C}export PATH=\"$BIN_DIR:\$PATH\"${X}"

# 3. Node >= 24 advisory (recommended floor; not a gate — the binary runs without it)
if command -v node >/dev/null 2>&1 && [ "$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)" -ge 24 ]; then
  ok "node $(node -v)  ${D}recommended floor met${X}"
else
  warn "Node ≥ 24 recommended for Claude Code hooks (later); not needed to run asgard."
fi

# summary
printf '\n  %s✔ installed%s — next:\n' "$G" "$X"
printf '    %sasgard doctor%s   %s# verify%s\n' "$B" "$X" "$D" "$X"
printf '    %sasgard --help%s\n' "$B" "$X"
[ "$on_path" = 1 ] || printf '    %s↳ restart shell (or add %s to PATH) first%s\n' "$D" "$BIN_DIR" "$X"
printf '\n'
