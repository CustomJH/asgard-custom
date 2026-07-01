#!/usr/bin/env bash
# Asgard installer — curl entry point (CUS-108 Path B). Polished terminal UX; plain fallback non-tty.
#   curl -fsSL https://raw.githubusercontent.com/CustomJH/asgard-custom/main/install.sh | bash
#
# Bootstraps uv → a standalone CPython 3.14 → installs the `asgard` CLI as a uv tool. No system
# Python/Node/git-to-run needed (uv fetches everything). `asgard` lands on PATH via uv's tool bin.
# Env: ASGARD_VERSION (pin vX.Y.Z) · ASGARD_INSTALL_SPEC (override source) · NO_COLOR · ASGARD_NO_IMAGE
set -euo pipefail

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
VERSION_URL="${ASGARD_VERSION_URL:-https://raw.githubusercontent.com/CustomJH/asgard-custom/main/src/asgard/__init__.py}"

banner() {
  local v="$(_version)"
  printf '\n'
  if [ "$TTY" = 1 ] && [ "${ASGARD_NO_IMAGE:-0}" != 1 ] && _logo; then
    _ver_line "$v" 38
    printf '  %s· make anything, your way%s\n\n' "$D" "$X"
  else
    _logo_art     # universal mark + wordmark — renders in any terminal, any background
    _ver_line "$v" 68
    printf '  %s· make anything, your way%s\n\n' "$D" "$X"
  fi
}

# _version — best-effort asgard version for the splash: pinned env → local __init__.py (dev checkout)
# → __init__.py on main (curl|bash installs). Parses `__version__ = "X.Y.Z"`.
_version() {
  if [ -n "${ASGARD_VERSION:-}" ]; then printf '%s' "$ASGARD_VERSION"; return 0; fi
  if [ -n "${SRC_DIR:-}" ] && [ -f "$SRC_DIR/src/asgard/__init__.py" ]; then
    sed -n 's/.*__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$SRC_DIR/src/asgard/__init__.py" | head -1
    return 0
  fi
  curl -fsSL --max-time 5 "$VERSION_URL" 2>/dev/null \
    | sed -n 's/.*__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' | head -1 || true
}

