#!/usr/bin/env python3
# Asgard secret-guard — Canon Law 4 (시크릿 보호). 법조문은 "never read, print, log, or commit" 인데
# 오래도록 기계가 맡은 것은 **commit 절반뿐**이었다 (Write/Edit PreToolUse). 나머지 절반 — read·print —
# 이 이 파일의 두 번째 계층이다.
#
# 왜 읽기가 더 급한가 (26-07-27 실측): 네이티브 루프의 `session.py`는 도구 출력을 그대로
# `messages`에 넣고, 그 messages는 **매 턴 프로바이더로 재전송된다**. 즉 `cat .env` 한 번이면
# 시크릿이 (1) 제3자에게 나가고 (2) 세션이 끝날 때까지 매 요청에 다시 들어간다. 쓰기는 로컬에
# 남지만 읽기는 밖으로 나간다 — 구멍의 크기가 반대였다.
# (구 주석이 "알려진 구멍: shell 우회는 안 잡는다"로 남겨 둔 자리가 여기다.)
#
# ── 두 계층, 다른 판정 근거 ──────────────────────────────────────────────────────────
#   쓰기(Write/Edit/apply_patch) — 본문에 credential **패턴**이 있으면 차단. 내용이 근거다.
#   읽기(Read/Grep/Bash …)       — 경로·명령이 **오직 credential을 담기 위해 존재**하면 차단.
#                                   이름이 근거다.
#
# 왜 읽기는 이름으로 판정하나: 내용을 보려면 먼저 읽어야 하고, 읽은 시점에 이미 늦었다. 그래서
# 읽기 측은 "정적으로 증명 가능한 것만" 막는다 — `.netrc`·`.pgpass`·`.aws/credentials`·ssh 개인키처럼
# 다른 용도가 없는 파일. `.npmrc`·`.docker/config.json`처럼 설정과 자격이 섞이는 파일은 뺐다:
# 증명할 수 없는 것을 막으면 오탐이 쌓이고, 오탐이 쌓인 게이트는 꺼진다.
#
# 왜 fail-open 인가: 가드 오류로 모든 편집이 막히면 안 된다. exit 2 = 차단, 그 외 = 허용.
import json
import os
import re
import shlex
import sys

# 발화 계측은 훅과 함께 깔리는 공용 라이브러리가 쥔다 — 이 훅은 자기 이름만 넘긴다.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.firing import run  # noqa: E402

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass


# 앞 4개는 포맷이 고정된 토큰(오탐 거의 없음), 마지막은 key=value 휴리스틱(넓지만 값 8자 이상만 —
# "password: xxx" 같은 placeholder 오탐을 줄인다).
SECRET = [
    (r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----", "private key"),  # PEM 헤더
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS key"),  # AWS access key ID 고정 프리픽스
    (r"\bghp_[A-Za-z0-9]{36}\b", "GitHub token"),  # GitHub classic PAT
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "Slack token"),
    (r"(?i)\b(secret|password|passwd|api[_-]?key|access[_-]?token|private[_-]?key)\s*[:=]\s*\S{8,}", "credential"),
]

# ── 읽기 측 ─────────────────────────────────────────────────────────────────────
# 공유용 템플릿 — 이름이 자격 파일 계열이어도 값이 없다. 쓰기·읽기 양쪽에서 같은 면제.
# `.env.example` 뿐 아니라 `secrets.example.yaml`·`credentials.yaml.template`도 같은 성격이라
# 마커를 파일명 어느 마디에서든 인정한다 — k8s·terraform 저장소가 이 형태를 흔히 쓴다.
_TEMPLATE_MARKERS = frozenset({"example", "sample", "template", "dist", "schema", "tpl"})
_ENV_TEMPLATE = re.compile(r"\.env\.(example|sample|template|dist|schema)$", re.I)
_ENV_FILE = re.compile(r"(^|/)\.env(\.[^/]*)?$", re.I)
# ssh 공개키 — 핑거프린트 확인은 정상 작업이다. 개인키 규칙보다 먼저 면제한다.
_PUBLIC_KEY = re.compile(r"\.pub$", re.I)


def _is_template(path: str) -> bool:
    """파일명 마디 중 하나가 템플릿 마커면 값이 없는 공유 파일로 본다."""
    return any(part.lower() in _TEMPLATE_MARKERS for part in os.path.basename(path).split("."))


