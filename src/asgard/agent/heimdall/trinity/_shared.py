"""Trinity 순환이 쓰는 상수와 순수 판정 — 실행 상태를 안 든다."""

from __future__ import annotations

import os
import re
import shlex
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # 순환 임포트 — core 가 trinity 를 들여온다. 어노테이션은 지연 평가라 이걸로 충분하다.
    from ....providers import ResolvedProvider
    from ..bifrost import BifrostLedger, CoordinatorLoop
    from ..core import Heimdall

MAX_TRINITY_TURNS = 12  # budget_priors.deep — 이 위는 폭주로 간주, Odin 보고
_CRAFT_MAX_BLOCKS = 2  # hooks/craft_gate.py MAX_BLOCKS와 동일 유지 (모드 간 같은 상한)
_CRAFT_MAX_PATHS = 200  # 판정 인자 폭주 방지 — craft_gate 훅과 같은 상한


def _craft_blocking(root: str, paths: list[str]) -> list[dict]:
    """이 퀘스트가 쓴 경로의 막는 판정 — craft(예산)와 thor gate(정확성)를 따로 부른다.

    한 호출로 묶으면 한쪽 판정기의 고장이 양쪽 판정을 조용히 통과시킨다 (craft-gate 훅과 같은
    규약). 두 판정기 모두 HEAD 대조 래칫이라 물려받은 부채는 여기서 안 걸린다."""
    from dataclasses import asdict

    from .... import craft as _craft
    from .... import thor_gate as _thor_gate

    out: list[dict] = []
    for label, module in (("craft", _craft), ("thor gate", _thor_gate)):
        try:
            report = module.judge(root, tuple(paths[:_CRAFT_MAX_PATHS]))
        except Exception:
            continue  # 이 판정기가 고장 났다 — 나머지 판정은 살린다
        out += [{"gate": label, **asdict(finding)} for finding in report.blocking]
    return out


_PYTHONISH = re.compile(r"^python[0-9.]*$")


def _runner_identity(cmd: str) -> str:
    """러너 래퍼를 벗긴 검증 명령 신원 — `uv run pytest X` 실패 뒤 `python -m pytest X` 성공이
    같은 검증의 해소로 인정되게 한다 (26-07-22 실측: 격리 워크스페이스에 .venv가 없어 uv 레인이
    환경 실패 → 동등 러너로 통과했는데 PASS가 무효화돼 재시도 턴 전체를 태웠다).
    파싱 불가·정규화 불일치는 원문 신원 그대로 — 종전 엄격 경로와 동일 (fail-safe)."""
    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError:
        return cmd
    while tokens:
        while tokens and "=" in tokens[0] and not tokens[0].startswith(("=", "-")):
            tokens = tokens[1:]  # 선행 VAR= 대입은 신원이 아니다
        if not tokens:
            break
        head = os.path.basename(tokens[0])
        if head == "env":
            tokens = tokens[1:]
            continue
        if head == "uv" and len(tokens) >= 2 and tokens[1] == "run":
            tokens = tokens[2:]
            while tokens and tokens[0].startswith("-"):
                tokens = tokens[1:]  # 값 취하는 플래그(--with X)는 미해석 — 불일치는 그저 미해소 유지
            continue
        if _PYTHONISH.match(head) and len(tokens) >= 3 and tokens[1] == "-m":
            tokens = tokens[2:]
            continue
        break
    if not tokens:
        return cmd
    head = os.path.basename(tokens[0])
    if _PYTHONISH.match(head):
        head = "python"
    return shlex.join([head, *tokens[1:]])


_FINDING_ACTIONS = ("auto-fix", "ask-user", "no-op")


def _classified_findings(verdict: dict) -> list[dict]:
    """판정에 실린 결함을 소유자별로 정규화 — 기계 수리(auto-fix)와 사람 판단(ask-user)을 가른다.

    `findings` 자체는 선택 필드다: 아예 없으면 종전 경로 그대로 (재시도)라 회귀가 없다. 다만 판정자가
    결함을 **올려 놓고** 분류를 빠뜨렸거나 모르는 값을 넣었다면 사람 쪽으로 닫는다 — 분류 불가를
    기계 수리로 흘리면 판단이 필요한 결함이 조용히 추측으로 해소된다."""
    raw = verdict.get("findings")
    if not isinstance(raw, list):
        return []
    rows: list[dict] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        action = str(item.get("action") or "").strip().lower()
        rows.append(
            {
                "id": str(item.get("id") or f"f{index}").strip()[:32],
                "severity": str(item.get("severity") or "").strip().lower()[:16],
                "file": str(item.get("file") or "").strip()[:200],
                "action": action if action in _FINDING_ACTIONS else "ask-user",
                "description": description[:600],
            }
        )
    return rows


class _RunState:
    """믹스인 셋이 공유하는 순환 상태의 선언 — 값은 `TrinityRun.__init__` 이 채운다.

    선언만 있고 대입이 없어서 런타임에는 아무 속성도 안 만든다. 분해 전에는 한 클래스라
    물을 일이 없던 것이 분해 뒤에 남았다: 믹스인 하나만 읽는 검사기에게 `self.request` 가
    어디서 오는지 말해 주는 자리가 없었다.

    형제 믹스인·`TrinityRun` 이 정의하는 메서드는 `Callable[..., T]` 로 적는다 — `def`
    스텁으로 적으면 MRO 끝자리에 안 부르는 구현이 하나 더 생긴다."""

    # ── 퀘스트 좌표 (생성 시 고정) ──
    _hd: Heimdall
    request: str
    cls: dict
    dual: bool
    standard: bool
    qid: str
    sid: str
    tc: str

    # ── 순환 가변 상태 ──
    _loop: CoordinatorLoop | None
    bifrost: BifrostLedger
    fail_history: list[str]
    gate_sigs: dict[str, int]
    gate_blocks: int
    craft_blocks: int
    coordinator_answers: list[tuple[str, str]]
    unit_reports: list[dict]

    # ── 턴 스코프 (매 턴 run() 이 재설정) ──
    role: str
    sess_role: str
    why: str
    level: str
    budget_note: str
    model: str | None
    used_model: str
    rrp: ResolvedProvider

    # ── 형제 믹스인·`TrinityRun` 이 정의하는 메서드 ──
    _orchestration_note: Callable[..., str]
    _intent_block: Callable[..., str]
    _trajectory_note: Callable[..., str]
    _tend_memory: Callable[..., None]
    _quest_paths: Callable[..., list[str]]
    _fail_and_repair: Callable[..., bool]
