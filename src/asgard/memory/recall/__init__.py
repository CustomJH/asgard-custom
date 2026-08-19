"""검색·주입면 — RRF 3-스트림 query, 노출/사용 추적, 동결 스냅샷·회수 블록·증류 넛지.

파사드다. 본문은 아래 모듈들이 나눠 진다 — 부르는 쪽은 종전대로 `asgard.memory.recall` 하나만
보면 되고, 밑줄로 시작하는 이름도 여기서 그대로 다시 내보낸다 (시험이 직접 임포트한다).

**이름을 갈아 끼우려면 정의한 모듈에 꽂아라.** 파사드의 이름을 바꿔도 정의한 모듈 안의
호출자는 자기 모듈에서 찾으므로 바뀐 것을 못 본다 (`mock.patch.object(recall.grams, "_grams", …)`).
분해 전에는 두 자리가 같은 모듈이라 파사드에 꽂아도 닿았다.
"""

from __future__ import annotations

# 분해 전 `recall` 이 들고 있던 이름 — 이 파사드 안에서는 안 쓰지만 부르는 쪽이 이 이름으로
# 닿을 수 있어 그대로 남긴다 (표준 라이브러리 모듈까지).
import contextlib  # noqa: F401
import datetime as _dt  # noqa: F401
import hashlib  # noqa: F401
import math  # noqa: F401
import os  # noqa: F401
import re  # noqa: F401

from ..index import _db, clean_remember, clean_verdicts  # noqa: F401
from ..policy import (  # noqa: F401
    _INVISIBLE,
    _memory_settings,
    autosave_enabled,
    index_budget,
    inject_enabled,
    kind_budgets,
    memory_dir,
    scan_threats,
)
from ..store import (  # noqa: F401
    PAGES,
    _desc,
    _kind,
    _pages_token,
    _read_all_cached,
    poison_key,
    poisoned,
    slot_query_aliases,
)
from ..temporal import event_date  # noqa: F401
from .blocks import (  # noqa: F401 — 밑줄 이름은 시험이 직접 임포트한다
    RECALL_BUDGET,
    RECALL_PREFIX,
    RECALL_SUFFIX,
    _diversify,
    recall_note,
    recall_rows,
)
from .clean import _VERDICT_MEMO, clean_pages, page_verdicts  # noqa: F401
from .grams import _containment, _Grams, _grams, _jaccard  # noqa: F401
from .nudge import DISTILL_MAX_PATHS, distill_nudge  # noqa: F401
from .ppr import (  # noqa: F401
    _GRAPH_EDGE_MODES,
    _GRAPH_EDGES_DEFAULT,
    _GRAPH_EDGES_ENV,
    _LINKS_MEMO,
    PPR_DAMPING,
    PPR_STEPS,
    _graph_order,
    _links_for,
    graph_edges,
)
from .rerank import (  # noqa: F401
    _RERANK_ENV,
    RERANK_BASE_WEIGHT,
    RERANK_CANDIDATES,
    RERANK_DISPERSION_ENV,
    RERANK_DISPERSION_FLOOR,
    RERANK_GATE_ENV,
    RERANK_GATE_MODE,
    RERANK_MAX_PASSAGES,
    RERANK_MAX_WEIGHT,
    RERANK_MIN_PASSAGES,
    RERANK_PASSAGE_CHARS,
    RERANK_TOP_PASSAGES,
    _dispersion,
    _dispersion_floor,
    _gate_mode,
    _gate_weight,
    _passage_scores,
    _passages,
    _PassageVectors,
    _rerank_order,
    rerank_enabled,
)
from .rows import SNIPPET_MAX, _fuse, _hit_row, _neutralize, _row  # noqa: F401
from .search import (  # noqa: F401
    RRF_K,
    SEM_FLOOR,
    TEMPORAL_ALPHA,
    TEMPORAL_DAYS,
    TEMPORAL_KINDS,
    _sem_floor,
    _snippet,
    _temporal_multiplier,
    _track,
    query,
)
from .snapshot import (  # noqa: F401
    _SECTIONS,
    _SNAPSHOT_WARN,
    _fit_total,
    _section,
    _snapshot_rows,
    section_usage,
    snapshot_note,
)
from .stems import (  # noqa: F401
    _EN_STEM_SUFFIXES,
    _EN_SUFFIXES,
    _GROUNDING_STOP,
    _KO_ENDINGS,
    _KO_PARTICLES,
    _KO_STEM_SUFFIXES,
    EN_STEM_MIN,
    KO_STEM_MIN,
    _content_words,
    _stem_floor,
    _stem_hit,
    _stopword,
)