# 다른 용도가 없는 파일만. 각 항목은 "이 이름을 가진 파일은 자격 증명 저장소다"가 참이어야 한다.
SECRET_READ_PATHS = [
    (_ENV_FILE, "dotenv"),
    (re.compile(r"(^|/)_?\.?netrc$", re.I), ".netrc"),
    (re.compile(r"(^|/)\.pgpass$", re.I), ".pgpass"),
    (re.compile(r"(^|/)\.git-credentials$", re.I), "git credential store"),
    (re.compile(r"(^|/)\.aws/credentials$", re.I), "AWS credentials"),
    # ssh 개인키 — `.pub`은 공개키라 앞선 면제가 먼저 제거한다 (핑거프린트 확인은 정상 작업).
    # 키가 `~/.ssh/` 안에만 있다고 가정하면 안 된다: 실코퍼스에 `ssh_key/rnd1.key`처럼 배포용
    # 디렉터리에 둔 개인키가 있었다. 확장자 없는 `*_ed25519`·`*_rsa`는 위치와 무관하게 키다
    # (`foo_rsa.py`는 확장자가 있어 걸리지 않는다).
    (re.compile(r"(^|/)\.ssh/id_[^/]+$", re.I), "ssh private key"),
    (re.compile(r"(^|/)[^/]*_(rsa|dsa|ecdsa|ed25519)$", re.I), "ssh private key"),
    (re.compile(r"\.(pem|p12|pfx|jks|keystore|key)$", re.I), "key material"),
    (re.compile(r"(^|/)(credentials|secrets)\.(json|ya?ml|toml|ini)$", re.I), "credential file"),
    (re.compile(r"(^|/)[^/]*service[-_]account[^/]*\.json$", re.I), "service account key"),
]

# 자격 증명을 stdout으로 쏟는 명령. 여기에도 같은 문턱을 적용한다 — 증명 가능한 것만.
# `git config --list`는 뺐다: 토큰이 섞일 **수** 있을 뿐이고 정상 사용이 압도적이다.
# 각 항목의 인자 튜플은 **전부 있어야** 성립한다(AND). 대안은 항목을 따로 적는다 — 한 튜플에
# 대안을 섞으면 AND가 걸려 아무것도 안 잡힌다 (26-07-27 탐침이 잡은 결함).
SECRET_READ_COMMANDS = [
    ("security", ("find-generic-password",), "macOS keychain dump"),
    ("security", ("find-internet-password",), "macOS keychain dump"),
    ("gcloud", ("auth", "print-access-token"), "gcloud token print"),
    ("gcloud", ("auth", "print-identity-token"), "gcloud token print"),
    ("aws", ("configure", "get"), "aws configure get"),
]
# 파일을 stdout으로 내보내는 도구 — 인자에 시크릿 경로가 오면 `Read`와 같은 판정.
# 파일을 인자로 받는 판독기 — **모든** 비플래그 인자가 경로다.
# 26-08-05 감사가 통과시킨 형태들을 여기 담았다. 판정이 고정된 이름 집합이라, 같은 파일을 같은
# 목적으로 읽는 다른 도구는 전부 빠져나갔다 — `cut -d= -f2 .env` 는 cat 과 다르지 않다.
# 내보내는 형태도 같이 담는다: stdout 으로 안 쏟아도 자격 증명이 다른 자리로 간다.
_FILE_READERS = frozenset(
    {
        "cat", "bat", "less", "more", "head", "tail", "strings", "xxd", "od", "base64", "nl", "tac", "openssl",
        "cut", "sort", "uniq", "paste", "join", "column", "fold", "expand", "rev", "split", "csplit",
        "xmllint", "diff", "sdiff", "vimdiff", "colordiff",
        "cp", "mv", "install", "rsync", "scp", "tee", "dd", "tar", "zip", "gzip", "bzip2", "xz", "shasum", "md5sum",
    }
)  # fmt: skip
# 패턴을 먼저 받는 판독기 — **첫 비플래그 인자는 찾을 글자이지 경로가 아니다.**
# 이 구분이 없던 판은 `grep -rn database.key src/` 의 검색어를 파일로 읽어 평범한 조사를 막았다
# (26-08-05 재판정이 재현). 이름만 넓히고 자리를 안 가르면 오탐과 구멍이 번갈아 난다.
_PATTERN_READERS = frozenset({"sed", "gsed", "awk", "gawk", "nawk", "mawk", "grep", "egrep", "fgrep", "rg", "ag", "jq", "yq"})  # fmt: skip
_READERS = _FILE_READERS | _PATTERN_READERS
# 글롭 꼬리 — `cat .env*` 는 경로 정규식의 `$` 앵커를 깨서 통째로 빠져나갔다. 판정 전에만 벗기고
# 보고에는 원문을 쓴다.
_GLOB_TAIL = re.compile(r"[*?\[\]]+$")
# 셸이나 인터프리터가 **문자열 인자를 다시 명령으로 편다**는 표. `git_guard._OPAQUE_CORE` 와
# 글자까지 같아야 한다 — 두 가드가 같은 질문에 다른 답을 들면, 한쪽에서 막힌 것이 다른 쪽에서는
# 통과한다. 실제로 그랬다: secret 쪽에만 파이프 실행(`… | sh`)이 빠져 있어 감싸는 것이 곧
# 우회였다 (26-08-05 재판정). 훅은 배포 디렉터리에서 서로를 임포트하지 못하므로(파일 이름이
# 붙임표다) 같은 글자를 두 벌 두고, `tests/test_secret_guard.py` 가 동일성을 고정한다.
#
# `-c` 는 `-ec`·`-cx` 처럼 다른 낱글자와 앞뒤로 뭉쳐 오므로, 묶음 **안 어디에나** 있으면 받는다.
_OPAQUE_CORE = (
    r"\$\(|`|\beval\b|\b(?:ba|z|k)?sh\s+-[a-z]*c[a-z]*\b|\bxargs\b"
    r"|\bpython[0-9.]*\s+-c\b|\bnode\s+-(?:e|-eval)\b|\bperl\s+-e\b|\bruby\s+-e\b"
    r"|\|\s*(?:ba|z|k)?sh\b"
)
# 읽기 쪽만 표준 입력 리다이렉션을 더 본다 — 파일을 명령에 흘려보내는 것도 읽기다.
_OPAQUE_READ = re.compile(_OPAQUE_CORE + r"|<\s*[^\s<>|&]+")


