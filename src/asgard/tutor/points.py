"""파일 하나를 판정한다 — 무엇이 바뀌었나(인벤토리)와 사람이 확인할 자리(물음).

이 모듈이 되짚기의 사실을 만든다. 여기서 나온 것만 위층이 조립하고, 여기서 못 본 것은
`_judge` 가 사유와 함께 되돌려 준다 — 조용한 절단 금지(모듈 계약 ④).
"""

from __future__ import annotations

import hashlib
import os

from .. import craft_lex, tutor_probes
from ..craft_rules import Unit
from ..health import _read
from ..tutor_model import Checkpoint, FileChange
from .diffs import _at_base

MAX_PATHS = 400  # 한 번에 읽을 파일 상한 — 초과분은 잘린 사실로 넣는다(조용한 절단 금지)
REMOVAL_DETAIL_LIMIT = 2  # 같은 파일의 대량 삭제는 단위별 심문이 아니라 책임 묶음 하나로 묻는다
# (인벤토리, 확인할 자리, 미판정 사유, 단위→줄). 마지막 칸은 표면 판정에 좌표를 주기 위한 것이다 —
# surface는 심볼 이름만 알고 줄을 모르는데, `file:1`은 사람이 열어 볼 수 없는 좌표다.
_Judged = tuple["FileChange", list["Checkpoint"], str | None, dict[str, int]]
_Moves = dict[tuple[str, str], tuple[tuple[str, str], ...]]


def _moved_only(now: Unit, old: Unit) -> bool:
    """줄 위치 이동은 변경이 아니다 — 위에서 함수가 길어지면 아래 전부가 바뀐 것으로 보인다."""
    return (now.lines, now.depth, now.stmts) == (old.lines, old.depth, old.stmts)


def _inventory(
    rel: str,
    now: dict[str, Unit],
    old: dict[str, Unit],
    stat: tuple[int, int],
    fresh: bool,
    moves: _Moves,
) -> FileChange:
    added = tuple(sorted(set(now) - set(old)))
    gone = sorted(set(old) - set(now))
    moved = tuple(_move_label(name, moves[(rel, name)]) for name in gone if (rel, name) in moves)
    removed = tuple(name for name in gone if (rel, name) not in moves)
    changed = tuple(sorted(n for n in set(now) & set(old) if not _moved_only(now[n], old[n])))
    return FileChange(
        path=rel,
        added=stat[0],
        removed=stat[1],
        units_added=added,
        units_changed=changed,
        units_removed=removed,
        new_file=fresh,
        judged=True,
        code=True,
        units_moved=moved,
    )


def _move_label(name: str, destinations: tuple[tuple[str, str], ...]) -> str:
    places = " · ".join(f"{path} {unit}" for path, unit in destinations)
    return f"{name} → {places}"


def _relocations(root: str, base: str, targets: list[str]) -> _Moves:
    """변경 범위 안에서 본문이 그대로 살아 있는 제거 단위의 목적지.

    목적지도 이번 변경에서 새로 생겼거나 본문이 바뀐 단위여야 한다. 예전부터 우연히 같은 함수가
    다른 파일에 있었다는 이유로 실제 삭제를 이동이라 부르면 안 되기 때문이다.
    """
    destinations: dict[str, list[tuple[str, str]]] = {}
    removed: list[tuple[str, str, str]] = []
    for rel in targets[:MAX_PATHS]:
        text = _read(root, rel)
        before = _at_base(root, rel, base)
        now = tutor_probes.unit_fingerprints(text or "", rel)
        old = tutor_probes.unit_fingerprints(before or "", rel)
        for name, fingerprint in now.items():
            if old.get(name) != fingerprint:
                destinations.setdefault(fingerprint, []).append((rel, name))
        for name, fingerprint in old.items():
            if name not in now:
                removed.append((rel, name, fingerprint))
    out: _Moves = {}
    for rel, name, fingerprint in removed:
        found = tuple(sorted(set(destinations.get(fingerprint, ())) - {(rel, name)}))
        if found:
            out[(rel, name)] = found
    return out


