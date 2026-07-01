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
  TTY=1; B=$'\033[1m'; D=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; M=$'\033[35m'; W=$'\033[97m'; X=$'\033[0m'
else
  TTY=0; B=; D=; G=; Y=; R=; C=; M=; W=; X=
fi

ok()   { printf '  %s✔%s %s\n' "$G" "$X" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$X" "$*"; }
die()  { printf '\n  %s✗%s %s\n\n' "$R" "$X" "$*" >&2; exit 1; }

# LOGO — brand lockup. Rendered as a real inline image on graphics-capable terminals
# (kitty/Ghostty/WezTerm, iTerm2); rune wordmark elsewhere. ASGARD_NO_IMAGE=1 forces runes.
LOGO_URL="${ASGARD_LOGO_URL:-https://raw.githubusercontent.com/CustomJH/asgard-custom/main/assets/individual/15-white-lockup.png}"
VERSION_URL="${ASGARD_VERSION_URL:-https://raw.githubusercontent.com/CustomJH/asgard-custom/main/package.json}"

banner() {
  local v="$(_version)"
  printf '\n'
  if [ "$TTY" = 1 ] && [ "${ASGARD_NO_IMAGE:-0}" != 1 ] && _logo; then
    _ver_line "$v" 38
    printf '  %s· make anything, your way%s\n\n' "$D" "$X"
  else
    _logo_art     # universal mark + wordmark — renders in any terminal, any background
    _ver_line "$v" 58
    printf '%*s%s· make anything, your way%s\n\n' 18 "" "$D" "$X"
  fi
}

# _version — best-effort asgard version for the splash, auto-tracking the current release:
# pinned env → local package.json (dev checkout) → package.json on main (curl|bash installs).
_version() {
  if [ -n "${ASGARD_VERSION:-}" ]; then printf '%s' "$ASGARD_VERSION"; return 0; fi
  if [ -n "${SRC_DIR:-}" ] && [ -f "$SRC_DIR/package.json" ]; then
    sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$SRC_DIR/package.json" | head -1
    return 0
  fi
  curl -fsSL --max-time 5 "$VERSION_URL" 2>/dev/null \
    | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1 || true
}

# _ver_line <version> <width> — dim (vX.Y.Z), right-aligned to sit under the wordmark. No-op if empty.
_ver_line() {
  [ -n "$1" ] || return 0
  local tag="(v$1)" pad
  pad=$(( $2 - ${#tag} )); [ "$pad" -lt 2 ] && pad=2
  printf '%*s%s%s%s\n' "$pad" "" "$D" "$tag" "$X"
}

# _logo_art — universal fallback where inline images aren't supported: the Yggdrasil mark +
# the ASGARD wordmark, both braille-rendered from the brand art (real letterforms) + a divider,
# in white. Under NO_COLOR the tint is empty → terminal's default fg.
_logo_art() {
  printf '%s' "$W"
  cat <<'ART'
                        ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
                        ⠀⠀⢀⣴⣿⣿⣿⣿⣶⡀⠀⠀
                        ⠀⢀⣿⣿⣿⣾⣷⡿⣿⣿⡄⠀
                        ⠀⠘⡞⠃⢸⣿⣷⡇⠘⢻⠃⠀
                        ⠀⠀⠈⠻⣿⣿⣯⣿⠿⠃⠀⠀
                        ⠀⠀⠀⠀⠀⠈⠁⠀⠀⠀⠀⠀
  ⠀⠀⠀⠀⣴⠀⠀⠀⠀⠀⠀⠀⢀⣤⣶⣤⡀⠀⠀⠀⠀⠀⣠⣶⣄⡀⠀⠀⠀⠀⠀⠀⢠⣆⠀⠀⠀⠀⠀⠲⣶⣶⣶⣦⡀⠀⠀⠀⠰⣶⣶⣄⡀⠀⠀⠀
  ⠀⠀⠀⣼⣿⣧⠀⠀⠀⠀⠀⣴⣿⠋⠀⠙⠋⠀⠀⠀⣠⣾⠟⠉⠙⠋⠀⠀⠀⠀⠀⢀⣾⣿⡆⠀⠀⠀⠀⠀⣿⡇⠀⠈⢻⣦⠀⠀⠀⢸⡏⠙⢿⣦⡀⠀
  ⠀⠀⢰⣿⠉⣿⣆⠀⠀⠀⠀⠈⠻⢷⣦⡀⠀⠀⠀⢸⣿⠁⠀⠀⢀⣀⣀⠀⠀⠀⠀⣼⡟⠹⣿⡄⠀⠀⠀⠀⣿⡇⢀⣴⡿⠋⠀⠀⠀⢸⡇⠀⠀⠙⣿⡆
  ⠀⢠⣿⠃⣀⠘⣿⡄⠀⠀⠀⠀⠀⠀⠙⠻⣷⡄⠀⠘⢿⣤⡀⠀⠈⣿⡏⠀⠀⠀⣸⡿⢁⡀⢹⣷⠀⠀⠀⠀⣿⡿⠻⣿⡀⠀⠀⠀⠀⢸⡇⠀⢀⣴⡿⠁
  ⢀⣾⡏⠘⠿⠃⢹⣿⡀⠀⠀⢶⣦⣤⣴⡿⠋⠀⠀⠀⠀⠙⢿⣦⣤⣿⡇⠀⠀⣰⣿⠃⠙⠟⠀⢻⣧⠀⠀⢀⣿⡇⠀⠙⢿⣆⠀⠀⠀⣸⣧⣴⠟⠋⠀⠀
  ⠉⠉⠉⠀⠀⠀⠈⠉⠉⠀⠀⠀⠈⠉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠉⠉⠟⠁⠀⠈⠉⠉⠁⠀⠀⠀⠉⠉⠁⠀⠉⠉⠉⠀⠀⠀⠉⠁⠀⠈⠉⠉⠁⠀⠀⠀⠀
  ────────────────────────── ◇ ──────────────────────────
ART
  printf '%s' "$X"
}

# _logo — emit the lockup PNG via a terminal graphics protocol. Returns nonzero (→ rune fallback)
# on any miss: unknown terminal, no base64, fetch fail. Prefers a local asset over the network.
_logo() {
  command -v base64 >/dev/null 2>&1 || return 1
  local proto=""
  case "${TERM_PROGRAM:-}" in
    iTerm.app|WezTerm) proto=iterm ;;
    kitty|ghostty|Ghostty) proto=kitty ;;
  esac
  case "${TERM:-}" in *kitty*|*ghostty*) proto=kitty ;; esac
  [ -n "${KITTY_WINDOW_ID:-}" ] && proto=kitty
  [ -n "${GHOSTTY_RESOURCES_DIR:-}" ] && proto=kitty
  [ "${LC_TERMINAL:-}" = iTerm2 ] && proto=iterm
  [ -n "$proto" ] || return 1

  local f own=0
  if [ -n "${SRC_DIR:-}" ] && [ -f "$SRC_DIR/assets/individual/15-white-lockup.png" ]; then
    f="$SRC_DIR/assets/individual/15-white-lockup.png"
  else
    f="$(mktemp 2>/dev/null)" || return 1; own=1
    curl -fsSL --max-time 10 -o "$f" "$LOGO_URL" 2>/dev/null && [ -s "$f" ] || { rm -f "$f"; return 1; }
  fi

  local b64; b64="$(base64 < "$f" | tr -d '\n')"
  printf '  '
  if [ "$proto" = iterm ]; then
    printf '\033]1337;File=inline=1;width=36;preserveAspectRatio=1:%s\a\n' "$b64"
  else
    # kitty graphics: PNG (f=100), transmit+display (a=T), 36 cols wide; base64 in ≤4096-char chunks
    local len=${#b64} off=0 first=1 more piece
    while [ "$off" -lt "$len" ]; do
      piece="${b64:off:4096}"; off=$((off + 4096))
      [ "$off" -lt "$len" ] && more=1 || more=0
      if [ "$first" = 1 ]; then printf '\033_Gf=100,a=T,c=36,m=%d;%s\033\\' "$more" "$piece"; first=0
      else printf '\033_Gm=%d;%s\033\\' "$more" "$piece"; fi
    done
    printf '\n'
  fi
  [ "$own" = 1 ] && rm -f "$f"
  return 0
}

# spin <pid> <label> — braille spinner while pid runs (tty); one plain line otherwise.
# Frames live in an ARRAY: ${fr[i]} yields a whole glyph. A byte-substring (${s:i:1})
# would slice one byte out of a 3-byte braille char under a C/POSIX locale → garbled ''.
spin() {
  local pid=$1 label=$2 rc i=0
  local fr=(⣾ ⣽ ⣻ ⢿ ⡿ ⣟ ⣯ ⣷)
  if [ "$TTY" != 1 ]; then
    printf '  %s→%s %s\n' "$C" "$X" "$label"
    wait "$pid"; return $?
  fi
  while kill -0 "$pid" 2>/dev/null; do
    printf '\r  %s%s%s %s' "$C" "${fr[i]}" "$X" "$label"
    i=$(( (i + 1) % ${#fr[@]} ))
    sleep 0.08
  done
  wait "$pid"; rc=$?
  printf '\r\033[K'
  return "$rc"
}

# download <url> <dest> <label> — fetch to dest with a live spinner + percentage (tty);
# one plain line on non-tty. Percentage needs Content-Length; without it, spinner only.
# Always call as `download ... || die` so set -e is ignored inside (lets us capture wait's rc).
download() {
  local url=$1 dest=$2 label=$3 total sz pct rc pid i=0
  local fr=(⣾ ⣽ ⣻ ⢿ ⡿ ⣟ ⣯ ⣷)
  total="$(curl -fsSLI --max-time 15 "$url" 2>/dev/null | awk 'BEGIN{IGNORECASE=1}/^content-length:/{v=$2} END{gsub(/\r/,"",v);print v}' || true)"
  curl -fsSL -o "$dest" "$url" & pid=$!
  if [ "$TTY" != 1 ]; then
    printf '  %s→%s %s\n' "$C" "$X" "$label"
    wait "$pid"; return $?
  fi
  while kill -0 "$pid" 2>/dev/null; do
    if [ -n "$total" ] && [ "$total" -gt 0 ] 2>/dev/null; then
      sz=$(stat -f%z "$dest" 2>/dev/null || stat -c%s "$dest" 2>/dev/null || echo 0)
      pct=$(( sz * 100 / total )); [ "$pct" -gt 100 ] && pct=100
      printf '\r  %s%s%s %s  %s%3d%%%s' "$C" "${fr[i]}" "$X" "$label" "$B" "$pct" "$X"
    else
      printf '\r  %s%s%s %s' "$C" "${fr[i]}" "$X" "$label"
    fi
    i=$(( (i + 1) % ${#fr[@]} ))
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

# SRC_DIR resolved before the banner so a source checkout can render the local logo asset.
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
banner
mkdir -p "$ASGARD_HOME/bin" "$BIN_DIR"

# obtain the self-contained binary (precedence: explicit URL → local build → release download)
if [ -n "$DL" ]; then
  download "$DL" "$DEST" "fetching binary" || die "download failed: $DL"
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
  download "$url" "$DEST" "downloading $asset" || die "download failed: $url"
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
