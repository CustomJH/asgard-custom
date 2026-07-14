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
info() { printf '  %s·%s %s\n' "$D" "$X" "$*"; }
die()  { printf '\n  %s✗%s %s\n\n' "$R" "$X" "$*" >&2; exit 1; }

# phase <title> — numbered section header ([n/N]) so the install reads as ordered steps to the user.
STEP=0; STEPS=3
phase() { STEP=$((STEP + 1)); printf '\n  %s%s[%d/%d]%s %s%s%s\n' "$B" "$C" "$STEP" "$STEPS" "$X" "$B" "$1" "$X"; }

# spin <label> <cmd…> — run cmd in the background, animate a braille spinner beside <label>, return
# cmd's exit code. Non-tty: run silently, no animation. The spinner line is cleared when cmd finishes
# (callers print their own ✔). Braille via a bash array (${fr[i]}) — slicing a multibyte glyph garbles.
spin() {
  local label="$1"; shift
  if [ "$TTY" != 1 ]; then "$@" >/dev/null 2>&1; return $?; fi
  "$@" >/dev/null 2>&1 & local pid=$! rc=0
  local fr=(⣾ ⣽ ⣻ ⢿ ⡿ ⣟ ⣯ ⣷) i=0
  while kill -0 "$pid" 2>/dev/null; do
    printf '\r  %s%s%s %s' "$C" "${fr[i]}" "$X" "$label"
    i=$(( (i + 1) % 8 )); sleep 0.08
  done
  wait "$pid" || rc=$?
  printf '\r\033[K'
  return $rc
}

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
  # 다크 배경은 흰색($W), 라이트 배경은 진한 청록 — 흰 룬은 밝은 배경서 안 보인다. NO_COLOR 면 무틴트.
  local tint="$W"
  if [ -n "$W" ] && [[ "${COLORFGBG:-}" =~ \;([789]|1[0-5])$ ]]; then tint=$'\033[38;5;30m'; fi
  printf '%s' "$tint"
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
  # 라이트 배경엔 흰 lockup 이 안 보인다 → 이미지 스킵, 룬(braille) 폴백. COLORFGBG='fg;bg' 의 bg 7~15.
  if [[ "${COLORFGBG:-}" =~ \;([789]|1[0-5])$ ]]; then return 1; fi
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
REPO_SLUG="CustomJH/asgard-custom"

# pkg_install <pkg…> — install OS packages via whatever manager the host has (CUS-112). Uses sudo
# when not root and sudo exists. Returns nonzero if no known manager or the install fails — caller
# decides whether that's fatal. Runs cleanly inside spin's background subshell (inherits functions).
pkg_install() {
  local sudo=""; [ "$(id -u 2>/dev/null)" = 0 ] || { command -v sudo >/dev/null 2>&1 && sudo="sudo"; }
  if   command -v apt-get >/dev/null 2>&1; then $sudo apt-get update -qq && $sudo apt-get install -y -qq "$@"
  elif command -v dnf     >/dev/null 2>&1; then $sudo dnf install -y -q "$@"
  elif command -v yum     >/dev/null 2>&1; then $sudo yum install -y -q "$@"
  elif command -v pacman  >/dev/null 2>&1; then $sudo pacman -Sy --noconfirm "$@"  # -Sy (not -Syu): only refresh, add pkg
  elif command -v apk     >/dev/null 2>&1; then $sudo apk add --no-cache "$@"
  elif command -v zypper  >/dev/null 2>&1; then $sudo zypper -q install -y "$@"
  elif command -v brew    >/dev/null 2>&1; then brew install "$@"
  else return 1; fi
}

# ensure_curl — curl is the one hard dependency (fetches uv, and optionally the logo, over https).
# Minimal hosts may lack it; provision it per-OS instead of dead-ending. Best-effort → the caller
# fails with a manual instruction if this can't recover, never bricks the session.
ensure_curl() {
  command -v curl >/dev/null 2>&1 && return 0
  info "curl ${D}absent — provisioning per-OS${X}"
  spin "installing curl…" pkg_install curl ca-certificates \
    || spin "installing curl…" pkg_install curl || true   # ca-certificates pkg name varies; curl alone as fallback
  command -v curl >/dev/null 2>&1
}

# bootstrap_uv — install uv the way that fits the host, so a missing runtime self-heals per-OS.
# Astral's script covers Linux + macOS; if curl|sh is blocked, fall back to Homebrew (macOS) or pip.
bootstrap_uv() {
  spin "bootstrapping uv…" bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' && return 0
  case "$(uname -s 2>/dev/null)" in
    Darwin) command -v brew >/dev/null 2>&1 && spin "uv via Homebrew…" brew install uv && return 0 ;;
  esac
  command -v pip3 >/dev/null 2>&1 && spin "uv via pip…" pip3 install --user uv && return 0
  return 1
}

# latest_version — newest published release tag (vX.Y.Z → X.Y.Z) via the /releases/latest redirect.
# No API token, no git. Used to resolve the wheel to install when ASGARD_VERSION isn't pinned.
latest_version() {
  curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$REPO_SLUG/releases/latest" 2>/dev/null \
    | sed -n 's#.*/tag/v\([0-9][0-9.]*\).*#\1#p'
}

