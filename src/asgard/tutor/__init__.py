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

계약 ③ 에는 예외가 둘 있고 둘 다 같은 조건에서 열린다: **저자가 사람이 아닐 때**. 루프가 고른
자리의 근거는 `loop.mandate_for` 가, 그 턴이 무엇을 맞추려 했고 무엇으로 닫혔는지는
`tutor_rationale` 이 퀘스트 로그에서 읽어 온다. 둘 다 추측이 아니라 기계가 이미 적어 둔 기록이고,
기록이 없으면 빈칸은 그대로 빈칸이다. 이 예외가 필요한 이유는 ① 과 같은 축이다 — 남이 쓴 코드에
대해 "왜 그렇게 했나"를 사람에게 물으면 그것은 되짚기가 아니라 시험이다.

래칫은 `craft`와 같다: base에 이미 있던 것은 다시 묻지 않는다. 물음도 부채라서, 매 턴 같은
것을 물으면 세 번째부터 아무도 안 읽는다.

물음을 놓은 **뒤**는 `tutor_growth`가 센다 — 답했는가, 건너뛰었는가, 그래서 다음엔 얼마나 말할
것인가(조절), 안 답한 것을 언제 다시 꺼낼 것인가(재방문). 이 층은 계속 "이번 변경의 사실"만
만들고, 그 사실을 사람에 맞춰 **줄이는** 일은 `pacing` 에서만 일어난다. 나누는 이유는
하나다: 사실이 사람에 따라 달라지기 시작하면 `--json`이 두 사람에게 다른 답을 내게 된다.

파사드다. 본문은 아래 모듈들이 나눠 진다 — 부르는 쪽은 종전대로 `asgard.tutor` 하나만 보면
되고, 밑줄로 시작하는 이름도 여기서 그대로 다시 내보낸다 (시험이 직접 임포트한다).
"""

from __future__ import annotations

# 분해 전 `tutor` 가 들고 있던 이름 — 이 파사드에서는 안 쓰지만 부르는 쪽이 이 이름으로 닿을 수
# 있어 그대로 남긴다. `importlib` 는 시험이 `tutor.importlib.import_module` 를 갈아 끼운다.
import hashlib  # noqa: F401
import importlib  # noqa: F401
import os  # noqa: F401
import subprocess  # noqa: F401
import time  # noqa: F401
from dataclasses import replace  # noqa: F401

from .. import craft, craft_lex, loop, surface, tutor_growth, tutor_probes  # noqa: F401
from ..craft_rules import Unit  # noqa: F401
from ..health import _read  # noqa: F401
from ..io_files import read_json, write_json  # noqa: F401

# 본문은 `tutor_brief` 가 갖는다 — 축이 다르다. 이 층은 **이번 변경의 사실**을 만들고, 그쪽은
# 이미 쌓인 기록을 요청 문장에 맞춰 고르기만 한다. 이름을 여기 남기는 것은 부르는 쪽 때문이다:
# `commands/tutor` 와 시험 여럿이 `tutor.brief` 로 부른다.
from ..tutor_brief import brief as brief

# 재수출 — 스튜디오 패널과 시험, 그리고 사전 브리핑이 `tutor.WEIGHT`·`tutor.KIND_LABEL` 로 부른다.
from ..tutor_model import KIND_LABEL as KIND_LABEL
from ..tutor_model import WEIGHT as WEIGHT
from ..tutor_model import Checkpoint, FileChange, Lesson  # noqa: F401
from .contracts import _surface_points, _untested_points  # noqa: F401
from .diffs import _at_base, _int, _numstat  # noqa: F401
from .labels import _folded_line, _point_label  # noqa: F401
from .lesson import _anchored, _normalise, review  # noqa: F401
from .narrative import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _SIGNAL_LABEL,
    _SPAN_DAYS,
    _SPAN_LABEL,
    _TIP_ASK,
    TIPS_REL,
    _active_signals,
    _closed_in_span,
    _debt_ledger,
    _kind_summary,
    _ledger_int,
    _recap_debt,
    _recap_has_material,
    _recap_open,
    _recap_work,
    _row_float,
    _sid,
    _signal_level,
    _signal_name,
    _tip_card,
    _tips_mark,
    _tips_path,
    _tips_seen,
    recap,
    tips,
)
from .native import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    DEFAULT_MODE,
    MODES,
    _card,
    _card_back,
    _card_points,
    _explained,
    _fingerprint,
    _mode,
    _rationale_lines,
    _repeat,
    _session_rel,
    _session_writes,
    _shown_rows,
    mode,
    turn_note,
)
from .pacing import ANGLES, _alive, angled, hand_back, record, revisits, shaped  # noqa: F401
from .points import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    MAX_PATHS,
    REMOVAL_DETAIL_LIMIT,
    _fresh,
    _inventory,
    _is_code,
    _judge,
    _Judged,
    _mark_point,
    _move_label,
    _moved_only,
    _Moves,
    _own_names,
    _python_points,
    _relocations,
    _removal_group_point,
    _removal_point,
    _removal_points,
    _stat,
)
