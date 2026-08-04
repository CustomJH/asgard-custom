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
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import os
import re
import shutil

from .contradiction import ACKNOWLEDGED, contradiction_key, open_contradictions
from .contradiction import record as record_contradictions
from .index import _db, write_index
from .pages import lint
from .pages import merge as _merge_pages
from .policy import _memory_settings, memory_dir, scan_secrets, scan_threats
from .recall import _containment, _content_words, _jaccard, _stem_floor, _stem_hit, _stopword
from .store import (
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
from .usage import merged as usage_merged

STATE_FILE = "norn-state.json"
BACKUP_DIR = "norn-backups"
ARCHIVE_DIR = "archive"
REPORTS_DIR = "reports"
BACKUP_KEEP = 5

OPS_THRESHOLD = 25  # log.md 신규 연산 누적 문턱 — config [memory].norn_ops_threshold
MIN_INTERVAL_DAYS = 3  # 노른 간 최소 간격 — config [memory].norn_min_interval_days
MERGE_FLOOR = 0.25  # merge 결정적 유사도 플로어 — LLM 주장과 무관하게 코드가 본다
MAX_MERGES, MAX_ARCHIVES, MAX_INSIGHTS, MAX_CONTRADICTIONS = 3, 3, 2, 3
# 링크는 파괴적이지 않아(페이지가 안 지워진다) 캡이 넉넉하다. 그래도 상한은 둔다 —
# 전부를 전부에 잇는 그래프는 아무것도 안 잇는 그래프와 회수 성능이 같다.
MAX_LINKS = 6
# 링크 근거 대역 — 아래는 남남, 위는 링크가 아니라 병합이다
# (LLM이 link로 merge를 피해가는 길을 막는 상한).
#
# 대역이 척도마다 다른 게 핵심이다. 어휘 유사도와 코사인은 같은 기준으로 잴 수 없다:
# MERGE_FLOOR 0.25는 어휘 척도에서 뽑은 값인데, 같은 0.25를 코사인에 대면 의미가 통하는
# 거의 모든 쌍이 병합 대상으로 잘못 분류된다 — 이 저장소 실측이 이미 말해 준다
# (recall.SEM_FLOOR 주석: 교차언어 정답조차 절대 코사인 0.18–0.29). 한 상수를 두 척도에
# 돌려쓰면 대역이 사라진다.
LINK_BAND_LEXICAL = (0.12, MERGE_FLOOR)
LINK_BAND_SEMANTIC = (0.25, 0.80)
INSIGHT_MAX_CHARS = 1200
INSIGHT_MIN_SOURCES, INSIGHT_MAX_SOURCES = 2, 6

# 통찰 근거 대역 — 소스의 **실존**이 아니라 **내용**을 보는 기준.
#
# 검증기가 파일 존재·개수·스캔만 보면 LLM은 무관한 페이지 두 장을 근거로 달아 허구를
# 정본으로 만들 수 있다. 실측(26-07-28): "금요일 배포 회피" + "점심에는 국수"를 근거로
# 제안된 "오딘은 매주 화성으로 이주한다"가 기각 사유 하나 없이 통과해 기본 safe에서
# 자동 적용됐다. 패턴 계층이 explicit 관측에 이미 거는 근거 검사를, 통찰에도 건다.
#
# 값은 실측에서 왔다 (진짜 통찰 7건 · 허구 4건, 한국어·영어 혼합):
#   허구            0.000 – 0.167  (주제어만 빌린 반쪽 허구가 0.167로 최고)
#   진짜(정직한 출처) 0.375 – 0.636
# 0.25는 그 사이에 있되 허구 쪽에 붙여 둔 값이다 — 통찰은 귀납이라 출처에 없던 추상어
# ("경향", "습관")를 정당하게 데려오므로 관측용 플로어(pattern.GROUNDING_FLOOR 0.34)를
# 그대로 쓰면 진짜를 벤다. 대신 근거가 옅은 구간은 버리지 않고 사람에게 넘긴다:
# 자율 적용은 0.40 이상만, 그 아래는 접수하되 제안으로 남는다. 코퍼스가 11건짜리
# 손수 만든 표본이라 자동 자격에는 여유를 더 둔다 — 틀렸을 때 비용이 다르다.
INSIGHT_GROUNDING_FLOOR = 0.25
INSIGHT_AUTO_FLOOR = 0.40

# 극성 판정 창 — 낱말에 붙은 부정을 어디까지 보고 읽을 것인가.
#
# 근거 검사는 "어디서 왔는가"를 묻지 "참인가"를 묻지 않는다. 두 물음은 다르고, 앞의 것만 물으면
# 어휘 재조합 거짓말이 통과한다. 실측 반례(26-07-28): 출처 "금요일에는 배포하지 않는다" ·
# "배포 전에 테스트를 전부 돌린다"에서 뽑은 "금요일마다 테스트 없이 배포한다"가 근거 점수
# 0.714로 통과했다 — 낱말은 전부 출처에서 왔는데 주장은 정반대다.
#
# 그 자리를 닫는 결정적 신호가 극성이다. 다만 부정의 **작용역**이 언어마다 다르다:
#
#   한국어 — 낱말에 붙어 인접에서 끝난다: "배포하지 않는다", "테스트 없이"
#   영어   — 동사에 붙어 절 오른쪽 전체를 덮는다: "never deploys on Fridays"
#            (부정어와 대상 낱말 사이가 멀다 — 인접 창으로는 영영 못 본다)
#
# 그래서 뒤는 짧은 창으로, 앞은 **절 단위**로 읽는다. 절 경계에 등위접속사를 넣는 것이
# 핵심이다: "avoids Friday deploys **and** always tests first"에서 avoids는 and를 넘지
# 못한다. 이 경계가 없으면 정직한 통찰이 자기 문장의 앞 절 때문에 부정으로 물든다 (실측).
POLARITY_PRE, POLARITY_POST, POLARITY_CLAUSE = 14, 12, 80
# 영어는 뒤쪽도 절 단위다. 수동태가 그 증거다 — "checks are bypassed"는 부정 동사가 주어
# 뒤에 서고, 한국어용 인접 창(12자)으로는 영영 닿지 않는다. 그래서 ASCII 앵커만 뒤도
# 절 경계까지 본다. 경계를 두는 것이 핵심이다: 창만 넓히면 "tests are run, deploys are
# skipped"에서 앞 절의 tests가 뒤 절의 부정에 물든다.
POLARITY_POST_CLAUSE = 40

# 낱말 뒤에 붙어 그 낱말을 부정하는 것들 (한국어 어미·보조용언 + 영어 후치 전치사).
#
# "안 한다" 만이 부정이 아니다. 한국어는 **하지 않음을 뜻하는 본동사**로도 똑같이 부정한다 —
# "테스트를 생략한다", "점검을 건너뛴다", "리뷰를 제외하고". 실측(26-07-30): 이 갈래가 사전에
# 없어 `_polarity("테스트", "배포 시 테스트를 생략한다")`가 **+1**을 돌려줬다. 출처가 부정하는
# 것을 긍정으로 읽으면 극성 게이트는 그 출처에 대해 영영 눈이 먼다.
_NEG_AFTER = re.compile(
    # 어간이 모음으로 끝나는 것들은 활용에서 음절이 통째로 갈린다 — "피하"로는 "피한다"를,
    # "삼가"로는 "삼간다"를 못 잡는다 (한자어 어간 지양·중단·거부 등은 활용해도 어간이 그대로다).
    r"않|못하|못한|못\s|없|말라|마라|금지|피하|피한|피함|피해|지양|삼가|삼간|삼감|회피|자제|거부|중단|아니|"
    # 한국어 활용은 어간의 **음절이 통째로 바뀐다** — "건너뛰"로는 "건너뛴다"를 못 잡는다
    # (뛰≠뛴, 자모가 아니라 음절이 코드포인트다). 갈래를 적어 두는 편이 어간을 줄이는 것보다
    # 안전하다: "건너"까지 줄이면 "건너편"·"건너서"가 부정으로 읽힌다.
    r"생략|누락|건너뛰|건너뛴|건너뜁|건너뜀|제외|빼고|빼는|빼먹|무시하|미실행|미적용|"
    r"(?:^|\s)안\s|\bwithout\b|\bnever\b|\bnot\b|\bno\b|\brather than\b|\binstead of\b|"
    # 영어 수동태 — "checks are bypassed"처럼 부정 동사가 주어 **뒤에** 온다. 능동태
    # ("omit the review")는 절 작용역인 _NEG_BEFORE가 잡는다.
    r"\b(?:are|is|was|were|get|gets|got)\s+(?:being\s+)?"
    r"(?:skipped|omitted|excluded|bypassed|ignored|dropped)\b",
    re.IGNORECASE,
)
# 낱말 앞 — 절 작용역. 영어 부정어만 본다: 한국어의 앞선 부정("결코")은 뒤의 "않"과 짝을
# 이루므로 _NEG_AFTER가 이미 잡고, 절까지 넓히면 옆 낱말까지 부정으로 물든다.
_NEG_BEFORE = re.compile(
    r"\b(?:not|never|no|without|avoids?|avoiding|refrains?|skips?|skipping|cannot|can'?t|don'?t|"
    # 하지 않음을 뜻하는 본동사 — 영어는 이것도 목적어 **앞**에 서서 절을 덮는다
    # ("deploys omit the review step"). 한국어 대응분은 _NEG_AFTER 쪽에 있다.
    r"omits?|omitting|exclud(?:e|es|ing)|bypass(?:es|ing)?|ignor(?:e|es|ing)|"
    r"doesn'?t|didn'?t|won'?t|rarely|seldom)\b",
    re.IGNORECASE,
)
# 낱말 앞 — 인접 작용역. 한국어 강조 부정 부사는 뒤 낱말 하나만 덮는 것으로 본다.
_NEG_BEFORE_ADJACENT = re.compile(r"결코|절대|(?:^|\s)안\s|(?:^|\s)못\s")
# 절 경계 — 구두점과 등위·종속 접속사. 부정은 이 선을 넘지 못한다.
_CLAUSE_EDGE = re.compile(
    r"[.;:,!?()\[\]\n]|\b(?:and|but|or|yet|while|whereas|though|although|however|because|so)\b",
    re.IGNORECASE,
)


# 자기중독 방지 — 환경 의존 실패·도구 부정 주장은 통찰이 아니라 그날의 사정이다.
_FORBIDDEN_INSIGHT = re.compile(
    r"command not found|no such file|permission denied|not installed|rate.?limit|"
    r"(?:tool|mcp|browser)s?\s+(?:is\s+)?(?:broken|not\s+work)|do(?:es)?\s+not\s+work|not supported|"
    r"credential|api.?key|unauthorized|미설치|권한 거부|작동하지 않",
    re.IGNORECASE,
)

# LLM행 기본 프롬프트는 영어 정본 — 사람 표면은 한국어 유지.
_NORN_SYS = (
    "You are the Norn tender of Yggdrasil, a personal memory wiki. Review the page catalog "
    "and propose a SMALL set of consolidation deltas. You never rewrite the library wholesale: "
    "you emit deltas only, and deterministic code validates and applies them.\n\n"
    "Allowed operations (JSON array `ops`):\n"
    '- {"op":"merge","src":"<slug>","dst":"<slug>","why":"..."} — src is absorbed into dst, then '
    "src is removed. Only when both pages state the same fact or one strictly contains the other.\n"
    '- {"op":"archive","slug":"<slug>","why":"..."} — retire a stale page (kept restorable). Only '
    "slugs listed under `decay_candidates` are eligible; anything else will be dropped.\n"
    '- {"op":"insight","title":"...","text":"...","sources":["<slug>","<slug>"],"why":"..."} — a NEW '
    "higher-order pattern that is only visible across 2+ existing pages (inductive reasoning: "
    "preferences, tendencies, recurring behaviors). The text must be self-contained, declarative, "
    "grounded ONLY in the listed source pages, and must not merely restate a single page. "
    "Deterministic code checks that grounding: the insight must reuse the concrete vocabulary of "
    "its sources, and EVERY listed source must contribute to it. Do not pad the source list — a "
    "page that the insight does not actually draw on will be rejected as decoration. Code also "
    "checks polarity: an insight that reuses source vocabulary while flipping what the sources "
    "assert (dropping or adding a negation) is rejected. If sources genuinely disagree with each "
    "other, that is a `contradiction` for a human to resolve, not an insight to synthesize.\n"
    '- {"op":"contradiction","a":"<slug>","b":"<slug>","why":"..."} — two pages make incompatible '
    "claims. Report only; a human resolves it. Pairs listed under `acknowledged_contradictions` "
    "have already been reviewed by the human — do not report them again.\n"
    '- {"op":"link","a":"<slug>","b":"<slug>","why":"..."} — two EXISTING pages are related but '
    "distinct: one gives context the other needs, they belong to the same decision, or knowing one "
    "makes the other findable. Do NOT use this for pages that state the same fact — that is a merge.\n\n"
    "Rules:\n"
    '- Output STRICT JSON: {"ops":[...]} and nothing else. No prose, no code fences.\n'
    "- Be conservative. An empty ops list is a valid, common outcome — do not invent work.\n"
    "- Never put environment-dependent failures, negative claims about tools, or credentials in "
    "insight text.\n"
    '- Never merge a page of kind "user" into a page of another kind.\n'
    "- Write insight text in the dominant language of the source pages."
)


def _settings_int(key: str, default: int) -> int:
    try:
        v = _memory_settings().get(key)
        return max(1, int(v)) if v is not None else default
    except Exception:
        return default


def _merge_floor() -> float:
    try:
        v = _memory_settings().get("norn_merge_floor")
        return float(v) if v is not None else MERGE_FLOOR
    except Exception:
        return MERGE_FLOOR


def _state_path(d: str) -> str:
    return os.path.join(d, STATE_FILE)


def _load_state(d: str) -> dict:
    try:
        with open(_state_path(d), encoding="utf-8") as handle:
            state = json.load(handle)
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def _save_state(d: str, state: dict) -> None:
    with contextlib.suppress(Exception):
        _atomic_write(_state_path(d), json.dumps(state, ensure_ascii=False, indent=1))


def _log_lines(d: str) -> int:
    """log.md 누적 연산 행 수 — 노른 트리거의 결정적 활동 신호 (LLM·중요도 점수 불필요)."""
    try:
        with open(os.path.join(d, LOG), encoding="utf-8") as handle:
            return sum(1 for line in handle if line.startswith("- "))
    except Exception:
        return 0


def norn_due(d: str | None = None) -> tuple[bool, str]:
    """트리거 판정 — (due, 사유). 연산 누적 문턱 + 최소 간격 — 활동이 쌓였을 때만 손질한다."""
    d = d or memory_dir()
    state = _load_state(d)
    threshold = _settings_int("norn_ops_threshold", OPS_THRESHOLD)
    interval = _settings_int("norn_min_interval_days", MIN_INTERVAL_DAYS)
    delta = _log_lines(d) - int(state.get("log_lines", 0))
    if delta < threshold:
        return False, f"연산 누적 {delta}/{threshold}건 — 아직 이르다"
    last = str(state.get("last_norn", ""))
    if last:
        try:
            days = (_dt.date.today() - _dt.date.fromisoformat(last[:10])).days
            if days < interval:
                return False, f"최근 노른 {days}일 전 — 최소 간격 {interval}일"
        except ValueError:
            pass
    return True, f"연산 누적 {delta}건 (문턱 {threshold})"


# ── 신호 수집 (결정론) ─────────────────────────────────────────────────────────


def signals(d: str | None = None) -> dict:
    """LLM에게 보여줄 증거 카드 — 페이지 카탈로그·usage·lint 판정. 쓰기 없음."""
    d = d or memory_dir()
    # 사람이 실제로 찾은 횟수 — 자동 주입은 여기 안 섞인다 (`memory.usage`). 파일과 DB 중
    # 큰 쪽을 보므로 파생이 방금 날아간 기계에서도 증거 카드가 0을 말하지 않는다.
    uses = {slug: row["uses"] for slug, row in usage_merged(d).items()}
    pages: list[dict] = []
    for slug in _pages(d):
        pg = _read(d, slug)
        if not pg or poisoned(*pg):
            continue  # 오염 페이지는 노른 대상도 아니다 — lint가 threat로 보고한다
        meta, body = pg
        first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
        pages.append(
            {
                "slug": slug,
                "title": meta.get("title", slug),
                "kind": meta.get("kind", "note"),
                "updated": meta.get("updated", meta.get("created", "")),
                "uses": int(uses.get(slug, 0)),
                "excerpt": first[:160],
            }
        )
    findings = lint(d)
    return {
        "pages": pages,
        "decay_candidates": sorted({f["slug"] for f in findings if f["code"] == "decay-candidate"}),
        "near_duplicates": [
            f["msg"].replace("≈ ", f"{f['slug']} ≈ ") for f in findings if f["code"] == "near-duplicate"
        ],
        # 사람이 이미 보고 넘긴 어긋남 — 다시 제안해 봐야 장부에서 같은 줄로 접힌다.
        # 증거 카드에 같이 넣으면 LLM 이 애초에 그 쌍을 안 고른다 (`memory.contradiction`).
        "acknowledged_contradictions": [
            {"a": row["a"], "b": row["b"], "note": row["note"]}
            for row in open_contradictions(d, include_acknowledged=True)
            if row["status"] == ACKNOWLEDGED
        ],
    }


# ── 계획 (LLM 제안 → 결정적 검증) ──────────────────────────────────────────────


def _confidence(n_sources: int) -> str:
    """근거 수가 confidence를 결정한다 — 2=low, 3~4=medium, 5+=high (LLM 자기 신고 불신)."""
    return "high" if n_sources >= 5 else "medium" if n_sources >= 3 else "low"


def _insight_grounding(title: str, text: str, sources: list[tuple[dict, str]]) -> tuple[float, list[float]]:
    """통찰의 내용어가 출처에 실제로 남아 있는 비율과, **출처별** 기여도.

    두 값이 다른 일을 한다. 총량은 "이 문장이 어디서 왔는가"를 묻고 (허구는 0에 붙는다),
    출처별 기여도는 "이 근거가 정말 근거인가"를 묻는다 — 통찰은 2장 이상에 걸쳐야만 보이는
    것이라는 계약(_NORN_SYS)이라, 아무것도 기여하지 않는 소스가 끼어 있으면 그 계약은
    거짓이다. 총량만 보면 진짜 소스 하나에 장식 소스를 달아 문턱을 넘길 수 있다."""
    claim = {w for w in _content_words(f"{title} {text}") if not _stopword(w)}
    if not claim:
        return 0.0, []
    haystacks = [f"{meta.get('title', '')} {body}".lower() for meta, body in sources]
    total = sum(1 for w in claim if any(_stem_hit(w, h) for h in haystacks)) / len(claim)
    per_source = [sum(1 for w in claim if _stem_hit(w, h)) / len(claim) for h in haystacks]
    return total, per_source


def _spans(word: str, haystack: str) -> list[tuple[int, int]]:
    """낱말이 건초더미에 나타난 자리들 — `_stem_hit`과 **같은 어간 규칙**으로 찾는다.

    근거 검사가 "있다/없다"로 답하는 자리를 극성은 "어디에 있나"로 물어야 해서 위치가 필요하다.
    두 함수가 다른 어간 규칙을 쓰면 근거 검사는 통과했는데 극성은 낱말을 못 찾는 일이 생긴다 —
    그래서 하한을 여기 다시 적지 않고 `_stem_floor` 하나에서 가져온다 (각자 적으면 갈라진다)."""
    floor = _stem_floor(word)
    for cut in range(len(word), floor - 1, -1):
        stem = word[:cut]
        found: list[tuple[int, int]] = []
        at = haystack.find(stem)
        while at != -1:
            found.append((at, at + len(stem)))
            at = haystack.find(stem, at + 1)
        if found:
            return found
    return []


def _anchors(text: str) -> set[str]:
    """극성을 물을 만한 낱말 — 짧은 기능어는 뺀다.

    한국어와 영어의 낱말 길이가 같은 뜻을 담지 않는다: "배포"는 두 글자로 내용어지만
    영어의 두세 글자는 대개 전치사·관사다("on", "to", "the"). 그런 낱말은 부분 문자열로
    남의 낱말 안에서도 걸려("on" ⊂ "front") 극성 판정을 흔든다. 척도를 문자 체계로 가른다."""
    return {w for w in _content_words(text) if not _stopword(w) and not (w.isascii() and len(w) < 4)}


def _clause_before(haystack: str, start: int) -> str:
    """낱말이 속한 절의 시작부터 낱말 앞까지 — 영어 부정의 작용역."""
    window = haystack[max(0, start - POLARITY_CLAUSE) : start]
    edges = [m.end() for m in _CLAUSE_EDGE.finditer(window)]
    return window[edges[-1] :] if edges else window


def _clause_after(haystack: str, end: int) -> str:
    """낱말 뒤부터 그 절이 끝나는 데까지 — 영어 수동태 부정("are bypassed")의 작용역."""
    window = haystack[end : end + POLARITY_POST_CLAUSE]
    edge = _CLAUSE_EDGE.search(window)
    return window[: edge.start()] if edge else window


def _polarity(word: str, haystack: str, *, assertion: bool = False) -> int | None:
    """낱말에 붙은 극성 — +1 긍정, -1 부정, None = 언급 없음 (또는 문서에서의 혼재).

    **혼재를 읽는 법이 문서와 주장에서 다르다.** 두 쪽이 다른 것이라서다:

      문서(출처) — 여러 문장의 모음. 같은 낱말을 긍정으로도 부정으로도 쓰면("배포에
        신중하며 … 금요일 배포를 피하고") 그 문서는 이 낱말에 **아무 편도 안 든다**.
        모르는 것을 모른다고 말해야 진짜 통찰이 극성으로 잘리지 않는다 → None.

      주장(통찰) — 하나의 단언. 제목은 본문에 붙은 **딱지**이지 따로 선 주장이 아니다.
        그래서 낱말에 부정이 한 번이라도 걸리면 그 단언은 부정을 말한 것이다 → -1.

    이 구분이 없을 때 무슨 일이 났는지 (실측 26-07-30). 검증기는 `title + text`를 한 덩어리로
    보는데, 제목은 본문의 핵심 명사를 되풀이하는 것이 정상이고 `_NORN_SYS`가 title+text 쌍을
    요구한다. 그 되풀이가 **비부정 위치의 +1**을 하나 만들어 본문의 -1과 상쇄되고, 혼재는
    None이 되어 게이트가 통째로 침묵했다 — 같은 거짓말이 제목만 갈아입으면 표식을 잃었다:

        제목 "배포 습관"          → 표식 있음   (앵커를 안 건드림)
        제목 "금요일 무테스트 배포"  → 표식 없음 ← 근거 점수 0.714로 자동 승격까지 갔다
        제목 "테스트 관련 습관"     → 표식 없음 ←

    부정 쪽으로 읽는 것이 안전한 쪽인 이유는 이 신호가 **기각이 아니라 표식**이기 때문이다
    (`_polarity_conflict` 독스트링). 과하게 달린 표식은 사람이 출처와 대조하고 넘기면 그만이고,
    안 달린 표식은 허구를 정본에 저장한다 — 두 오류의 비용이 다르다."""
    signs = set()
    for start, end in _spans(word, haystack):
        # 뒤쪽 작용역이 문자 체계마다 다르다 — 한국어는 낱말에 붙어 인접에서 끝나고,
        # 영어는 수동태로 절 오른쪽까지 간다 (POLARITY_POST_CLAUSE 주석).
        after = _clause_after(haystack, end) if word.isascii() else haystack[end : end + POLARITY_POST]
        negated = (
            bool(_NEG_AFTER.search(after))
            or bool(_NEG_BEFORE_ADJACENT.search(haystack[max(0, start - POLARITY_PRE) : start]))
            or bool(_NEG_BEFORE.search(_clause_before(haystack, start)))
        )
        signs.add(-1 if negated else 1)
    if len(signs) == 1:
        return signs.pop()
    return -1 if (signs and assertion) else None


def _polarity_conflict(title: str, text: str, sources: list[tuple[dict, str]]) -> tuple[str, str] | None:
    """통찰이 출처의 주장을 **뒤집었는가** — (낱말, 사유) 또는 None.

    근거 점수로는 못 잡는 거짓말의 모양이 하나 있다: 출처의 어휘를 그대로 쓰면서 부정만
    떼거나 붙이는 것. 그런 문장은 근거 점수가 오히려 **높다** (낱말이 전부 출처에서 왔으니까).

    표식은 만장일치일 때만 단다 — 그 낱말을 언급한 모든 출처가 통찰과 반대 극성일 때.
    한 출처라도 통찰 편이면 그건 모순이 아니라 출처들 사이의 이견이고, 이견의 해소는
    contradiction op가 사람에게 넘길 일이다.

    **왜 기각이 아니라 표식인가** (26-07-28 측정으로 정해졌다). 이 신호는 어휘만 보므로
    진짜 뒤집기와 우연한 극성 반전을 못 가른다. 둘은 형상이 같다:

        거짓말  통찰 "테스트 **없이** 배포" ↔ 출처 "테스트를 전부 돌린다"
        참      통찰 "문제 **없이** 배포"   ↔ 출처 "문제를 즉시 해결한다"

    가르려면 "테스트는 하는 일이고 문제는 겪는 상태"라는 세계 지식이 필요하다 — 어휘
    정련으로 닿지 않는 자리다. 충돌 앵커 수로도 안 갈렸다(진짜 거짓말 4건 중 2건이 앵커
    1개, 오탐 후보도 1~2개 — 완전히 겹친다).

    그래서 이 신호는 **자동 승격을 막는 데만** 쓴다: 되돌리기 어려운 쪽(정본화)에는 이
    정밀도로 충분하고, 후보 지식을 없애는 쪽에는 부족하다. 사람에게는 표식이 붙어 간다 —
    "이 낱말을 확인하라"는 말이 "이 통찰은 없다"보다 언제나 더 쓸모 있다."""
    claim = f"{title} {text}".lower()
    haystacks = [f"{meta.get('title', '')} {body}".lower() for meta, body in sources]
    # 긴 낱말부터 본다 — 기각 사유에 들어가는 것은 처음 걸린 낱말이고, 사람이 판단하려면
    # 그 낱말이 "on"이 아니라 "fridays" 여야 한다.
    for word in sorted(_anchors(claim), key=lambda w: (-len(w), w)):
        # 통찰은 단언이고 출처는 문서다 — 혼재를 같은 기준으로 읽으면 제목의 되풀이가 게이트를
        # 침묵시킨다 (`_polarity` 독스트링의 실측).
        mine = _polarity(word, claim, assertion=True)
        if mine is None:
            continue
        theirs = [p for p in (_polarity(word, hay) for hay in haystacks) if p is not None]
        if theirs and all(p == -mine for p in theirs):
            side = "출처는 부정하는데 통찰은 긍정한다" if mine > 0 else "출처는 긍정하는데 통찰은 부정한다"
            return word, side
    return None


def _parse_ops(raw: str) -> list[dict]:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("norn: LLM output is not JSON")
    payload = json.loads(raw[start : end + 1])
    ops = payload.get("ops") if isinstance(payload, dict) else None
    if not isinstance(ops, list):
        raise ValueError("norn: LLM output has no ops list")
    return [op for op in ops if isinstance(op, dict)]


def _existing_links(meta: dict) -> set[str]:
    return {s.strip() for s in str(meta.get("links") or "").split(",") if s.strip()}


def _relatedness(d: str, a: str, b: str, pa: tuple[dict, str], pb: tuple[dict, str]) -> tuple[float, str]:
    """두 페이지의 근접도와 **어느 자로 쟀는지** — ("semantic"|"lexical"). 척도를 같이 돌려주는
    이유는 대역이 척도마다 다르기 때문이다 (LINK_BAND_* 참조).

    링크는 **말이 다른데 관련된** 것을 잇는 연산이라 어휘만으로 재면 잴 수가 없다("릴리스
    태그 규칙"과 "배포 전 확인 목록"은 겹치는 낱말이 거의 없다). 그래서 벡터가 있으면 그걸
    본다. 벡터가 없을 때만 어휘로 내려오고, 그 경우 링크는 보수적으로 덜 생긴다 — 근거 없이
    잇느니 안 잇는 쪽이다."""
    with contextlib.suppress(Exception):
        from .. import memory_semantic as sem
        from .index import _db

        if sem.active():
            conn = _db(d)
            rows = {
                row[0]: sem.unpack(row[1])
                for row in conn.execute("SELECT slug, data FROM vec WHERE slug IN (?,?)", (a, b)).fetchall()
            }
            conn.close()
            if a in rows and b in rows:
                return max(0.0, sem.cosine(rows[a], rows[b])), "semantic"
    ta = pa[0].get("title", "") + " " + pa[1]
    tb = pb[0].get("title", "") + " " + pb[1]
    return max(_containment(ta, tb), _jaccard(ta, tb)), "lexical"


def _add_link(d: str, a: str, b: str) -> bool:
    """양쪽 frontmatter에 서로를 적는다. 반환 = 한 쪽이라도 실제로 바뀌었는가.

    회수(PPR)는 어차피 무향이지만 사람이 페이지를 열었을 때 한쪽에서만 보이면 관계가 반쪽으로
    읽힌다.

    락을 잡는 이유: 이것은 읽고-고쳐-쓰기이고, 노른은 `_spawn_auto` 로 분리된 프로세스에서
    돈다 — 사용자의 대화형 ingest 와 진짜로 동시에 실행된다. 락이 없으면 읽은 뒤 남이 쓴
    본문 위에 옛 본문을 덮어써서 그 쓰기가 통째로 사라진다. 다른 쓰기 경로(add·ingest·
    remove·merge)가 전부 같은 락을 지나므로, 여기만 안 지나면 직렬화가 성립하지 않는다."""
    changed = False
    with _lock(d):
        for source, target in ((a, b), (b, a)):
            pg = _read(d, source)
            if not pg:
                continue
            meta, body = pg
            links = _existing_links(meta)
            if target in links:
                continue
            meta = {**meta, "links": ",".join(sorted(links | {target})), "updated": _today()}
            _atomic_write(_page_path(d, source), render_page(meta, body))
            changed = True
    return changed


def validate_ops(ops: list[dict], d: str) -> tuple[list[dict], list[dict]]:
    """결정적 검증 — 통과한 op와 (op, 기각 사유). LLM 주장은 검증 입력일 뿐이다."""
    floor = _merge_floor()
    lint_findings = lint(d)
    decay_ok = {f["slug"] for f in lint_findings if f["code"] == "decay-candidate"}
    accepted: list[dict] = []
    dropped: list[dict] = []
    counts = {"merge": 0, "archive": 0, "insight": 0, "contradiction": 0, "link": 0}
    caps = {
        "merge": MAX_MERGES,
        "archive": MAX_ARCHIVES,
        "insight": MAX_INSIGHTS,
        "contradiction": MAX_CONTRADICTIONS,
        "link": MAX_LINKS,
    }

    def _drop(op: dict, reason: str) -> None:
        dropped.append({"op": op, "reason": reason})

    def _clean(slug: object) -> tuple[dict, str] | None:
        if not isinstance(slug, str) or not valid_slug(slug):
            return None
        pg = _read(d, slug)
        return pg if pg and not poisoned(*pg) else None

    for op in ops:
        kind = str(op.get("op") or "")
        if kind not in counts:
            _drop(op, f"unknown op: {kind!r}")
            continue
        if counts[kind] >= caps[kind]:
            _drop(op, f"cap reached: {kind} ≤ {caps[kind]}")
            continue
        if kind == "merge":
            src, dst = op.get("src"), op.get("dst")
            ps, pd = _clean(src), _clean(dst)
            if not ps or not pd or src == dst:
                _drop(op, "merge: src/dst missing, poisoned, or identical")
                continue
            if ps[0].get("kind") == "user" and pd[0].get("kind") != "user":
                _drop(op, "merge: user page must not merge into non-user page")
                continue
            a = ps[0].get("title", "") + " " + ps[1]
            b = pd[0].get("title", "") + " " + pd[1]
            sim = max(_containment(a, b), _jaccard(a, b))
            if sim < floor:
                _drop(op, f"merge: similarity {sim:.2f} < floor {floor:.2f} (deterministic backstop)")
                continue
            accepted.append(
                {"op": "merge", "src": src, "dst": dst, "sim": round(sim, 2), "why": str(op.get("why", ""))[:200]}
            )
        elif kind == "link":
            a, b = op.get("a"), op.get("b")
            pa, pb = _clean(a), _clean(b)
            if not pa or not pb or a == b:
                _drop(op, "link: a/b missing, poisoned, or identical")
                continue
            if b in _existing_links(pa[0]) and a in _existing_links(pb[0]):
                _drop(op, "link: already linked")
                continue
            sim, scale = _relatedness(d, str(a), str(b), pa, pb)
            low, high = LINK_BAND_SEMANTIC if scale == "semantic" else (LINK_BAND_LEXICAL[0], floor)
            if sim < low:
                _drop(op, f"link: {scale} relatedness {sim:.2f} < floor {low:.2f} (deterministic backstop)")
                continue
            if sim >= high:
                _drop(op, f"link: {scale} relatedness {sim:.2f} ≥ {high:.2f} — propose merge, not link")
                continue
            accepted.append(
                {
                    "op": "link",
                    "a": a,
                    "b": b,
                    "sim": round(sim, 2),
                    "scale": scale,
                    "why": str(op.get("why", ""))[:200],
                }
            )
        elif kind == "archive":
            slug = op.get("slug")
            if not isinstance(slug, str) or slug not in decay_ok:
                _drop(op, "archive: only lint decay-candidates are eligible")
                continue
            accepted.append({"op": "archive", "slug": slug, "why": str(op.get("why", ""))[:200]})
        elif kind == "insight":
            title = str(op.get("title") or "").strip()[:80]
            text = str(op.get("text") or "").strip()
            sources = [s for s in (op.get("sources") or []) if isinstance(s, str)]
            sources = list(dict.fromkeys(sources))
            if not title or not text or len(text) > INSIGHT_MAX_CHARS:
                _drop(op, "insight: missing/oversized title or text")
                continue
            if not (INSIGHT_MIN_SOURCES <= len(sources) <= INSIGHT_MAX_SOURCES):
                _drop(op, f"insight: needs {INSIGHT_MIN_SOURCES}–{INSIGHT_MAX_SOURCES} distinct sources")
                continue
            pages = [_clean(s) for s in sources]
            if any(pg is None for pg in pages):
                _drop(op, "insight: source page missing or poisoned")
                continue
            if _FORBIDDEN_INSIGHT.search(title + " " + text):
                _drop(op, "insight: forbidden capture (env-dependent/tool-negativity/credential)")
                continue
            threat = scan_threats(text, title) or scan_secrets(text, title)
            if threat:
                _drop(op, f"insight: {threat}")
                continue
            # 소스가 실존한다는 것과 통찰이 그 소스에서 나왔다는 것은 다른 말이다.
            score, per_source = _insight_grounding(title, text, [pg for pg in pages if pg])
            if score < INSIGHT_GROUNDING_FLOOR:
                _drop(op, f"insight: not grounded in its sources ({score:.2f} < {INSIGHT_GROUNDING_FLOOR})")
                continue
            if (weakest := min(per_source, default=0.0)) <= 0:
                idle = sources[per_source.index(weakest)]
                _drop(op, f"insight: source [[{idle}]] contributes nothing — not a cross-page pattern")
                continue
            row = {
                "op": "insight",
                "title": title,
                "text": text,
                "sources": sources,
                "grounding": round(score, 3),
                "confidence": _confidence(len(sources)),
                "why": str(op.get("why", ""))[:200],
            }
            # 근거 점수가 높다는 것은 출처의 어휘를 썼다는 뜻이지 출처에 동의한다는 뜻이 아니다.
            # 표식이지 기각이 아닌 이유는 _polarity_conflict 독스트링에 있다 — 이 신호는
            # 자동 승격을 막을 만큼은 강하지만 후보 지식을 없앨 만큼 정밀하지는 않다.
            if conflict := _polarity_conflict(title, text, [pg for pg in pages if pg]):
                word, side = conflict
                row["polarity_conflict"] = f"{word}: {side}"
            accepted.append(row)
        else:  # contradiction — 보고 전용, 페이지 실존만 확인
            a, b = op.get("a"), op.get("b")
            if not _clean(a) or not _clean(b) or a == b:
                _drop(op, "contradiction: pages missing, poisoned, or identical")
                continue
            accepted.append({"op": "contradiction", "a": a, "b": b, "why": str(op.get("why", ""))[:200]})
        counts[kind] += 1
    return accepted, dropped


def _complete(root: str, system: str, user: str) -> str:
    """LLM 단발 호출 간접점 — 테스트가 이 지점만 대체한다.

    개인 메모리를 손질하는 provider는 memory.manager가 정한다 (기본 = 메인 provider)."""
    from .manager import complete

    return complete(root, system, user, max_tokens=3000)


def plan_norn(root: str, d: str | None = None) -> dict:
    """신호 수집 → LLM 제안 → 결정적 검증. 반환 = {"ops", "dropped", "signals"}. 쓰기 없음."""
    d = ensure_home(d)
    sig = signals(d)
    if len(sig["pages"]) < 2:
        return {"ops": [], "dropped": [], "signals": sig}
    user = json.dumps(
        {
            "pages": sig["pages"],
            "decay_candidates": sig["decay_candidates"],
            "near_duplicates": sig["near_duplicates"],
            "acknowledged_contradictions": sig["acknowledged_contradictions"],
        },
        ensure_ascii=False,
    )
    raw = _complete(root, _NORN_SYS, user)
    ops = _parse_ops(raw)
    accepted, dropped = validate_ops(ops, d)
    return {"ops": accepted, "dropped": dropped, "signals": sig}


# ── 적용 (결정론 — 백업 → 커밋 → 보고) ─────────────────────────────────────────


def _backup(d: str) -> str:
    """pages/ 전체 스냅샷 — 손질은 언제든 되돌릴 수 있어야 한다."""
    ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d%H%M%S")
    dst = os.path.join(d, BACKUP_DIR, ts)
    shutil.copytree(os.path.join(d, PAGES), dst)
    backups = sorted(os.listdir(os.path.join(d, BACKUP_DIR)))
    for old in backups[:-BACKUP_KEEP]:
        shutil.rmtree(os.path.join(d, BACKUP_DIR, old), ignore_errors=True)
    return dst


def archive_page(slug: str, d: str | None = None) -> bool:
    """페이지 보관 전이 — pages/ 밖 archive/ 로 이동 (검색·주입에서 사라짐, 복원 가능)."""
    d = d or memory_dir()
    if not valid_slug(slug):
        raise ValueError(f"invalid slug: {slug!r}")
    with _lock(d):
        path = _page_path(d, slug)
        if not os.path.exists(path):
            return False
        adir = os.path.join(d, ARCHIVE_DIR)
        os.makedirs(adir, exist_ok=True)
        ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d%H%M%S")
        shutil.move(path, os.path.join(adir, f"{slug}-{ts}.md"))
        with contextlib.suppress(Exception):
            conn = _db(d)
            with conn:
                conn.execute("DELETE FROM fts WHERE slug = ?", (slug,))
                conn.execute("DELETE FROM vec WHERE slug = ?", (slug,))
            conn.close()
        write_index(d)
        log_op(d, "norn:archive", slug)
    return True


def restore_page(slug: str, d: str | None = None) -> bool:
    """보관 해제 — 최신 아카이브 스냅샷을 pages/ 로 복귀."""
    d = d or memory_dir()
    if not valid_slug(slug):
        raise ValueError(f"invalid slug: {slug!r}")
    adir = os.path.join(d, ARCHIVE_DIR)
    snaps = sorted(
        f
        for f in (os.listdir(adir) if os.path.isdir(adir) else [])
        if re.fullmatch(rf"{re.escape(slug)}-\d{{14}}\.md", f)
    )
    if not snaps:
        return False
    with _lock(d):
        dst = _page_path(d, slug)
        if os.path.exists(dst):
            raise ValueError(f"page '{slug}' already exists — remove it before restoring")
        shutil.move(os.path.join(adir, snaps[-1]), dst)
        write_index(d)
        log_op(d, "norn:restore", slug)
    from .index import reindex

    reindex(d)
    return True


def apply_norn(d: str | None, plan: dict) -> dict:
    """검증 통과 op만 결정론 커밋. 반환 = {"applied", "failed", "backup", "report"}."""
    d = ensure_home(d)
    ops = list(plan.get("ops") or [])
    applied: list[dict] = []
    failed: list[dict] = []
    # 기존 페이지를 **고치거나 없애는** op 앞에서만 스냅샷을 뜬다. link가 여기 들어가는 것이
    # 요점이다 — 파괴적이지 않다는 말이 무변경이라는 뜻은 아니고, `_add_link`는 양쪽
    # frontmatter를 실제로 다시 쓴다. insight·contradiction은 순수 추가라 뺀다
    # (아무것도 안 고치는 런에서 pages/ 전체를 복사하는 것은 비용만 드는 일이다).
    backup = _backup(d) if any(op["op"] in ("merge", "archive", "link") for op in ops) else ""
    linked = False  # link op이 실제로 페이지를 고쳤는가 — 아래 파생 목차 갱신의 조건
    for op in ops:
        try:
            if op["op"] == "merge":
                _merge_pages(op["src"], op["dst"], d)
                applied.append(op)
            elif op["op"] == "archive":
                if archive_page(op["slug"], d):
                    applied.append(op)
                else:
                    failed.append({**op, "error": "page disappeared"})
            elif op["op"] == "insight":
                from .pages import add

                date = _today()
                provenance = " ".join(f"[[{s}]]" for s in op["sources"])
                body = (
                    f"{op['text']}\n\nsources: {provenance} (norn {date}, "
                    f"confidence: {op['confidence']}, grounding: {op.get('grounding', '?')})"
                )
                slug, _ = add(body, title=op["title"], kind="insight", links=",".join(op["sources"]), d=d)
                applied.append({**op, "slug": slug})
            elif op["op"] == "link":
                linked = _add_link(d, op["a"], op["b"]) or linked
                applied.append(op)
            else:  # contradiction — 보고 전용 (아무것도 안 고친다), 장부에만 접수한다
                applied.append(op)
        except ValueError as e:  # 예산 초과·경합 등 — 노른은 부분 실패를 정직하게 남긴다
            failed.append({**op, "error": str(e)})
    # link만 파생 목차를 안 고치고 있었다. 나머지 페이지 쓰기 경로(merge·archive·insight)는
    # 자기 안에서 이미 `write_index`를 부르므로 여기서 또 부를 이유가 없다 — link이 실제로
    # 무엇인가를 고쳤을 때만 한 번 부른다. 갱신 대상은 index.md 뿐이 아니다: maps/ 는 각
    # 페이지의 links를 그대로 적는 목차라(`vault._rows`) link op 직후 곧바로 낡는다.
    if linked:
        with contextlib.suppress(Exception), _lock(d):  # 파생 목차 실패가 손질 결과를 무르지 않는다
            write_index(d)
    # 모순은 리포트 파일 하나로 끝나면 안 된다 — 런마다 새로 생기는 파일에 흩어지면 같은
    # 어긋남이 열 번 뜨고 사람이 이미 판단한 것도 매번 다시 뜬다 (`memory.contradiction`).
    # 여기서도 해소는 없다: 장부에 접수만 하고 페이지는 손대지 않는다.
    ledger = {
        row["key"]: row for row in record_contradictions([op for op in applied if op["op"] == "contradiction"], d)
    }
    state = _load_state(d)
    state.update({"last_norn": _today(), "log_lines": _log_lines(d)})
    _save_state(d, state)
    log_op(d, "norn", "-", f"applied={len(applied)} failed={len(failed)} dropped={len(plan.get('dropped') or [])}")
    report = _write_report(d, plan, applied, failed, backup, ledger)
    return {
        "applied": applied,
        "failed": failed,
        "backup": backup,
        "report": report,
        "contradictions": list(ledger.values()),
    }


def _write_report(
    d: str, plan: dict, applied: list[dict], failed: list[dict], backup: str, ledger: dict[str, dict] | None = None
) -> str:
    """노른 리포트 — reports/ 는 pages/ 밖 (인덱스 예산 무관). Obsidian vault에서 바로 읽힌다."""
    rdir = os.path.join(d, REPORTS_DIR)
    os.makedirs(rdir, exist_ok=True)
    ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d-%H%M")
    lines = [f"# Norn {ts}", ""]
    for op in applied:
        if op["op"] == "merge":
            lines.append(f"- merge: [[{op['src']}]] → [[{op['dst']}]] (sim {op.get('sim', '?')}) — {op['why']}")
        elif op["op"] == "archive":
            lines.append(f"- archive: {op['slug']} — {op['why']} (복원: asgard memory norn-restore {op['slug']})")
        elif op["op"] == "insight":
            srcs = ", ".join(f"[[{s}]]" for s in op["sources"])
            lines.append(
                f"- insight: [[{op.get('slug', '')}]] ({op['confidence']}, "
                f"grounding {op.get('grounding', '?')}) ← {srcs}"
            )
        else:
            # 처음 보는 것과 또 보는 것을 가려 쓴다 — 같은 경고가 매번 같은 얼굴로 뜨면
            # 사람은 그 줄을 안 읽게 된다. 장부가 신원을 쥐고 있어 여기선 표시만 한다.
            entry = (ledger or {}).get(contradiction_key(op["a"], op["b"])) or {}
            seen = "" if entry.get("new", True) else f" · {entry.get('count', 2)}번째 감지"
            if entry.get("status") == ACKNOWLEDGED:
                seen += " · 이미 본 것"
            lines.append(f"- ⚠ contradiction: [[{op['a']}]] ↔ [[{op['b']}]] — {op['why']} (사람이 해소){seen}")
    for op in failed:
        lines.append(f"- ✗ {op['op']} 실패 — {op.get('error', '')}")
    for op in plan.get("proposed") or []:  # 자율 런의 잔류 제안 — 백그라운드 결과도 흔적을 남긴다
        if op["op"] == "insight":  # 사람에게 넘어온 통찰 — 판단할 재료를 같이 적는다
            target = f"{op.get('title', '')} (grounding {op.get('grounding', '?')})"
            if flag := op.get("polarity_conflict"):
                target += f" ⚠ 극성 충돌 [{flag}] — 출처와 대조할 것"
        else:
            target = op.get("slug") or f"{op.get('src', '')} → {op.get('dst', '')}"
        lines.append(f"- (제안) {op['op']}: {target} — 검토: asgard memory norn")
    for row in plan.get("dropped") or []:
        lines.append(f"- (기각) {row['op'].get('op', '?')} — {row['reason']}")
    if backup:
        lines.append(f"\n백업: {os.path.relpath(backup, d)}")
    path = os.path.join(rdir, f"norn-{ts}.md")
    _atomic_write(path, "\n".join(lines) + "\n")
    return path


# ── 자율 계층 (오딘 결정 26-07-24: "추가는 자율, 파괴는 동의") ─────────────────────
#
# 스스로 기록하며 성장하되, 되돌릴 수 없는 것은 손대지 않는다:
# 완전 가역·순수 추가인 op는 자율로 기록하고, 위키의 형태를 바꾸는
# op(병합·보관)는 제안으로 남긴다. 스킬 승인 게이트(CUS-251)는 이 계층과 무관하게 불변 —
# 여기서 자율화되는 것은 advisory 지식(개인 위키)뿐이고, 그마저 스캔·플로어·캡을 통과한
# 것만이다. 게이트는 여전히 어떤 메모리도 완료 증거로 신뢰하지 않는다.
#
#   off  — 자율 없음: 전부 제안 (넛지만)
#   safe — contradiction(보고 전용)만 자동, 기본값
#   full — merge·archive까지 자동 (백업+복원 가능하지만 형태 변경 — 명시 선택)
#
# 통찰(insight)은 어느 모드에도 기본으로 들어가지 않는다. 26-07-28 판정:
#
# 통찰을 자동에서 뺀 것은 게이트가 약해서가 아니라 **게이트가 답할 수 없는 물음이라서**다.
# 검증기가 결정론으로 답할 수 있는 것은 "이 문장이 출처에서 왔는가"(근거 대조)와 "출처의 주장을
# 뒤집었는가"(극성)까지다. "출처에서 왔고, 뒤집지도 않았는데, 그래도 틀린 추론"은 결정론이
# 잡을 수 있는 모양이 아니다 — 귀납의 비약은 형상이 없다.
#
# 가역성은 이 자리에서 자격이 되지 못한다. remove로 지울 수 있다는 사실은, 허구가 정본
# 자리에 앉아 회수에 섞여 나가고 다른 통찰의 출처가 되던 시간을 되돌려 주지 않는다.
# 그래서 기본은 "접수하되 사람이 연다"이고, 자동은 그 비용을 아는 사람이 켜는 것이다:
#
#   [memory] norn_insight_auto = true   — 켜도 근거 점수가 INSIGHT_AUTO_FLOOR 이상 + 극성 충돌
#                                          없음만 자동이고, mode=off 에서는 여전히 안 켜진다.

AUTO_MODES = ("off", "safe", "full")
_AUTO_OPS = {
    "off": frozenset(),
    "safe": frozenset({"contradiction"}),
    "full": frozenset({"merge", "archive", "contradiction"}),
}


def auto_mode() -> str:
    """노른 자율 모드 — config [memory].norn_auto ∈ off|safe|full (기본 safe)."""
    try:
        v = str(_memory_settings().get("norn_auto", "safe")).strip().lower()
        return v if v in AUTO_MODES else "safe"
    except Exception:
        return "safe"


def insight_auto() -> bool:
    """통찰 자동 승격 옵트인 — config [memory].norn_insight_auto (기본 false).

    기본이 false 인 이유는 위 주석에 있다. 이 스위치는 "검증기를 믿는다"가 아니라
    "검증기가 못 잡는 오류를 내가 감당한다"는 선언이다."""
    try:
        value = _memory_settings().get("norn_insight_auto", False)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    except Exception:
        return False


def partition_ops(ops: list[dict], mode: str, *, allow_insight: bool | None = None) -> tuple[list[dict], list[dict]]:
    """검증 통과 op를 (자동 적용분, 제안 잔류분)으로 가른다 — 모드가 자격을 정하되,
    통찰은 모드만으로 자격을 얻지 못한다: 옵트인 + 근거가 짙어야 자동이다.

    allow_insight를 명시하면 설정을 덮는다 (테스트·호출측 정책용)."""
    allowed = _AUTO_OPS.get(mode, frozenset())
    opted_in = insight_auto() if allow_insight is None else allow_insight

    def _eligible(op: dict) -> bool:
        if op["op"] == "insight":
            # 옵트인 + 모드가 자율을 허용 + 극성 무충돌 + 근거가 짙음. 넷 다여야 자동이다.
            if not opted_in or not allowed or op.get("polarity_conflict"):
                return False
            # 근거 점수 없는 통찰 = 검증기를 안 거친 통찰. 모르면 자동으로 넣지 않는다.
            with contextlib.suppress(TypeError, ValueError):
                return float(op.get("grounding") or 0.0) >= INSIGHT_AUTO_FLOOR
            return False
        return op["op"] in allowed

    auto = [op for op in ops if _eligible(op)]
    proposed = [op for op in ops if not _eligible(op)]
    return auto, proposed


def run_auto(root: str, d: str | None = None) -> dict:
    """자율 노른 1회 — due 판정 → 계획 → 모드 자격분만 적용, 잔류분은 제안으로 보고.

    비-due 여도 강제하지 않는다 (호출측이 due를 확인하고 부르는 것이 정상 경로지만,
    수동 `norn --auto`는 즉시 실행을 원하므로 due를 다시 막지 않는다)."""
    d = ensure_home(d)
    mode = auto_mode()
    plan = plan_norn(root, d)
    auto_ops, proposed = partition_ops(plan["ops"], mode)
    if auto_ops or proposed or plan["dropped"]:
        # 제안·기각뿐이어도 리포트는 남긴다 — 백그라운드 런의 결과가 침묵 속에 사라지지 않는다
        result = apply_norn(d, {"ops": auto_ops, "dropped": plan["dropped"], "proposed": proposed})
    else:
        result = {"applied": [], "failed": [], "backup": "", "report": ""}
        state = _load_state(d)  # 무수확 런도 상태는 전진 — 같은 누적으로 재발화하지 않는다
        state.update({"last_norn": _today(), "log_lines": _log_lines(d)})
        _save_state(d, state)
    return {
        "mode": mode,
        "applied": result["applied"],
        "failed": result["failed"],
        "proposed": proposed,
        "report": result["report"],
    }


# ── wake (호출면 단일 출처 — 훅·네이티브 루프가 같은 판정을 쓴다) ─────────────────


def wake(root: str, d: str | None = None) -> str | None:
    """턴·퀘스트가 끝난 자리에서 부르는 손질 신호 — 사람에게 보일 한 줄 또는 None(침묵).

    **왜 함수인가.**이 판정은 호출면마다 다시 쓰면 안 된다. 개인 메모리는 소유자의 기억이라
    어느 호스트에서 일하든 같은 속도로 손질돼야 하는데(policy.CLIENT_MODES 주석), 등급 분기와
    latch를 표면마다 따로 구현하면 호스트에 따라 위키가 다르게 자란다. 훅(`memory norn
    --wake`)과 네이티브 루프가 여기 하나를 본다.

    **비싼 일은 여기서 안 한다.** due 판정은 log.md 행 수와 state 파일만 읽는다 — LLM도
    임베더도 안 뜬다. 실제 손질(plan_norn의 LLM 왕복)은 분리 스폰한 자식이 맡는다:
    호출자의 턴은 그 사이 그냥 끝난다.

    동의 경계는 `norn_auto` 등급이 쥐고 있지 이 함수가 쥐고 있지 않다 — off는 넛지만,
    기본 safe는 보고 전용(contradiction)까지, full 이라야 병합·보관이 자동이다."""
    d = ensure_home(d)
    due, reason = norn_due(d)
    if not due:
        return None
    mode = auto_mode()
    if mode == "off":
        return nudge_line(d)
    state = _load_state(d)
    digest = str(_log_lines(d))
    if state.get("auto_spawn_digest") == digest:
        return None  # 같은 누적 상태로 이미 스폰 — 중복 백그라운드 방지
    state["auto_spawn_digest"] = digest
    _save_state(d, state)
    if not _spawn_auto(root):
        return None  # 스폰 못 했으면 말도 안 한다 — 시작하지 않은 일을 시작했다고 하지 않는다
    return f"위그드라실 노른 자동 통합 시작 — {reason} (모드 {mode}: 추가는 자율, 병합·보관은 제안)"


def _spawn_auto(root: str) -> bool:
    """`memory norn --auto`를 분리 스폰 — 호출자의 수명과 끊는다 (훅 타임아웃·턴 종료 무관).

    **에이전트를 env로 명시해서 넘긴다.** `profiles.scoped()`는 contextvar라 자식에게 안 따라간다
    — 안 넘기면 이 자식은 끈끈한 활성 에이전트로 떨어져, 에이전트 A로 돌던 세션의 기억을 B의
    위키에 쓴다. 턴마다 도는 자식이라 조용히 쌓이고, 기억은 되돌리기가 가장 어렵다
    (hermes 이슈 18594가 같은 사고였다).

    **시간 상한 표식은 떼고 넘긴다** (`memory_semantic.detached_env`). 훅이 켠
    `ASGARD_MEMORY_NO_DOWNLOAD` 는 부모의 시계를 뜻하는데 이 자식은 그 밖에서 돌고, 물려받으면
    위키를 쓰면서 벡터를 안 만들어 vec_coverage 가 조용히 썩는다."""
    import shutil as _shutil
    import subprocess
    import sys

    from ..memory_semantic import detached_env
    from ..profiles import subprocess_env

    exe = _shutil.which("asgard") or sys.argv[0]
    try:
        subprocess.Popen(
            [exe, "memory", "norn", "--auto"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=root or None,
            env=detached_env(subprocess_env()),
        )
    except Exception:
        return False
    return True


# ── 넛지 (latch — 제안 피로 방지) ──────────────────────────────────────────────


def nudge_line(d: str | None = None) -> str | None:
    """노른이 due 이고 같은 누적 상태로 아직 말하지 않았을 때만 한 줄. 그 외 None."""
    d = d or memory_dir()
    due, reason = norn_due(d)
    if not due:
        return None
    state = _load_state(d)
    digest = hashlib.sha1(f"{_log_lines(d)}".encode()).hexdigest()[:12]
    if state.get("nudge_digest") == digest:
        return None
    state["nudge_digest"] = digest
    _save_state(d, state)
    return f"위그드라실 노른 제안 — {reason}. asgard memory norn으로 통합 검토 (--apply 전엔 무변경)"
