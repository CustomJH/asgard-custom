"""훅이 설 파이썬을 그 기계 위에서 정하는 두 스크립트 — 배선이 부르는 런처와 환경 프리플라이트.

배선 파일은 팀에 커밋돼 전달된다 (`commands/setup.py` 의 gitignore 블록: 스캐폴드는 팀 공유).
그래서 배선은 어느 기계에서 읽어도 같은 뜻이어야 하고, 인터프리터를 고르는 일은 실행 시점으로
내려간다 — 그 자리가 `hook_launcher_sh()` 이고, 배선은 그 파일 경로만 적는다
(`platform.hook_python`).

프리플라이트는 그 다음 물음을 맡는다: 런처가 찾을 uv 가 이 기계에 아예 없을 때. 훅 계약이
fail-open 이라 그때 훅 줄은 조용히 exit 127 로 끝나고, 가드도 주입도 게이트도 없는 채로 세션이
돈다.

`asgard doctor` 의 `_hook_interpreter_check` 가 같은 것을 재지만, doctor 를 부르려면 아스가르드가
이미 있어야 한다. 여기 있는 스크립트는 파이썬도 아스가르드도 없이 도는 POSIX sh 라서, 고칠
대상이 없는 기계에서도 자기는 선다.

세션마다 한 번 도는 줄이라 바깥 프로세스를 아낀다. 뿌리를 `git rev-parse --show-toplevel` 로
찾던 판은 실측 29ms 였고 그것이 이 스크립트가 쓰는 값의 절반이었다 — 뿌리도 인터프리터 추출도
셸 내장으로 푼다."""

from ..platform import HOOK_LAUNCHER, PYTHON_PIN

# uv 찾는 차례 — PATH 를 먼저 보고, 없으면 설치기들이 쓰는 자리를 밟는다. 훅 런처와 프리플라이트가
# 같은 차례를 봐야 한다: 런처가 골라 쓰는 uv 와 프리플라이트가 "있다"고 판정하는 uv 가 갈리면,
# 초록을 받은 기계에서 훅이 계속 죽는다. `~/.local/bin` 이 먼저인 것은 install.sh 가 거기 깔기
# 때문이고, 그 뒤 셋은 cargo·Homebrew(Apple 실리콘·Intel)의 기본 자리다.
_UV_PATH_SH = r"""uv_path() {
  p=$(command -v uv 2>/dev/null) || p=""
  [ -n "$p" ] && { printf '%s' "$p"; return 0; }
  for p in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    [ -x "$p" ] && { printf '%s' "$p"; return 0; }
  done
  return 1
}"""

