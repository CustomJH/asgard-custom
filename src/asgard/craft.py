"""asgard craft — 이번 변경분의 미시 형상 판정. `health`가 나무를 재면 이쪽은 **손댄 자리**를 잰다.

왜 따로인가: health는 추세를 산출물로 내고 아무것도 막지 않는다(모듈 docstring 참조). 그런데
추세는 이미 악화 방향이고, 추세를 되돌리는 행위는 항상 "다음 한 번의 변경"에서 일어난다. 나무
전체를 판정하면 43,000행의 기존 부채가 전부 걸려 아무 작업도 못 하고, 아무것도 판정하지 않으면
같은 부채가 매 턴 조금씩 늘어난다. 그래서 이 모듈의 계약은 **래칫** 하나다:

    이미 있던 것은 막지 않는다. 이번 변경이 **더 나쁘게 만든 것**만 막는다.

규칙 자체는 `craft_rules`가 갖는다 — 이 파일이 아는 것은 base를 어떻게 구하고, 무엇을 이번
변경의 책임으로 볼지, 그리고 못 판정한 것을 어떻게 정직하게 실을지뿐이다.

base를 구하는 일에는 조건이 하나 더 붙는다: **개명은 기준선을 지우는 사건이 아니다.** 기준선을
경로로만 찾으면 파일을 옮긴 것만으로 그 파일의 물려받은 위반이 전부 신규로 뒤집힌다(`_Origin`
참조). 래칫의 두 반쪽 — 물려받은 것은 통과, 나빠진 것은 차단 — 중 앞쪽이 경로에 매여 있으면
안 된다.
"""

from __future__ import annotations

import os
import subprocess
from collections import Counter
from dataclasses import dataclass

from . import craft_c, craft_lex, craft_note, craft_rules
from .craft_rules import Finding, Unit, shape_findings
from .health import FILE_LINES_WARN, _code_lines, _read, borrowed

# 언어 → health의 주석 규약 이름 (코드 행 수를 언어에 맞게 센다)
_COMMENT_LANG = {
    "python": "Python", "c": "C", "cpp": "C++", "java": "Java", "kotlin": "Kotlin",
    "go": "Go", "rust": "Rust", "csharp": "C#", "swift": "Swift", "ts": "TypeScript",
}  # fmt: skip


@dataclass(frozen=True)
class Report:
    base: str
    judged: tuple[str, ...]  # 실제로 판정한 파일
    undetermined: tuple[tuple[str, str], ...]  # (경로, 사유) — 조용한 절단 금지
    findings: tuple[Finding, ...]
    inherited: int  # 기존 부채로 분류해 막지 않은 건수 (래칫이 일한 양)
    moved: tuple[tuple[str, str], ...] = ()  # (지금 경로, base의 옛 경로) — 기준선을 이어붙인 자리

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.blocking)


# ── base 원본 찾기 ─────────────────────────────────────────────────