# 확장자만으로 붙는 이름표 중 **설정 키 이름과 글자로 구분되지 않는** 것. 이것만 경로 모양을
# 요구하고, 나머지 키 자재 확장자(`.pem`·`.p12`·`.pfx`·`.jks`·`.keystore`)는 이름으로 받는다.
#
# lagom: 남는 구멍은 하나다 — 경로 없는 `*.key` 를 셸 래퍼로 감싼 형태(`sh -c 'cat id.key'`).
# 같은 파일이라도 경로가 붙거나(`certs/id.key`) 안 감싸면 잡히고, 다른 키 확장자는 전부 잡힌다.
# 이 자리를 닫으려면 불투명 명령의 **토큰 자리**를 알아야 하는데, 그건 문자열을 다시 파싱한다는
# 뜻이라 이 훅이 안 하기로 한 일이다(파일 머리 주석). 대신 이 한 칸을 남기고 오탐 0을 지킨다 —
# 오탐이 쌓인 게이트는 꺼지고, 꺼진 게이트는 없는 것과 같다. 상향 경로: 셸 파서를 들이거나,
# OS 실행 경계(`asgard start --execution container|sandbox`)로 이 층 자체를 대체한다.
_AMBIGUOUS_KEY_EXT = (".key",)


def _path_shaped(token: str) -> bool:
    """이 낱말이 경로처럼 생겼는가 — 토큰 자신만 본다 (명령 전체를 보지 않는다)."""
    return token.startswith((".", "~", "/")) or "/" in token


_ASSIGN_LITERAL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_VAR_OPERAND = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")


def _expand(token: str, assigned: dict[str, str]) -> str:
    """이 명령문 안에서 리터럴로 대입된 변수 하나를 편다. 모르는 변수는 그대로 둔다."""
    m = _VAR_OPERAND.match(token)
    return assigned.get(m.group(1), token) if m else token