# _ver_line <version> <width> — dim (vX.Y.Z), right-aligned to sit under the wordmark. No-op if empty.
_ver_line() {
  [ -n "$1" ] || return 0
  local tag="(v$1)" pad
  pad=$(( $2 - ${#tag} )); [ "$pad" -lt 2 ] && pad=2
  printf '%*s%s%s%s\n' "$pad" "" "$D" "$tag" "$X"
}

# _logo_art — universal fallback where inline images aren't supported: the Yggdrasil mark to the
# left of the ASGARD wordmark (horizontal lockup), both braille-rendered from the brand art so the
# real letterforms show. White; under NO_COLOR the tint is empty → terminal's default fg.
_logo_art() {
  printf '%s' "$W"
  cat <<'ART'
  ⠀⠀⠀⠀⢀⡤⣶⣶⣶⣲⠤⣀⠀⠀⠀⠀  ⠀⠀⠀⢰⡄⠀⠀⠀⠀⠀⢀⣤⣦⣄⡀⠀⠀⠀⠀⣠⣦⣀⠀⠀⠀⠀⠀⠀⣦⠀⠀⠀⠀⠰⣶⣶⣶⣦⡀⠀⠀⠐⣶⣦⣄⠀⠀⠀
  ⠀⠀⢀⣼⣽⣻⡟⣿⣷⢫⣟⣯⣧⡀⠀⠀  ⠀⠀⢀⣿⣷⠀⠀⠀⠀⢰⣿⠋⠈⠙⠁⠀⠀⣠⡾⠋⠈⠛⠀⠀⠀⠀⠀⣸⣿⡆⠀⠀⠀⠀⣿⡇⠀⠙⣷⡄⠀⠀⣿⡏⠻⣷⡄⠀
  ⠀⠀⣸⢽⣦⡷⣻⣻⡟⣟⢾⣴⣯⣧⠀⠀  ⠀⠀⣼⡏⢻⣇⠀⠀⠀⠈⠛⢷⣤⡀⠀⠀⢸⣿⠁⠀⠀⣀⣀⠀⠀⠀⢠⣿⠙⣿⡀⠀⠀⠀⣿⡇⣀⣴⠟⠀⠀⠀⣿⡇⠀⠈⢻⡆
  ⠀⠀⢻⠽⠇⠁⣸⢸⡇⣷⠈⠸⠯⡟⠀⠀  ⠀⢰⡿⢀⡈⣿⡄⠀⠀⠀⠀⠀⠙⢿⣦⠀⠘⢿⣄⠀⠀⢹⡏⠀⠀⠀⣾⠇⣀⢹⣧⠀⠀⠀⣿⡿⢻⣧⠀⠀⠀⠀⣿⡇⠀⣠⡿⠃
  ⠀⠀⠈⢳⣲⣶⡿⣾⣷⢿⣶⣖⡞⠁⠀⠀  ⢀⣿⠁⠻⠃⢸⣷⡀⠀⠰⣶⣤⣴⠿⠃⠀⠀⠀⠙⢷⣤⣼⡇⠀⠀⣸⡟⠘⠟⠁⢻⣆⠀⠀⣿⡇⠀⠹⣷⡀⠀⠀⣿⣧⡾⠋⠀⠀
  ⠀⠀⠀⠀⠈⠓⠻⠯⠵⠟⠚⠉⠀⠀⠀⠀  ⠉⠉⠁⠀⠀⠈⠉⠁⠀⠀⠀⠉⠁⠀⠀⠀⠀⠀⠀⠀⠉⠹⠃⠀⠈⠉⠉⠀⠀⠀⠉⠉⠁⠈⠉⠉⠀⠀⠈⠉⠀⠈⠉⠉⠀⠀⠀⠀
  ─────────────────────────────── ◇ ────────────────────────────────
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

# ── install (CUS-108 Path B): uv-managed. Bootstrap uv → standalone CPython 3.14 → `uv tool install`.
# The `asgard` command lands on PATH via uv's tool bin (uv tool update-shell wires the shell rc).
# Wrapped in main() so a truncated `curl | bash` stream can't execute a partial script.
SPEC="${ASGARD_INSTALL_SPEC:-git+https://github.com/CustomJH/asgard-custom.git}"
[ -n "${ASGARD_VERSION:-}" ] && SPEC="${SPEC}@v${ASGARD_VERSION}"

main() {
  SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
  banner

  # 1) uv — installs a standalone CPython, so no system Python is required.
  if ! command -v uv >/dev/null 2>&1; then
    ( curl -LsSf https://astral.sh/uv/install.sh | sh ) >/dev/null 2>&1 \
      || die "uv install failed. Manual: https://astral.sh/uv"
    export PATH="$HOME/.local/bin:$PATH"
  fi
  command -v uv >/dev/null 2>&1 || die "uv not on PATH — add ~/.local/bin and re-run."
  ok "uv ${D}$(uv --version 2>/dev/null | awk '{print $2}')${X}"

  # 2) CPython 3.14 (managed by uv).
  uv python install 3.14 >/dev/null 2>&1 || warn "Python 3.14 pre-install skipped (uv fetches on demand)."
  ok "python ${D}3.14${X}"

  # 3) asgard as a uv tool — from a local checkout when present, else the git repo.
  FROM="$SPEC"
  [ -n "${SRC_DIR:-}" ] && [ -f "$SRC_DIR/pyproject.toml" ] && FROM="$SRC_DIR"
  ( uv tool install --force --python 3.14 "$FROM" ) >/dev/null 2>&1 & spinner=$!
  wait $spinner || die "install failed: $FROM"
  uv tool update-shell >/dev/null 2>&1 || true
  export PATH="$HOME/.local/bin:$PATH"
  VERSION="$(asgard --version 2>/dev/null || echo '?')"
  ok "asgard ${B}v${VERSION}${X}  ${D}(uv tool)${X}"

  # summary
  printf '\n  %s✔ installed%s — next:\n' "$G" "$X"
  printf '    %sasgard doctor%s   %s# verify%s\n' "$B" "$X" "$D" "$X"
  printf '    %sasgard --help%s\n' "$B" "$X"
  command -v asgard >/dev/null 2>&1 || printf '    %s↳ restart shell (or run: uv tool update-shell) first%s\n' "$D" "$X"
  printf '\n'
}

main "$@"
