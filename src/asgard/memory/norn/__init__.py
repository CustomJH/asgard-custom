"""노른 (norn) — 위그드라실을 손질하는 손. 자라난 기억을 주기적으로 돌보는 자가 진화 패스.

노르니르가 우르드 샘물을 길어 나무가 마르지 않게 돌보듯, 노른은 위키를 손질한다:
같은 사실은 하나로 모으고(merge), 낱개 관측 뒤의 패턴을 승격하고(insight), 낡은 가지는
접어 보관하고(archive), 서로 어긋난 기록은 사람에게 알린다(contradiction).

계약 — LLM은 델타만 제안하고, 커밋은 결정론 코드가 한다:
- 전면 재작성 금지. 델타 단위 제안만 받아야 반복 손질이 기억을 뭉개지 않는다.
- 각 op는 기계 검증을 통과한 것만 남는다 — LLM의 주장은 검증 입력일 뿐이다:
  merge는 결정적 유사도 플로어 미달이면 기각, archive는 lint decay-candidate만 자격,
  insight는 실존 소스 2개 이상 + 인젝션/시크릿 스캔 + **근거 대조** + **극성** 통과
  (세 물음이 다 다르다: 소스가 있는가 · 통찰이 그 소스에서 나왔는가 · 나왔는데 뒤집지는
  않았는가. 어휘를 그대로 쓰면서 부정만 떼어 낸 문장은 근거 점수가 오히려 높다),
  confidence는 근거 수로 코드가 계산한다 (자기 신고 불신).
- 그래도 결정론이 답할 수 없는 물음이 남는다 — "출처에서 왔고 뒤집지도 않았는데 틀린
  추론". 그래서 통찰은 기본적으로 자동 승격되지 않는다 (norn_insight_auto 옵트인).
- 환경 의존 실패·도구 부정 주장은 기억으로 굳히지 않는다 — 그날의 사정이 원칙으로
  박제되면 미래의 자신을 거부하는 근거가 된다.
- 기존 페이지를 고치거나 없애는 op(merge·archive·link) 앞에 pages/ 전체 백업
  (norn-backups/, 최근 5개 유지), 삭제 없음 — archive는 archive/ 로 이동해 언제든
  복원 가능하다 (norn-restore).
- 게이트는 노른 산출물도 신뢰하지 않는다 — insight 페이지 역시 힌트일 뿐 완료 증거가 아니다.

파사드다. 본문은 아래 모듈들이 나눠 진다 — 부르는 쪽은 종전대로 `asgard.memory.norn` 하나만
보면 되고, 밑줄로 시작하는 이름도 여기서 그대로 다시 내보낸다 (시험이 직접 임포트한다).

**이름을 갈아 끼우려면 정의한 모듈에 꽂아라.** 파사드의 이름을 바꿔도 정의한 모듈 안의
호출자는 자기 모듈에서 찾으므로 바뀐 것을 못 본다 (`mock.patch.object(norn.plan, "_complete", …)`).
분해 전에는 두 자리가 같은 모듈이라 파사드에 꽂아도 닿았다. 패키지 밖에서 부르는 자리
(`norn.wake` · `norn.spawn_pass`)는 종전대로 파사드에 꽂으면 된다.
"""

from __future__ import annotations

# 분해 전 `norn` 이 들고 있던 이름 — 이 파사드 안에서는 안 쓰지만 부르는 쪽이 이 이름으로
# 닿을 수 있어 그대로 남긴다 (표준 라이브러리 모듈까지).
import contextlib  # noqa: F401
import datetime as _dt  # noqa: F401
import hashlib  # noqa: F401
import json  # noqa: F401
import os  # noqa: F401
import re  # noqa: F401
import shutil  # noqa: F401

from ..contradiction import ACKNOWLEDGED, contradiction_key, open_contradictions  # noqa: F401
from ..contradiction import record as record_contradictions  # noqa: F401
from ..index import _db, write_index  # noqa: F401
from ..pages import lint  # noqa: F401
from ..pages import merge as _merge_pages  # noqa: F401
from ..policy import _memory_settings, memory_dir, scan_secrets, scan_threats  # noqa: F401
from ..recall import (  # noqa: F401
    _containment,
    _content_words,
    _jaccard,
    _stem_floor,
    _stem_hit,
    _stopword,
)
from ..store import (  # noqa: F401
    LOG,
    PAGES,
    _atomic_write,
    _lock,
    _page_path,
    _pages,
    _read,
    _today,
    ensure_home,
    log_op,
    poisoned,
    render_page,
    valid_slug,
)
from ..usage import merged as usage_merged  # noqa: F401
from .apply import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    ARCHIVE_DIR,
    BACKUP_DIR,
    BACKUP_KEEP,
    REPORTS_DIR,
    _add_link,
    _backup,
    _write_report,
    apply_norn,
    archive_page,
    restore_page,
)
from .auto import (  # noqa: F401
    _AUTO_OPS,
    AUTO_MODES,
    MIN_INTERVAL_DAYS,
    OPS_THRESHOLD,
    _settings_int,
    auto_mode,
    insight_auto,
    norn_due,
    nudge_line,
    partition_ops,
    run_auto,
    spawn_pass,
    wake,
)
from .insight import (  # noqa: F401
    _CLAUSE_EDGE,
    _FORBIDDEN_INSIGHT,
    _NEG_AFTER,
    _NEG_BEFORE,
    _NEG_BEFORE_ADJACENT,
    INSIGHT_AUTO_FLOOR,
    INSIGHT_GROUNDING_FLOOR,
    INSIGHT_MAX_CHARS,
    INSIGHT_MAX_SOURCES,
    INSIGHT_MIN_SOURCES,
    POLARITY_CLAUSE,
    POLARITY_POST,
    POLARITY_POST_CLAUSE,
    POLARITY_PRE,
    _anchors,
    _clause_after,
    _clause_before,
    _confidence,
    _insight_grounding,
    _polarity,
    _polarity_conflict,
    _spans,
)
from .plan import _NORN_SYS, _complete, _parse_ops, plan_norn, signals  # noqa: F401
from .state import STATE_FILE, _load_state, _log_lines, _save_state, _state_path  # noqa: F401
from .validate import (  # noqa: F401
    LINK_BAND_LEXICAL,
    LINK_BAND_SEMANTIC,
    MAX_ARCHIVES,
    MAX_CONTRADICTIONS,
    MAX_INSIGHTS,
    MAX_LINKS,
    MAX_MERGES,
    MERGE_FLOOR,
    _existing_links,
    _merge_floor,
    _relatedness,
    validate_ops,
)