def _stat(rel: str, text: str | None, stats: dict[str, tuple[int, int]], before: str | None = None) -> tuple[int, int]:
    """(추가행, 삭제행). numstat에 없는 경로는 `before`가 갈라 준다.

    추적되지 않은 새 파일은 `git diff --numstat`에 안 나온다 — 본문 전체가 이번에 추가된 것이다.
    안 세면 신규 파일이 전부 `+0/-0`으로 보이고, 그러면 보고서에서 가장 큰 변경이 가장 작아
    보인다. 0은 "안 바뀜"이라는 뜻으로 읽히므로 못 센 것을 0으로 두면 그건 거짓말이다.

    반대 방향도 거짓말이다: 경로를 지목받은 호출(훅은 write sentinel이 준 경로를 넘긴다)에는
    **안 바뀐 추적 파일**도 들어온다. numstat은 그런 파일을 안 싣는데, base에 본문이 있으면
    안 바뀐 것이므로 (0, 0)이다 — 안 가르면 안 건드린 파일이 통째로 새 파일로 보고된다
    (실측: `asgard tutor --json --path src/asgard/tutor.py`가 `added: 1032`을 냈다).
    """
    known = stats.get(rel)
    if known is not None:
        return known
    if before is not None:
        return (0, 0)
    return (len(text.splitlines()), 0) if text is not None else (0, 0)


def _fresh(now: dict[str, int], old: dict[str, int]) -> dict[str, int]:
    """이번에 새로 생긴 서명만 — 물려받은 것은 이번 변경의 물음이 아니다(래칫)."""
    return {sig: line for sig, line in now.items() if sig not in old}


def _judge(
    root: str,
    rel: str,
    base: str,
    stats: dict[str, tuple[int, int]],
    own: frozenset[str],
    moves: _Moves,
) -> _Judged:
    """(인벤토리, 확인할 자리, 미판정 사유). 사유가 있어도 인벤토리는 낸다 — 바뀐 사실은 사실이다."""
    code = _is_code(rel)
    text = _read(root, rel)
    before = _at_base(root, rel, base)
    if text is None:
        stat = _stat(rel, None, stats, before)
        if before is None:
            return (
                FileChange(path=rel, added=stat[0], removed=stat[1], judged=False, code=code),
                [],
                "읽지 못했어요",
                {},
            )
        old = tutor_probes.units_of(before, rel)
        if old is None:
            why = "삭제 전 코드 단위를 읽지 못했어요" if code else None
            return (
                FileChange(path=rel, added=stat[0], removed=stat[1], judged=not code, code=code),
                [],
                why,
                {},
            )
        change = _inventory(rel, {}, old, stat, False, moves)
        return (change, _removal_points(rel, list(change.units_removed), old), None, {})
    stat = _stat(rel, text, stats, before)
    marks = _fresh(tutor_probes.marks(text, rel), tutor_probes.marks(before or "", rel))
    points = [_mark_point(rel, sig, line) for sig, line in sorted(marks.items(), key=lambda kv: kv[1])]
    now = tutor_probes.units_of(text, rel)
    if now is None:
        why = "코드 단위를 읽지 못해서 함수 인벤토리와 예외·의존 판정을 못 냈어요"
        return (FileChange(rel, *stat, judged=False, code=code), points, why if code else None, {})
    old = (tutor_probes.units_of(before, rel) or {}) if before is not None else {}
    if rel.endswith(".py"):
        points.extend(_python_points(rel, text, before or "", own))
    change = _inventory(rel, now, old, stat, before is None, moves)
    points.extend(_removal_points(rel, list(change.units_removed), old))
    anchors = {name: unit.line for name, unit in now.items()}
    return (change, points, None, anchors)


def _is_code(rel: str) -> bool:
    """코드로 읽어야 할 파일인가. 문서·설정이 미판정 목록을 채우면 그 목록을 아무도 안 본다."""
    return rel.endswith(".py") or craft_lex.language(rel) is not None


def _own_names(root: str) -> frozenset[str]:
    """이 저장소가 자기 이름으로 쓰는 top-level 패키지.

    없으면 `tests/` 안에서 자기 패키지를 import 한 줄이 "외부 의존이 늘었다"로 올라온다(실측).
    자기 나무를 남이라 부르는 물음은 한 번이면 신뢰를 잃는다 — 미검출이 오탐보다 낫다.
    """
    names = {os.path.basename(root.rstrip("/\\")), "tests", "test"}
    for parent in (root, os.path.join(root, "src")):
        try:
            entries = os.listdir(parent)
        except OSError:
            continue
        for entry in entries:
            path = os.path.join(parent, entry)
            if entry.startswith(".") or not os.path.isdir(path):
                continue
            if parent.endswith("src") or os.path.exists(os.path.join(path, "__init__.py")):
                names.add(entry)
    return frozenset(names)