_ENV_SETUP_SH = r"""#!/bin/sh
# Asgard 환경 프리플라이트 — 훅이 부를 파이썬이 이 기계에 있는지 보고, 없으면 세우는 자리.
#
# 왜 있는가. 배선이 부르는 것은 훅 폴더의 런처이고, 런처는 이 기계에서 uv 를 찾는다. 찾을 것이
# 아예 없으면 훅 줄이 전부 exit 127 이 되고, 훅 계약이 fail-open 이라 아무 말도 안 나온다 —
# 가드도 주입도 게이트도 없는 채로 세션이 돈다. 이 스크립트가 그 침묵을 한 문단으로 바꾼다.
# 런처보다 먼저 만들어진 배선(인터프리터 절대 경로가 박힌 것)도 같은 자리에서 같이 읽는다.
#
#   sh env-setup.sh [claude-code|codex|cursor]   배선이 부르는 것이 서는지 본다 (기본)
#   sh env-setup.sh --install                    uv 와 CPython __PIN__ 을 깔고 옛 배선을 다시 쓴다
#
# 파이썬 없이 도는 POSIX sh 다 — 고칠 대상이 없는 기계에서도 자기는 선다. 판정만 하고 아무것도
# 막지 않는다 (`--check` 는 언제나 exit 0).
#
# `--install` 은 배선 파일을 고쳐 쓴다. readonly-guard 가 에이전트에게 막는 그 파일들이 맞지만,
# 그 금지의 이유는 "아스가르드 자신의 명령으로만 바꿔라"이고(`asgard sync`), 아스가르드가 없는
# 기계에서 그 명령에 해당하는 것이 이 스크립트다.
set -u

PIN="__PIN__"
SELF="$0"
MODE=check
CLIENT=claude-code
for arg in "$@"; do
  case "$arg" in
    --install) MODE=install ;;
    --check) MODE=check ;;
    claude-code|codex|cursor) CLIENT="$arg" ;;
  esac
done

WIRING=".claude/settings.json .codex/config.toml .cursor/hooks.json"

# 저장소 뿌리로 내려선다. 이 파일은 `<뿌리>/<호스트>/hooks/` 에 깔리므로 `$0` 에서 두 칸 올라가면
# 뿌리다. `git rev-parse --show-toplevel` 을 부르던 판은 실측 29ms 였고 세션마다 나갔다 — `cd` 는
# 셸 내장이라 프로세스를 하나도 안 띄운다. 후보를 순서대로 밟아 배선 파일이 보이는 자리에 선다.
START=$PWD
for candidate in "${0%/*}/../.." "${CLAUDE_PROJECT_DIR:-$START}" "$START"; do
  cd "$START" 2>/dev/null || exit 0
  cd "$candidate" 2>/dev/null || continue
  for f in $WIRING; do [ -f "$f" ] && break 2; done
done

# 훅 런처 — 배선이 실제로 부르는 파일이고, 이 스크립트 바로 옆에 깔린다 (`platform.hook_python`).
LAUNCHER="${0%/*}/__LAUNCHER__"

# 배선 줄을 고르는 문구. `command` 를 함께 요구한다 — Claude Code 의 배선 파일에는 권한
# 허용목록도 같이 사는데 거기에 `Bash(uv run --no-project python .claude/hooks/quest-log.py *)`
# 가 있고, 그 줄이 파일 앞쪽이라 문구만 보고 첫 줄을 집으면 인터프리터가 `Bash(uv` 로 읽힌다.
# 허용목록은 모델이 타이핑할 맨 토큰이지 훅이 실행할 명령이 아니다.
MATCH='command.*run --no-project python'

# token_of <배선 줄> — 그 줄이 부르는 인터프리터를 TOKEN 에 담는다.
#
# 값을 돌려주지 않고 변수에 담는 이유는 값이다 — `$(…)` 는 호출마다 서브셸을 하나 띄우고 이
# 스크립트는 세션마다 돈다. 자르기도 셸 내장이라 `sed` 를 안 부른다. 마지막 따옴표 뒤부터가
# 프로그램 경로이고, JSON 은 큰따옴표를, Codex 의 TOML 리터럴 문자열은 작은따옴표를 쓴다.
# lagom: 공백이 든 경로(`"C:/Program Files/uv.exe"`)는 탈출된 따옴표에 감싸여 빈 값이 된다 —
# 그 기계에서는 아래 PATH 조회가 대신 답한다.
token_of() {
  TOKEN=${1%% run --no-project python*}
  TOKEN=${TOKEN##*\"}
  TOKEN=${TOKEN##*\'}
  TOKEN=${TOKEN##*\\}
}

runnable() {
  case "${1:-}" in
    '') return 1 ;;
    */*) [ -x "$1" ] ;;
    *) command -v "$1" >/dev/null 2>&1 ;;
  esac
}

__UV_PATH__

# say — 호스트가 읽는 통로. SessionStart 는 Claude Code·Codex 모두 평문 stdout 이 곧 주입이고,
# Cursor 만 `additional_context` JSON 을 받는다 (asgard_hooklib/inject.py 와 같은 규약).
say() {
  if [ "$CLIENT" = cursor ]; then
    printf '{"additional_context":"%s"}\n' \
      "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk '{printf "%s\\n", $0}')"
  else
    printf '%s\n' "$1"
  fi
}

if [ "$MODE" = check ]; then
  have=0
  for f in $WIRING; do [ -f "$f" ] && have=1; done
  [ "$have" = 1 ] || exit 0

  # 호스트마다 배선을 쓴 시점이 달라 인터프리터도 다를 수 있다 — 세 파일을 다 본다. 다만
  # grep 은 한 번만 부른다 (`-m1` 은 파일마다 첫 줄이라 최대 세 줄이 나온다). 없는 파일은
  # grep 이 알아서 건너뛴다. 줄 단위로 쪼개려고 IFS 를 개행으로 두고, `set -f` 로 줄 안의
  # 글로브 문자가 파일 이름으로 펼쳐지는 것을 막는다.
  broken=""
  found=0
  # POSIX 배선은 인터프리터를 직접 적지 않고 런처를 부른다 — 어느 uv 를 쓸지는 런처가 그 기계
  # 위에서 정하므로 아래 배선 파싱은 이 물음에 답을 못 낸다. 런처를 한 번 돌려 보는 것이 같은
  # 물음의 정확한 형태다. `-c pass` 는 인터프리터가 서는지만 묻는다. 여기서 `found` 를 세워 두면
  # 아래 파싱이 빈손으로 끝나도 PATH 조회 갈래로 새지 않는다.
  if [ -f "$LAUNCHER" ]; then
    sh "$LAUNCHER" -c pass >/dev/null 2>&1 && exit 0
    broken=$LAUNCHER
    found=1
  fi
  # grep 을 먼저 부르고 IFS 를 바꾼다 — `$WIRING` 도 IFS 로 쪼개지므로 순서가 뒤집히면 파일
  # 세 개가 이름 하나로 붙어 grep 이 아무것도 못 읽는다.
  matches=$(grep -h -m1 "$MATCH" $WIRING 2>/dev/null)
  saved_ifs=$IFS
  IFS='
'
  set -f
  for line in $matches; do
    token_of "$line"
    [ -n "$TOKEN" ] || continue
    found=1
    runnable "$TOKEN" || { broken="$TOKEN"; break; }
  done
  set +f
  IFS=$saved_ifs
  if [ "$found" = 0 ]; then
    # uv 없이 만들어진 배선은 맨 `python3`·`py` 토큰이라 위 추출에 안 걸린다 — PATH 조회로 답한다.
    for c in python3 python py; do command -v "$c" >/dev/null 2>&1 && exit 0; done
    broken=python3
  fi
  [ -n "$broken" ] || exit 0

  say "[asgard] 이 저장소의 훅을 돌릴 파이썬이 이 기계에 없어요.
배선이 부르는 \`$broken\` 이 여기서는 안 서요. 훅은 실패해도 세션을 막지 않아서,
지금 이 세션은 가드·기억 주입·퀘스트 게이트가 전부 꺼진 채로 돌고 있어요.

세우는 명령 — uv 와 CPython $PIN 를 깔고, 훅 배선을 이 기계의 uv 자리로 다시 써요:
    sh $SELF --install

이 문단을 사용자에게 그대로 전하고, 설치해도 되는지 물어본 뒤에 실행하세요."
  exit 0
fi

printf '[asgard] 환경을 세워요 — uv, CPython %s, 훅 배선.\n' "$PIN"

uv=$(uv_path) || uv=""
if [ -z "$uv" ]; then
  case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*|Windows*)
      powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" || true
      ;;
    *)
      if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh || true
      elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh || true
      fi
      ;;
  esac
  PATH="$HOME/.local/bin:$PATH"
  export PATH
  uv=$(uv_path) || uv=""
fi
# 애스트랄 설치 스크립트가 막힌 망에서는 패키지 매니저가 남은 길이다 (install.sh 의 bootstrap_uv 와 같은 순서).
if [ -z "$uv" ]; then
  [ "$(uname -s 2>/dev/null)" = Darwin ] && command -v brew >/dev/null 2>&1 && brew install uv >/dev/null 2>&1
  command -v pip3 >/dev/null 2>&1 && pip3 install --user uv >/dev/null 2>&1
  uv=$(uv_path) || uv=""
fi
if [ -z "$uv" ]; then
  printf '[asgard] uv 를 못 깔았어요. 손으로 깔고 다시 실행해 주세요 — https://docs.astral.sh/uv/getting-started/installation/\n' >&2
  exit 1
fi
printf '  uv      %s\n' "$uv"

if "$uv" python install "$PIN" >/dev/null 2>&1; then
  printf '  python  %s\n' "$PIN"
else
  printf '  python  %s — 미리 받기는 건너뛰었어요 (uv 가 처음 쓸 때 받아요)\n' "$PIN"
fi

# 배선에 인터프리터 경로가 박혀 있던 시절의 수리다. 런처를 부르는 배선에는 고쳐 쓸 자리가 없다 —
# 위에서 uv 를 깔았으면 런처가 다음 세션부터 그것을 찾아 쓴다.
changed=0
for f in $WIRING; do
  [ -f "$f" ] || continue
  line=$(grep -m1 "$MATCH" "$f" 2>/dev/null) || continue
  [ -n "$line" ] || continue
  token_of "$line"
  old=$TOKEN
  [ -n "$old" ] || continue
  [ "$old" = "$uv" ] && continue
  # 맨 토큰 배선(`uv …`)은 PATH 가 푸는 값이라 다시 쓸 자리가 없다 — uv 를 깐 것만으로 이미
  # 고쳐졌다. 그런데 아래 치환은 파일 전체를 훑으므로, `old` 가 두 글자 `uv` 면 권한 허용목록의
  # `Bash(uv run --no-project python …)` 까지 절대 경로로 바뀐다. 그러면 모델이 안내문대로 친
  # 명령이 허용목록과 어긋나 헤드리스에서 자동 거부된다 (tests/test_mode_parity.py 가 그 항목은
  # 맨 토큰이어야 한다고 잰다). 슬래시가 없으면 경로가 아니므로 건너뛴다.
  case "$old" in */*) ;; *) continue ;; esac
  # 구분자는 `|` — 경로에는 안 들어간다. `$old` 안의 `.` 는 정규식 임의 문자로 읽히지만
  # 자기 자신과 먼저 맞으므로 치환 결과는 같다.
  if sed "s|$old|$uv|g" "$f" > "$f.asgard-new" && mv "$f.asgard-new" "$f"; then
    changed=1
    printf '  배선    %s\n' "$f"
  else
    rm -f "$f.asgard-new"
  fi
done
if [ "$changed" = 1 ]; then
  printf '  %s\n' "배선 파일은 기계마다 값이 달라요 — 이 변경은 이 기계 것이라 커밋하지 않는 편이 좋아요."
else
  printf '  배선    고쳐 쓸 자리가 없어요 — 배선이 이미 이 기계에서 uv 를 찾아요\n'
fi

if "$uv" run --no-project python -c pass >/dev/null 2>&1; then
  printf '[asgard] 훅이 서요 — %s run --no-project python\n' "$uv"
  printf '         새 세션부터 적용돼요. 이 세션은 한 번 다시 열어 주세요.\n'
else
  printf '[asgard] 아직 안 서요. 새 터미널을 열고 다시 실행해 주세요 — sh %s --install\n' "$SELF" >&2
  exit 1
fi
"""


