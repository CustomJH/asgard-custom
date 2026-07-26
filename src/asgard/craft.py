"""asgard craft — 이번 변경분의 미시 형상 판정. `health` 가 나무를 재면 이쪽은 **손댄 자리**를 잰다.

왜 따로인가: health 는 추세를 산출물로 내고 아무것도 막지 않는다(모듈 docstring 참조). 그런데
추세는 이미 악화 방향이고, 추세를 되돌리는 행위는 항상 "다음 한 번의 변경"에서 일어난다. 나무
전체를 판정하면 43,000행의 기존 부채가 전부 걸려 아무 작업도 못 하고, 아무것도 판정하지 않으면
같은 부채가 매 턴 조금씩 늘어난다. 그래서 이 모듈의 계약은 **래칫** 하나다:

    이미 있던 것은 막지 않는다. 이번 변경이 **더 나쁘게 만든 것**만 막는다.

규칙 자체는 `craft_rules` 가 갖는다 — 이 파일이 아는 것은 base 를 어떻게 구하고, 무엇을 이번
변경의 책임으로 볼지, 그리고 못 판정한 것을 어떻게 정직하게 실을지뿐이다.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from .craft_rules import Finding, pattern_findings, shape_findings, units
from .health import FILE_LINES_WARN, _code_lines, _read


@dataclass(frozen=True)
class Report:
    base: str
    judged: tuple[str, ...]  # 실제로 판정한 파일
    undetermined: tuple[tuple[str, str], ...]  # (경로, 사유) — 조용한 절단 금지
    findings: tuple[Finding, ...]
    inherited: int  # 기존 부채로 분류해 막지 않은 건수 (래칫이 일한 양)

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.blocking)


# ── 판정 ───────────────────────────────────────────────────────────


def _base_text(root: str, rel: str, base: str) -> str | None:
    try:
        proc = subprocess.run(["git", "show", f"{base}:{rel}"], cwd=root, capture_output=True, text=True, timeout=20)
    except OSError, subprocess.SubprocessError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _file_note(rel: str, text: str, before: str | None) -> list[Finding]:
    """파일이 커진 것은 알리되 막지 않는다 — 큰 파일을 못 건드리게 하면 수리 자체가 멈춘다."""
    size = len(_code_lines(text, "Python"))
    if size <= FILE_LINES_WARN:
        return []
    prior = len(_code_lines(before, "Python")) if before is not None else 0
    if before is not None and size <= prior:
        return []
    return [
        Finding(
            "file-growth",
            rel,
            1,
            "",
            f"{size:,}행 (문턱 {FILE_LINES_WARN:,}행" + (f", 이전 {prior:,}행" if before else ", 신규") + ")",
            "이번 변경을 막지는 않는다 — 다음 기능을 여기 얹기 전에 경계를 하나 그어라",
            blocking=False,
        )
    ]


def _judge_file(root: str, rel: str, base: str) -> tuple[list[Finding], int, str | None]:
    """(판정, 물려받아 넘긴 건수, 미판정 사유)."""
    text = _read(root, rel)
    if text is None:
        return ([], 0, "읽지 못했다")
    current = units(text)
    if current is None:
        return ([], 0, "파싱 실패")
    before = _base_text(root, rel, base)
    prior_units = units(before) if before is not None else None
    spans = list(current.values())
    found = shape_findings(rel, current, prior_units)
    leaks = pattern_findings(text, rel, spans)
    inherited_keys = _inherited(before)
    fresh = [f for f in leaks if (f.rule, f.unit, f.detail) not in inherited_keys]
    found.extend(fresh)
    found.extend(_file_note(rel, text, before))
    return (found, len(leaks) - len(fresh), None)


def _inherited(before: str | None) -> set[tuple[str, str, str]]:
    """base 에 이미 있던 누수 형상 — 물려받은 부채는 이번 변경의 책임이 아니다."""
    if before is None:
        return set()
    prior = units(before)
    if prior is None:
        return set()
    return {(f.rule, f.unit, f.detail) for f in pattern_findings(before, "", list(prior.values()))}


def judge(root: str, paths: object, base: str = "HEAD") -> Report:
    """지목된 경로만 판정한다 — 나무 전수 스캔은 health 의 일이다."""
    rels = _normalise(paths)
    findings: list[Finding] = []
    judged: list[str] = []
    unknown: list[tuple[str, str]] = []
    inherited = 0
    for rel in rels:
        if not rel.endswith(".py"):
            unknown.append((rel, "Python 아님 — 함수 단위·자원 수명 미측정"))
            continue
        found, passed, why = _judge_file(root, rel, base)
        if why:
            unknown.append((rel, why))
            continue
        judged.append(rel)
        inherited += passed
        findings.extend(found)
    return Report(base, tuple(judged), tuple(unknown), tuple(findings), inherited)


def _normalise(paths: object) -> list[str]:
    if not isinstance(paths, (list, tuple, set, frozenset)):
        return []
    return sorted({rel for raw in paths if (rel := str(raw).strip().replace(os.sep, "/"))})


def changed_paths(root: str, base: str = "HEAD") -> tuple[str, ...]:
    """base 대비 작업 트리에서 달라진 경로 + 추적되지 않은 새 파일."""
    out: list[str] = []
    for args in (["diff", "--name-only", base], ["ls-files", "--others", "--exclude-standard"]):
        try:
            proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
        except OSError, subprocess.SubprocessError:
            continue
        if proc.returncode == 0:
            out.extend(line.strip() for line in proc.stdout.splitlines() if line.strip())
    return tuple(sorted(set(out)))