def _opaque_secret_read(command: str) -> str:
    """불투명한 명령문 안에 자격 파일 경로가 있는가.

    `python3 -c "print(open('.env').read())"` · `F=.env; cat $F` · `while read l; do echo $l;
    done < .env` — 셋 다 토큰 분류기에는 자격 파일이 안 보인다 (26-08-05 감사). 여기서만
    명령문 글자를 본다. 평범한 명령에 그대로 대면 `.env` 를 **설명하는** 한 줄이 유출로 읽힌다."""
    if not _OPAQUE_READ.search(command):
        return ""
    for candidate in re.findall(r"[\w./~-]*\.?[\w./~-]+", command):
        stripped = _GLOB_TAIL.sub("", candidate)
        label = secret_path(stripped)
        if not label:
            continue
        # 확장자로 붙는 `key material` 중 **모호한 것은 `.key` 하나뿐**이다 — 설정 키 이름이
        # 그 꼴로 산다(`database.key`·`api.key`). `.pem`·`.p12`·`.jks` 를 딕셔너리 키로 쓰는
        # 코드는 없으므로 그쪽은 이름만으로 받는다.
        #
        # 종전에는 "이 **명령**이 파일을 여는가"로 갈랐는데, 그건 **피연산자 단위 질문에
        # 명령 단위로 답하는** 것이라 구멍과 오탐이 동시에 났다: 패턴형 판독기는 그 검사를
        # 영영 만족 못 해 감싼 읽기가 새고, 반대로 파일 판독기 이름이 명령 어딘가에 있으면
        # 같은 명령 안의 모든 점 찍힌 낱말이 키 파일로 승격됐다 (26-08-05 4차 판정).
        # 판정은 토큰 자신만 보고 내린다.
        if label == "key material" and stripped.lower().endswith(_AMBIGUOUS_KEY_EXT) and not _path_shaped(stripped):
            continue
        return f"{label} ({candidate})"
    return ""


# 환경 전체를 쏟는 이름. 피연산자 없이 부르면 덤프다.
_ENV_DUMPERS = frozenset({"env", "printenv"})
# 환경변수·grep 패턴이 자격 증명을 겨냥하는지. `key`·`auth`는 단독으로도 인정한다 — 여기서
# 넓게 잡는 비용은 "더 좁은 패턴으로 다시 grep" 뿐이고, 좁게 잡는 비용은 키가 전사에 들어가는 것이다.
_SECRET_ENV_NAME = re.compile(r"(?i)(secret|token|password|passwd|key|auth|credential)")


def deny(protocol: str, message: str) -> None:
    """차단 응답 — Cursor는 permission JSON, Claude Code/Codex는 exit 2 + stderr (git-guard와 동일 규약)."""
    if protocol == "cursor":
        sys.stdout.write(
            json.dumps({"permission": "deny", "user_message": message, "agent_message": message}, ensure_ascii=False)
        )
        sys.exit(0)
    print(message, file=sys.stderr)
    sys.exit(2)


def secret_path(path: str) -> str:
    """경로가 자격 증명 저장소면 그 이름표, 아니면 빈 문자열. 순수 함수 — 파일을 열지 않는다."""
    if not path:
        return ""
    norm = str(path).replace("\\", "/")
    # 면제는 어느 규칙보다 먼저 — 템플릿엔 값이 없고, 공개키는 공개가 목적이다.
    if _is_template(norm) or _PUBLIC_KEY.search(norm):
        return ""
    for pattern, label in SECRET_READ_PATHS:
        if pattern.search(norm):
            return label
    return ""