_HOOK_LAUNCHER_SH = r"""#!/bin/sh
# Asgard 훅 런처 — 배선이 부르는 인터프리터가 정해지는 한 자리.
#
# 배선 파일(.claude/settings.json · .codex/config.toml · .cursor/hooks.json)은 팀에 커밋돼
# 전달된다. 그래서 거기에 스캐폴드를 만든 기계의 uv 절대 경로를 적으면, 저장소를 받은 다른
# 기계에서는 훅 줄이 전부 exit 127 로 끝난다. 훅 계약이 fail-open 이라 그 죽음은 화면에 안 뜬다 —
# 가드도 주입도 게이트도 없는 채로 세션이 돈다.
#
# 맨 `uv` 를 적을 수도 없다. 독·Finder·launchd 가 띄운 프로세스가 물려받는 PATH 는
# `/usr/bin:/bin:/usr/sbin:/sbin` 넉 줄이 전부고, 거기에 `python3` 는 있어도 `uv` 는 없다.
# 그래서 배선에는 저장소 안 경로인 이 파일만 적고, 어느 uv 를 쓸지는 여기서 그 기계 위에서 정한다.
#
# `exec` 라 프로세스가 늘지 않는다 — 이 셸이 인터프리터로 바뀐다.
set -u

__UV_PATH__

uv=$(uv_path) && exec "$uv" run --no-project python "$@"

# uv 가 없는 기계 — 패키지 매니저로 asgard 를 따로 깐 경우다. 훅은 stdlib 만 쓰므로 어느
# CPython 이든 선다.
for c in python3 python py; do
  command -v "$c" >/dev/null 2>&1 && exec "$c" "$@"
done

printf '[asgard] uv 도 python 도 없어서 훅을 못 돌려요 — https://astral.sh/uv\n' >&2
exit 127
"""