def _python_points(rel: str, text: str, before: str, own: frozenset[str]) -> list[Checkpoint]:
    fresh_imports = {
        name: line
        for name, line in _fresh(tutor_probes.imports(text), tutor_probes.imports(before)).items()
        if name not in own
    }
    out = [
        Checkpoint(
            "silent-failure",
            rel,
            line,
            sig.split("@", 1)[-1],
            f"{sig.split('@', 1)[0]}를 잡고 아무것도 하지 않아요 — 이유가 어디에도 안 적혀 있어요",
            "삼킨 예외는 실패를 성공처럼 보이게 만들어요. 일부러 열어 둔 건지 흘린 건지는 코드만 보고는 알 수 없어요",
            "이 예외가 실제로 일어나면 사용자 화면에는 무엇이 보이나요? 아무것도 안 보이는 게 맞다면 왜 그런가요?",
            sig,  # 한 함수 안에 삼킴이 둘이면 `unit`이 같다 — 예외 종류까지 넣어야 다른 물음이 된다
        )
        for sig, line in sorted(_fresh(tutor_probes.swallows(text), tutor_probes.swallows(before)).items())
    ]
    for name, line in sorted(fresh_imports.items()):
        out.append(
            Checkpoint(
                "new-dependency",
                rel,
                line,
                "",
                f"외부 의존 `{name}`이 이 파일에 새로 들어왔어요",
                "의존 하나는 코드보다 오래 남아요 — 버전·보안·라이선스·이관 비용이 전부 따라 들어와요",
                f"`{name}`이 하는 일을 직접 짜면 몇 줄인가요? 그 줄 수를 이 비용과 바꿀 값이 있나요?",
                name,  # 의존 물음은 `unit`이 비어 있다 — 이름이 없으면 한 파일의 의존 전부가 한 물음이 된다
            )
        )
    return out


def _mark_point(rel: str, sig: str, line: int) -> Checkpoint:
    kind, _, body = sig.partition(":")
    return Checkpoint(
        "todo-left",
        rel,
        line,
        "",
        f"{kind} 표식이 새로 남았어요 — {body or '(내용 없음)'}",
        "표식은 저자가 스스로 '여기 안 끝났다'고 적어 둔 자리예요. 안 갚기로 했다면 표식이 아니라 결정으로 남아야 해요",
        "이건 언제 갚나요? 안 갚을 거라면 왜 남겨 두나요?",
        sig,  # 한 파일의 표식이 여럿이면 본문이 유일한 구분자다 (`unit`은 비어 있다)
    )


def _removal_points(rel: str, gone: list[str], old: dict[str, Unit]) -> list[Checkpoint]:
    """사라진 단위. 테스트가 사라진 것과 구현이 사라진 것은 물음이 다르다."""
    tests = tutor_probes.test_units(gone) if tutor_probes.is_test_path(rel) else set()
    out: list[Checkpoint] = []
    for is_test, names in ((False, [n for n in gone if n not in tests]), (True, [n for n in gone if n in tests])):
        if len(names) > REMOVAL_DETAIL_LIMIT:
            out.append(_removal_group_point(rel, names, old, is_test))
            continue
        for name in names:
            out.append(_removal_point(rel, name, old, is_test))
    return out


def _removal_point(rel: str, name: str, old: dict[str, Unit], is_test: bool) -> Checkpoint:
    return Checkpoint(
        "test-removed" if is_test else "behavior-removed",
        rel,
        old[name].line if name in old else 1,
        name,
        f"`{name}`이 사라졌어요 ({old[name].lines}행)" if name in old else f"`{name}`이 사라졌어요",
        "판정이 사라진 것과 기능이 사라진 것은 diff에서 똑같이 보여요"
        if is_test
        else "삭제는 diff에서 가장 조용한 변경이에요 — 부르던 곳이 남아 있어도 실행 전엔 티가 안 나요",
        "이 테스트가 지키던 조건은 지금 무엇이 지키나요?"
        if is_test
        else "이걸 부르던 곳은 어디였고, 왜 이제 필요 없나요?",
    )


def _removal_group_point(rel: str, names: list[str], old: dict[str, Unit], is_test: bool) -> Checkpoint:
    total_lines = sum(old[name].lines for name in names if name in old)
    sample = " · ".join(f"`{name}`" for name in names[:2])
    key = "group:" + hashlib.sha1("\0".join(names).encode("utf-8")).hexdigest()[:12]
    noun = "테스트" if is_test else "동작 단위"
    return Checkpoint(
        "test-removed" if is_test else "behavior-removed",
        rel,
        min((old[name].line for name in names if name in old), default=1),
        "",
        f"{sample} 외 {len(names) - 2}개 {noun}가 함께 사라졌어요 (합계 {total_lines}행)",
        "여러 삭제를 하나씩 물으면 같은 구조 결정을 여러 번 답하게 돼요",
        "이 묶음이 맡던 책임은 지금 어디에 있고, 삭제 전후에 유지돼야 할 조건은 무엇인가요?"
        if not is_test
        else "이 판정 묶음이 지키던 조건은 지금 어느 테스트나 검증이 대신하나요?",
        key,
    )
