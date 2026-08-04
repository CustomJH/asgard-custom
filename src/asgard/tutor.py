"""asgard tutor — 이번 변경을 **사용자가 직접 되짚게** 만드는 층.

`craft`가 손댄 자리를 재고 막는다면, 여기는 손댄 자리를 **사람에게 돌려준다**. 필요한 이유는
하나다: 에이전트가 코드를 다 쓰고 "완료"라고 말하면, 아무도 못 건드리는 저장소가 서서히
만들어진다. 코드는 늘어나는데 그 코드를 읽은 사람이 없기 때문이다. 인지부채는 AI를 얼마나
쓰느냐가 아니라 **관여 순서**의 함수다 — 사람이 나중에 읽으면 안 남고, 먼저 물으면 남는다
(미미르 캐논과 같은 근거 축). 그래서 이 모듈은 설명을 더 하는 장치가 아니라 **설명을 덜 하고
물음을 남기는** 장치다. 성공 지표도 같다: 에이전트 없이 이 변경을 재구성할 수 있는가.

계약 네 줄:

  ① 답을 주지 않는다. 볼 자리(`file:line`)와 물음만 준다 — 튜터가 대신 이해해 주면 이 층의
     목적이 그 자리에서 사라진다.
  ② 아무것도 막지 않는다. `health`와 같은 등급이다 — 튜터가 관문이 되면 사람이 튜터를 끈다.
  ③ 사실만 기계가 만든다. "무엇이 어떻게 바뀌었나"는 여기서 결정론으로 뽑고, "왜 그렇게
     했나"는 **빈칸으로 남긴다** — 그 칸은 코드를 쓴 쪽이 채우고 사용자가 검사한다.
  ④ 못 본 것은 못 봤다고 적는다. 조용한 절단은 "0건"을 "안 봤다"로 만든다.

래칫은 `craft`와 같다: base에 이미 있던 것은 다시 묻지 않는다. 물음도 부채라서, 매 턴 같은
것을 물으면 세 번째부터 아무도 안 읽는다.

물음을 놓은 **뒤**는 `tutor_growth`가 센다 — 답했는가, 건너뛰었는가, 그래서 다음엔 얼마나 말할
것인가(조절), 안 답한 것을 언제 다시 꺼낼 것인가(재방문). 이 모듈은 계속 "이번 변경의 사실"만
만들고, 그 사실을 사람에 맞춰 **줄이는** 일은 여기 아래쪽 조립부에서만 일어난다. 나누는 이유는
하나다: 사실이 사람에 따라 달라지기 시작하면 `--json`이 두 사람에게 다른 답을 내게 된다.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import re
import subprocess
import time
from dataclasses import dataclass, replace

from . import craft, craft_lex, loop, surface, tutor_growth, tutor_probes
from .craft_rules import Unit
from .health import _read
from .io_files import read_json, write_json

MAX_PATHS = 400  # 한 번에 읽을 파일 상한 — 초과분은 잘린 사실로 넣는다(조용한 절단 금지)
# (인벤토리, 확인할 자리, 미판정 사유, 단위→줄). 마지막 칸은 표면 판정에 좌표를 주기 위한 것이다 —
# surface는 심볼 이름만 알고 줄을 모르는데, `file:1`은 사람이 열어 볼 수 없는 좌표다.
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
    "contract-break": "공개 계약 바뀜",
    "behavior-removed": "동작 사라짐",
    "test-removed": "판정 사라짐",
    "silent-failure": "조용히 삼킨 실패",
    "new-dependency": "외부 의존 늘어남",
    "untested-surface": "판정 없는 새 표면",
    "todo-left": "안 끝난 표식",
}
# 다시 물을 때의 **각도**. 같은 문장을 네 번째로 놓는 것은 재방문이 아니라 반복이고, 반복은
# 답을 못 받은 이유를 그대로 한 번 더 재현한다. 인출이 실패한 자리에서 바꿀 것은 목소리 크기가
# 아니라 각도다 — 결과를 묻던 것을 신호로, 신호를 묻던 것을 복구로 옮긴다. 0번은 최초 문장이라
# 여기 없다(Checkpoint.ask가 갖는다). 각도가 떨어지면 마지막 각도를 유지한다.
ANGLES: dict[str, tuple[str, ...]] = {
    "contract-break": (
        "이 계약을 쓰던 코드를 지금 처음 보는 사람은 무엇부터 실행해 봐야 할까요?",
        "되돌려야 한다면 어디를 되돌리나요? 한 줄로 말할 수 있나요?",
    ),
    "behavior-removed": (
        "이 동작이 없어서 깨지는 상황을 하나만 들어 볼까요? 하나도 못 대겠다면 그건 왜일까요?",
        "이걸 다시 살려야 할 날이 온다면 무엇을 근거로 판단하나요?",
    ),
    "test-removed": (
        "이 테스트가 잡던 실패를 지금 일부러 만들면 무엇이 빨개지나요?",
        "지운 판정을 대신하는 게 없다면, 없어도 되는 이유를 한 줄로 적어 볼까요?",
    ),
    "silent-failure": (
        "이 예외가 지금 하루에 100번씩 일어나고 있다면 그걸 어떻게 알아차리나요?",
        "여기서 삼키는 대신 위로 올렸다면 무엇이 깨지나요? 그게 삼키는 이유인가요?",
    ),
    "new-dependency": (
        "이게 내일 폐기되거나 라이선스가 바뀐다면 무엇을 해야 하나요?",
        "이 의존이 하는 일 중 실제로 쓰는 건 얼마나 되나요? 나머지도 같이 짊어질 값인가요?",
    ),
    "untested-surface": (
        "다음 사람이 이걸 반대로 고쳐 놓으면 무엇이 그 사실을 알려 주나요?",
        "판정을 안 붙이기로 했다면 그 결정은 지금 어디에 적혀 있나요?",
    ),
    "todo-left": (
        "이 표식을 지우려면 그 전에 무엇이 끝나야 하나요?",
        "여섯 달 뒤 이 줄을 처음 보는 사람이 무엇을 해야 하는지 알 수 있을까요?",
    ),
}


@dataclass(frozen=True)
class Checkpoint:
    """사용자가 **직접** 확인해야 하는 자리 하나.

    `what`은 기계가 뽑은 사실, `why`는 왜 당신 눈이 필요한가, `ask`는 당신이 답할 수 있어야
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
    key: str = ""  # 식별용 구분자 — 아래 `cid` 주석 참고. 비면 `unit`이 그 일을 한다

    @property
    def weight(self) -> int:
        return WEIGHT.get(self.kind, 0)

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line}" + (f" {self.unit}" if self.unit else "")

    @property
    def cid(self) -> str:
        """이 물음의 이름. 사용자가 답을 되돌려 보낼 때 쓰는 유일한 좌표다.

        **줄 번호를 안 쓴다** — 답을 적는 사이에 위에서 함수가 길어지면 좌표가 바뀌는 식별자는
        식별자가 아니다. 대신 `key`로 한 파일 안의 물음을 가른다: 의존 물음의 `unit`은 비어
        있고 한 함수 안의 삼킴도 이름이 같아서, 좌표만으로는 `requests`와 `yaml`이 **같은
        물음**이 된다(실측). 그러면 답 하나가 안 답한 물음까지 닫는다 — 기록이 거짓이 되는
        가장 조용한 경로다.
        """
        return tutor_growth.cid(self.kind, self.path, self.key or self.unit)


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
    # 컨트롤러가 이 자리를 고른 근거 (`loop.mandate_for`). 사람이 쓴 변경이면 항상 비어 있다.
    #
    # 계약 ①("답을 주지 않는다")과 다투지 않는 이유: 이것은 코드에 대한 답이 아니라 **좌표에
    # 대한 사실**이다. "이 함수가 왜 이렇게 생겼나"는 여전히 안 적는다(그건 계약 ③ 의 빈칸이고
    # 저자 몫이다). 여기 싣는 것은 "왜 하필 이 파일 이 줄이었나"인데, 루프가 쓴 변경에는 그
    # 물음에 답할 저자가 아예 없다 — diff 어디에도 안 적혀 있고 사람이 유도할 방법도 없다.
    # 빈칸을 비워 두는 것과 답이 없는 물음을 남기는 것은 다르다. 후자는 부채다.
    mandate: tuple[dict, ...] = ()

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
        proc = subprocess.run(
            ["git", "show", f"{base}:{rel}"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
        )
    except OSError, subprocess.SubprocessError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _numstat(root: str, base: str) -> dict[str, tuple[int, int]]:
    """경로 → (추가행, 삭제행). 바이너리(`-`)는 0 — 못 센 것을 0이라 부르되 인벤토리에는 남긴다."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--numstat", base],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
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


def _judge(root: str, rel: str, base: str, stats: dict[str, tuple[int, int]], own: frozenset[str]) -> _Judged:
    """(인벤토리, 확인할 자리, 미판정 사유). 사유가 있어도 인벤토리는 낸다 — 바뀐 사실은 사실이다."""
    code = _is_code(rel)
    text = _read(root, rel)
    if text is None:
        return (FileChange(rel, *_stat(rel, None, stats), judged=False, code=code), [], "읽지 못했어요", {})
    before = _at_base(root, rel, base)
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
    for name in gone:
        is_test = name in tests
        out.append(
            Checkpoint(
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
        )
    return out


# ── 표면 계약 (surface 재사용) ─────────────────────────────────────


def _surface_points(root: str, base: str) -> tuple[list[Checkpoint], list[tuple[str, str]]]:
    """공개 시그니처 변화 + 호출부 후보. 목록을 손 grep에 맡기지 않는 것이 surface의 존재 이유다."""
    try:
        diff = surface.diff(root, base)
    except Exception:
        return ([], [("(public surface)", "표면 대조를 돌리지 못해서 계약이 바뀌었는지 못 봤어요")])
    out: list[Checkpoint] = []
    for change in diff.changes:
        if not change.breaking or change.kind == "removed":
            continue  # 삭제는 단위 인벤토리가 이미 묻는다 — 같은 것을 두 번 묻지 않는다
        sites = diff.obligations.get(change.qualname.rsplit(".", 1)[-1], ())
        where = ", ".join(sites[:6]) if sites else "이 변경 밖에서 같은 이름을 못 찾았어요"
        out.append(
            Checkpoint(
                "contract-break",
                change.path,
                1,
                change.qualname,
                f"공개 계약이 바뀌었어요 — {change.kind} ({change.detail})",
                f"호출부가 그대로면 깨져요. 이름으로 찾은 후보는 {where}예요",
                "위 후보를 하나씩 열어 확인해 보셨나요? 안 고쳐도 되는 것은 왜 그런가요?",
            )
        )
    unparsed = [(p, "구문을 못 읽어서 표면 대조에서 빠졌어요") for p in diff.unparsed]
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
                f"새 공개 심볼 `{change.qualname}` — 테스트 트리에서 이름이 안 보여요",
                "판정 없는 표면은 다음 사람이 마음대로 바꿔도 아무것도 빨개지지 않아요",
                "이게 틀렸을 때 무엇이 빨개지나요? 아무것도 안 빨개진다면 그래도 괜찮은 이유는 뭔가요?",
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
            (
                f"(+{len(targets) - MAX_PATHS} more)",
                f"한 번에 {MAX_PATHS}개까지만 읽었어요 — 경로를 좁혀 다시 봐 주세요",
            )
        )
    contract, gaps = _surface_points(root, base)
    # 경로를 지목받았으면 표면 판정도 그 안으로 자른다. surface는 나무 전체의 변경을 보는데,
    # 훅은 "이 세션이 쓴 경로"만 넘긴다 — 안 자르면 남이 만든 계약 파괴를 이 턴의 물음으로
    # 돌려주게 되고, 그건 craft 래칫이 막는 것과 똑같은 종류의 오귀속이다.
    scope = set(named)
    if scope:
        contract = [point for point in contract if point.path in scope]
        gaps = [gap for gap in gaps if gap[0] in scope]
    points.extend(_anchored(point, anchors) for point in contract)
    # 컨트롤러 근거는 **손댄 경로에 대해서만** 넣는다 — 안 건드린 자리의 지시를 이번 되짚기에
    # 붙이면 craft 래칫이 막는 것과 같은 종류의 오귀속이 된다.
    mandate = loop.mandate_for(root, targets)
    return Lesson(base, tuple(files), tuple(points), tuple(unknown + gaps), mandate)


def _anchored(point: Checkpoint, anchors: dict[str, dict[str, int]]) -> Checkpoint:
    """표면 판정에 좌표를 붙인다. `file:1`은 사람이 열어 볼 수 없는 좌표라 물음이 도달하지 않는다."""
    line = anchors.get(point.path, {}).get(point.unit)
    return point if line is None else replace(point, line=line)


def _normalise(paths: object) -> list[str]:
    if not isinstance(paths, (list, tuple, set, frozenset)):
        return []
    return sorted({rel for raw in paths if (rel := str(raw).strip().replace(os.sep, "/"))})


# ── 조절·재방문 (사실을 사람에 맞춰 줄인다) ───────────────────────


def angled(point: Checkpoint, asks: int) -> Checkpoint:
    """같은 물음을 다시 놓을 때 각도를 바꾼 문장으로 갈아 끼운다. 1회차는 원문 그대로."""
    turns = ANGLES.get(point.kind, ())
    index = tutor_growth.angle(point.kind, asks) - 1
    if index < 0 or not turns:
        return point
    return replace(point, ask=turns[min(index, len(turns) - 1)])


def shaped(root: str, points: tuple[Checkpoint, ...]) -> list[tuple[Checkpoint, str]]:
    """(물음, 크기) 목록 — 크기는 `full` · `ask` · `fold` · `quiet`.

    이 저장소에서 이미 세 번 답한 종류를 네 번째에도 같은 분량으로 설명하면, 그건 배려가 아니라
    사용자 시간을 쓰는 일이다(안내는 줄어쓰는 것이 목표다). 반대로 접는다고 지우지는 않는다 —
    접힌 줄은 화면에 남아서 "이 종류도 이번에 있었다"는 사실을 계속 말한다.

    문장의 각도도 여기서 정해진다: 같은 물음을 두 번째로 놓는 자리면 두 번째 각도로 갈아 끼운다.
    `record` 뒤에 부르는 것이 계약이다 — 회차를 세기 전에 각도를 고르면 한 박자씩 밀린다.
    """
    data = tutor_growth.load(root)
    out: list[tuple[Checkpoint, str]] = []
    for point in points:
        entry = data["open"].get(point.cid)
        asks = int(entry.get("asks") or 1) if isinstance(entry, dict) else 1
        out.append((angled(point, asks), tutor_growth.form(data, point.kind)))
    return out


def revisits(root: str, now: float | None = None, cap: int = 2, skip: object = ()) -> list[tutor_growth.Revisit]:
    """때가 됐고 **코드가 아직 거기 있는** 물음 — 각도를 바꿔서, 다음 회차 예약까지 끝내서 준다.

    없는 자리를 열어 보라고 두 번 말하면 사용자는 이 카드를 통째로 안 믿는다. 그래서 재방문은
    기록만으로 결정하지 않고 매번 나무를 한 번 본다 — 되짚기가 유일하게 파일을 다시 읽는 자리다.
    죽은 좌표는 여기서 만료로 닫힌다(조용히 지우지 않는다).

    `skip`은 이번 턴이 방금 물은 자리다. 같은 물음이 위(이번 변경)와 아래(재방문)에 두 번 들어가면
    읽는 쪽은 그걸 두 건으로 세고, 두 번 실린 화면은 한 번도 안 읽힌다.
    """
    seen = {str(s) for s in skip} if isinstance(skip, (list, tuple, set, frozenset)) else set()
    alive, dead = [], []
    for row in tutor_growth.due(root, now, cap=max(cap * 4, 8)):
        if row.cid in seen:
            continue
        (alive if _alive(root, row) else dead).append(row)
    if dead:
        tutor_growth.expire(root, [row.cid for row in dead], "gone", now)
    out = []
    for row in alive[:cap]:
        turns = ANGLES.get(row.kind, ())
        index = row.asks - 1  # asks는 아래 record에서 곧 +1 된다 — 그 회차의 각도를 미리 고른다
        ask = turns[min(index, len(turns) - 1)] if turns and index >= 0 else row.ask
        out.append(replace(row, ask=ask, asks=row.asks + 1))
    if out:
        record(
            root,
            [{"kind": r.kind, "path": r.path, "unit": r.unit, "key": r.key, "ask": r.ask} for r in out],
            now,
        )
    return out


def _alive(root: str, row: tutor_growth.Revisit) -> bool:
    """좌표가 아직 살아 있는가. **모르면 살아 있다고 본다** — 물음을 조용히 지우는 쪽이 더 나쁘다.

    단위 이름이 본문 어디에도 없으면 확실히 사라진 것이다. 이름이 있으면(다른 곳에서 언급만 하는
    경우 포함) 살아 있다고 친다. 단위가 없는 물음(표식 등)은 파일 존재만 본다 — 표식 한 줄의
    생사까지 여기서 다시 판정하면 판정기가 두 벌이 된다.
    """
    text = _read(root, row.path)
    if text is None:
        return False
    return True if not row.unit else row.unit.rsplit(".", 1)[-1] in text


def hand_back(
    root: str,
    points: tuple[Checkpoint, ...],
    limit: int = 3,
    count: bool = True,
    now: float | None = None,
) -> tuple[list[tuple[Checkpoint, str]], list[tutor_growth.Revisit]]:
    """화면에 들어갈 모양 + 되돌아온 물음. 두 도달 경로(훅·네이티브)가 같은 함수를 쓴다.

    **화면에 실린 것만 센다.** 판정이 119건을 찾아도 카드에 셋이 올라갔으면 물은 것은 셋이다 —
    나머지를 세면 사용자가 본 적 없는 물음이 "건너뛴 것"으로 기록되고, 그러면 조절이 사람이 아닌
    판정기의 크기를 따라간다(실측: 400파일 넓은 진단 한 번이 기록을 119건으로 부풀렸다).

    세는 것이 먼저이고 문장을 고르는 것이 나중이다 — 회차를 센 뒤라야 그 회차의 각도가 나온다.
    """
    data = tutor_growth.load(root)
    shown = [p for p in points if tutor_growth.form(data, p.kind) not in ("fold", "quiet")][:limit]
    if count and shown:
        record(root, shown, now)
    rows = shaped(root, points)
    back = revisits(root, now, skip=[p.cid for p in points]) if count else []
    return (rows, back)


def record(root: str, points: object, now: float | None = None) -> dict[str, str]:
    """놓은 물음을 성장 기록에 남긴다 — 중복 호출에 안전(같은 턴에 훅과 네이티브가 겹쳐 돈다).

    `now`를 그대로 넘기는 것이 계약이다. 여기서 시계를 갈아 끼우면 재방문 사다리가 제자리를
    맴돈다 — 예약은 미래 시각으로 재고 판정은 현재 시각으로 하면 영원히 "아직 때가 아니다"가 된다.
    """
    try:
        return tutor_growth.note_asked(root, points, now)
    except Exception:
        return {}  # 기록 실패가 화면을 막지 않는다 — 되짚기는 규율이지 관문이 아니다


# ── 도중 개입·서사 되짚기 ─────────────────────────────────────────

TIPS_REL = os.path.join(".asgard", "tutor", "tips.json")
_SIGNAL_LABEL = {
    "acceptance-latency": "답 수용 속도",
    "unanswered-backlog": "답 없는 물음",
    "review-ratio": "검토 비율",
    "skip-streak": "연속 건너뜀",
    "session-load": "세션 부하",
}
_TIP_ASK = {
    "acceptance-latency": "방금 받아들인 답을 반대로 깨뜨리는 예를 하나 떠올려 보셨나요?",
    "unanswered-backlog": "계속 진행하기 전에 답 없는 물음 하나를 골라 직접 설명해 볼까요?",
    "review-ratio": "가장 큰 변경 하나를 열고, 왜 이렇게 됐는지 말로 다시 확인해 볼까요?",
    "skip-streak": "이 물음은 정말 버릴 물음인가요, 아니면 지금 닫을 답이 있나요?",
    "session-load": "다음 변경 전에 지금까지의 결정을 한 줄로 다시 말해 볼까요?",
}
_SPAN_LABEL = {"session": "이번 세션", "day": "오늘", "week": "이번 주"}
_SPAN_DAYS = {"day": 1.0, "week": 7.0}


def tips(root: str, sid: str = "", cap: int = 1, now: float | None = None) -> list[str]:
    """작업 **도중** 놓을 팁. 없으면 빈 목록 — 대부분의 턴은 빈 목록이어야 한다."""
    try:
        limit = max(0, int(cap))
    except TypeError, ValueError:
        return []
    if limit <= 0:
        return []
    ledger = _debt_ledger(root, sid, now)
    seen = _tips_seen(root, sid)
    signals = [s for s in _active_signals(ledger) if _signal_name(s) not in seen]
    picked = signals[:limit]
    if not picked:
        return []
    _tips_mark(root, sid, [_signal_name(s) for s in picked])
    return [_tip_card(s) for s in picked]


def recap(root: str, sid: str = "", span: str = "session", now: float | None = None) -> str:
    """세션/일 단위 서사. span = "session" | "day" | "week". 없으면 빈 문자열."""
    name = str(span or "session")
    if name not in _SPAN_LABEL:
        return ""
    stamp = time.time() if now is None else now
    ledger = _debt_ledger(root, sid, stamp)
    data = tutor_growth.load(root)
    closed = _closed_in_span(data, name, stamp)
    open_rows = tutor_growth.open_points(root)
    if not _recap_has_material(ledger, closed, open_rows, name == "session"):
        return ""
    work_ledger = ledger if name == "session" else None
    parts = [_recap_work(_SPAN_LABEL[name], work_ledger, closed), _recap_open(open_rows, ledger, stamp)]
    debt = _recap_debt(ledger)
    if debt:
        parts.append(debt)
    return "\n\n".join(p for p in parts if p)


def _debt_ledger(root: str, sid: str, now: float | None):
    """부채 계측은 늦게 읽는다 — 같은 시각에 만드는 모듈이 없어도 튜터 시작은 깨지면 안 된다."""
    try:
        module = importlib.import_module(f"{__package__}.tutor_debt")
        return module.ledger(root, sid, now)
    except Exception:
        return None


def _active_signals(ledger: object) -> list[object]:
    rows = []
    for signal in getattr(ledger, "signals", ()) or ():
        if _signal_name(signal) and _signal_level(signal) > 0:
            rows.append(signal)
    return sorted(rows, key=lambda s: (-_signal_level(s), _signal_name(s)))


def _signal_name(signal: object) -> str:
    return str(getattr(signal, "name", "") or "")


def _signal_level(signal: object) -> int:
    try:
        return int(getattr(signal, "level", 0) or 0)
    except TypeError, ValueError:
        return 0


def _tip_card(signal: object) -> str:
    name = _signal_name(signal)
    fact = " ".join(str(getattr(signal, "fact", "") or "").split())
    head = f"⠶ 도중 점검 — {_SIGNAL_LABEL.get(name, name)}"
    if fact:
        head += f": {fact}"
    ask = _TIP_ASK.get(name, "이 신호를 보고 지금 사람이 직접 확인해야 할 판단은 무엇인가요?")
    return f"{head}\n    ▸ {ask}"


def _tips_path(root: str) -> str:
    return os.path.join(root, TIPS_REL)


def _sid(sid: str) -> str:
    return str(sid or "").strip() or "(default)"


def _tips_seen(root: str, sid: str) -> set[str]:
    data = read_json(_tips_path(root), {})
    sessions = data.get("sessions") if isinstance(data, dict) else {}
    row = sessions.get(_sid(sid), []) if isinstance(sessions, dict) else []
    return {str(name) for name in row} if isinstance(row, list) else set()


def _tips_mark(root: str, sid: str, names: list[str]) -> None:
    data = read_json(_tips_path(root), {})
    if not isinstance(data, dict):
        data = {}
    sessions = data.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        sessions = {}
        data["sessions"] = sessions
    key = _sid(sid)
    row = sessions.get(key, [])
    seen = {str(name) for name in row if name} if isinstance(row, list) else set()
    seen.update(names)
    sessions[key] = sorted(seen)
    data["version"] = 1
    try:
        write_json(_tips_path(root), data)
    except OSError:
        pass  # 못 적었으면 같은 팁이 한 번 더 나올 수 있다 — 기록 실패가 작업을 막으면 안 된다


def _closed_in_span(data: dict, span: str, stamp: float) -> list[dict]:
    rows = [r for r in data.get("closed", []) if isinstance(r, dict)]
    if span == "session":
        return []
    cutoff = stamp - _SPAN_DAYS[span] * tutor_growth.DAY
    return [r for r in rows if _row_float(r, "at") >= cutoff]


def _row_float(row: dict, name: str) -> float:
    try:
        return float(row.get(name) or 0.0)
    except TypeError, ValueError:
        return 0.0


def _recap_has_material(
    ledger: object, closed: list[dict], open_rows: list[tutor_growth.Revisit], include_work: bool
) -> bool:
    if closed or open_rows or _active_signals(ledger):
        return True
    names = ("open_debt", "oldest_days", "turns", "added") if include_work else ("open_debt", "oldest_days")
    return any(_ledger_int(ledger, name) for name in names)


def _ledger_int(ledger: object, name: str) -> int:
    try:
        return int(getattr(ledger, name, 0) or 0)
    except TypeError, ValueError:
        return 0


def _recap_work(label: str, ledger: object, closed: list[dict]) -> str:
    turns, added = _ledger_int(ledger, "turns"), _ledger_int(ledger, "added")
    if turns or added:
        return (
            f"⠶ 되짚기 — {label}에는 튜터가 {turns}턴을 보았고, 변경은 +{added:,}행까지 쌓였어요. "
            "닫힌 물음은 세션별로 나뉘어 있지 않아서, 아래에는 지금 남은 것과 부채 신호를 중심으로 적어요."
        )
    if closed:
        kinds = _kind_summary([str(r.get("kind") or "") for r in closed])
        return f"⠶ 되짚기 — {label}에는 물음 {len(closed)}건이 닫혔어요. 최근에는 {kinds} 쪽을 처리했어요."
    return f"⠶ 되짚기 — {label}에 새로 닫힌 물음은 아직 확인하지 못했어요. 그래서 남은 질문을 먼저 봐요."


def _recap_open(open_rows: list[tutor_growth.Revisit], ledger: object, stamp: float) -> str:
    if open_rows:
        oldest = min(open_rows, key=lambda r: r.opened)
        return (
            f"⠶ 답 없이 남은 것 — 열린 물음 {len(open_rows)}건이 그대로 남아 있어요. "
            f"가장 오래된 것은 {oldest.where}에서 {oldest.days(stamp)}일째 기다리고 있고, "
            f'질문은 "{oldest.ask}"예요.'
        )
    debt = _ledger_int(ledger, "open_debt")
    if debt:
        days = _ledger_int(ledger, "oldest_days")
        return (
            f"⠶ 답 없이 남은 것 — 계측에는 답 없는 물음 {debt}건이 잡혔지만 좌표 기록은 못 읽었어요. "
            f"가장 오래된 것은 {days}일째 남아 있어요."
        )
    return "⠶ 답 없이 남은 것 — 지금 열린 물음은 없어요. 기록에 안 드러난 채 남은 물음도 없다는 뜻이에요."


def _recap_debt(ledger: object) -> str:
    if ledger is None:
        return "⠶ 부채 위치 — 부채 계측을 읽지 못했어요. 못 본 값을 0으로 적지 않고 이 구간은 비워 둬요."
    signals = _active_signals(ledger)
    if not signals:
        return "⠶ 부채 위치 — 지금 경고 신호는 없어요. 그래도 새 물음이 생기면 답을 숨기지 않고 남겨 둬야 해요."
    signal = signals[0]
    name, fact = _signal_name(signal), " ".join(str(getattr(signal, "fact", "") or "").split())
    source = " ".join(str(getattr(signal, "source", "") or "").split())
    why = " ".join(str(getattr(signal, "why", "") or "").split())
    # 경로 뒤에 서술어를 붙이지 않는다 — `debt.json예요` 는 파일명의 일부처럼 읽히고, 사람이
    # 그 자리를 복사해 열 때 조사까지 딸려 간다. 좌표는 좌표로 끝낸다.
    tail = f" 출처: {source}." if source else ""
    if why:
        tail += f" 근거는 {why}" + ("" if why.endswith((".", "?", "!")) else ".")
    return (
        f"⠶ 부채 위치 — 지금 가장 큰 신호는 {_SIGNAL_LABEL.get(name, name)} 쪽이에요"
        + (f": {fact}." if fact else ".")
        + tail
        + " 여기서 답을 정하지 말고, 사람이 다시 설명할 수 있는지 먼저 확인해요."
    )


def _kind_summary(kinds: list[str]) -> str:
    counts: dict[str, int] = {}
    for kind in kinds:
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    return _folded_line(counts) if counts else "종류 없는 물음"


# ── 앞서 말하는 층 (일을 시작하기 전) ──────────────────────────────

_TOKEN = re.compile(r"[A-Za-z0-9_./\\-]{3,}")
# 자기 힘으로는 자리를 못 가리키는 조각. `src` 한 글자에 나무 전체가 걸리면 이 줄은 배경 소음이
# 되고, 배경 소음이 된 안내는 켜져 있어도 꺼진 것과 같다. 확장자·구조 디렉터리가 여기 온다.
_WEAK = frozenset("src lib test tests spec py js ts tsx jsx go rs java kt md json toml yaml yml".split())


def brief(root: str, text: str = "", paths: object = (), cap: int = 3) -> str:
    """**들어가기 전에**이 자리에 남아 있는 답 없는 물음. 없으면 빈 문자열.

    되짚기는 지금까지 전부 사후였다 — 다 쓰고 나서 물었다. 그런데 같은 자리를 다시 건드리는
    순간이야말로 지난번 물음이 값을 갖는 유일한 때다: 그때는 "언젠가 볼 것"이었지만 지금은
    **지금 여는 파일**이다. 사후 카드가 부채를 적는 층이면 이건 부채를 만나는 층이다.

    새로 판정하지 않는다 — 이미 열려 있는 물음만 좌표로 거른다. 여기서 파일을 다시 읽기 시작하면
    턴 시작이 느려지고, 느린 안내는 꺼지는 안내다.
    """
    named = set(_normalise(paths))
    here = named or _here(root, _keys(text or ""))
    if not here:
        return ""
    hit = [r for r in tutor_growth.open_points(root) if r.path in here]
    back = tutor_growth.recall(root, here)
    if not hit and not back:
        return ""
    hit.sort(key=lambda r: (-WEIGHT.get(r.kind, 0), r.opened))
    lines = []
    if hit:
        lines.append(f"⠶ 들어가기 전 — 이 자리에 답 없는 물음이 {len(hit)}건 남아 있어요.")
        for row in hit[:cap]:
            lines.append(f"  {KIND_LABEL.get(row.kind, row.kind)} — {row.where}  [{row.cid}]")
            lines.append(f"    ▸ {row.ask}")
        if len(hit) > cap:
            lines.append(f"  …외 {len(hit) - cap}건")
    lines += _recall_lines(back, bool(hit))
    return "\n".join(lines)


def _here(root: str, keys: set[str]) -> set[str]:
    """요청 문장이 가리키는 자리 — 열린 물음이 안 남은 자리도 포함한다(회상은 거기서 나온다)."""
    if not keys:
        return set()
    return {path for path, units in tutor_growth.places(root).items() if _touches(path, units, keys)}


def _recall_lines(back: list[tutor_growth.Said], after_questions: bool) -> list[str]:
    """그때 당신이 한 답을 그대로 되돌려 준다 — 기계의 판정으로 다시 쓰지 않는다.

    날짜를 반드시 붙인다. 그 사이 코드가 바뀌었을 수 있고, 바뀌었는지는 여기서 못 정한다 —
    "당신이 그때 이렇게 말했다"는 사실만 참이고, 지금도 맞는지는 사람이 본다.
    """
    if not back:
        return []
    now = time.time()
    head = "  " if after_questions else "⠶ 들어가기 전 — "
    lines = [f"{head}이 자리를 두고 **예전에 하신 답**이 있어요."]
    for row in back:
        days = row.days(now)
        when = f"{days}일 전" if days else "오늘"
        tag = "오탐으로 닫음" if row.dismissed else "답"
        lines.append(f"  ↺ {row.where} — {when} {tag}")
        lines.append(f'    "{row.said}"')
    return lines


def _keys(text: str) -> set[str]:
    """요청 문장에서 자리를 가리킬 수 있는 조각만. `app.py`는 통째로도, 쪼개서도 센다."""
    out: set[str] = set()
    for raw in _TOKEN.findall(text):
        for piece in [raw, *re.split(r"[/\\.]", raw)]:
            key = piece.lower().strip("-_")
            if len(key) >= 3 and key not in _WEAK:
                out.add(key)
    return out


def _touches(path: str, units: set[str], keys: set[str]) -> bool:
    """요청 문장이 이 자리를 가리키는가 — 경로 조각과 단위 이름만 본다(0-LLM).

    느슨하게 맞추면 아무 요청에나 남의 물음이 붙고, 그러면 이 줄은 배경 소음이 된다. 그래서
    경로의 **조각 하나가 통째로** 일치할 때만 센다 (`heimdall` ○, `dall` ✕).
    """
    parts = {p.lower() for p in re.split(r"[/\\.]", path) if p}
    parts.add(path.lower())
    parts.add(os.path.basename(path).lower())
    parts |= {u.rsplit(".", 1)[-1].lower() for u in units if u}
    return bool(parts & keys)


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
    rows, back = hand_back(root, points, limit)
    told = _explained(root, paths, limit)
    if not points and not back and not told:
        return ""  # 물을 것도 설명할 것도 없으면 침묵한다 — 빈 카드는 다음 카드의 신뢰를 깎는다
    if _repeat(root, key, points, back, told):
        return ""
    return _card(lesson, rows, back, limit, told)


def _explained(root: str, paths: list[str], limit: int) -> str:
    """이번 변경의 설명 절. 엔진이 없으면 빈 문자열 — 그러면 카드는 물음만 낸다.

    늦게 읽는 이유는 `_debt_ledger`와 같다: 같은 시각에 만드는 모듈이 없어도 되짚기 시작은
    깨지면 안 된다. 문장은 엔진의 `card`가 그대로 만든다 — 여기서 다시 조립하면 화면이 두 벌이
    되고, 두 벌은 반드시 갈라진다(훅 `_card`와 같은 계약).

    카드가 실제로 그린 말은 그 자리에서 용어집에 적립한다. 이 경로에만 사는 세션(네이티브 루프)은
    `asgard tutor`를 안 거치므로, 여기서 안 적으면 용어집이 영영 안 쌓이고 설명은 회차마다 같은
    길이로 나온다. 적립 목록을 `shown_terms`에서 받는 이유는 하나다 — 카드가 상한에서 자른 말까지
    적으면 사람이 못 본 말이 "이미 설명한 말"이 된다.
    """
    try:
        module = importlib.import_module(f"{__package__}.tutor_teach")
        exp = module.explain(root, "HEAD", paths)
        told = str(module.card(exp, limit) or "").strip()
    except Exception:
        return ""
    try:
        if told:
            module.glossary_merge(root, module.shown_terms(exp, limit))
    except Exception:
        pass  # 적립 실패가 카드를 지우지는 않는다 — 그 말은 다음 회차에 한 번 더 설명된다
    return told


def _session_writes(root: str, sid: str) -> list[str]:
    """이 세션이 쓴 경로 (write sentinel). 사용자가 원래 갖고 있던 dirt는 이 턴의 물음이 아니다."""
    if not sid:
        return []
    rows = read_json(os.path.join(root, ".asgard", "state", f"writes-{sid}.json"), [])
    return [str(row) for row in rows] if isinstance(rows, list) else []


def _repeat(
    root: str, sid: str, points: tuple[Checkpoint, ...], back: list[tutor_growth.Revisit], told: str = ""
) -> bool:
    """같은 물음을 매 턴 다시 놓으면 세 번째부터 아무도 안 읽는다 — 지문이 같으면 침묵."""
    path = os.path.join(root, ".asgard", "state", f"tutor-{sid}.json")
    sig = _fingerprint(points, back, told)
    seen = (read_json(path, {}) or {}).get("signature")
    try:
        write_json(path, {"signature": sig})
    except OSError:
        pass  # 못 적었으면 다음 턴에 같은 카드가 한 번 더 나온다 — 중복이 침묵보다 낫다
    return seen == sig


def _fingerprint(points: tuple[Checkpoint, ...], back: list[tutor_growth.Revisit], told: str = "") -> str:
    """카드에 실릴 것 전부의 지문. 재방문도 설명 절도 여기 들어간다 — 안 넣으면 이번 턴에 처음
    돌아온 옛 물음이나 새로 바뀐 설명이 "직전 턴과 같은 카드"로 판정돼 통째로 사라진다(래치가
    자기 성장 경로를 막는다)."""
    rows = [f"{p.kind}|{p.path}|{p.unit}" for p in points] + [f"revisit|{r.cid}|{r.asks}" for r in back]
    if told:
        rows.append("explain|" + hashlib.sha256(told.encode("utf-8")).hexdigest()[:16])
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()[:16]


def _card(
    lesson: Lesson,
    rows: list[tuple[Checkpoint, str]],
    back: list[tutor_growth.Revisit],
    limit: int,
    told: str = "",
) -> str:
    added, removed = lesson.touched
    lines = [
        f"⠶ 되짚기 — 이번 턴 {len(lesson.files)}개 파일 · +{added:,}/-{removed:,}행이에요."
        " 아래는 **기계가 못 답하는** 것들이에요.",
        "",
    ]
    # 설명이 물음보다 위에 온다. 전달된 적 없는 것을 인출부터 시키면 물음은 답이 아니라 침묵을
    # 받는다 — 설명 절은 물음에 답하지 않고 그 물음이 서 있는 자리만 준다.
    if told:
        lines.append(told)
        lines.append("")
    lines += _card_points(rows, limit)
    lines += _card_back(back)
    lines.append("")
    lines.append(
        '  답은 `asgard tutor --answer <표식> "..."` · 오탐이면 `asgard tutor --dismiss <표식>`'
        " · 전체와 '왜 이렇게 했는가' 빈칸은 `asgard tutor --report`"
    )
    return "\n".join(lines)


def _card_points(rows: list[tuple[Checkpoint, str]], limit: int) -> list[str]:
    """펼친 것 · 접은 것 · 넘친 것. 셋을 같은 화면에 두는 것이 이 카드의 정직성이다."""
    lines: list[str] = []
    folded: dict[str, int] = {}
    quiet: dict[str, int] = {}
    shown = 0
    for point, form in rows:
        if form in ("fold", "quiet"):
            bucket = folded if form == "fold" else quiet
            bucket[point.kind] = bucket.get(point.kind, 0) + 1
            continue
        if shown >= limit:
            continue
        lines.append(f"  {KIND_LABEL.get(point.kind, point.kind)} — {point.where}  [{point.cid}]")
        lines.append(f"    ▸ {point.ask}")
        shown += 1
    over = sum(1 for _, form in rows if form not in ("fold", "quiet")) - shown
    if over > 0:
        lines.append(f"  …외 {over}건")
    if folded:
        lines.append(f"  {_folded_line(folded)} — 이미 답해 오신 종류라 접었어요")
    if quiet:
        lines.append(f"  {_folded_line(quiet)} — 계속 못 닿아서 접었어요 (`asgard tutor --progress`)")
    return lines


def _folded_line(counts: dict[str, int]) -> str:
    return " · ".join(f"{KIND_LABEL.get(kind, kind)} {n}건" for kind, n in sorted(counts.items()))


def _card_back(back: list[tutor_growth.Revisit]) -> list[str]:
    """되돌아온 물음. 답을 받은 적이 없다는 사실을 숨기지 않고 각도만 바꿔서 다시 놓는다."""
    now = time.time()
    lines: list[str] = []
    for row in back:
        days = row.days(now)
        when = f"{days}일 전에 물었고" if days else "오늘 물었고"
        lines.append(f"  ↩ 다시 — {row.where}  [{row.cid}]  ({when} 아직 답이 없어요)")
        lines.append(f"    ▸ {row.ask}")
    return lines