def _segments(command: str) -> list[tuple[list[str], bool]]:
    """쉘 명령을 구분자로 쪼갠 (토큰, 이_세그먼트가_파이프로_이어지는가) 목록.

    파이프 여부를 버리면 `env`와 `env | grep -i asgard`를 구별하지 못한다 — 앞은 전체 환경이
    전사에 들어가고 뒤는 grep이 거른 몇 줄만 들어간다 (26-07-27 실코퍼스: 히트 23건 중 다수가
    후자였다). 렉싱 실패는 빈 목록 — 판정 불능은 허용이다(fail-open)."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except Exception:
        return []
    out: list[tuple[list[str], bool]] = []
    current: list[str] = []
    for token in tokens:
        if token and all(ch in "|&;<>" for ch in token):
            if current:
                out.append((current, token == "|"))
            current = []
            continue
        current.append(token)
    if current:
        out.append((current, False))
    return out


# 앞 명령의 출력을 걸러 내보내는 도구 — 뒤에 오면 전체 덤프가 전사에 실리지 않는다.
_FILTERS = frozenset({"grep", "rg", "ag", "egrep", "fgrep", "ack"})


def _filtered_to_safety(following: list[str]) -> bool:
    """`env | grep X`의 X가 시크릿 이름이 아니면 통과 — 걸러진 몇 줄만 나간다.
    grep 계열이 아니면(sort·cat·tee 등) 전량이 그대로 흐르므로 안전하지 않다."""
    program, args = _program(following)
    if program not in _FILTERS:
        return False
    patterns = [a for a in args if not a.startswith("-")]
    return bool(patterns) and not any(_SECRET_ENV_NAME.search(p) for p in patterns)


def _program(tokens: list[str]) -> tuple[str, list[str]]:
    """선행 `VAR=x` 대입과 sudo를 제거한 (프로그램, 인자). `env FOO=1 cmd`의 cmd를 본다."""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if "=" in token and not token.startswith("-") and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
            index += 1
            continue
        if os.path.basename(token) in {"sudo", "command", "nohup"}:
            index += 1
            continue
        break
    if index >= len(tokens):
        return "", []
    return os.path.basename(tokens[index]), tokens[index + 1 :]


def secret_command(command: str) -> str:
    """명령이 자격 증명을 쏟으면 사유, 아니면 빈 문자열."""
    if not command:
        return ""
    if opaque := _opaque_secret_read(command):
        return f"credential file read via an opaque command — {opaque}"
    segments = _segments(command)
    # 피연산자 자리의 변수를 한 겹 편다 — `F=.env; cat $F` 는 `cat .env` 다. 리터럴 대입만,
    # 한 겹만 (값이 또 변수거나 명령 치환이면 위 `_opaque_secret_read` 가 이미 받는다).
    assigned: dict[str, str] = {}
    for tokens, _ in segments:
        for token in tokens:
            m = _ASSIGN_LITERAL.match(token)
            if m and m.group(2) and not m.group(2).startswith("$"):
                assigned[m.group(1)] = m.group(2)
    for index, (tokens, piped) in enumerate(segments):
        program, args = _program(tokens)
        if not program:
            continue
        operands = [_expand(a, assigned) for a in args if not a.startswith("-")]
        if program in _ENV_DUMPERS:
            # `env FOO=1 cmd`는 실행이지 덤프가 아니다 — _program이 이미 걷어냈으므로 여기
            # 도달한 env는 피연산자가 없거나(전체 덤프) 시크릿 이름을 콕 집은 경우다.
            if any(_SECRET_ENV_NAME.search(name) for name in operands):
                return f"{program} of a credential variable"
            if operands:
                continue
            following = segments[index + 1][0] if piped and index + 1 < len(segments) else []
            if following and _filtered_to_safety(following):
                continue  # grep이 시크릿 아닌 이름으로 걸렀다 — 전체 환경은 나가지 않는다
            return f"{program} (full environment dump)"
        if program in _READERS:
            # 패턴형은 첫 비플래그 인자를 버린다 — 그건 찾을 글자다 (`grep <패턴> <경로들>`).
            if program in _PATTERN_READERS:
                operands = operands[1:]
            for operand in operands:
                # 글롭 꼬리를 벗기고 본다 — `cat .env*` 가 경로 정규식의 `$` 앵커를 깨고
                # 통째로 빠져나갔다 (26-08-05 감사).
                label = secret_path(operand) or secret_path(_GLOB_TAIL.sub("", operand))
                if label:
                    return f"{program} of {label} ({operand})"
            continue
        for wanted, needles, label in SECRET_READ_COMMANDS:
            if program == wanted and all(needle in args for needle in needles):
                return label
        if program == "kubectl" and "secret" in args and any(a in args for a in ("-o", "--output", "describe")):
            return "kubectl secret read"
        # 판독기 이름 목록은 전수일 수 없다. 목록 밖의 프로그램이 자격 파일을 **피연산자로**
        # 받는 형태는 종전에 통째로 빠져나갔다 — `python3 dump.py .env` · `./tool --config .env`
        # 셋 다 통과했다 (26-08-13 실측). 이름을 모르는 프로그램이라도 그 파일을 인자로 받는
        # 것이 근거다: 무엇을 하는지 모르는 것과 안전한 것은 다르다.
        #
        # 공백이 든 피연산자는 경로가 아니라 글이다 (`codex exec '... .env ...'`). 그 자리를
        # 함께 잡으면 자격 파일을 **설명하는** 명령이 유출로 읽힌다 — 이 가드가 26-08-13 에
        # 실제로 그렇게 퀘스트 개봉 한 줄을 막았다.
        for operand in operands:
            if " " in operand:
                continue
            label = secret_path(operand) or secret_path(_GLOB_TAIL.sub("", operand))
            if label:
                return f"{program} of {label} ({operand})"
    return ""


# ── 훅 ──────────────────────────────────────────────────────────────────────────
_WRITE_TOOLS = {"write", "edit", "notebookedit", "apply_patch", "applypatch", "multiedit", "delete", "update"}
_READ_TOOLS = {"read", "grep", "glob", "notebookread", "search", "readfile"}


def main() -> None:
    protocol = sys.argv[1] if len(sys.argv) > 1 else "claude"
    try:
        data = json.load(sys.stdin)
        ti = data.get("tool_input") or {}
    except Exception:
        sys.exit(0)
    tool = str(data.get("tool_name") or data.get("tool") or "").lower()
    path = str(ti.get("file_path") or ti.get("path") or "")
    # Write는 content, Edit은 new_string에 본문이 들어간다 — 합쳐서 한 번에 검사.
    # Codex의 apply_patch는 패치 텍스트 한 덩어리라 patch/command도 같은 본문으로 본다.
    text = " ".join(str(x) for x in (ti.get("content"), ti.get("new_string"), ti.get("patch")) if x)
    command = str(ti.get("command") or "")

    # ── 읽기 측 — 이름이 근거. 내용을 보기 전에 막아야 의미가 있다 ──
    if tool in _READ_TOOLS or (not tool and not text and not command and path):
        if label := secret_path(path):
            deny(
                protocol,
                f"Asgard Canon Law 4 — read blocked: {path} is a {label}. "
                "Credentials must never enter the transcript; every turn re-sends it to the model provider. "
                "Ask Odin for the value, or reference the variable name instead of its content.",
            )
    if command:
        if reason := secret_command(command):
            deny(
                protocol,
                f"Asgard Canon Law 4 — command blocked: {reason}. "
                "Credentials must never enter the transcript; every turn re-sends it to the model provider.",
            )

    # ── 쓰기 측 — 내용이 근거 ──
    if tool in _WRITE_TOOLS or not tool or text:
        # .env, .env.local 등 실제 시크릿 파일은 경로만으로 차단(내용 검사 전에) —
        # 단 .env.example/sample/template/dist는 공유용 템플릿이므로 허용.
        if _ENV_FILE.search(path.replace("\\", "/")) and not _ENV_TEMPLATE.search(path):
            deny(protocol, "Asgard Canon Law 4 — .env write blocked: " + path + " (secrets are not committed).")
        for pat, label in SECRET:
            if re.search(pat, text):
                deny(protocol, "Asgard Canon Law 4 — possible secret (" + label + ") blocked: " + path)
    # 같은 표를 명령문에도 댄다. 종전에는 `content`/`new_string`/`patch` 필드만 봐서, Bash 로
    # 적은 자격 증명(`echo 'AKIA…' > creds.txt`)은 그 필드가 없다는 이유로 검사 자체를 안 받았다
    # — 같은 리터럴을 `Write` 툴로 쓰면 거부되는데 (26-08-05 감사). 리터럴이 명령문에 있는 순간
    # 이미 전사에 들어간 것이라, 파일에 닿기 전에 막는 것이 이 계약의 요점이다.
    if command:
        for pat, label in SECRET:
            if re.search(pat, command):
                deny(
                    protocol,
                    f"Asgard Canon Law 4 — possible secret ({label}) in a command. "
                    "Credentials must never enter the transcript; every turn re-sends it to the model provider.",
                )

    if protocol == "cursor":  # Cursor는 침묵을 허용으로 안 본다 — 명시적 allow가 프로토콜 요구사항.
        sys.stdout.write(json.dumps({"permission": "allow"}, separators=(",", ":")))
    sys.exit(0)


if __name__ == "__main__":
    run("secret-guard", main)