def hook_launcher_sh() -> str:
    """`<hooks>/asgard-python` 본문 — 배선이 부르는 런처 (`platform.HOOK_LAUNCHER`)."""
    return _HOOK_LAUNCHER_SH.replace("__UV_PATH__", _UV_PATH_SH)


def env_setup_sh() -> str:
    """`<hooks>/env-setup.sh` 본문 — CPython 핀은 `platform.PYTHON_PIN` 하나에서 온다."""
    return (
        _ENV_SETUP_SH.replace("__PIN__", PYTHON_PIN)
        .replace("__UV_PATH__", _UV_PATH_SH)
        .replace("__LAUNCHER__", HOOK_LAUNCHER)
    )


# ── Windows ───────────────────────────────────────────────────────────────────
# 같은 물음을 그 기계의 말로 다시 묻는 자리. POSIX 쪽 `sh` 는 Windows 에 있다는 보장이 없고
# (`platform.hook_python` 이 같은 이유로 거기서 런처를 안 쓴다), 반대로 PowerShell 은 Windows 7
# 이후 모든 판에 실려 있다. 그래서 배선의 러너만 갈아 끼우고 판정과 수리의 뜻은 그대로 둔다.
#
# 설치 사다리는 `install.ps1` 의 `Install-Uv` 와 같은 순서다 — 애스트랄 설치 스크립트, winget,
# 그다음 pip. 순서가 갈리면 같은 기계에서 두 문이 서로 다른 uv 를 깔게 된다.
_ENV_SETUP_PS1 = r"""# Asgard 환경 프리플라이트 (Windows) — 훅이 부를 파이썬이 이 기계에 있는지 보고, 없으면 세운다.
#
# POSIX 쪽 쌍둥이는 `env-setup.sh` 이고 뜻이 같다. 러너만 다르다: Windows 에는 `sh` 가 있다는
# 보장이 없고 PowerShell 은 어느 판에나 실려 있다. 배선은 스캐폴드 시점에 갈려서, 한 기계에는
# 프리플라이트 줄이 하나만 선다 (`platform.py` 의 `preflight_command` 가 러너를 고른다).
#
#   powershell -File env-setup.ps1 <claude-code|codex|cursor>   배선된 런타임이 서는지 본다
#   powershell -File env-setup.ps1 -Install                     uv 와 CPython __PIN__ 을 깐다
#
# 판정만 하고 아무것도 막지 않는다 — 판정 갈래는 언제나 exit 0 이다.
[CmdletBinding()]
param(
  [Parameter(Position = 0)][string]$Client = 'claude-code',
  [switch]$Install
)

$ProgressPreference = 'SilentlyContinue'
$PIN = '__PIN__'
$WIRING = @('.claude/settings.json', '.codex/config.toml', '.cursor/hooks.json')
$MARK = ' run --no-project python'

# 저장소 뿌리 — 이 파일은 `<뿌리>\<호스트>\hooks\` 에 깔리므로 두 칸 올라가면 뿌리다. 호스트가
# 주는 환경 변수와 현재 위치를 뒤 후보로 두고, 배선 파일이 보이는 첫 자리에 선다.
function Find-Root {
  $candidates = @()
  if ($PSScriptRoot) { $candidates += (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) }
  if ($env:CLAUDE_PROJECT_DIR) { $candidates += $env:CLAUDE_PROJECT_DIR }
  $candidates += (Get-Location).Path
  foreach ($c in $candidates) {
    if (-not $c) { continue }
    foreach ($w in $WIRING) {
      if (Test-Path -LiteralPath (Join-Path $c $w) -PathType Leaf) { return $c }
    }
  }
  return $null
}

# 배선 줄이 부르는 인터프리터의 첫 낱말. `command` 를 함께 요구하는 이유는 권한 허용목록이다 —
# 거기에도 `Bash(uv run --no-project python ...)` 가 있고 파일 앞쪽이라, 문구만 보면 인터프리터가
# `Bash(uv` 로 읽힌다. 마지막 따옴표(또는 그 앞의 역슬래시) 뒤부터가 프로그램 경로다.
function Get-WiredToken([string]$Path) {
  foreach ($line in [System.IO.File]::ReadLines($Path)) {
    if ($line -notmatch 'command') { continue }
    $at = $line.IndexOf($MARK)
    if ($at -lt 0) { continue }
    $head = $line.Substring(0, $at)
    $cut = [Math]::Max([Math]::Max($head.LastIndexOf('"'), $head.LastIndexOf("'")), $head.LastIndexOf('\'))
    return $head.Substring($cut + 1)
  }
  return ''
}

function Test-Runnable([string]$Token) {
  if (-not $Token) { return $false }
  if ($Token -match '[\\/]') { return (Test-Path -LiteralPath $Token -PathType Leaf) }
  return [bool](Get-Command $Token -ErrorAction SilentlyContinue)
}

# uv 찾는 차례 — PATH 를 먼저 보고, 없으면 설치기들이 쓰는 자리를 밟는다. POSIX 쪽 `uv_path` 와
# 같은 뜻이고 자리 목록만 Windows 것이다 (애스트랄 설치기, cargo, winget 의 링크 폴더).
function Find-Uv {
  $cmd = Get-Command uv -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $spots = @()
  if ($env:USERPROFILE) {
    $spots += (Join-Path $env:USERPROFILE '.local\bin\uv.exe')
    $spots += (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe')
  }
  if ($env:LOCALAPPDATA) { $spots += (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe') }
  foreach ($s in $spots) { if (Test-Path -LiteralPath $s -PathType Leaf) { return $s } }
  return ''
}

# 방금 깐 uv 는 이 프로세스가 뜰 때 없던 폴더에 있다 — 레지스트리의 PATH 를 다시 읽어야 잡힌다.
function Update-PathFromEnvironment {
  try {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $joined = @($machine, $user) | Where-Object { $_ }
    if ($joined) { $env:Path = ($joined -join ';') }
  } catch { }
}

function Write-Offer([string]$Text) {
  if ($Client -eq 'cursor') {
    # Cursor 의 컨텍스트 통로는 이 키 하나다 (asgard_hooklib/inject.py 와 같은 규약).
    ConvertTo-Json -Compress -InputObject @{ additional_context = $Text }
  } else {
    $Text
  }
}

$root = Find-Root
if (-not $root) { exit 0 }
Set-Location -LiteralPath $root

if (-not $Install) {
  $broken = ''
  $found = $false
  foreach ($w in $WIRING) {
    $p = Join-Path $root $w
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { continue }
    $token = Get-WiredToken $p
    if (-not $token) { continue }
    $found = $true
    if (-not (Test-Runnable $token)) { $broken = $token; break }
  }
  if (-not $found) {
    # POSIX 기계에서 만들어진 배선은 인터프리터 대신 sh 런처를 부른다 — 그 줄은 위 추출에 안
    # 걸리고 여기서는 어차피 못 돈다. 그래도 uv 나 python 이 있으면 훅은 설 수 있으므로 물음을
    # 런타임 존재로 되돌린다.
    foreach ($c in @('uv', 'python', 'py')) {
      if (Get-Command $c -ErrorAction SilentlyContinue) { exit 0 }
    }
    $broken = 'uv'
  }
  if (-not $broken) { exit 0 }

  Write-Offer @"
[asgard] 이 저장소의 훅을 돌릴 파이썬이 이 기계에 없어요.
배선이 부르는 자리는 ``$broken`` 인데 거기가 비어 있어요. 훅은 실패해도 세션을 막지 않아서,
지금 이 세션은 가드·기억 주입·퀘스트 게이트가 전부 꺼진 채로 돌고 있어요.

세우는 명령 — uv 와 CPython $PIN 를 깔고, 훅 배선을 이 기계의 uv 자리로 다시 써요:
    powershell -NoProfile -ExecutionPolicy Bypass -File "$PSCommandPath" -Install

이 문단을 사용자에게 그대로 전하고, 설치해도 되는지 물어본 뒤에 실행하세요.
"@
  exit 0
}

Write-Output "[asgard] 환경을 세워요 - uv, CPython $PIN, 훅 배선."

$uv = Find-Uv
if (-not $uv) {
  # 애스트랄 설치 스크립트는 자식 PowerShell 에서 돌린다 — 남의 스크립트가 이 세션의
  # ErrorActionPreference·PATH·모듈 상태를 건드리지 않게 한다 (install.ps1 도 같은 이유).
  $ps = Get-Command powershell -ErrorAction SilentlyContinue
  if (-not $ps) { $ps = Get-Command pwsh -ErrorAction SilentlyContinue }
  if ($ps) {
    $inner = '$ErrorActionPreference = "Stop";' +
      '$ProgressPreference = "SilentlyContinue";' +
      '[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12;' +
      'Invoke-RestMethod https://astral.sh/uv/install.ps1 -UseBasicParsing | Invoke-Expression'
    $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
    & $ps.Source '-NoProfile' '-ExecutionPolicy' 'Bypass' '-NonInteractive' '-EncodedCommand' $enc | Out-Null
    Update-PathFromEnvironment
    $uv = Find-Uv
  }
}
if (-not $uv -and (Get-Command winget -ErrorAction SilentlyContinue)) {
  & winget install --id astral-sh.uv -e --source winget --accept-package-agreements --accept-source-agreements | Out-Null
  Update-PathFromEnvironment
  $uv = Find-Uv
}
if (-not $uv) {
  foreach ($py in @('py', 'python', 'python3')) {
    if (-not (Get-Command $py -ErrorAction SilentlyContinue)) { continue }
    $pipArgs = @('-m', 'pip', 'install', '--user', '--upgrade', 'uv')
    if ($py -eq 'py') { $pipArgs = @('-3') + $pipArgs }
    & $py @pipArgs | Out-Null
    Update-PathFromEnvironment
    $uv = Find-Uv
    if ($uv) { break }
  }
}
if (-not $uv) {
  Write-Error '[asgard] uv 를 못 깔았어요. 손으로 깔고 다시 실행해 주세요 - https://docs.astral.sh/uv/getting-started/installation/'
  exit 1
}
Write-Output "  uv      $uv"

& $uv python install $PIN 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
  Write-Output "  python  $PIN"
} else {
  Write-Output "  python  $PIN - 미리 받기는 건너뛰었어요 (uv 가 처음 쓸 때 받아요)"
}

$changed = $false
foreach ($w in $WIRING) {
  $p = Join-Path $root $w
  if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { continue }
  $old = Get-WiredToken $p
  if (-not $old -or $old -eq $uv) { continue }
  # 맨 토큰 배선(`uv ...`)은 PATH 가 푸는 값이라 다시 쓸 자리가 없다 — uv 를 깐 것만으로 이미
  # 고쳐졌다. 그런데 아래 치환은 파일 전체를 훑으므로, `old` 가 두 글자 `uv` 면 권한 허용목록의
  # `Bash(uv run --no-project python ...)` 까지 절대 경로로 바뀌고, 모델이 안내문대로 친 명령이
  # 헤드리스에서 자동 거부된다. 경로가 아니면 건너뛴다.
  if ($old -notmatch '[\\/]') { continue }
  $text = [System.IO.File]::ReadAllText($p)
  [System.IO.File]::WriteAllText($p, $text.Replace($old, $uv))
  $changed = $true
  Write-Output "  배선    $w"
}
if ($changed) {
  Write-Output '  배선 파일은 기계마다 값이 달라요 - 이 변경은 이 기계 것이라 커밋하지 않는 편이 좋아요.'
} else {
  Write-Output '  배선    고쳐 쓸 자리가 없어요 - 배선이 이미 이 기계에서 uv 를 찾아요'
}

& $uv run --no-project python -c pass 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
  Write-Output "[asgard] 훅이 서요 - $uv run --no-project python"
  Write-Output '         새 세션부터 적용돼요. 이 세션은 한 번 다시 열어 주세요.'
} else {
  Write-Error "[asgard] 아직 안 서요. 새 터미널을 열고 다시 실행해 주세요 - powershell -File `"$PSCommandPath`" -Install"
  exit 1
}
"""


def env_setup_ps1() -> str:
    """`<hooks>/env-setup.ps1` 본문 — Windows 쪽 프리플라이트."""
    return _ENV_SETUP_PS1.replace("__PIN__", PYTHON_PIN)
