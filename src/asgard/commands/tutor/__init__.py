"""asgard tutor — 되짚기 자료의 사람 표면.

계약 세 줄: ① **사실과 물음을 화면에서 분리한다** — 무엇이 바뀌었나가 먼저, 당신이 답할
것이 그 다음이다. ② 순위를 매겨 위에서부터 넣는다 — 스무 개를 나란히 늘어놓으면 아무도 첫
번째부터 보지 않는다. ③ 못 본 것을 같은 화면에 넣는다 — "확인할 것 0건"이 "안 봤다"를 뜻할 수
있으면 이 도구는 거짓말을 하는 것이다.

보고서(`--report`)에는 화면에 없는 절이 하나 더 있다: **왜 이렇게 했는가**. 그 칸의 절반은
기계가 채운다 — 이 변경을 만든 퀘스트가 무엇을 맞추려 했고 무엇으로 닫혔는지는 로그에 적혀
있고, `tutor_rationale` 이 그것을 원문 그대로 가져온다. 나머지 절반(왜 이 방법이었나, 버린
방법은 무엇인가)은 여전히 빈칸이고 코드를 쓴 쪽이 채운다.

화면이 무엇을 요구하는가는 모드가 정한다 (`tutor.mode`, 기본 `explain`). `explain` 은 짚을
자리를 사실로 놓고 끝내고, `quiz` 는 물음으로 놓고 `--answer` 왕복을 기다린다.

여기 표면이 넷 더 있다. 물음만 놓고 끝나던 층을 **왕복**으로 만드는 것들이다:
`--answer`/`--dismiss`는 답이 돌아오는 통로(답이 없으면 이 층은 아무것도 못 배운다),
`--collect`는 보고서에 손으로 적은 답을 한 번에 모아 오는 통로(편집기에서 적는 것이 실제
사람이 답하는 방식이다), `--progress`는 그 왕복이 쌓인 결과, `--brief`는 같은 자리를 다시
건드리기 **전에** 남은 물음을 꺼내는 통로다.

파사드다. 본문은 아래 모듈들이 나눠 진다 — 부르는 쪽은 종전대로 `asgard.commands.tutor` 하나만
보면 되고, 밑줄로 시작하는 이름도 여기서 그대로 다시 내보낸다 (시험이 직접 임포트한다).
"""

from __future__ import annotations

# 분해 전 이 모듈이 들고 있던 이름 — 파사드에서는 안 쓰지만 부르는 쪽이 이 이름으로 닿을 수 있어
# 그대로 남긴다.
import json  # noqa: F401
import os  # noqa: F401
import re  # noqa: F401
from dataclasses import asdict  # noqa: F401
from importlib import import_module  # noqa: F401
from typing import Any  # noqa: F401

from ... import tutor, tutor_growth, ui  # noqa: F401
from ..health import _project_root  # noqa: F401
from .answers import _CID_RE, _ITEM_RE, _flush, _run_collect, collect  # noqa: F401
from .engines import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _as_dict,
    _engine,
    _explanation,
    _learned,
    _rationale,
    _rationale_dict,
    _rationale_lines,
)
from .entry import _run_review, run_tutor  # noqa: F401
from .labels import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _KIND,
    _LADDER,
    _LEVEL_MARK,
    _SIGNAL_LABEL,
    _count_line,
    _counts,
    _point_counts,
    _point_label,
    _shown_rows,
    _summary,
    _units_line,
)
from .lanes import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _run_brief,
    _run_close,
    _run_debt,
    _run_expect,
    _run_explain,
    _run_mission,
    _run_progress,
    _run_recap,
    _run_settle,
    _run_tip,
)
from .payload import _payload  # noqa: F401
from .report import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _ANSWER_SLOT,
    _REPORT_DETAIL_LIMIT,
    _REPORT_GAP_LIMIT,
    _REPORT_REL,
    _REPORT_STEP_LIMIT,
    _REPORT_TERM_LIMIT,
    _WHY_SLOT,
    _report,
    _report_explain,
    _report_files,
    _report_mandate,
    _report_points,
    _report_why,
    _write_report,
)
from .screen import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    _emit_back,
    _emit_explain,
    _emit_folded,
    _emit_inventory,
    _emit_mandate,
    _emit_points,
    _emit_review,
    _emit_said,
    _emit_terms,
    _emit_why,
)
