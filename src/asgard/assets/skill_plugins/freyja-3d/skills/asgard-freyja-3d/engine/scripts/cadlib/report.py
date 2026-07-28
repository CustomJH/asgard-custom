"""판정 어휘 — 이 런타임이 무엇을 확인했고 무엇을 못 했는지 한 가지 방식으로만 말한다.

왜 자료구조가 필요한가. CAD 검증의 사고는 "틀린 답을 냈다"보다 **"안 한 검사를 했다고 적었다"**
쪽에서 훨씬 자주 난다. 측정이 예외로 죽었는데 보고에는 그 줄이 아예 없으면, 읽는 사람은 통과로
읽는다. 그래서 등급을 셋으로 고정한다:

    pass   실제로 돌렸고 기준을 만족했다
    warn   못 잰 것, 또는 기준 미달이지만 배달을 막을 근거는 못 되는 것 = **미확인**
    fail   실제로 돌렸고 기준을 어겼다

`warn` 을 "가벼운 fail" 로 쓰지 않는다. 여기서 warn 은 **판정 불능**이 정본 의미다. 이 구분이
흐려지면 보고가 다시 거짓말을 시작한다.

종료코드도 같은 축에 붙는다: fail 이 하나라도 있으면 1, 아니면 0. warn 은 종료코드를 바꾸지
않는다 — 미확인은 실패가 아니지만, 보고문에서는 절대 생략되지 않는다.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

LEVELS = ("pass", "warn", "fail")


@dataclass(frozen=True)
class Check:
    """검사 하나의 결과. `id` 는 기계가 잡는 손잡이고, `message` 는 사람이 읽는 문장이다."""

    id: str
    level: str
    message: str
    data: dict | None = None

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError(f"모르는 판정 등급이다: {self.level}")

    def as_dict(self) -> dict:
        entry: dict = {"id": self.id, "level": self.level, "message": self.message}
        if self.data:
            entry["data"] = self.data
        return entry


@dataclass
class Report:
    """한 도구 실행의 전체 결과. 사실(`facts`)과 판정(`checks`)을 섞지 않는다."""

    tool: str
    target: str = ""
    facts: dict = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)

    def add(self, id: str, level: str, message: str, data: dict | None = None) -> Check:
        check = Check(id=id, level=level, message=message, data=data)
        self.checks.append(check)
        return check

    def ok(self, id: str, message: str, data: dict | None = None) -> Check:
        return self.add(id, "pass", message, data)

    def unverified(self, id: str, message: str, data: dict | None = None) -> Check:
        """잴 수 없었다. 통과가 아니라 미확인이다 — 이 메서드 이름이 그 사실을 강제한다."""
        return self.add(id, "warn", message, data)

    def fail(self, id: str, message: str, data: dict | None = None) -> Check:
        return self.add(id, "fail", message, data)

    @property
    def verdict(self) -> str:
        if any(check.level == "fail" for check in self.checks):
            return "fail"
        if any(check.level == "warn" for check in self.checks):
            return "warn"
        return "pass"

    @property
    def exit_code(self) -> int:
        return 1 if self.verdict == "fail" else 0

    def as_dict(self) -> dict:
        return {
            "tool": self.tool,
            "target": self.target,
            "facts": self.facts,
            "checks": [check.as_dict() for check in self.checks],
            "verdict": self.verdict,
        }

    def render(self) -> str:
        """사람이 읽는 표. 미확인 줄은 생략되지 않는다 — 그것이 이 함수의 존재 이유다."""
        lines: list[str] = []
        if self.target:
            lines.append(f"{self.tool} — {self.target}")
        else:
            lines.append(self.tool)
        for key, value in self.facts.items():
            lines.append(f"  {key:<22} {_scalar(value)}")
        if self.checks:
            lines.append("")
            for check in self.checks:
                lines.append(f"  [{check.level.upper():<4}] {check.id:<24} {check.message}")
        unverified = sum(1 for check in self.checks if check.level == "warn")
        tail = f"  판정 {self.verdict.upper()}"
        if unverified:
            tail += f" — 미확인 {unverified}건 (통과로 세지 않는다)"
        lines.append("")
        lines.append(tail)
        return "\n".join(lines)

    def emit(self, as_json: bool) -> int:
        stream = sys.stdout
        if as_json:
            stream.write(json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + "\n")
        else:
            stream.write(self.render() + "\n")
        return self.exit_code


def _scalar(value: object) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (list, tuple)):
        return " × ".join(_scalar(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def utf8_console() -> None:
    """한국어 Windows(cp949)·서구권 Windows(cp1252) 콘솔에서 보고문이 마지막 write 에 죽는 것을 막는다.

    실측 사고: 진단을 다 만들어놓고 `'cp949' codec can't encode character '—'` 로 종료.
    저장소 본체가 같은 결함을 두 번 고쳤고 스킬 스크립트는 그 청소에서 빠져 있었다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute]
        except Exception:
            pass
