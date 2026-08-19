#!/bin/sh
# Asgard 환경 프리플라이트 — 훅이 부를 파이썬이 이 기계에 있는지 보고, 없으면 세우는 자리.
#
# 왜 있는가. 배선이 부르는 것은 훅 폴더의 런처이고, 런처는 이 기계에서 uv 를 찾는다. 찾을 것이
# 아예 없으면 훅 줄이 전부 exit 127 이 되고, 훅 계약이 fail-open 이라 아무 말도 안 나온다 —
# 가드도 주입도 게이트도 없는 채로 세션이 돈다. 이 스크립트가 그 침묵을 한 문단으로 바꾼다.
# 런처보다 먼저 만들어진 배선(인터프리터 절대 경로가 박힌 것)도 같은 자리에서 같이 읽는다.
#
#   sh env-setup.sh [claude-code|codex|cursor]   배선이 부르는 것이 서는지 본다 (기본)
#   sh env-setup.sh --install                    uv 와 CPython 3.14 을 깔고 옛 배선을 다시 쓴다
#
# 파이썬 없이 도는 POSIX sh 다 — 고칠 대상이 없는 기계에서도 자기는 선다. 판정만 하고 아무것도
# 막지 않는다 (`--check` 는 언제나 exit 0).
#
# `--install` 은 배선 파일을 고쳐 쓴다. readonly-guard 가 에이전트에게 막는 그 파일들이 맞지만,
# 그 금지의 이유는 "아스가르드 자신의 명령으로만 바꿔라"이고(`asgard sync`), 아스가르드가 없는
# 기계에서 그 명령에 해당하는 것이 이 스크립트다.
set -u

PIN="3.14"
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
LAUNCHER="${0%/*}/asgard-python"

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

uv_path() {
  p=$(command -v uv 2>/dev/null) || p=""
  [ -n "$p" ] && { printf '%s' "$p"; return 0; }
  for p in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    [ -x "$p" ] && { printf '%s' "$p"; return 0; }
  done
  return 1
}

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
