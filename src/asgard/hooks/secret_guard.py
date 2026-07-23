#!/usr/bin/env python3
# Asgard secret-guard — Canon Law 4 (시크릿 보호). 시크릿이 "파일에 기록되는 순간"을 차단 지점으로
# 삼는다 (Write/Edit PreToolUse, {"tool_input": {...}}). 에이전트가 시크릿을 남기는 경로의 대부분이
# 파일 쓰기라서다. 알려진 구멍: shell 우회(echo SECRET > .env)는 안 잡는다 — 필요해지면 git-guard 처럼
# pre-shell 검사 추가.
# 왜 fail-open 인가: 가드 오류로 모든 편집이 막히면 안 된다. exit 2 = 차단, 그 외 = 허용.
import json
import re
import sys

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 싣지 못한다 — 인코딩 오류가
# fail-open 에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except 로
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


def main() -> None:
    try:
        ti = json.load(sys.stdin).get("tool_input") or {}
    except Exception:
        sys.exit(0)
    path = str(ti.get("file_path") or "")
    # Write 는 content, Edit 은 new_string 에 본문이 실린다 — 합쳐서 한 번에 검사.
    text = " ".join(str(x) for x in (ti.get("content"), ti.get("new_string")) if x)
    # .env, .env.local 등 실제 시크릿 파일은 경로만으로 차단(내용 검사 전에) —
    # 단 .env.example/sample/template/dist 는 공유용 템플릿이므로 허용.
    if re.search(r"(^|/)\.env(\.[^/]*)?$", path) and not re.search(r"\.env\.(example|sample|template|dist)$", path):
        print("Asgard Canon Law 4 — .env write blocked: " + path + " (secrets are not committed).", file=sys.stderr)
        sys.exit(2)
    for pat, label in SECRET:
        if re.search(pat, text):
            print("Asgard Canon Law 4 — possible secret (" + label + ") blocked: " + path, file=sys.stderr)
            sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
