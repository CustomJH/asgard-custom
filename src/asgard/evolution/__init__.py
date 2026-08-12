"""evolution — 회고 증류기 + 진화 인박스 (자가발전 C1/C2, CUS-253·254).

quest 로그(.asgard/quest/*.jsonl)에서 hard-won 신호(실패를 딛고 PASS에 도달한 퀘스트)만
결정론적으로 선별해 스킬 초안을 만들고, .asgard/evolution/pending/ 인박스에 스테이징한다.

learned 스킬 뱅크(.asgard/skills/)로 설치하는 함수는 `approve` 하나다. 그 하나를 누가 누르는지는
자율 등급이 정한다 (`autonomy_mode` — 기본 safe 는 퀘스트 로그 채굴분을 스스로 설치하고, 정정
채굴분은 사람에게 남긴다). 등급이 무엇이든 검사는 approve 안에 있고, 설치된 것은
`evolve archive` 로 물러난다.

설계 근거 (CUS-251 리서치):
- 선별은 결정론, 가치 판단은 사용자 — 저신호 휴리스틱 양산은 승인율을 0으로 만든다는
  실증 교훈. 여기서는 "FAIL→PASS 전환"이라는 고신호만 후보가 된다 (hard-won 교훈).
- 캡처 금지 필터 — 환경 의존 실패·일시 장애는 스킬이 아니다 (실전 교훈: 도구 부정 주장을
  캡처하면 몇 달간 자기 인용해 스스로 거부하게 된다).
- 거부 신호는 latch — 같은 신호를 다시 제안하지 않는다 (consent-first, 제안 피로 방지).
- 초안은 증거 카드 (실측 failure_sig·통과 명령·criteria) — 추측 서사를 쓰지 않는다.

파사드다. 본문은 아래 모듈들이 나눠 진다 — 부르는 쪽은 종전대로 `asgard.evolution` 하나만
보면 되고, 밑줄로 시작하는 이름도 여기서 그대로 다시 내보낸다 (시험이 직접 임포트한다).
"""

from __future__ import annotations

# 분해 전 `evolution` 이 들고 있던 이름 — 이 모듈 안에서는 안 쓰지만 부르는 쪽이 이 이름으로
# 닿을 수 있어 그대로 남긴다.
from ..skill_bank import (  # noqa: F401
    APPROVAL_FILE,
    SKILL_FILE,
    approval_receipt,
    learned_skills,
    parse_skill_md,
)
from .autonomy import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _AUTONOMY_ORIGINS,
    AUTONOMY_ENV,
    AUTONOMY_MODES,
    AUTOSCAN_ENV,
    autoapprove,
    autonomy_mode,
    autoscan,
    autoscan_enabled,
)
from .corrections import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _BARE_END,
    _CLAUSE_END,
    _CLOSERS,
    _CORRECTION_MAX_CHARS,
    _CORRECTION_PATTERNS,
    _QUOTES,
    _STATEMENT_END,
    _corrections,
    correction_signal,
    record_correction,
)
from .decisions import approve, reject, reset
from .distill import _POLISH_SYS, polish  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
from .drafts import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _CONTRACT_TAIL,
    _CONTRACT_TAIL_RE,
    _DESC_FILES,
    _IDENT,
    _SEPARATORS,
    _SKIP_STEMS,
    _STOPWORDS,
    _TRIGGER_CAP,
    _TRIGGER_MIN,
    PLACEHOLDER_TRIGGER,
    _cand_id,
    _correction_draft,
    _draft,
    _more,
    _slug,
    _too_loose,
    _triggers,
    weak_triggers,
)
from .inbox import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _stage_candidate,
    mine,
    pending_list,
    show,
    unmined_signals,
)
from .nudge import _INBOX_TAIL, _fresh, _installed_line, nudge_line  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
from .quests import _FORBIDDEN_SIG, _quest_signal, _read_quest  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
from .skills import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _bundled_names,
    _discard_reopened_draft,
    _receipt_cid,
    _redraw_roster,
    _relatch,
    archive_skill,
    restore_skill,
)
from .store import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _CORRECTIONS_CAP,
    _DECIDED,
    _SCAN_CAP,
    ARCHIVED,
    CORRECTIONS_FILE,
    EVO_DIR,
    PENDING,
    PROPOSED,
    REJECTED,
    SEEN_FILE,
    _archive_slot,
    _clear_nudge_latch,
    _evo_dir,
    _latched,
    _load_seen,
    _mineable,
    _save_seen,
)

__all__ = [
    "ARCHIVED",
    "AUTONOMY_ENV",
    "AUTONOMY_MODES",
    "AUTOSCAN_ENV",
    "CORRECTIONS_FILE",
    "EVO_DIR",
    "PENDING",
    "PLACEHOLDER_TRIGGER",
    "PROPOSED",
    "REJECTED",
    "SEEN_FILE",
    "approve",
    "archive_skill",
    "autoapprove",
    "autonomy_mode",
    "autoscan",
    "autoscan_enabled",
    "correction_signal",
    "mine",
    "nudge_line",
    "pending_list",
    "polish",
    "record_correction",
    "reject",
    "reset",
    "restore_skill",
    "show",
    "unmined_signals",
    "weak_triggers",
]
