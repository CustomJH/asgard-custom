"""Tutor가 만드는 사실의 값 객체.

탐침과 조립은 :mod:`asgard.tutor`가 맡고, 그 결과를 옮기는 작은 불변 모델만 여기 둔다.
별도 모듈이어도 기존 호출부는 ``tutor.Checkpoint``처럼 계속 접근할 수 있도록 tutor가 재노출한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import tutor_growth

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
# 종류의 사람 이름 — 표면마다 다시 쓰면 같은 판정이 화면마다 다른 이름으로 불린다. `WEIGHT` 와
# 같은 자리에 있는 이유도 같다: 사후 카드와 사전 브리핑이 둘 다 읽으므로 어느 한쪽이 가지면
# 다른 쪽이 위층을 거꾸로 부르게 된다.
KIND_LABEL = {
    "contract-break": "공개 계약 바뀜",
    "behavior-removed": "동작 사라짐",
    "test-removed": "판정 사라짐",
    "silent-failure": "조용히 삼킨 실패",
    "new-dependency": "외부 의존 늘어남",
    "untested-surface": "판정 없는 새 표면",
    "todo-left": "안 끝난 표식",
}


@dataclass(frozen=True)
class Checkpoint:
    """사용자가 직접 확인해야 하는 자리 하나."""

    kind: str
    path: str
    line: int
    unit: str
    what: str
    why: str
    ask: str
    key: str = ""

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
    """파일 하나의 변경 인벤토리."""

    path: str
    added: int
    removed: int
    units_added: tuple[str, ...] = ()
    units_changed: tuple[str, ...] = ()
    units_removed: tuple[str, ...] = ()
    new_file: bool = False
    judged: bool = True
    code: bool = True
    units_moved: tuple[str, ...] = ()


@dataclass(frozen=True)
class Lesson:
    """한 번의 되짚기에 필요한 사실 묶음."""

    base: str
    files: tuple[FileChange, ...]
    checkpoints: tuple[Checkpoint, ...]
    undetermined: tuple[tuple[str, str], ...]
    mandate: tuple[dict, ...] = ()

    @property
    def ranked(self) -> tuple[Checkpoint, ...]:
        def key(point: Checkpoint) -> tuple[int, int, str, int]:
            grouped_removal = point.kind in {"behavior-removed", "test-removed"} and not point.unit
            return (-point.weight, 0 if grouped_removal else 1, point.path, point.line)

        return tuple(sorted(self.checkpoints, key=key))

    @property
    def touched(self) -> tuple[int, int]:
        return (sum(f.added for f in self.files), sum(f.removed for f in self.files))

    @property
    def moved(self) -> int:
        return sum(len(f.units_moved) for f in self.files)
