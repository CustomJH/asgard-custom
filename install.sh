#!/usr/bin/env bash
# Asgard installer — curl entry point. Polished terminal UX; plain fallback when non-tty.
#   curl -fsSL https://raw.githubusercontent.com/CustomJH/asgard-custom/main/install.sh | bash
#
# Installs a self-contained `asgard` binary (bun build --compile): no Node/Bun/git needed to RUN.
# Node >= 24 is recommended for the full system (Claude Code hooks, later) — NOT required by the CLI.
#
# Binary source (precedence):
#   1) ASGARD_DOWNLOAD_URL          exact binary URL, used as-is (e.g. file:// for tests)
#   2) source checkout + bun         build locally (dev convenience)
#   3) ASGARD_RELEASE_BASE/<asset>   download the prebuilt release asset for this OS/arch
# Env: ASGARD_HOME(~/.asgard) · BIN_DIR(~/.local/bin) · ASGARD_DOWNLOAD_URL · ASGARD_RELEASE_BASE · NO_COLOR
set -euo pipefail

ASGARD_HOME="${ASGARD_HOME:-$HOME/.asgard}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
DEST="$ASGARD_HOME/bin/asgard"
DL="${ASGARD_DOWNLOAD_URL:-}"
RELEASE_BASE="${ASGARD_RELEASE_BASE:-https://github.com/CustomJH/asgard-custom/releases/latest/download}"

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
  printf '  %sASGARD%s %s· make anything, your way%s\n\n' "$B" "$X" "$D" "$X"
}

# spin <pid> <label> — braille spinner while pid runs (tty); one plain line otherwise.
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

# detect_asset — release asset name for this OS/arch (must match scripts/release-build.sh).
detect_asset() {
  local os arch
  case "$(uname -s)" in
    Darwin) os=darwin ;;
    Linux) os=linux ;;
    *) die "unsupported OS for install.sh: $(uname -s). Windows → install.ps1 (planned)." ;;
  esac
  case "$(uname -m)" in
    x86_64 | amd64) arch=x64 ;;
    arm64 | aarch64) arch=arm64 ;;
    *) die "unsupported arch: $(uname -m)." ;;
  esac
  printf 'asgard-%s-%s' "$os" "$arch"
}

banner
mkdir -p "$ASGARD_HOME/bin" "$BIN_DIR"

# obtain the self-contained binary (precedence: explicit URL → local build → release download)
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$DL" ]; then
  ( curl -fsSL -o "$DEST" "$DL" ) & spin $! "fetching binary" || die "download failed: $DL"
  chmod +x "$DEST"
elif [ -n "${SRC_DIR:-}" ] && [ -f "$SRC_DIR/src/cli.ts" ] && command -v bun >/dev/null 2>&1; then
  ( cd "$SRC_DIR" && bun build src/cli.ts --compile --outfile "$DEST" >/dev/null 2>&1 ) & spin $! "building binary (bun --compile)" || die "build failed."
else
  asset="$(detect_asset)"
  if [ -n "${ASGARD_VERSION:-}" ]; then
    url="https://github.com/CustomJH/asgard-custom/releases/download/v${ASGARD_VERSION}/$asset"   # pin a version
  else
    url="$RELEASE_BASE/$asset"
  fi
  ( curl -fsSL -o "$DEST" "$url" ) & spin $! "downloading $asset" || die "download failed: $url"
  chmod +x "$DEST"
fi
[ -x "$DEST" ] || die "binary missing at $DEST."
VERSION="$("$DEST" --version 2>/dev/null || echo 0.0.0)"
ok "asgard ${B}v$VERSION${X}  ${D}$DEST${X}"

# link onto PATH
ln -sfn "$DEST" "$BIN_DIR/asgard"
ok "linked  ${D}$BIN_DIR/asgard${X}"

# PATH: if BIN_DIR isn't on PATH, add a guarded block to the shell rc (removed by `asgard uninstall`).
# Skip with ASGARD_NO_RC=1 (used by tests / when you manage PATH yourself).
on_path=0; case ":$PATH:" in *":$BIN_DIR:"*) on_path=1 ;; esac
if [ "$on_path" != 1 ]; then
  rc=""
  case "$(basename "${SHELL:-}")" in zsh) rc="$HOME/.zshrc" ;; bash) rc="$HOME/.bashrc" ;; esac
  if [ "${ASGARD_NO_RC:-0}" = 1 ] || [ -z "$rc" ]; then
    warn "not on PATH — add:  ${C}export PATH=\"$BIN_DIR:\$PATH\"${X}"
  elif grep -q '>>> asgard >>>' "$rc" 2>/dev/null; then
    ok "PATH already managed in ${D}$rc${X}"
  else
    [ -e "$rc" ] || touch "$rc"
    printf '\n# >>> asgard >>>\nexport PATH="%s:$PATH"\n# <<< asgard <<<\n' "$BIN_DIR" >> "$rc"
    ok "PATH added → ${D}$rc${X}  ${D}(removed by: asgard uninstall)${X}"
  fi
fi

# Node >= 24 advisory (recommended floor; not a gate — the binary runs without it)
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