def _git(root: str, args: list[str], timeout: int = 20) -> str | None:
    """git 한 번. 실패는 None — 못 물어본 것과 답이 빈 것은 다르다."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except OSError, subprocess.SubprocessError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _show(root: str, base: str, rel: str) -> str | None:
    return _git(root, ["show", f"{base}:{rel}"])


def _moves(root: str, base: str) -> dict[str, str]:
    """git 이 개명으로 읽은 짝 — 지금 경로 → base 의 옛 경로. `-z` 는 경로에 든 탭·따옴표 때문이다.

    `--diff-filter=R` 이라 모든 기록이 (상태, 옛 경로, 지금 경로) 세 칸으로 온다.
    """
    fields = (_git(root, ["diff", "-M", "-z", "--name-status", "--diff-filter=R", base]) or "").split("\0")
    return {fields[i + 2]: fields[i + 1] for i in range(0, len(fields) - 2, 3) if fields[i].startswith("R")}


def _deletions(root: str, base: str) -> tuple[str, ...]:
    """base 에는 있고 지금은 없는 경로 — 이동의 출발점 후보. `-M` 을 안 주는 이유는 개명으로
    짝지어진 것까지 후보에 남기기 위해서다(짝을 이미 아는 경로는 아래에서 먼저 걸러진다)."""
    raw = _git(root, ["diff", "-z", "--name-only", "--diff-filter=D", base]) or ""
    return tuple(path for path in raw.split("\0") if path)


_MOVE_SIMILARITY = 0.5  # git 의 -M 기본 문턱과 같은 값 — 게이트가 git 과 다른 답을 내면 안 된다


def _similarity(before: str, after: str) -> float:
    """두 본문이 얼마나 같은가 — 줄 다중집합의 겹침 비율(0.0~1.0).

    빈 줄을 뺀다: 관계 없는 두 파일도 빈 줄과 `from __future__ import annotations` 는 공유하고,
    짧은 파일일수록 그 공유분이 비율을 밀어 올린다.
    """
    left = Counter(line for line in before.splitlines() if line.strip())
    right = Counter(line for line in after.splitlines() if line.strip())
    total = sum(left.values()) + sum(right.values())
    return 2 * sum((left & right).values()) / total if total else 0.0


class _Origin:
    """base 쪽 원본을 찾아 준다 — 경로가 바뀌어도 같은 파일이면 같은 원본을 준다.

    기준선을 경로로만 찾으면 개명이 곧 기준선 삭제다. 그러면 물려받던 위반이 전부 이번 변경의
    책임으로 뒤집혀서, 파일 하나를 옮긴 것이 수십 건의 차단으로 돌아온다. 그때 사람이 하는 일은
    판정을 고치는 것이 아니라 게이트를 끄는 것이고, 그러면 규율이 통째로 사라진다.

    조회는 세 단이다. ① 같은 경로 ② git 이 개명으로 읽은 짝 (`git mv` 로 색인에 오른 이동)
    ③ 색인에 없는 이동 — 추적되지 않은 새 파일은 diff 에 안 나오므로, base 에서 사라진 같은
    확장자 파일 중 내용이 가장 닮은 것을 원본으로 본다.

    셋 다 빗나가면 신규 파일로 본다. 못 찾은 자리를 통과로 뭉개면 진짜 신규 파일의 결함이 전부
    빠져나가고, 래칫이 막아야 할 절반을 잃는다.
    """

    def __init__(self, root: str, base: str) -> None:
        self._root = root
        self._base = base
        self._renamed: dict[str, str] | None = None
        self._dropped: tuple[str, ...] | None = None
        self._texts: dict[str, str | None] = {}
        self.moved: dict[str, str] = {}  # 개명을 따라가 기준선을 이은 자리 — 보고에 들어간다

    def text(self, rel: str, current: str) -> str | None:
        """rel 의 base 쪽 본문. `current` 는 ③단에서 닮은 정도를 재는 데만 쓴다."""
        direct = self._at(rel)
        if direct is not None:
            return direct
        source = self._renames().get(rel) or self._nearest(rel, current)
        if source is None:
            return None
        self.moved[rel] = source
        return self._at(source)

    def _at(self, rel: str) -> str | None:
        if rel not in self._texts:
            self._texts[rel] = _show(self._root, self._base, rel)
        return self._texts[rel]

    def _renames(self) -> dict[str, str]:
        if self._renamed is None:
            self._renamed = _moves(self._root, self._base)
        return self._renamed

    def _nearest(self, rel: str, current: str) -> str | None:
        suffix = os.path.splitext(rel)[1]
        best: str | None = None
        score = _MOVE_SIMILARITY
        for gone in self._gone():
            before = self._at(gone) if gone.endswith(suffix) else None
            if before is None:
                continue
            ratio = _similarity(before, current)
            if ratio > score:
                best, score = gone, ratio
        return best

    def _gone(self) -> tuple[str, ...]:
        if self._dropped is None:
            self._dropped = _deletions(self._root, self._base)
        return self._dropped


def _base_text(root: str, rel: str, base: str) -> str | None:
    """base 쪽 본문 하나 — 조회기를 들고 있지 않는 호출자를 위한 한 발 진입점.

    thor_gate·freyja_gate 도 같은 래칫을 걸고 같은 경로 종속을 진다. 셋이 이 함수를 지나가면
    개명을 같은 규칙으로 읽는다 — 게이트마다 답이 다르면 그것이 곧 게이트를 못 믿는 이유가 된다.

    같은 경로에 있으면 조회기를 세우지 않는다. 대부분의 파일이 이쪽이고, 개명 목록을 묻는 git
    호출은 실제로 빗나간 자리에서만 낸다.
    """
    direct = _show(root, base, rel)
    if direct is not None:
        return direct
    return _Origin(root, base).text(rel, _read(root, rel) or "")


# ── 판정 ───────────────────────────────────────────────────────────


def _file_note(rel: str, text: str, before: str | None, lang: str) -> list[Finding]:
    """파일이 커진 것은 알리되 막지 않는다 — 큰 파일을 못 건드리게 하면 수리 자체가 멈춘다."""
    marker = _COMMENT_LANG.get(lang, "Python")
    size = len(_code_lines(text, marker))
    if size <= FILE_LINES_WARN:
        return []
    prior = len(_code_lines(before, marker)) if before is not None else 0
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


def _language(rel: str) -> str | None:
    """판정 가능한 언어인가. Python은 구문 트리로, 중괄호 계열은 어휘로 잰다."""
    return "python" if rel.endswith(".py") else craft_lex.language(rel)


def _units(text: str, lang: str) -> dict[str, Unit] | None:
    return craft_rules.units(text) if lang == "python" else craft_lex.units(text, lang)


def _patterns(text: str, rel: str, spans: list[Unit], lang: str) -> list[Finding]:
    """언어별 수명·비용 규칙. 규칙이 없는 언어는 형상만 재고 침묵한다 — 없는 판정을 지어내지 않는다."""
    if lang == "python":
        return craft_rules.pattern_findings(text, rel, spans)
    if lang in craft_lex.C_FAMILY:
        return craft_c.pattern_findings(text, rel, spans, lang)
    return []


def _ratcheted(text: str, rel: str, spans: list[Unit], lang: str) -> list[Finding]:
    """래칫이 거르는 판정 — 파일 전체를 보는 규칙들. 이미 base에 있던 것은 뒤에서 빠진다."""
    return [*_patterns(text, rel, spans, lang), *craft_note.note_findings(text, rel, spans, lang)]


def _judge_file(root: str, rel: str, origin: _Origin) -> tuple[list[Finding], int, str | None]:
    """(판정, 물려받아 넘긴 건수, 미판정 사유)."""
    if why := borrowed(rel):
        return ([], 0, why)
    text = _read(root, rel)
    if text is None:
        return ([], 0, "읽지 못했다")
    lang = _language(rel)
    if lang is None:
        return ([], 0, "판정기가 모르는 언어 — 함수 단위·자원 수명 미측정")
    current = _units(text, lang)
    if current is None:
        return ([], 0, "구문을 읽지 못했다 — 미판정")
    before = origin.text(rel, text)
    prior_units = _units(before, lang) if before is not None else None
    spans = list(current.values())
    found = shape_findings(rel, current, prior_units)
    leaks = _ratcheted(text, rel, spans, lang)
    inherited_keys = _inherited(before, lang)
    fresh = [f for f in leaks if (f.rule, f.unit, f.detail) not in inherited_keys]
    found.extend(fresh)
    found.extend(_file_note(rel, text, before, lang))
    return (found, len(leaks) - len(fresh), None)


def _inherited(before: str | None, lang: str) -> set[tuple[str, str, str]]:
    """base에 이미 있던 형상 — 물려받은 부채는 이번 변경의 책임이 아니다.

    base의 구문을 못 읽어도 주석 판정은 낸다. 못 읽었다고 빈 집합을 돌려주면 그 파일의 옛 주석이
    전부 이번 변경이 새로 넣은 것으로 잡힌다."""
    if before is None:
        return set()
    prior = _units(before, lang)
    spans = list(prior.values()) if prior else []
    findings = craft_note.note_findings(before, "", spans, lang)
    if prior is not None:
        findings += _patterns(before, "", spans, lang)
    return {(f.rule, f.unit, f.detail) for f in findings}


def judge(root: str, paths: object, base: str = "HEAD") -> Report:
    """지목된 경로만 판정한다 — 나무 전수 스캔은 health의 일이다."""
    rels = _normalise(paths)
    origin = _Origin(root, base)
    findings: list[Finding] = []
    judged: list[str] = []
    unknown: list[tuple[str, str]] = []
    inherited = 0
    for rel in rels:
        found, passed, why = _judge_file(root, rel, origin)
        if why:
            unknown.append((rel, why))
            continue
        judged.append(rel)
        inherited += passed
        findings.extend(found)
    moved = tuple(sorted(origin.moved.items()))
    return Report(base, tuple(judged), tuple(unknown), tuple(findings), inherited, moved)


def _normalise(paths: object) -> list[str]:
    if not isinstance(paths, (list, tuple, set, frozenset)):
        return []
    return sorted({rel for raw in paths if (rel := str(raw).strip().replace(os.sep, "/"))})


def changed_paths(root: str, base: str = "HEAD") -> tuple[str, ...]:
    """base 대비 작업 트리에서 달라진 경로 + 추적되지 않은 새 파일."""
    out: list[str] = []
    for args in (["diff", "--name-only", base], ["ls-files", "--others", "--exclude-standard"]):
        raw = _git(root, args, timeout=30)
        out.extend(line.strip() for line in (raw or "").splitlines() if line.strip())
    return tuple(sorted(set(out)))
