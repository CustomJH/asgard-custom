"""asgard tutor — 이번 변경을 **사용자가 직접 되짚게** 만드는 층.

`craft` 가 손댄 자리를 재고 막는다면, 여기는 손댄 자리를 **사람에게 돌려준다**. 필요한 이유는
하나다: 에이전트가 코드를 다 쓰고 "완료"라고 말하면, 아무도 못 건드리는 저장소가 서서히
만들어진다. 코드는 늘어나는데 그 코드를 읽은 사람이 없기 때문이다. 인지부채는 AI 를 얼마나
쓰느냐가 아니라 **관여 순서**의 함수다 — 사람이 나중에 읽으면 안 남고, 먼저 물으면 남는다
(미미르 캐논과 같은 근거 축). 그래서 이 모듈은 설명을 더 하는 장치가 아니라 **설명을 덜 하고
물음을 남기는** 장치다. 성공 지표도 같다: 에이전트 없이 이 변경을 재구성할 수 있는가.

계약 네 줄:

  ① 답을 주지 않는다. 볼 자리(`file:line`)와 물음만 준다 — 튜터가 대신 이해해 주면 이 층의
     목적이 그 자리에서 사라진다.
  ② 아무것도 막지 않는다. `health` 와 같은 등급이다 — 튜터가 관문이 되면 사람이 튜터를 끈다.
  ③ 사실만 기계가 만든다. "무엇이 어떻게 바뀌었나"는 여기서 결정론으로 뽑고, "왜 그렇게
     했나"는 **빈칸으로 남긴다** — 그 칸은 코드를 쓴 쪽이 채우고 사용자가 검사한다.
  ④ 못 본 것은 못 봤다고 적는다. 조용한 절단은 "0건"을 "안 봤다"로 만든다.

래칫은 `craft` 와 같다: base 에 이미 있던 것은 다시 묻지 않는다. 물음도 부채라서, 매 턴 같은
것을 물으면 세 번째부터 아무도 안 읽는다.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, replace

from . import craft, craft_lex, surface, tutor_probes
from .craft_rules import Unit
from .health import _read
from .io_files import read_json, write_json

MAX_PATHS = 400  # 한 번에 읽을 파일 상한 — 초과분은 잘린 사실로 싣는다(조용한 절단 금지)
# (인벤토리, 확인할 자리, 미판정 사유, 단위→줄). 마지막 칸은 표면 판정에 좌표를 주기 위한 것이다 —
# surface 는 심볼 이름만 알고 줄을 모르는데, `file:1` 은 사람이 열어 볼 수 없는 좌표다.
_Judged = tuple["FileChange", list["Checkpoint"], str | None, dict[str, int]]
# 확인 순위 — 사람의 눈은 유한하다. 계약이 깨진 자리가 표식보다 먼저 온다.
WEIGHT = {
    "contract-break": 5,
    "behavior-removed": 4,
    "test-removed": 4,
    "silent-failure": 3,
    "new-dependency": 3,
    "untested-surface": 2,
    "todo-left": 1,
}
# 종류의 사람 이름 — 표면마다 다시 쓰면 같은 판정이 화면마다 다른 이름으로 불린다.
KIND_LABEL = {
    "contract-break": "공개 계약이 바뀌었다",
    "behavior-removed": "동작이 사라졌다",
    "test-removed": "판정이 사라졌다",
    "silent-failure": "실패를 조용히 삼킨다",
    "new-dependency": "외부 의존이 늘었다",
    "untested-surface": "판정 없는 새 표면",
    "todo-left": "안 끝난 표식",
}


@dataclass(frozen=True)
class Checkpoint:
    """사용자가 **직접** 확인해야 하는 자리 하나.

    `what` 은 기계가 뽑은 사실, `why` 는 왜 당신 눈이 필요한가, `ask` 는 당신이 답할 수 있어야
    하는 물음이다. 셋을 나눠 두는 이유: 사실과 물음이 한 문장에 섞이면 읽는 쪽이 물음까지
    설명으로 읽고 넘어간다 — 그러면 읽은 사람은 늘고 답한 사람은 그대로다.
    """

    kind: str
    path: str
    line: int
    unit: str
    what: str
    why: str
    ask: str

    @property
    def weight(self) -> int:
        return WEIGHT.get(self.kind, 0)

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line}" + (f" {self.unit}" if self.unit else "")


@dataclass(frozen=True)
class FileChange:
    """파일 1개의 변경 인벤토리 — 보고서 "어떻게 바뀌었나" 절의 재료."""

    path: str
    added: int
    removed: int
    units_added: tuple[str, ...] = ()
    units_changed: tuple[str, ...] = ()
    units_removed: tuple[str, ...] = ()
    new_file: bool = False
    judged: bool = True  # 단위 수준까지 읽었는가
    code: bool = True  # 코드로 읽어야 할 파일인가 (문서·설정은 못 읽은 게 아니라 읽을 게 없다)


@dataclass(frozen=True)
class Lesson:
    base: str
    files: tuple[FileChange, ...]
    checkpoints: tuple[Checkpoint, ...]
    undetermined: tuple[tuple[str, str], ...]

    @property
    def ranked(self) -> tuple[Checkpoint, ...]:
        return tuple(sorted(self.checkpoints, key=lambda c: (-c.weight, c.path, c.line)))

    @property
    def touched(self) -> tuple[int, int]:
        return (sum(f.added for f in self.files), sum(f.removed for f in self.files))


# ── git 재료 ───────────────────────────────────────────────────────


def _at_base(root: str, rel: str, base: str) -> str | None:
    """base 시점의 본문. 새 파일이면 None."""
    try:
        proc = subprocess.run(["git", "show", f"{base}:{rel}"], cwd=root, capture_output=True, text=True, timeout=20)
    except OSError, subprocess.SubprocessError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _numstat(root: str, base: str) -> dict[str, tuple[int, int]]:
    """경로 → (추가행, 삭제행). 바이너리(`-`)는 0 — 못 센 것을 0 이라 부르되 인벤토리에는 남긴다."""
    try:
        proc = subprocess.run(["git", "diff", "--numstat", base], cwd=root, capture_output=True, text=True, timeout=30)
    except OSError, subprocess.SubprocessError:
        return {}
    out: dict[str, tuple[int, int]] = {}
    for line in proc.stdout.splitlines() if proc.returncode == 0 else []:
        bits = line.split("\t")
        if len(bits) == 3:
            out[bits[2].strip()] = (_int(bits[0]), _int(bits[1]))
    return out


def _int(raw: str) -> int:
    return int(raw) if raw.strip().isdigit() else 0


# ── 파일 1개 ───────────────────────────────────────────────────────


def _moved_only(now: Unit, old: Unit) -> bool:
    """줄 위치 이동은 변경이 아니다 — 위에서 함수가 길어지면 아래 전부가 바뀐 것으로 보인다."""
    return (now.lines, now.depth, now.stmts) == (old.lines, old.depth, old.stmts)


def _inventory(rel: str, now: dict[str, Unit], old: dict[str, Unit], stat: tuple[int, int], fresh: bool) -> FileChange:
    added = tuple(sorted(set(now) - set(old)))
    removed = tuple(sorted(set(old) - set(now)))
    changed = tuple(sorted(n for n in set(now) & set(old) if not _moved_only(now[n], old[n])))
    return FileChange(rel, stat[0], stat[1], added, changed, removed, fresh, judged=True, code=True)


def _stat(rel: str, text: str | None, stats: dict[str, tuple[int, int]]) -> tuple[int, int]:
    """추적되지 않은 새 파일은 `git diff --numstat` 에 안 나온다 — 본문 전체가 이번에 추가된 것이다.

    안 세면 신규 파일이 전부 `+0/-0` 으로 보이고, 그러면 보고서에서 가장 큰 변경이 가장 작아
    보인다. 0 은 "안 바뀜"이라는 뜻으로 읽히므로 못 센 것을 0 으로 두면 그건 거짓말이다.
    """
    known = stats.get(rel)
    if known is not None:
        return known
    return (len(text.splitlines()), 0) if text is not None else (0, 0)


def _fresh(now: dict[str, int], old: dict[str, int]) -> dict[str, int]:
    """이번에 새로 생긴 서명만 — 물려받은 것은 이번 변경의 물음이 아니다(래칫)."""
    return {sig: line for sig, line in now.items() if sig not in old}


def _judge(root: str, rel: str, base: str, stats: dict[str, tuple[int, int]], own: frozenset[str]) -> _Judged:
    """(인벤토리, 확인할 자리, 미판정 사유). 사유가 있어도 인벤토리는 낸다 — 바뀐 사실은 사실이다."""
    code = _is_code(rel)
    text = _read(root, rel)
    if text is None:
        return (FileChange(rel, *_stat(rel, None, stats), judged=False, code=code), [], "읽지 못했다", {})
    stat = _stat(rel, text, stats)
    before = _at_base(root, rel, base)
    marks = _fresh(tutor_probes.marks(text, rel), tutor_probes.marks(before or "", rel))
    points = [_mark_point(rel, sig, line) for sig, line in sorted(marks.items(), key=lambda kv: kv[1])]
    now = tutor_probes.units_of(text, rel)
    if now is None:
        why = "코드 단위를 읽지 못했다 — 함수 인벤토리·예외/의존 판정 없음"
        return (FileChange(rel, *stat, judged=False, code=code), points, why if code else None, {})
    old = (tutor_probes.units_of(before, rel) or {}) if before is not None else {}
    if rel.endswith(".py"):
        points.extend(_python_points(rel, text, before or "", own))
    points.extend(_removal_points(rel, sorted(set(old) - set(now)), old))
    anchors = {name: unit.line for name, unit in now.items()}
    return (_inventory(rel, now, old, stat, before is None), points, None, anchors)


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
            f"{sig.split('@', 1)[0]} 를 잡고 아무것도 하지 않는다 — 이유가 어디에도 안 적혀 있다",
            "삼킨 예외는 실패를 성공처럼 보이게 만든다. 의도한 fail-open 인지 흘린 것인지는 코드만 보고 알 수 없다",
            "이 예외가 실제로 일어나면 사용자 화면에는 무엇이 보이는가? 아무것도 안 보이는 게 맞다면 왜인가?",
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
                f"외부 의존 `{name}` 이 이 파일에 새로 들어왔다",
                "의존 하나는 코드보다 오래 남는다 — 버전·보안·라이선스·이관 비용이 전부 따라 들어온다",
                f"`{name}` 이 하는 일을 직접 짜면 몇 줄인가? 그 줄 수를 이 비용과 바꿀 값이 있는가?",
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
        f"{kind} 표식이 새로 남았다 — {body or '(내용 없음)'}",
        "표식은 저자가 스스로 '여기 안 끝났다'고 적은 자리다. 안 갚기로 했다면 표식이 아니라 결정으로 남아야 한다",
        "이건 언제 갚는가? 안 갚을 것이면 왜 남겨 두는가?",
    )


def _removal_points(rel: str, gone: list[str], old: dict[str, Unit]) -> list[Checkpoint]:
    """사라진 단위. 테스트가 사라진 것과 구현이 사라진 것은 물음이 다르다."""
    tests = tutor_probes.test_units(gone) if tutor_probes.is_test_path(rel) else set()
    out: list[Checkpoint] = []
    for name in gone:
        is_test = name in tests
        out.append(
            Checkpoint(
                "test-removed" if is_test else "behavior-removed",
                rel,
                old[name].line if name in old else 1,
                name,
                f"`{name}` 이 사라졌다 ({old[name].lines}행)" if name in old else f"`{name}` 이 사라졌다",
                "판정이 사라진 것과 기능이 사라진 것은 diff 에서 똑같이 보인다"
                if is_test
                else "삭제는 diff 에서 가장 조용한 변경이다 — 부르던 곳이 남아 있어도 실행 전엔 티가 안 난다",
                "이 테스트가 지키던 조건은 지금 무엇이 지키는가?"
                if is_test
                else "이걸 부르던 곳은 어디였고, 왜 이제 필요 없는가?",
            )
        )
    return out


# ── 표면 계약 (surface 재사용) ─────────────────────────────────────


def _surface_points(root: str, base: str) -> tuple[list[Checkpoint], list[tuple[str, str]]]:
    """공개 시그니처 변화 + 호출부 후보. 목록을 손 grep 에 맡기지 않는 것이 surface 의 존재 이유다."""
    try:
        diff = surface.diff(root, base)
    except Exception:
        return ([], [("(public surface)", "표면 대조를 돌리지 못했다 — 계약 변화 미판정")])
    out: list[Checkpoint] = []
    for change in diff.changes:
        if not change.breaking or change.kind == "removed":
            continue  # 삭제는 단위 인벤토리가 이미 묻는다 — 같은 것을 두 번 묻지 않는다
        sites = diff.obligations.get(change.qualname.rsplit(".", 1)[-1], ())
        where = ", ".join(sites[:6]) if sites else "이 변경 밖에서 같은 이름을 못 찾았다"
        out.append(
            Checkpoint(
                "contract-break",
                change.path,
                1,
                change.qualname,
                f"공개 계약이 바뀌었다 — {change.kind} ({change.detail})",
                f"호출부가 그대로면 깨진다. 이름 기반 후보: {where}",
                "위 후보를 하나씩 열어 확인했는가? 안 고쳐도 되는 것은 왜 안 고쳐도 되는가?",
            )
        )
    unparsed = [(p, "구문을 못 읽어 표면 대조에서 빠졌다") for p in diff.unparsed]
    return (out + _untested_points(root, diff), unparsed)


def _untested_points(root: str, diff: surface.SurfaceDiff) -> list[Checkpoint]:
    """새로 생긴 공개 심볼 중 테스트 트리 어디에서도 이름이 안 보이는 것."""
    added = [c for c in diff.changes if c.kind == "added"]
    if not added:
        return []
    try:
        found = surface.candidates(root, [c.qualname for c in added])
    except Exception:
        return []
    out: list[Checkpoint] = []
    for change in added:
        name = change.qualname.rsplit(".", 1)[-1]
        if any(tutor_probes.is_test_path(p) for p in found.get(name, ())):
            continue
        out.append(
            Checkpoint(
                "untested-surface",
                change.path,
                1,
                change.qualname,
                f"새 공개 심볼 `{change.qualname}` — 테스트 트리에서 이름이 안 보인다",
                "판정 없는 표면은 다음 사람이 마음대로 바꿔도 아무것도 빨개지지 않는다",
                "이게 틀렸을 때 무엇이 빨개지는가? 아무것도 안 빨개진다면 그래도 괜찮은 이유는?",
            )
        )
    return out


# ── 조립 ───────────────────────────────────────────────────────────


def review(root: str, base: str = "HEAD", paths: object = ()) -> Lesson:
    """이번 변경의 되짚기 자료. 지목된 경로가 없으면 base 대비 달라진 전부를 본다."""
    named = _normalise(paths)
    targets = named or list(craft.changed_paths(root, base))
    stats = _numstat(root, base)
    own = _own_names(root)
    files: list[FileChange] = []
    points: list[Checkpoint] = []
    unknown: list[tuple[str, str]] = []
    anchors: dict[str, dict[str, int]] = {}
    for rel in targets[:MAX_PATHS]:
        change, found, why, lines = _judge(root, rel, base, stats, own)
        files.append(change)
        points.extend(found)
        anchors[rel] = lines
        if why:
            unknown.append((rel, why))
    if len(targets) > MAX_PATHS:
        unknown.append(
            (f"(+{len(targets) - MAX_PATHS} more)", f"한 번에 {MAX_PATHS}개까지만 읽었다 — 경로를 좁혀 다시 보라")
        )
    contract, gaps = _surface_points(root, base)
    # 경로를 지목받았으면 표면 판정도 그 안으로 자른다. surface 는 나무 전체의 변경을 보는데,
    # 훅은 "이 세션이 쓴 경로"만 넘긴다 — 안 자르면 남이 만든 계약 파괴를 이 턴의 물음으로
    # 돌려주게 되고, 그건 craft 래칫이 막는 것과 똑같은 종류의 오귀속이다.
    scope = set(named)
    if scope:
        contract = [point for point in contract if point.path in scope]
        gaps = [gap for gap in gaps if gap[0] in scope]
    points.extend(_anchored(point, anchors) for point in contract)
    return Lesson(base, tuple(files), tuple(points), tuple(unknown + gaps))


def _anchored(point: Checkpoint, anchors: dict[str, dict[str, int]]) -> Checkpoint:
    """표면 판정에 좌표를 붙인다. `file:1` 은 사람이 열어 볼 수 없는 좌표라 물음이 도달하지 않는다."""
    line = anchors.get(point.path, {}).get(point.unit)
    return point if line is None else replace(point, line=line)


def _normalise(paths: object) -> list[str]:
    if not isinstance(paths, (list, tuple, set, frozenset)):
        return []
    return sorted({rel for raw in paths if (rel := str(raw).strip().replace(os.sep, "/"))})


# ── 네이티브 루프 도달 경로 ────────────────────────────────────────


def turn_note(root: str, sid: object, limit: int = 3) -> str:
    """네이티브 턴 끝에 실을 되짚기 카드. 없으면 빈 문자열 (토큰 회귀 없음).

    외부 클라이언트는 Stop 훅이 이 일을 한다. 네이티브 루프에는 훅이 없어서 — 단일 프로세스라
    끼어들 자리가 없다 — 도달 경로를 여기 하나 더 둔다. 판정기는 하나이므로 두 경로가 다른
    답을 낼 수는 없고, 다른 것은 화면 형식뿐이다.
    """
    key = str(sid or "").strip()
    paths = _session_writes(root, key)
    if not paths:
        return ""
    lesson = review(root, "HEAD", paths)
    points = lesson.ranked
    if not points:
        return ""  # 물을 것이 없으면 침묵한다 — 빈 카드는 다음 카드의 신뢰를 깎는다
    if _repeat(root, key, points):
        return ""
    return _card(lesson, points, limit)


def _session_writes(root: str, sid: str) -> list[str]:
    """이 세션이 쓴 경로 (write sentinel). 사용자가 원래 갖고 있던 dirt 는 이 턴의 물음이 아니다."""
    if not sid:
        return []
    rows = read_json(os.path.join(root, ".asgard", "state", f"writes-{sid}.json"), [])
    return [str(row) for row in rows] if isinstance(rows, list) else []


def _repeat(root: str, sid: str, points: tuple[Checkpoint, ...]) -> bool:
    """같은 물음을 매 턴 다시 놓으면 세 번째부터 아무도 안 읽는다 — 지문이 같으면 침묵."""
    path = os.path.join(root, ".asgard", "state", f"tutor-{sid}.json")
    sig = _fingerprint(points)
    seen = (read_json(path, {}) or {}).get("signature")
    try:
        write_json(path, {"signature": sig})
    except OSError:
        pass  # 못 적었으면 다음 턴에 같은 카드가 한 번 더 나온다 — 중복이 침묵보다 낫다
    return seen == sig


def _fingerprint(points: tuple[Checkpoint, ...]) -> str:
    raw = "\n".join(sorted(f"{p.kind}|{p.path}|{p.unit}" for p in points))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _card(lesson: Lesson, points: tuple[Checkpoint, ...], limit: int) -> str:
    added, removed = lesson.touched
    lines = [
        f"⠶ 되짚기 — 이번 턴 {len(lesson.files)}개 파일 · +{added:,}/-{removed:,}행."
        " 아래는 **기계가 못 답하는** 것들이다.",
        "",
    ]
    for point in points[:limit]:
        lines.append(f"  {KIND_LABEL.get(point.kind, point.kind)} — {point.where}")
        lines.append(f"    ▸ {point.ask}")
    if len(points) > limit:
        lines.append(f"  …외 {len(points) - limit}건")
    lines.append("")
    lines.append("  전체와 '왜 이렇게 했는가' 빈칸: `asgard tutor --report`")
    return "\n".join(lines)
