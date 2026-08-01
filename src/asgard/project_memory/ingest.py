"""문서 인제스트 — 사람이 던진 문서를 프로젝트 메모리가 받을 수 있는 모양으로 만든다.

사람들은 명령어를 치지 않는다. "이 문서 분석해서 프로젝트에 넣어줘" 하고 파일을 던진다.
그 한 문장이 도달해야 하는 판단이 넷이고, 셋은 코드가 결정론으로 답할 수 있다:

  ① 무슨 파일인가        — 확장자별 추출기 (pdf·docx·hwp·hwpx·md·txt)
  ② 어떤 종류의 문서인가  — 형상으로 판정 (요구사항 ID 밀도·절 번호·표·결정 어휘)
  ③ 무엇이 엔티티인가     — 요구사항 ID·표제 (정규식. LLM 추측이 아니다)
  ④ 승인할 것인가        — 사람 몫. 팀 공유 스코프의 쓰기는 언제나 사람을 지난다

②가 전략을 정한다. 요구사항·설계처럼 **정적이고 큰** 문서는 `document` 전략(hindsight
chunks 모드 — LLM 추출 없이 원문 청크 저장)으로, 결정·사건처럼 **관계가 중요한** 짧은 것은
`record` 전략(LLM 추출 + 관찰 통합)으로 보낸다. 한 프로젝트 = 한 뱅크이고, 갈리는 것은
뱅크가 아니라 아이템이다 (hindsight `MemoryItem.strategy`).

판정이 틀릴 수 있으므로 언제나 사람이 덮어쓸 수 있다 — 자동은 기본값이지 구속이 아니다.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import re

from ..memory import scan_secrets, scan_threats
from .records import _PLACEHOLDERS, _SECRET_PATTERNS, MAX_ARTIFACT_BYTES

# hindsight 뱅크 설정에 심는 전략 표. 이름은 우리가 정하고, 값은 서버의 hierarchical 필드다.
#
# 26-07-28 **1차 판정은 틀렸다.** 그때는 326KB 문서가 링크 3,511개를 만들고 서버가 죽는 것을
# 보고 "링크 폭발"로 읽어 청크를 3000→8000으로 키웠다. 버려도 되는 뱅크를 새로 파서 변수를
# 하나씩 갈라 재 보니(3차, tests/load/README.md) 링크는 용의자가 아니었다. 서버 로그의
# 단계별 시간이 그대로 말해 준다:
#
#     [2] Parallel retrieval … graph=0(0.003s)
#     [4] Reranking [cross-encoder]: 3 candidates scored in 20.675s
#
# 회수 시간의 99%가 CPU 크로스 인코더 리랭크이고, 비용은 **후보 수 × 후보 길이**다. 링크를
# 7,260개까지 늘린 구성이 오히려 가장 건강했다(적중 10건). 청크를 키운 조치가 실제로 한 일은
# 정반대였다 — 후보 하나를 거대하게 만들어 리랭크를 느리게 했고, 더 나쁘게는 한국어 8000자
# 단위가 회수 예산(max_tokens=2048)을 넘겨 **토큰 필터에서 통째로 버려졌다**: 리랭크 비용은
# 다 물고 결과는 0건인 쓰기 전용 경로였다.
#
#   문서 96,000자 고정, 청크만 바꿔 실측 (한국어 실물 산문):
#     8000 →  13 units ·   109 links · 33s 뒤 서버 사망 · 적중 0
#     4000 →  32 units ·   541 links · 57~67s          · 적중 1
#     1000 → 168 units · 3,360 links · 56~63s          · 적중 3~5
#      500 → 363 units · 7,260 links · 41~46s          · 적중 9~10
#
# 그래서 청크를 **줄인다**. 1000자는 단위 하나가 회수 예산 안에 들어오는 크기이고(적중이
# 0에서 살아난다), 500자만큼 잘게 부수지 않아 절 단위 의미가 남는다. 상수로 빼 두는 이유는
# unit 예측(predict_units)이 **같은 값**을 봐야 하기 때문이다 — 예측과 실제가 갈리면
# 상한이 헛돈다.
DOCUMENT_CHUNK_CHARS = 1000

STRATEGIES = {
    # 정적 대용량 — 요구사항서·규격서·기획서. 원문을 그대로 두고 찾을 수 있게만 한다.
    "document": {
        # 추출 없음: 우리 신뢰 게이트가 어차피 원문만 받으므로 뽑은 사실은 쓰이지 않는다.
        "retain_extraction_mode": "chunks",
        "retain_chunk_size": DOCUMENT_CHUNK_CHARS,
    },
    # 관계가 중요한 짧은 것 — 결정·사건. 추출과 관찰 통합이 실제로 값을 한다.
    "record": {"retain_extraction_mode": "concise"},
}

DEFAULT_STRATEGY = "document"

# 뱅크 기본값으로만 걸리는 설정. 전략(strategy)에 넣어도 소용이 없다 — 26-07-28 소스 확인:
# 통합 제출 판정(`memory_engine._submit_post_retain_tasks`)은 `resolve_full_config` 결과를 보고,
# `apply_strategy`는 그보다 **나중에** 적용된다. 즉 전략은 추출·청킹은 바꾸지만 "통합을 걸까"는
# 이미 지난 뒤다. 그래서 이건 뱅크 설정에 둔다.
#
# 프로젝트 뱅크에는 정적 문서와 관계형 기록이 함께 있으므로 자동 통합은 끈다. 대신 observation
# 자체는 켜고, Asgard가 승인된 decision/policy/incident 같은 태그만 골라 `/consolidate`에
# 예약한다. 그러면 raw artifact 수천 건을 LLM에 태우지 않으면서 Hindsight의 학습층은 살린다.
BANK_DEFAULTS = {
    "retain_default_strategy": DEFAULT_STRATEGY,
    "enable_observations": True,
    "enable_auto_consolidation": False,
}

MAX_DOCUMENT_BYTES = 64 * 1024 * 1024  # 추출 입력 상한 (agent.tools와 같은 자리)
MAX_ENTITIES = 40

# 그래프 수용 상한 — 이 문서를 뱅크에 넣어도 그 뱅크가 계속 쓸 수 있는가.
#
# 문턱은 임의값이 아니라 **제품이 이미 정한 값**이다: memory_context.project_recall_note는
# 턴 시작 주입을 `operation_timeout = min(cfg timeout, 5)`로 자른다. 5초를 넘는 회수는
# 느린 게 아니라 주입면에서 **존재하지 않는다**. 그러니 상한은 "5초 안에 돌아오는 크기"다.
#
# 실측 (26-07-28 3차, 청크 1000 · 한국어 실물 산문 · 질의 3개 · tests/load/README.md):
#
#     chars   units  links   회수      적중   ≤5s
#      2,000      3      9   0.9s        3     ✓
#      4,000      5     25   2.0s        3     ✓
#      8,000     11    121   4.4s      2~3     ✓   ← 경계
#     12,000     16    256   6.0s        1     ✗   (asgard 클라이언트 왕복으로 잰 값)
#     16,000     25    500  10.4s      3~4     ✗
#     48,000     77  1,540  29.6s      3~4     ✗
#
# 회수 시간 ≈ 0.38s × units (리랭크가 후보마다 무는 값). 5초 예산 ÷ 0.38 ≈ 13 units 이고,
# 실측 통과점(11 units 4.4s)과 실패점(16 units 6.0s) 사이가 정확히 거기다. 품질은 어느
# 크기에서도 3~4건으로 멀쩡했다: 큰 문서가 그래프 레인에서 탈락하는 이유는 못 찾아서가
# 아니라 **제때 못 돌아와서**다.
#
# 넘겼을 때의 비용은 대칭이 아니다. 밑돌면 문서 하나가 로컬 레인으로 가고 여전히 검색되지만,
# 넘치면 서버 프로세스가 종료돼(실측 RestartCount 1→4) **다른 뱅크의 회수까지** 같이 죽는다.
GRAPH_UNIT_CEILING = 13
# 예측은 **청크 상한이 아니라 실측 평균 단위 크기**로 나눈다. 서버는 상한을 채우지 않고
# 경계에서 자르므로 단위가 상한보다 작다 — 26-07-28 실측(청크 1000):
#
#     chars    실제 units   1000자당
#      2,000        3         1.50
#      8,000       11         1.38
#     12,000       16         1.33
#     16,000       25         1.56
#     48,000       77         1.60
#
# 상한으로 나누면(=1.0/1000자) 큰 문서를 **1.5배 과소평가**해 게이트가 그만큼 헐거워진다.
# 실제로 asgard 클라이언트 왕복 검증에서 "예측 12 units" 문서가 16 units·6.0s로 나와
# 주입 예산을 넘겼다. 620은 위 표에서 가장 빡빡한 점(48,000/77 = 623)보다도 작은 값이다 —
# 모든 실측점에서 예측이 실제를 **밑돌지 않는** 쪽으로 고른다 (테스트가 이 성질을 지킨다).
EFFECTIVE_UNIT_CHARS = 620
GRAPH_CHAR_CEILING = GRAPH_UNIT_CEILING * EFFECTIVE_UNIT_CHARS  # 8,060자
# 전략에 청크 크기가 없을 때(record) 쓰는 값. record는 어차피 짧아서 이 값이 판정을 가르는
# 일이 없지만, 예측이 0으로 무너지는 자리를 남기지 않는다.
CHUNK_FALLBACK = 3000
LANE_GRAPH, LANE_LOCAL = "graph", "local"
SUPPORTED = (".pdf", ".docx", ".hwp", ".hwpx", ".md", ".markdown", ".txt", ".rst")

# 요구사항 ID — 실제 문서에서 쓰이는 모양. "METER-001", "REQ-12", "SRS-3.2.1"
_REQ_ID = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,4}(?:\.\d{1,3})*)\b")
# 같은 모양이지만 요구사항이 아닌 것들 — 규격·표준 이름. 26-07-28 실측: DLMS 문서에서
# RS-485·CRC-16이 REQUIREMENT로 잡혔다. 형상이 같으니 형상으로는 못 가른다 — 근거를 더 본다.
_REQ_ID_LABEL = re.compile(
    # 실제 문서는 "**요구사항 ID**: METER-001"처럼 굵게 표시가 라벨과 콜론 사이에 낀다.
    # 콜론 앞뒤 양쪽에서 마크다운 강조를 흘려보낸다.
    r"(?:요구사항\s*ID|요구\s*번호|Requirement\s*ID|REQ\s*ID)\s*\**\s*[:：]?\s*\**\s*"
    r"([A-Z][A-Z0-9]{1,9}-\d{1,4}(?:\.\d{1,3})*)",
    re.IGNORECASE,
)
_REQ_ID_MIN_OCCURRENCES = 3  # 표제 + 상호참조 — 진짜 요구사항 ID는 문서 안에서 반복된다
# 절 번호 — "## 3.2 제목" / "3.2.1 제목"
_SECTION = re.compile(r"^#{0,6}\s*(\d+(?:\.\d+){0,3})\s+\S", re.MULTILINE)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
# 결정문의 어휘 — 이게 짙으면 record 다
_DECISION = re.compile(
    r"결정(했|한다|사항)|채택(했|한다)|기각(했|한다)|합의(했|한다)|decided|adopted|rejected|"
    r"장애|사고|원인|재발\s*방지|postmortem|incident|root\s*cause",
    re.IGNORECASE,
)
# 요구사항·설계문의 어휘
_SPEC = re.compile(
    r"요구사항|수용\s*기준|제약|규격|사양|인터페이스|프로토콜|아키텍처|설계|기획|"
    r"requirement|acceptance\s*criteria|specification|architecture|protocol|shall\b|must\b",
    re.IGNORECASE,
)


MAX_FINDINGS = 20  # 미리보기에 싣는 자리 수 상한. 한 문서가 화면을 통째로 먹지 않게 한다
_EXCERPT_PAD = 60  # 걸린 자리 앞뒤로 보여 줄 글자 수 — 사람이 "이건 예시다"를 판단할 만큼만


class IngestError(ValueError):
    """인제스트 계약 위반 — 미지원 형식·빈 문서·과대 파일."""


class IngestBlocked(IngestError):
    """비밀·인젝션 검사에 걸려 저장을 막았다.

    IngestError를 물려받는 것은 의도다 — `plan`이 이미 그 하나만 잡고 있고, 호출측은 "못
    들어간 문서"를 한 갈래로 다루면 된다. 갈리는 것은 `findings`가 붙어 있다는 것뿐이다."""

    def __init__(self, message: str, findings: list[dict]):
        super().__init__(message)
        self.findings: list[dict] = list(findings)


