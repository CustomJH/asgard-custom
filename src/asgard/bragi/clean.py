"""검사 사본 — 원문 보존 계약 대상(코드·인용·URL·경로)을 지운 두 벌.

원문은 바꾸지 않는다. 사본이 둘인 이유는 규칙마다 봐야 할 경계가 달라서다 (`_SPAN_SENSITIVE`).
"""

from __future__ import annotations

import re

# ── 검사 사본 — 원문 보존 계약 대상(코드·인용·URL·경로)은 지운다. 원문은 바꾸지 않는다.
_PATH = re.compile(r"(?:[\w.-]+/){1,}[\w.-]+|\b\w+\.(?:py|js|ts|tsx|md|json|toml|yaml|yml|sh|rs|go|java)\b")
_DATA_LINE = re.compile(r"""^\s*(?:[{}\[\]]\s*,?\s*$|["'][^"']+["']\s*:|[\w.-]+\s*[:=]\s*["'{\[\d])""")


def lintable(text: str) -> str:
    """코드 블록·인용·인라인 코드·URL·링크 대상·파일 경로·구조화 데이터 행을 지운 검사 사본.

    데이터 행을 남기면 JSON의 쉼표가 산문의 쉼표로 계산된다 (26-07-26 실측: 독스트링 안의
    예시 JSON 하나가 쉼표 밀도 자질을 통째로 오탐시켰다)."""
    out: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or line.lstrip().startswith(">"):
            continue
        if _DATA_LINE.match(line):  # `"key": value,` · `{` · `- key: value` 같은 데이터 행
            continue
        line = re.sub(r"`[^`]*`", "", line)
        line = re.sub(r"https?://\S+", "", line)
        line = re.sub(r"\]\([^)]*\)", "]", line)
        line = _PATH.sub("", line)
        out.append(line)
    return "\n".join(out)


def lintable_spans(text: str) -> str:
    """맞춤법 검사용 사본 — 블록만 제거하고 인라인 코드·경로·URL은 원문대로 둔다.

    lintable()은 보존 계약 대상을 지운다. 조사 띄어쓰기는 앞말과 조사가 맞닿은 자리를 보는
    규칙이라, 앞말을 지우면 검사할 경계가 함께 사라진다 (`config.py를`가 `를`로 남는다).
    여기서 코드를 남겨도 산문 흔적이 오탐되지 않는다 — 이 사본을 쓰는 규칙은 라틴 낱말 뒤에
    떨어져 선 한국어 조사만 보고, 한국어 조사는 코드 안에 나오지 않는다. 남겨 두면 보고되는
    표본도 자리표가 아니라 사람이 고칠 수 있는 원문이 된다."""
    out: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or line.lstrip().startswith(">"):
            continue
        if _DATA_LINE.match(line):
            continue
        out.append(line)
    return "\n".join(out)


# 자리표 사본에서 돌아야 하는 흔적 — 보존 계약 대상과 산문이 맞닿은 경계를 보는 규칙.
_SPAN_SENSITIVE = frozenset({"KO-josa-spacing"})