# resolve_install_source — decide where `uv tool install` pulls asgard from; sets globals FROM and
# INSTALL_SRC_DESC (must not run in a subshell — command substitution would lose the assignments).
# Priority:
#   1) local checkout (dev / sandbox) — pyproject.toml next to this script
#   2) ASGARD_INSTALL_SPEC override (any uv-installable spec)
#   3) release wheel by version — pure-python, needs NO git or compiler on the host (the default)
FROM=""; INSTALL_SRC_DESC=""
resolve_install_source() {
  if [ -n "${SRC_DIR:-}" ] && [ -f "$SRC_DIR/pyproject.toml" ]; then
    FROM="$SRC_DIR"; INSTALL_SRC_DESC="local checkout"; return 0
  fi
  if [ -n "${ASGARD_INSTALL_SPEC:-}" ]; then
    FROM="$ASGARD_INSTALL_SPEC"; INSTALL_SRC_DESC="custom spec"; return 0
  fi
  local v="${ASGARD_VERSION:-$(latest_version)}"
  [ -n "$v" ] || return 1
  FROM="https://github.com/$REPO_SLUG/releases/download/v${v}/asgard-${v}-py3-none-any.whl"
  INSTALL_SRC_DESC="v$v wheel"
  return 0
}

main() {
  SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
  banner

  # ── [1/3] preflight — confirm (and, where possible, provision) prerequisites before we touch anything. ──
  phase "preflight · check environment"
  ensure_curl || die "curl required (installer fetches uv over https) and auto-install failed. Install curl + ca-certificates, re-run."
  ok "curl ${D}present${X}"
  local os arch have_uv=0
  os="$(uname -s 2>/dev/null || echo '?')"; arch="$(uname -m 2>/dev/null || echo '?')"
  case "$os" in
    Linux|Darwin) ok "platform ${D}${os}/${arch}${X}" ;;
    *) warn "platform ${os}/${arch} — uv targets Linux/macOS; install may not work" ;;
  esac
  if command -v uv >/dev/null 2>&1; then
    have_uv=1; ok "uv ${D}$(uv --version 2>/dev/null | awk '{print $2}') (already installed)${X}"
  else
    info "uv ${D}absent — will bootstrap in step 2${X}"
  fi

  # ── [2/3] install — bootstrap the toolchain (uv → CPython 3.14), then install asgard. ──
  phase "install · toolchain + asgard"
  if [ "$have_uv" = 0 ]; then
    bootstrap_uv || die "uv install failed. Install manually: https://docs.astral.sh/uv/getting-started/installation/"
    export PATH="$HOME/.local/bin:$PATH"
    command -v uv >/dev/null 2>&1 || die "uv not on PATH — add ~/.local/bin and re-run."
    ok "uv ${D}$(uv --version 2>/dev/null | awk '{print $2}')${X}"
  fi
  spin "preparing python 3.14…" uv python install 3.14 \
    || warn "Python 3.14 pre-install skipped (uv fetches on demand)."
  ok "python ${D}3.14${X}"
  # asgard as a uv tool — release wheel by default (no git/compiler needed); local checkout for dev.
  resolve_install_source || die "could not resolve a version to install (network down?). Pin ASGARD_VERSION=X.Y.Z and retry."
  # Local path installs need --refresh-package: uv caches a path's built wheel by dir hash and can
  # serve a stale version after __init__ bumps. Wheel/URL installs are version-keyed, so no refresh.
  if [ "$INSTALL_SRC_DESC" = "local checkout" ]; then
    spin "installing asgard (${INSTALL_SRC_DESC})…" uv tool install --force --python 3.14 --refresh-package asgard "$FROM" \
      || die "install failed: $FROM"
  else
    spin "installing asgard (${INSTALL_SRC_DESC})…" uv tool install --force --python 3.14 "$FROM" \
      || die "install failed: $FROM"
  fi
  uv tool update-shell >/dev/null 2>&1 || true
  export PATH="$HOME/.local/bin:$PATH"
  ok "asgard ${D}linked (uv tool)${X}"

  # ── [3/3] verify — prove the CLI runs, then point the user at next steps. ──
  phase "verify · check install"
  VERSION="$(asgard --version 2>/dev/null || echo '?')"
  ok "asgard ${B}v${VERSION}${X}"
  if command -v asgard >/dev/null 2>&1; then
    ok "on PATH ${D}$(command -v asgard)${X}"
  else
    warn "not on PATH yet — restart shell (or run: uv tool update-shell)"
  fi
  # shell completions — 로그인 셸($SHELL) 기준으로 배선. 실패해도 설치는 유효 (수동 안내만).
  if asgard completions --install >/dev/null 2>&1; then
    ok "completions ${D}wired ($(basename "${SHELL:-bash}") — restart shell to activate)${X}"
  else
    info "completions ${D}skipped — run: asgard completions --install${X}"
  fi

  printf '\n  %s✔ installed%s — next:\n' "$G" "$X"
  printf '    %sasgard doctor%s   %s# verify%s\n' "$B" "$X" "$D" "$X"
  printf '    %sasgard --help%s\n\n' "$B" "$X"
}

main "$@"