@dataclasses.dataclass(frozen=True)
class IngestedDocument:
    """추출·판정이 끝난 문서. 등록은 아직 하지 않았다 (승인 전 상태)."""

    path: str
    name: str
    text: str
    suffix: str
    bytes_in: int
    strategy: str
    kind: str
    entities: tuple[tuple[str, str], ...]
    signals: dict
    content_hash: str
    lane: str = LANE_GRAPH

    @property
    def document_id(self) -> str:
        """같은 파일을 다시 던지면 같은 id — update_mode=replace가 갈아끼운다."""
        return f"asgard:doc:{hashlib.sha256(self.name.encode()).hexdigest()[:24]}"

    @property
    def graph_units(self) -> int:
        """이 문서가 뱅크에 만들 unit 수의 예측 (서버 청킹 규칙 그대로)."""
        return predict_units(len(self.text), self.strategy)


def predict_units(chars: int, strategy: str = DEFAULT_STRATEGY) -> int:
    """chars → 서버가 만들 unit 수 (실측 모형).

    청크 **상한**이 아니라 실측 평균 단위 크기로 나눈다 — 상한으로 나누면 큰 문서를 1.5배
    과소평가한다 (EFFECTIVE_UNIT_CHARS 주석의 표). 예측은 실제보다 조금 큰 쪽이어야 한다:
    게이트가 틀릴 때 문서 하나가 로컬로 더 가는 것과 뱅크가 멎는 것은 비용이 다르다."""
    size = EFFECTIVE_UNIT_CHARS if strategy == "document" else CHUNK_FALLBACK
    return max(1, -(-max(0, chars) // size))


def assign_lane(chars: int, strategy: str = DEFAULT_STRATEGY) -> str:
    """이 문서를 그래프에 넣을 것인가, 로컬 레인으로 보낼 것인가 (결정론).

    판정 기준이 "문서가 큰가"가 아니라 "뱅크가 살아남는가"인 것이 중요하다 — 크기는
    수단이고, 지켜야 하는 것은 팀 전원이 공유하는 회수 경로다."""
    return LANE_LOCAL if predict_units(chars, strategy) > GRAPH_UNIT_CEILING else LANE_GRAPH


# ── ① 추출 ────────────────────────────────────────────────────────────────────


def extract_text(path: str) -> str:
    """문서 → 평문. 형식별 추출기는 agent.tools의 것을 재사용한다 (단일 출처).

    던져지는 문서는 저장소 밖에 있을 수 있으므로 경로를 프로젝트 안으로 가두지 않는다 —
    대신 크기 상한과 아카이브 안전 검사는 그대로 통과시킨다."""
    suffix = os.path.splitext(path)[1].lower()
    if suffix not in SUPPORTED:
        raise IngestError(f"지원하지 않는 형식: {suffix or '(확장자 없음)'} — {', '.join(SUPPORTED)}")
    if not os.path.isfile(path):
        raise IngestError(f"파일이 없다: {path}")
    if os.path.getsize(path) > MAX_DOCUMENT_BYTES:
        raise IngestError(f"문서가 {MAX_DOCUMENT_BYTES // (1024 * 1024)}MiB 상한을 넘는다")
    if suffix in (".md", ".markdown", ".txt", ".rst"):
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    from ..agent.tools import _extract_docx, _extract_hwp, _extract_hwpx, _extract_pdf

    extractors = {".pdf": _extract_pdf, ".docx": _extract_docx, ".hwpx": _extract_hwpx, ".hwp": _extract_hwp}
    try:
        return extractors[suffix](path)
    except Exception as exc:  # ToolError 포함 — 호출측은 IngestError 하나만 알면 된다
        raise IngestError(f"{suffix[1:].upper()} 추출 실패: {exc}") from exc


# ── ①' 비밀·인젝션 검사 ───────────────────────────────────────────────────────
#
# record 경로는 `records.validate_record`가 지키고 개인 메모리는 `memory.policy`의 저장 관문을
# 지나는데, **던져진 문서만 무검사로** 정본과 팀 공유 뱅크에 앉고 있었다. 문서는 남이 쓴 것이고
# 두 레인 모두 공유물이 된다 — 뱅크는 팀 전원이 회수하고, 로컬 정본은 커밋과 함께 저장소로
# 나간다. 그러니 검사는 레인이 갈리기 **전**에 있어야 한다.
#
# 판정은 공용 관문(scan_secrets·scan_threats)이 한다. 여기 있는 코드가 하는 일은 그 판정이
# 참일 때 **어디인지**를 짚어 주는 것뿐이다: 승인 미리보기가 "무엇이 걸렸는지"를 못 보여 주면
# 사람은 통째 거절과 통째 승인 중 하나만 고를 수 있고, 그것은 고르는 게 아니다.


def _where(text: str, offset: int) -> tuple[int, int]:
    """문자 오프셋 → (행, 열). 둘 다 1부터 센다 — 편집기가 세는 방식과 같아야 쓸모가 있다."""
    line = text.count("\n", 0, offset) + 1
    start = text.rfind("\n", 0, offset) + 1
    return line, offset - start + 1


def _excerpt(text: str, start: int, end: int, *, mask: bool) -> str:
    """걸린 자리의 발췌. 비밀은 걸린 스팬만 가리고 **주변은 남긴다**.

    통째로 가리면 사람이 판단할 근거가 사라지고, 그대로 두면 미리보기가 유출면이 된다.
    `<`·`>`를 바꿔 두는 것은 발췌가 표면에서 태그로 읽히지 않게 하기 위해서다 (documents 레인의
    주입 경로와 같은 규율)."""
    head = text[max(start - _EXCERPT_PAD, 0) : start]
    body = "[redacted-credential]" if mask else text[start:end]
    tail = text[end : end + _EXCERPT_PAD]
    joined = " ".join(f"{head}{body}{tail}".split())
    return joined.replace("<", "‹").replace(">", "›")


def _secret_spans(text: str) -> list[tuple[int, int]]:
    """credential 패턴이 걸린 스팬 — `scan_secrets`와 **같은 패턴·같은 예외**로 훑는다.

    placeholder 예외를 여기서 다시 적는 것은 중복이 아니라 계약이다: 관문이 통과시킨 자리를
    미리보기가 "걸렸다"고 그리면 두 화면이 갈린다."""
    low = text.lower()
    spans: list[tuple[int, int]] = []
    for pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            nearby = low[max(0, match.start() - 30) : match.end() + 30]
            if any(marker in match.group(0).lower() or marker in nearby for marker in _PLACEHOLDERS):
                continue
            spans.append((match.start(), match.end()))
            if len(spans) >= MAX_FINDINGS:
                return sorted(spans)
    return sorted(spans)


def screen(text: str) -> list[dict]:
    """문서 원문 검사 — 반환 = 걸린 자리 목록. 빈 목록이 통과다.

    자리 찾기는 관문이 "걸렸다"고 말했을 때만 돈다 (문서는 64MiB까지 오므로 통과 경로에 전수
    순회를 달지 않는다). 찾기가 실패해도 막는 결정은 그대로다 — 자리를 못 짚은 것이 무해하다는
    뜻은 아니므로 행 0으로 한 건을 남긴다."""
    body = text or ""
    findings: list[dict] = []
    if secret := scan_secrets(body):
        spans = _secret_spans(body)
        for start, end in spans:
            line, column = _where(body, start)
            findings.append(
                {
                    "kind": "secret",
                    "reason": secret,
                    "line": line,
                    "column": column,
                    "excerpt": _excerpt(body, start, end, mask=True),
                }
            )
        if not spans:  # 관문은 걸었는데 자리를 못 짚었다 — 판정을 낮추지 않는다
            findings.append({"kind": "secret", "reason": secret, "line": 0, "column": 0, "excerpt": ""})
    if threat := scan_threats(body):
        located = 0
        offset = 0
        for line_number, line in enumerate(body.splitlines(keepends=True), start=1):
            if located >= MAX_FINDINGS:
                break
            if reason := scan_threats(line):
                findings.append(
                    {
                        "kind": "injection",
                        "reason": reason,
                        "line": line_number,
                        "column": 1,
                        "excerpt": _excerpt(body, offset, offset + len(line.rstrip("\n")), mask=False),
                    }
                )
                located += 1
            offset += len(line)
        if not located:  # 줄을 넘겨 걸린 패턴 — 한 줄씩 보면 안 보인다
            findings.append({"kind": "injection", "reason": threat, "line": 0, "column": 0, "excerpt": ""})
    return findings[:MAX_FINDINGS]


def _blocked_reason(findings: list[dict]) -> str:
    """사람이 읽는 한 줄 사유. 발췌는 `findings`가 들고, 여기서는 셈과 첫 자리만 말한다."""
    secrets_found = sum(1 for row in findings if row["kind"] == "secret")
    threats_found = len(findings) - secrets_found
    parts = (
        f"비밀 {secrets_found}건" if secrets_found else "",
        f"인젝션 {threats_found}건" if threats_found else "",
    )
    counted = "·".join(part for part in parts if part)
    head = findings[0]
    where = f"{head['line']}행" if head["line"] else "위치 미상"
    return f"검사에 걸려 저장하지 않는다 ({counted}) — 첫 자리 {where}: {head['reason']}"


def guard(text: str, name: str = "") -> None:
    """걸리면 `IngestBlocked`, 깨끗하면 조용히 돌아온다. 조용히 지우지도 통과시키지도 않는다."""
    findings = screen(text)
    if findings:
        prefix = f"{name}: " if name else ""
        raise IngestBlocked(prefix + _blocked_reason(findings), findings)


# ── ② 종류 판정 (결정론) ──────────────────────────────────────────────────────


def classify(text: str, name: str = "") -> tuple[str, str, dict]:
    """(strategy, kind, signals) — 형상만 본다. LLM 없음.

    가르는 축은 "크고 정적인가" 대 "짧고 관계적인가"다. 요구사항 ID가 여럿이거나 절 번호·표가
    빽빽하면 앞쪽, 결정·사고 어휘가 짙고 짧으면 뒤쪽. 애매하면 document로 둔다 — 잘못 넣어
    LLM 추출비를 무는 것보다, 원문을 그대로 두고 사람이 나중에 승격하는 편이 되돌리기 쉽다."""
    body = text or ""
    req_ids = set(_REQ_ID.findall(body))
    sections = len(_SECTION.findall(body))
    tables = len(_TABLE_ROW.findall(body))
    decision = len(_DECISION.findall(body))
    spec = len(_SPEC.findall(body))
    length = len(body)
    signals = {
        "chars": length,
        "requirement_ids": len(req_ids),
        "sections": sections,
        "table_rows": tables,
        "decision_terms": decision,
        "spec_terms": spec,
    }
    lowered = name.lower()
    if any(word in lowered for word in ("결정", "decision", "adr", "postmortem", "장애", "incident")):
        return "record", "decision", signals
    if any(word in lowered for word in ("요구", "requirement", "spec", "설계", "design", "기획", "규격", "프로토콜")):
        return "document", "specification", signals
    # 짧고 결정 어휘가 스펙 어휘보다 짙으면 record
    if length < 4000 and decision > spec:
        return "record", "decision", signals
    if req_ids or sections >= 5 or tables >= 5 or length >= 8000:
        return "document", "specification", signals
    return DEFAULT_STRATEGY, "artifact", signals


# ── ③ 엔티티 (결정론) ─────────────────────────────────────────────────────────


def extract_entities(text: str) -> tuple[tuple[str, str], ...]:
    """문서에서 확정 엔티티를 뽑는다 — 요구사항 ID만. 추측하지 않는다.

    hindsight의 chunks 모드에서는 서버가 엔티티를 추출하지 않으므로 여기서 준 것이 **유일한**
    엔티티 출처다 (fact_extraction._extract_facts_chunks 독스트링). 그래서 정규식으로 확실한
    것만 올린다 — 문서 제목이나 사람 이름처럼 형상으로 못 가르는 것은 넣지 않는다."""
    body = text or ""
    # ① 명시 라벨이 붙은 것은 확실하다
    labelled = {match.upper() for match in _REQ_ID_LABEL.findall(body)}
    # ② 라벨이 없으면 반복 횟수로 가른다. 규격 이름(RS-485)은 한두 번 스치고 지나가지만
    #    요구사항 ID는 자기 절 표제와 다른 절의 상호참조에 거듭 나온다.
    counts: dict[str, int] = {}
    for match in _REQ_ID.findall(body):
        counts[match] = counts.get(match, 0) + 1
    repeated = {name for name, count in counts.items() if count >= _REQ_ID_MIN_OCCURRENCES}
    seen: list[tuple[str, str]] = []
    for name in _REQ_ID.findall(body):  # 문서 등장 순서를 유지한다
        if name not in labelled and name not in repeated:
            continue
        pair = (name, "REQUIREMENT")
        if pair not in seen:
            seen.append(pair)
        if len(seen) >= MAX_ENTITIES:
            break
    return tuple(seen)


# ── 조립 ──────────────────────────────────────────────────────────────────────


def prepare(path: str, *, strategy: str | None = None, lane: str | None = None) -> IngestedDocument:
    """문서 하나를 등록 직전 상태까지 만든다. 쓰기 없음.

    strategy를 명시하면 자동 판정을 덮는다 — 자동은 기본값이지 구속이 아니다.
    lane도 같다: 그래프를 강제하는 선택은 남겨 두되, 기본은 뱅크를 지키는 쪽이다."""
    text = extract_text(path)
    if not text.strip():
        raise IngestError("추출된 텍스트가 없다 (스캔 PDF 라면 OCR이 필요하다)")
    name = os.path.basename(path)
    # 판정·엔티티·레인보다 **앞**이다. 뒤에 두면 걸린 문서도 승인 대기 줄에는 한 번 선다.
    guard(text, name)
    auto_strategy, kind, signals = classify(text, name)
    chosen = (strategy or auto_strategy).strip().lower()
    if chosen not in STRATEGIES:
        raise IngestError(f"알 수 없는 전략: {chosen} — {', '.join(STRATEGIES)}")
    auto_lane = assign_lane(len(text), chosen)
    picked = (lane or auto_lane).strip().lower()
    if picked not in (LANE_GRAPH, LANE_LOCAL):
        raise IngestError(f"알 수 없는 레인: {picked} — {LANE_GRAPH}, {LANE_LOCAL}")
    return IngestedDocument(
        path=os.path.abspath(path),
        name=name,
        text=text,
        suffix=os.path.splitext(path)[1].lower(),
        bytes_in=os.path.getsize(path),
        strategy=chosen,
        kind=kind,
        entities=extract_entities(text),
        signals={
            **signals,
            "auto_strategy": auto_strategy,
            "overridden": bool(strategy),
            "auto_lane": auto_lane,
            "lane_overridden": bool(lane) and lane != auto_lane,
            "graph_units": predict_units(len(text), chosen),
            "graph_unit_ceiling": GRAPH_UNIT_CEILING,
        },
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        lane=picked,
    )


def plan(
    paths: list[str], *, strategy: str | None = None, lane: str | None = None
) -> tuple[list[IngestedDocument], list[dict]]:
    """여러 문서를 한 번에 준비한다. 반환 = (준비된 것, 못 들어간 것). 쓰기 없음.

    못 들어간 줄에는 `findings`가 늘 있다 — 검사에 걸린 것만 내용이 차고 나머지는 빈 목록이다.
    키를 조건부로 두면 미리보기가 매번 존재를 물어야 하고, 그 물음을 빠뜨리면 사유가 사라진다."""
    ready: list[IngestedDocument] = []
    failed: list[dict] = []
    for path in paths:
        try:
            ready.append(prepare(path, strategy=strategy, lane=lane))
        except IngestError as exc:
            failed.append({"path": path, "error": str(exc), "findings": list(getattr(exc, "findings", ()))})
    return ready, failed


def document_item(document: IngestedDocument, project_id: str, *, project_uid: str = "", binding_id: str = "") -> dict:
    """hindsight가 받는 아이템 한 묶음. 전략과 확정 엔티티를 함께 보낸다.

    본문은 **원문 그대로**다 — 요약하지 않는다. 요약은 되돌릴 수 없고, 무엇이 빠졌는지
    나중에 알 방법이 없다. 크기 상한은 서버 청킹이 감당한다."""
    header = (
        f"[ProjectDocument:{document.kind}]\n"
        f"Name: {document.name}\n"
        f"Format: {document.suffix[1:] or 'text'}\n"
        f"Content-SHA256: {document.content_hash}\n"
        f"Strategy: {document.strategy}\n\n"
    )
    return {
        "content": header + document.text,
        "context": f"asgard project document {document.kind}",
        "document_id": document.document_id,
        "update_mode": "replace",  # 같은 문서를 다시 던지면 갈아끼운다 (교정 경로)
        "strategy": document.strategy,
        "timestamp": "unset",  # 규격·요구사항에는 발생 시각이 없다
        "tags": [f"project:{project_id}", "document", f"kind:{document.kind}"],
        "entities": [{"text": name, "type": kind} for name, kind in document.entities],
        "metadata": {
            "source": f"document:{document.name}",
            "source_revision": document.content_hash[:16],
            "content_hash": document.content_hash,
            "ontology_type": "project-document",
            "origin": "ingest",
            "kind": document.kind,
            "strategy": document.strategy,
            "scope": "project",
            "status": "active",
            "confidence": "verified",
            "project_uid": project_uid,
            "binding_id": binding_id,
        },
    }


def oversized(document: IngestedDocument) -> bool:
    """Git 정본으로 두기엔 큰가 — 사본 보관 여부 판단에 쓴다."""
    return len(document.text.encode()) > MAX_ARTIFACT_BYTES


__all__ = [
    "DEFAULT_STRATEGY",
    "BANK_DEFAULTS",
    "GRAPH_CHAR_CEILING",
    "GRAPH_UNIT_CEILING",
    "LANE_GRAPH",
    "LANE_LOCAL",
    "MAX_FINDINGS",
    "STRATEGIES",
    "SUPPORTED",
    "IngestBlocked",
    "IngestError",
    "IngestedDocument",
    "assign_lane",
    "classify",
    "document_item",
    "extract_entities",
    "extract_text",
    "guard",
    "oversized",
    "plan",
    "predict_units",
    "prepare",
    "screen",
]


# ── 등록 (승인 게이트 경유) ────────────────────────────────────────────────────


def ensure_strategies(cfg: dict) -> dict:
    """뱅크 설정에 전략 표를 심는다. 이미 같으면 건드리지 않는다.

    전략은 뱅크 설정에 이름으로 살고 아이템은 이름만 참조한다 — 그래서 한 프로젝트(=한 뱅크)
    안에서 문서마다 다른 처리가 가능하다. 뱅크를 나눌 일이 아니다."""
    from ..project_memory_backends import get_backend

    backend = get_backend(cfg)
    try:
        # 뱅크 설정 표면은 backend 선택 사항이다 — 공용 Protocol이 요구하지 않는다.
        # 없는 backend에서 그냥 부르면 AttributeError로 ingest 전체가 죽으므로, 없으면
        # 전략을 안 심고 그 사실을 정직하게 돌려준다 (문서는 기본 전략으로 처리된다).
        read = getattr(backend, "bank_config", None)
        write = getattr(backend, "update_bank_config", None)
        if not (callable(read) and callable(write)):
            return {"changed": False, "strategies": {}, "reason": "backend exposes no bank config surface"}
        config = read()
        current = config.get("retain_strategies") or {}
        strategies_ok = all(current.get(name) == body for name, body in STRATEGIES.items())
        # 통합 플래그는 전략이 아니라 **뱅크 기본값**으로만 걸린다 (BANK_DEFAULTS 주석 참고).
        # 전략만 심고 이걸 빠뜨리면 링크 폭발이 그대로 남는다 — 실측에서 서버가 거기서 죽었다.
        defaults_ok = all(config.get(key) == value for key, value in BANK_DEFAULTS.items())
        if strategies_ok and defaults_ok:
            return {"changed": False, "strategies": current, "defaults": BANK_DEFAULTS}
        merged = {**current, **STRATEGIES}
        write({"retain_strategies": merged, **BANK_DEFAULTS})
        return {"changed": True, "strategies": merged, "defaults": BANK_DEFAULTS}
    finally:
        backend.close()


def stage_documents(root: str, cfg: dict, documents: list[IngestedDocument]) -> list[dict]:
    """준비된 문서를 레인별로 보낸다.

    graph — 승인 대기로 올린다. 여기서 등록하지 않는다: 뱅크는 팀 공유 스코프다.
    local — 저장소 정본으로 바로 적고 로컬 인덱스에 태운다. 승인 게이트를 건너뛰는 것이
            아니라 **게이트가 다른 것**이다: 공유의 순간이 등록이 아니라 커밋이고, 그
            커밋은 사람이 한다. 파일은 git status에 그대로 보이고, 지우면 사라진다."""
    from ..memory_bridge import backend_target, stage_retain
    from . import documents as local_lane

    # 쓰기 앞에 한 번 더 센다. `prepare`를 지난 문서는 이미 깨끗하지만 이 함수는 직접 조립한
    # IngestedDocument도 받는다 — 검사를 지나는 문이 하나뿐이면 그 문을 안 지나는 길이 생긴다.
    # 전수 선검사인 것도 의도다: 한 건이 걸릴 때 그 앞 문서만 저장돼 있으면 배치가 반쪽으로 남는다.
    for document in documents:
        guard(document.text, document.name)
    graph = [d for d in documents if d.lane == LANE_GRAPH]
    target = backend_target(cfg) if graph else {}
    staged: list[dict] = []
    for document in documents:
        row = {
            "name": document.name,
            "kind": document.kind,
            "strategy": document.strategy,
            "lane": document.lane,
            "entities": len(document.entities),
            "chars": len(document.text),
            "graph_units": document.graph_units,
            "document_id": document.document_id,
            "approval_id": "",
        }
        if document.lane == LANE_LOCAL:
            row["canonical_path"] = local_lane.save_document(root, document)
        else:
            item = document_item(
                document,
                str(target["project_id"]),
                project_uid=str(target.get("project_uid") or ""),
                binding_id=str(target.get("binding_id") or ""),
            )
            row["approval_id"] = stage_retain(root, item, target=target)
        staged.append(row)
    # 인덱스는 **전부 적은 뒤에 한 번** 만든다. 문서마다 부르면 저장이 지문을 바꾸는 만큼
    # 재구축이 배치 길이만큼 반복된다 (n건 → n회 전체 재구축).
    if any(d.lane == LANE_LOCAL for d in documents):
        chunks = local_lane.sync(root)
        for row in staged:
            if row["lane"] == LANE_LOCAL:
                row["chunks"] = chunks
    return staged
