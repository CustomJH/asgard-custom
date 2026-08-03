"""asgard thor gate — 이번 변경분의 백엔드 **정확성** 판정. `craft`가 형상을 재면 이쪽은 정확성이다.

왜 craft와 한 명령이 아닌가: 두 게이트의 판정 근거가 다르다. craft는 이 저장소가 스스로 정한
예산(함수 길이·중첩)을 재고, 여기는 언어와 무관하게 **틀린 것**을 잰다 — 값 자리의 문자열 보간은
어느 저장소에서도 틀렸고, 예산처럼 조정할 여지가 없다. 둘을 섞으면 "예산을 올리자"는 대화가
"바인딩을 쓰자"는 판정까지 끌고 들어온다.

래칫은 craft와 같다 — **이미 있던 것은 막지 않는다. 이번 변경이 더 나쁘게 만든 것만 막는다.**
그리고 하나 더 진다: **무엇을 못 쟀는지 같이 넣는다.**이 게이트는 언어마다 판정할 수 있는
규칙 수가 다르다(Python 7 · 중괄호 계열 3 · 그 밖 0). "0건"이 "안 봤다"를 뜻할 수 있으면 게이트가
아니라 알리바이가 된다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import craft_rules, thor_lex, thor_rules
from .craft import _base_text, changed_paths
from .craft_lex import units as lex_units
from .craft_rules import Finding, Unit
from .health import _read, borrowed

# 언어별로 실제 발화하는 규칙 — 미측정을 정직하게 세기 위한 단일 출처.
PYTHON_RULES = (
    "sql-interpolated",
    "swallowed-exception",
    "call-no-timeout",
    "secret-literal",
    "tx-external-io",
    "money-float",
    "naive-now",
)
LEX_RULES = ("sql-interpolated", "swallowed-exception", "secret-literal")
# JVM은 타입 선언과 애너테이션이 있어 둘을 더 잰다 (thor_lex 모듈 docstring 참조).
JVM_RULES = LEX_RULES + ("money-float", "tx-external-io")
_NO_CATCH = ("go", "rust")
_JVM = ("java", "kotlin")


@dataclass(frozen=True)
class Report:
    base: str
    judged: tuple[str, ...]
    undetermined: tuple[tuple[str, str], ...]  # (경로, 사유) — 조용한 절단 금지
    findings: tuple[Finding, ...]
    inherited: int  # 물려받은 부채로 분류해 넘긴 건수 (래칫이 일한 양)
    unmeasured: tuple[tuple[str, tuple[str, ...]], ...]  # (경로, 이 파일에서 못 잰 규칙들)

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.blocking)


def _spans(text: str, lang: str) -> list[Unit]:
    """함수 귀속용 단위. 못 읽어도 판정은 계속한다 — 귀속이 빈 문자열이 될 뿐이다."""
    units = craft_rules.units(text) if lang == "python" else lex_units(text, lang)
    return list(units.values()) if units else []


def _rules_for(lang: str) -> tuple[str, ...]:
    if lang == "python":
        return PYTHON_RULES
    fired = JVM_RULES if lang in _JVM else LEX_RULES
    return tuple(r for r in fired if not (r == "swallowed-exception" and lang in _NO_CATCH))


def _language(rel: str) -> str | None:
    return "python" if rel.endswith(".py") else thor_lex.lang_of(rel)


def _findings(text: str, rel: str, lang: str) -> list[Finding] | None:
    spans = _spans(text, lang)
    if lang == "python":
        return thor_rules.findings(text, rel, spans)
    return thor_lex.findings(text, rel, spans, lang)


def _key(finding: Finding) -> tuple[str, str, str]:
    """행 번호는 빼고 비교한다 — 위쪽에 한 줄 넣었다고 물려받은 부채가 새 부채가 되면 안 된다."""
    return (finding.rule, finding.unit, finding.detail)


def _judge_file(root: str, rel: str, base: str) -> tuple[list[Finding], int, str | None, tuple[str, ...]]:
    """(판정, 물려받아 넘긴 건수, 미판정 사유, 못 잰 규칙)."""
    if why := borrowed(rel):
        return ([], 0, why, ())
    text = _read(root, rel)
    if text is None:
        return ([], 0, "읽지 못했어요", ())
    lang = _language(rel)
    if lang is None:
        return ([], 0, "판정기가 모르는 언어예요 — 백엔드 정확성은 못 쟀어요", ())
    found = _findings(text, rel, lang)
    if found is None:
        return ([], 0, "구문을 읽지 못해서 판정에서 빠졌어요", ())
    before = _base_text(root, rel, base)
    inherited_keys: set[tuple[str, str, str]] = set()
    if before is not None:
        prior = _findings(before, "", lang)
        inherited_keys = {_key(f) for f in prior or ()}
    fresh = [f for f in found if _key(f) not in inherited_keys]
    missing = tuple(r for r in PYTHON_RULES if r not in _rules_for(lang))
    return (fresh, len(found) - len(fresh), None, missing)


def judge(root: str, paths: object, base: str = "HEAD") -> Report:
    rels = _normalise(paths)
    findings: list[Finding] = []
    judged: list[str] = []
    unknown: list[tuple[str, str]] = []
    unmeasured: list[tuple[str, tuple[str, ...]]] = []
    inherited = 0
    for rel in rels:
        found, passed, why, missing = _judge_file(root, rel, base)
        if why:
            unknown.append((rel, why))
            continue
        judged.append(rel)
        inherited += passed
        findings.extend(found)
        if missing:
            unmeasured.append((rel, missing))
    return Report(base, tuple(judged), tuple(unknown), tuple(findings), inherited, tuple(unmeasured))


def _normalise(paths: object) -> list[str]:
    if not isinstance(paths, (list, tuple, set, frozenset)):
        return []
    return sorted({rel for raw in paths if (rel := str(raw).strip().replace(os.sep, "/"))})


__all__ = ["LEX_RULES", "PYTHON_RULES", "Report", "changed_paths", "judge"]
