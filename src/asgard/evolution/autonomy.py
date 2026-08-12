"""자율 손잡이 둘 — 스스로 캘 것인가(`autoscan`), 스스로 설치할 것인가(`autonomy_mode`)."""

from __future__ import annotations

import os

from .decisions import approve
from .inbox import mine

AUTOSCAN_ENV = "ASGARD_EVOLVE_AUTOSCAN"


def autoscan_enabled() -> bool:
    """퀘스트가 닫힐 때 스스로 채굴하는가 — env > 글로벌 `evolution.autoscan`, 기본 on.

    채굴 자체는 **능력을 바꾸지 않는다**: 결과는 pending 인박스의 초안 파일이다. 그 초안이
    라우팅에 서느냐는 별개의 손잡이가 정한다 (`autonomy_mode`) — 이 스위치를 꺼도 저 등급이
    켜져 있으면 채굴이 없어 설치도 없고, 이 스위치만 켜면 초안까지만 생긴다.

    왜 기본을 켜는가. 넛지만 두었더니 신호가 **실제로 채굴되지 않았다** (26-07-31 실측: 이
    저장소에 hard-won 신호 2건이 닷새째 남아 있었고 인박스는 한 번도 만들어진 적이 없다).
    넛지는 신호 집합이 바뀔 때 한 번만 말하는 latch라 놓치면 영영 조용하고, 퀘스트 로그는
    keep-last-N으로 지워진다 — 교훈이 조용히 사라지는 쪽이 기본값이었다."""
    value = str(os.environ.get(AUTOSCAN_ENV) or "").strip().lower()
    if value:
        return value in ("on", "1", "true", "yes")
    try:
        from ..settings import load_global

        setting = (load_global().get("evolution") or {}).get("autoscan", True)
    except Exception:
        return True
    return str(setting).strip().lower() not in ("off", "0", "false", "no")


def autoscan(root: str) -> list[dict]:
    """퀘스트 종료 시 자동 채굴 — 실패는 삼킨다 (성장은 부가 기능이지 종료 조건이 아니다)."""
    if not autoscan_enabled():
        return []
    try:
        return mine(root)
    except Exception:
        return []


AUTONOMY_ENV = "ASGARD_EVOLVE_AUTONOMY"
AUTONOMY_MODES = ("off", "safe", "full")
# 어느 채굴원까지 스스로 설치해도 되는가. 등급은 채굴원의 증거 무게로 가른다 (pattern 의
# explicit/deductive 경계와 같은 물음이다).
#
# retrospective = 퀘스트 하나가 실제로 FAIL 을 내고 그 다음에 PASS 한 기록이다. 실패 서명도
# 통과 명령도 하네스가 관측한 값이라 사람이 다시 확인할 것이 적다.
#
# correction = 오딘의 발화 한 줄이다. 그 한 줄이 검증된 수정인지 그때의 기분인지 문장만으로는
# 안 갈리고, 정정은 대개 취향을 담으므로 잘못 설치하면 그 취향이 다음 배차마다 되풀이된다.
# 그래서 safe 에서는 초안으로만 남기고 사람이 읽고 넘긴다.
_AUTONOMY_ORIGINS = {
    "off": frozenset(),
    "safe": frozenset({"retrospective"}),
    "full": frozenset({"retrospective", "correction"}),
}


def autonomy_mode() -> str:
    """자율 성장 등급 — env `ASGARD_EVOLVE_AUTONOMY` > 글로벌 `evolution.autonomy`, 기본 safe.

    off 는 종전 계약 그대로다: 채굴은 하고 설치는 사람만 한다. safe·full 은 그 승인 관문을
    없애는 것이 아니라 **대신 눌러 준다** — `approve` 를 그대로 지나므로 약한 트리거 거부와
    이름 충돌 거부가 한 자리도 빠지지 않고 선다. 금지 서명 필터는 그보다 앞선 채굴 단계에
    있어서(`_quest_signal`) 자동 설치분도 애초에 후보가 안 된다.

    기본을 켜는 근거는 autoscan 과 같다. 26-08-12 실측: 이 저장소에 초안 7건이 대기 중이고
    설치된 학습 스킬은 0건이었다 — 사람 손 하나에 레인 전체가 걸려 있으면 그 레인은 안 돈다.
    자율의 상한은 '가역'에 둔다: 자동 설치분은 영수증에 표식을 남기고 `evolve archive` 한 줄로
    물러난다. 판정 표면(Verifier·loki)에는 어느 등급에서도 안 들어간다 (skill_bank 헌법)."""
    value = str(os.environ.get(AUTONOMY_ENV) or "").strip().lower()
    if value in AUTONOMY_MODES:
        return value
    try:
        from ..settings import load_global

        setting = str((load_global().get("evolution") or {}).get("autonomy", "safe")).strip().lower()
    except Exception:
        return "safe"
    return setting if setting in AUTONOMY_MODES else "safe"


def autoapprove(root: str, mined: list[dict]) -> list[dict]:
    """방금 캔 초안 중 등급 자격분을 스스로 설치한다 — 반환 = 실제로 설치된 후보 메타.

    **이번 스캔이 캔 것만** 본다. 인박스에 이미 있던 초안은 사람이 읽고 그대로 둔 것일 수
    있고, 그것을 뒤늦게 설치하면 "설치하지 않는다"는 판단을 정책이 뒤집는다. 자율은 새로
    자라는 자리에만 서고 사람이 손댄 자리는 사람의 것으로 남긴다.

    한 번 보관된 신호는 등급과 무관하게 안 선다. 보관은 "이 카드는 안 쓴다"는 판단이고,
    보관이 신호를 다시 채굴 가능하게 열어 두므로(`_mineable`) 그 판단이 없으면 다음 tick 이
    같은 카드를 캐서 그대로 다시 설치한다 — 보관·재설치가 매 턴 도는 고리가 된다. 다시 캐는
    것까지는 값이 있다: 초안 생성기가 좋아졌을 때 사람이 새 카드를 **읽고** 고를 수 있다.

    설치 실패(약한 트리거·이름 충돌)는 조용히 넘긴다 — 초안은 pending 에 그대로 있고 사람이
    `evolve list` 에서 같은 것을 본다."""
    allowed = _AUTONOMY_ORIGINS.get(autonomy_mode(), frozenset())
    if not allowed or not mined:
        return []
    installed: list[dict] = []
    for meta in mined:
        if str(meta.get("origin") or "") not in allowed:
            continue
        if meta.get("reopened"):
            continue  # 사람이 한 번 내려놓은 것 — 다시 캐되 다시 설치하지는 않는다
        try:
            ok, _msg = approve(root, str(meta.get("id") or ""), auto=True)
        except Exception:
            continue  # 성장 실패가 턴을 막지 않는다
        if ok:
            installed.append(meta)
    return installed
