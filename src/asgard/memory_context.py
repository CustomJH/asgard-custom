"""개인 로컬 메모리와 선택된 프로젝트 메모리 backend의 범위 분리 협력 회수."""

from __future__ import annotations

import hashlib
import os
import re

from . import memory
from .memory_bridge import find_config, is_backend_trusted, server_recall

PROJECT_RECALL_BUDGET = 3000
# 턴 시작 자동 회수가 원격 하나를 기다리는 상한(초). 명시 MCP 조회의 timeout 과 별개다 —
# 저쪽은 사람이 기다리기로 하고 부른 것이고, 이쪽은 사람이 부른 적 없는 왕복이다.
#
# 기본값은 죽은 backend 를 매 턴 그만큼만 기다린다는 계약이고, 손잡이를 연 이유는 살아 있는데
# 느린 backend 가 그 상한에서 죽은 것과 구별되지 않기 때문이다 (26-08-11 실측: 2,085 fact
# 뱅크의 recall 이 44.9초 — 리랭커 후보 상한을 실제로 적용한 뒤 6.5초. 5초 상한 아래에서는
# 두 상태 다 빈 회수로 같아 보였다). 값은 `project_memory.inject_timeout` 이고, 올린 만큼
# 매 턴의 대기가 늘어난다.
#
# 5 에서 10 으로 올렸다. 후보 상한을 적용한 뒤의 실측 분포가 5 를 위아래로 걸친다 — 같은
# 뱅크에서 회수가 3.1~3.6초인데 doctor 의 탐침은 같은 항목에서 5초를 넘겼고(26-08-12
# helios-asgard), 26-08-11 의 다른 뱅크는 6.5초였다. 상한이 분포 한가운데 있으면 주입이
# 되고 안 되고가 그날의 부하로 갈리고, 떨어질 때 조용하다. 10 은 그 분포를 덮으면서
# 44.9초짜리 병리는 여전히 잘라 낸다.
INJECT_TIMEOUT_DEFAULT = 10
INJECT_TIMEOUT_CEILING = 30
# 회수 질의 상한 — 턴 원문을 통째로 보내면 backend 임베딩이 요청의 잡음까지 닮은 것을 찾는다.
# 값의 근거는 취향이 아니라 대조군이다: 같은 backend(Hindsight)를 쓰는 hermes의
# recall_max_input_chars 기본값이 800 이다. 자르는 쪽은 앞부분 — 사용자의 요청은 앞에 온다.
RECALL_QUERY_MAX_CHARS = 800
# 한 줄에 실을 본문 상한. record는 자립 문장이라 대개 통째로 들어간다(정본 3건 실측 356~401자).
RECALL_BODY_CAP = 700
MAX_METADATA_FIELDS = 128
MAX_METADATA_CHARS = 8192
MAX_METADATA_DEPTH = 8

_QUERY_STOPWORDS = frozenset(
    {
        # 한국어 — 질의에 흔하지만 도메인을 안 가르는 말
        "프로젝트",
        "관련",
        "정보",
        "기억",
        "무엇",
        "어떤",
        "어느",
        "현재",
        "함께",
        "알려줘",
        "대해서",
        "대한",
        # 영어 — 같은 값의 낱말. 이게 없으면 영어 질의의 도메인어 판정이 무너진다:
        # "what", "the", "is"는 거의 모든 영어 본문에 있으므로 하나만 걸려도 통과가 되고,
        # 그러면 게이트가 켜져 있어도 아무것도 안 거른다 (계기만 있고 이빨이 없는 상태).
        "the",
        "this",
        "that",
        "what",
        "which",
        "where",
        "when",
        "who",
        "how",
        "why",
        "and",
        "or",
        "but",
        "for",
        "with",
        "from",
        "into",
        "about",
        "was",
        "were",
        "are",
        "is",
        "be",
        "been",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "can",
        "could",
        "should",
        "would",
        "will",
        "our",
        "your",
        "their",
        "its",
        "it",
        "we",
        "you",
        "they",
        "me",
        "my",
        "project",
        "info",
        "information",
        "memory",
        "current",
        "related",
        "tell",
        "show",
        "give",
    }
)
_QUERY_PARTICLES = (
    "으로",
    "에서",
    "에게",
    "까지",
    "부터",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "에",
    "의",
    "로",
    "과",
    "와",
    "도",
    "만",
)


def _query_terms(query: str) -> list[str]:
    """질의에서 뽑은 도메인어 — 조사를 떼고 불용어를 버린다 (한국어는 `\\b`가 안 듣는다)."""
    terms: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9@._+-]+|[가-힣]+", query.lower()):
        candidates = [raw]
        suffix = next((part for part in _QUERY_PARTICLES if raw.endswith(part) and len(raw) > len(part) + 1), None)
        if suffix:
            candidates.append(raw[: -len(suffix)])
        for candidate in candidates:
            if len(candidate) >= 2 and candidate not in _QUERY_STOPWORDS:
                terms.append(candidate)
    return terms


def _dominant_script(text: str) -> str:
    """이 글의 주된 문자체계 — "hangul" | "latin" | "" (판정 불가).

    글자 수로 정한다. 섞임을 이렇게 다루는 이유는 한국어 질의가 기술 용어를 라틴 문자로
    품는 일이 흔하기 때문이다 ("uv로 테스트 돌려"). '라틴 글자가 있는가'로 판정하면 그런
    질의가 영어 본문과 같은 언어로 오인돼 교차언어 회수가 막힌다."""
    hangul = len(re.findall(r"[가-힣]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if not hangul and not latin:
        return ""
    return "hangul" if hangul >= latin else "latin"


def _same_language_lexical_admission(query: str, text: str) -> bool:
    """동언어 질의의 무근거 자동 주입을 보수적으로 차단한다 (언어 대칭).

    Hindsight 0.8.x recall 결과에는 안정적인 relevance score가 없어서 임의의 점수 문턱을
    둘 수 없다. 그래서 쓰는 자가 어휘 겹침이다: 질의와 본문이 **같은 문자체계**인데
    도메인어가 하나도 안 겹치면 기권한다. 교차언어(한국어 질의 ↔ 영어 본문)는 어휘가 안
    겹치는 것이 정상이므로 backend 순위를 그대로 보존한다.

    26-07-29 수정 — 이 게이트는 원래 **양쪽이 한글일 때만** 돌았다. 영어↔영어는 검사가
    아예 없어서 backend 순위를 무조건 믿었다. 근거(점수 부재)는 언어와 무관한데 결과만
    비대칭이었고, 그 대가는 영어 프로젝트가 잡음 통제를 못 받는 것이다 — 세계에 배포하는
    도구에서 그쪽이 오히려 다수 경로다. 판정을 '한글인가'에서 '주된 문자체계가 같은가'로
    바꾸면 기존 한국어 거동은 그대로면서 영어에도 같은 기준이 생긴다."""
    body = text.split("\n\n", 1)[-1]
    if not query.strip():
        return True
    script = _dominant_script(query)
    if not script or script != _dominant_script(body):
        return True  # 교차언어 또는 판정 불가 — backend 순위를 존중한다
    terms = _query_terms(query)
    haystack = text.lower()
    return not terms or any(term in haystack for term in terms)


def _neutralize(value: str) -> str:
    return value.replace("<", "‹").replace(">", "›")


def _metadata_texts(value) -> list[str]:
    texts: list[str] = []
    total = 0
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_METADATA_DEPTH or len(texts) >= MAX_METADATA_FIELDS:
            raise ValueError("project recall metadata exceeds safety bounds")
        if isinstance(item, dict):
            if len(item) * 2 + len(texts) > MAX_METADATA_FIELDS:
                raise ValueError("project recall metadata exceeds safety bounds")
            stack.extend((child, depth + 1) for pair in reversed(list(item.items())) for child in reversed(pair))
            continue
        if isinstance(item, (list, tuple, set)):
            if len(item) + len(texts) > MAX_METADATA_FIELDS:
                raise ValueError("project recall metadata exceeds safety bounds")
            stack.extend((child, depth + 1) for child in reversed(list(item)))
            continue
        if item is None:
            continue
        text = str(item)
        total += len(text)
        if total > MAX_METADATA_CHARS:
            raise ValueError("project recall metadata exceeds safety bounds")
        texts.append(text)
    return texts


def _deterministic_projection_is_current(root: str, metadata: dict) -> bool:
    from .project_memory import load_projection_manifest

    source = str(metadata.get("source") or "")
    expected_hash = str(metadata.get("content_hash") or "")
    if not source or not expected_hash:
        return False
    full = os.path.realpath(os.path.join(root, source))
    canonical_root = os.path.realpath(root)
    try:
        if os.path.commonpath((canonical_root, full)) != canonical_root:
            return False
        manifest_entry = load_projection_manifest(root)["items"].get(source, {})
        if manifest_entry.get("status") != "active" or manifest_entry.get("content_hash") != expected_hash:
            return False
        digest = hashlib.sha256()
        with open(full, "rb") as current:
            for chunk in iter(lambda: current.read(64 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected_hash
    except OSError, KeyError, ValueError:
        return False


# drop 사유 — 사람에게 그대로 말해야 하므로 한 칸에 뭉치지 않는다. "오염 의심 N건"이라는
# 한 마디는 사용자가 보안 사고로 읽는데, 실제 drop의 대부분은 정본과 바이트가 안 맞은 것이다.
DROP_TAINTED = "tainted"  # 오염 의심 — 인젝션 스캔 적중·신뢰 못 할 출처·metadata 안전 한계 초과
DROP_MISMATCH = "mismatch"  # 정본 불일치 — 저장소 정본으로 확인되지 않았다 (소유권·바이트·신선도)
DROP_OTHER = "other"  # 그 밖 — 통제 문서·빈 본문·자격 미달(status/confidence)·질의 무관
DROP_REASONS = (DROP_TAINTED, DROP_MISMATCH, DROP_OTHER)

_DROP_LABELS = ((DROP_TAINTED, "오염 의심"), (DROP_MISMATCH, "정본 불일치"), (DROP_OTHER, "기타"))


def drop_note(tally: dict[str, int]) -> str:
    """제외 안내 한 줄 — 사유별로 갈라 센다. 아무것도 안 빠졌으면 빈 문자열."""
    parts = [f"{label} {tally[key]}건" for key, label in _DROP_LABELS if tally.get(key)]
    return f"\n({' · '.join(parts)} 제외)" if parts else ""


# backend 에게 미리 거는 필터 — `_injectable_knowledge` 가 보는 두 축을 그대로 태그로 쓴다.
# 게이트를 옮긴 것이 아니라 앞당긴 것이다: 어차피 떨어질 후보를 리랭커에 올리지 않는다.
# 이 태그를 붙이는 자리는 records.record_item·projection 의 artifact item 이고, 그 전에
# 적재된 뱅크는 태그가 없어 여기서 0건이 나온다 — `asgard memory project-rehydrate` 가 다시 태그한다.
INJECTABLE_TAGS = ("status:active", "confidence:verified")


def _injectable_knowledge(scope: object, status: object, confidence: object) -> bool:
    """자동 주입 자격 — 프로젝트 스코프의 active·verified 지식만.

    직접 주입(`_automatic_context_drop_reason`)과 관계 1홉 확장(`_relation_neighbors`)이
    **같은 술어**를 쓴다. 두 자리가 각자 판정하던 시절 이웃 경로는 status만 보고 confidence를
    안 봤고, evolve가 의도적으로 `observed`로 남겨 둔 LLM 추론(통찰)이 역엣지를 타고
    프롬프트에 들어왔다. 자동 승격을 막아 둔 게이트가 옆문으로 새면 막아 둔 것이 아니다."""
    return scope == "project" and status == "active" and confidence == "verified"


def _automatic_context_drop_reason(root: str, metadata: dict, cfg: dict | None = None) -> str:
    """주입에서 뺄 사유 — 통과하면 빈 문자열, 아니면 DROP_REASONS 중 하나.

    provenance를 증명하지 못하는 legacy item은 ambient 및 explicit MCP context에 넣지 않는다.
    두 경로가 공유하는 trust boundary는 fail-closed다.
    """
    if not _injectable_knowledge(metadata.get("scope"), metadata.get("status"), metadata.get("confidence")):
        return DROP_OTHER
    if metadata.get("trust") == "untrusted-conversation" or metadata.get("kind") == "turn":
        return DROP_TAINTED
    if metadata.get("kind") == "binding":
        return DROP_OTHER
    if cfg is not None:
        if (
            not cfg.get("project_uid")
            or not cfg.get("binding_id")
            or metadata.get("project_uid") != cfg.get("project_uid")
            or metadata.get("binding_id") != cfg.get("binding_id")
        ):
            return DROP_MISMATCH  # 이 저장소의 정본이 아니다 — 남의 프로젝트 것이거나 표류했다
    try:
        metadata_texts = _metadata_texts(metadata)
    except ValueError:
        return DROP_TAINTED
    if metadata.get("origin") == "deterministic":
        if not _deterministic_projection_is_current(root, metadata):
            return DROP_MISMATCH
        return DROP_TAINTED if memory.scan_threats(*metadata_texts) else ""
    if not metadata.get("record_id") or not metadata.get("source") or not metadata.get("source_revision"):
        return DROP_OTHER
    return DROP_TAINTED if memory.scan_threats(*metadata_texts) else ""


def _eligible_for_automatic_context(root: str, metadata: dict, cfg: dict | None = None) -> bool:
    """자동 주입은 active·verified 지식과 source artifact만 허용한다 (사유는 안 묻는 표면)."""
    return not _automatic_context_drop_reason(root, metadata, cfg)


def _canonical_record_items(root: str, cfg: dict) -> dict[str, dict]:
    """현재 Git 정본을 backend가 반환해야 할 정확한 item으로 재구성한다."""
    try:
        from .project_memory import load_canonical_records, record_item

        project_id = str(cfg.get("project_id") or cfg.get("bank") or "")
        project_uid = str(cfg.get("project_uid") or "")
        binding_id = str(cfg.get("binding_id") or "")
        return {
            record.record_id: record_item(
                record,
                project_id,
                project_uid=project_uid,
                binding_id=binding_id,
            )
            for record, _path, _digest in load_canonical_records(root)
        }
    except Exception:
        return {}


def _matches_canonical_record(text: str, metadata: dict, canonical_items: dict[str, dict]) -> dict | None:
    """정본과 바이트 단위로 같은 backend 응답이면 그 **정본 원자료**를 돌려준다 (아니면 None).

    게이트 자체는 그대로다 — 대조는 여전히 backend가 보낸 전문(`content`) 전체로 한다.
    달라진 것은 통과 후에 무엇을 손에 쥐느냐다: 통과했다는 사실만 남기면 주입할 때 쓸 수
    있는 건 backend blob 뿐이고, 그건 backend가 검색하라고 만든 온톨로지 머리글이 본문을
    밀어낸 형태다. 통과한 순간 우리는 같은 내용을 **로컬 정본**으로도 갖고 있으므로,
    사람이 쓴 본문(title·content)을 그대로 꺼내 주입한다. 검증은 전문 대조, 표시는 정본 —
    신뢰 경계는 한 치도 넓어지지 않는다."""
    expected = canonical_items.get(str(metadata.get("record_id") or ""))
    if not expected or text != expected["content"]:
        return None
    expected_metadata = expected["metadata"]
    matched = all(
        (key == "content_hash" and key not in metadata) or metadata.get(key) == value
        for key, value in expected_metadata.items()
    )
    record = expected.get("record")
    return (record if isinstance(record, dict) else {}) if matched else None


def filter_project_hits(
    root: str, cfg: dict, hits: list[dict], *, max_results: int | None = None, query: str = ""
) -> tuple[list[dict], dict[str, int]]:
    """Ambient와 explicit MCP가 공유하는 최소 ownership/provenance 정책.

    둘째 반환값은 **사유별 건수**다(DROP_REASONS를 키로). 건수 하나만 세던 시절 호출부는 그
    수를 통째로 "오염 의심"이라 불렀는데, 실제 drop의 대부분은 정본과 바이트가 안 맞은 것이라
    사용자가 없는 보안 사고를 읽었다."""
    clean: list[dict] = []
    tally = dict.fromkeys(DROP_REASONS, 0)
    canonical_items = _canonical_record_items(root, cfg)
    for hit in hits:
        text = str(hit.get("text") or "").strip()
        raw_metadata = hit.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        document_id = str(hit.get("document_id") or "")
        if document_id.startswith("asgard:project-binding:"):
            tally[DROP_OTHER] += 1
            continue
        if not text:
            tally[DROP_OTHER] += 1
            continue
        if memory.scan_threats(text):
            tally[DROP_TAINTED] += 1
            continue
        reason = _automatic_context_drop_reason(root, metadata, cfg)
        if reason:
            tally[reason] += 1
            continue
        canonical: dict | None = None
        if metadata.get("origin") != "deterministic":
            canonical = _matches_canonical_record(text, metadata, canonical_items)
            if canonical is None:
                tally[DROP_MISMATCH] += 1
                continue
        if query and not _same_language_lexical_admission(query, text):
            tally[DROP_OTHER] += 1  # 질의와 어휘가 안 겹친다 — 보안이 아니라 적합성 판정이다
            continue
        clean.append({**hit, "text": text, "metadata": metadata, "canonical": canonical})
        if max_results is not None and len(clean) >= max_results:
            break
    return clean, tally


# backend 검색용으로만 붙은 머리글 줄 — 주입면에서 모델이 이걸로 할 수 있는 판단이 없다.
# Revision·Content-SHA256은 한 줄에 128·64 자의 16진수다. 실측(정본 3건, 26-07-29):
# 주입 1398자 중 476자(34%)가 이 해시였고 정작 본문은 78자에서 문장 중간에 잘렸다.
_NOISE_PREFIXES = ("Revision:", "Content-SHA256:", "Status:", "Importance:", "Confidence:")


def _artifact_body(text: str) -> str:
    """deterministic artifact 본문 — 해시 줄과 빈 온톨로지 줄만 제거한다.

    artifact는 record와 달리 머리글이 곧 신호다(Path·Symbols·Imports는 digest 계층의
    본문 그 자체다). 그래서 머리글을 통째로 버리지 않고, 모델이 쓸 수 없는 줄만 뺀다."""
    kept = [
        line for line in text.splitlines() if not line.startswith(_NOISE_PREFIXES) and not line.endswith(": (none)")
    ]
    return "\n".join(kept).strip()


def hit_body(hit: dict, *, cap: int = RECALL_BODY_CAP) -> str:
    """주입·응답에 실을 본문 한 덩어리 — 정본이 있으면 정본, 없으면 정리한 artifact 본문.

    ambient 주입(project_recall_note)과 명시 MCP 조회(memory_bridge.server)가 같은 함수를
    쓴다. 두 표면이 각자 자르던 시절, MCP 쪽 상한 300자는 머리글(약 321자)에 전부 먹혀
    본문을 **한 글자도** 못 실었다.

    줄바꿈은 접는다. 밀도 때문만이 아니다 — 주입 블록은 `- `로 시작하는 줄의 목록이라,
    본문에 든 줄바꿈은 없는 항목을 하나 만들어낸다 (`_neutralize`는 꺾쇠만 무력화한다)."""
    canonical = hit.get("canonical")
    if isinstance(canonical, dict) and canonical.get("content"):
        title = _neutralize(str(canonical.get("title") or "").strip())
        body = _neutralize(str(canonical["content"]).strip())
        text = f"{title} — {body}" if title else body
    else:
        text = _neutralize(_artifact_body(str(hit.get("text") or "")))
    return " ".join(text.split())[:cap]


def hit_provenance(metadata: dict) -> str:
    """출처 표기 — 한 번만, 짧게. record_id와 파일 경로면 사람도 에이전트도 원본에 닿는다.

    source_revision은 뺐다: 주입면에 실린 그 128자 16진수로 할 수 있는 판단이 없다
    (모델은 비교 대상 해시를 갖고 있지 않다). 신선도 판정은 이미 게이트가 한다 —
    정본과 바이트 단위로 같아야 통과하고, 전체 문자열은 .asgard/memory/records/ 에 있다."""
    parts = []
    for label, key, cap in (("record", "record_id", 120), ("src", "source", 200)):
        value = _neutralize(str(metadata.get(key) or "").strip())[:cap]
        if value:
            parts.append(f"{label}: {value}")
    return f" [{' · '.join(parts)}]" if parts else ""


RELATION_EXPANSION_CAP = 3  # 관계로 딸려오는 record 상한 — 이웃이 본체를 밀어내면 안 된다


def _relation_neighbors(root: str, seed_ids: set[str], cap: int = RELATION_EXPANSION_CAP) -> list[tuple[str, str, str]]:
    """적중 record의 1홉 이웃 — [(record_id, 관계 표기, 본문)]. 없으면 빈 리스트.

    왜 필요한가: backend 검색은 **말이 닮은 것**을 찾는다. 그런데 프로젝트 지식에서 정작
    필요한 이웃은 말이 안 닮았다 — "이 정책이 무엇에 의존하는가"는 어휘가 아니라 관계다
    (리서치 정합: 임베딩·희소검색은 자연어 발견을 늘리지만 정확한 의존이 걸린 과업에는
    그래프 제약이 따로 필요하다). record는 이미 타입 있는 관계를 갖고 있었는데
    (records.RELATIONS 8종) 회수가 한 번도 그걸 안 봤다.

    양방향으로 걷는다: a가 b를 가리키면 b도 a의 이웃이다. 관계 방향은 표기에 남긴다 —
    `dependsOn`(나감)과 `dependsOn⁻`(들어옴)은 읽는 사람에게 전혀 다른 사실이다.

    정본(`.asgard/memory/records/`)에서 직접 읽으므로 신뢰 게이트를 우회하지 않는다.
    게이트가 backend 응답을 대조하는 그 원본이 여기 입력이다. 다만 **원본이라는 것이 자격은
    아니다**: 이웃도 직접 주입과 같은 술어(`_injectable_knowledge`)를 통과해야 한다."""
    try:
        from .project_memory import load_canonical_records

        records = {record.record_id: record for record, _path, _digest in load_canonical_records(root)}
    except Exception:
        return []
    found: list[tuple[str, str, str]] = []
    seen = set(seed_ids)
    for seed_id in sorted(seed_ids):
        seed = records.get(seed_id)
        if seed is None:
            continue
        edges: list[tuple[str, str]] = [
            (str(rel.get("target") or ""), str(rel.get("type") or "")) for rel in seed.relations
        ]
        edges += [
            (rid, f"{rel.get('type')}⁻")
            for rid, record in records.items()
            for rel in record.relations
            if str(rel.get("target") or "") == seed_id
        ]
        for target, relation in edges:
            neighbor = records.get(target)
            if not target or target in seen or neighbor is None:
                continue
            if not _injectable_knowledge(neighbor.scope, neighbor.status, neighbor.confidence):
                continue
            seen.add(target)
            found.append((target, f"{seed_id} {relation}", neighbor.content))
            if len(found) >= cap:
                return found
    return found


PROJECT_PREFIX_TEMPLATE = (
    '\n\n<memory-recall scope="project">\n'
    "요청 관련 프로젝트 공유 메모리 (project_id={project_id}; 힌트 — 원본·완료 증거 아님):\n"
)
PROJECT_SUFFIX = "\n</memory-recall>"


def inject_timeout(cfg: dict) -> int:
    """자동 회수 한 번이 기다릴 초. 설정이 없거나 못 읽으면 기본값, 천장을 넘으면 천장."""
    raw = cfg.get("inject_timeout")
    if raw is None:
        return INJECT_TIMEOUT_DEFAULT
    try:
        value = int(raw)
    except TypeError, ValueError:
        return INJECT_TIMEOUT_DEFAULT
    return max(1, min(value, INJECT_TIMEOUT_CEILING))


def project_recall_rows(query: str, *, start: str | None = None, max_results: int = 5) -> tuple[list[str], str]:
    """프로젝트 backend 회수 본문 목록 + project_id — 렌더도 예산도 없다 (조립기가 건다).

    관계 확장(1홉 이웃)까지 여기서 붙인다: 이웃은 질의에 답한 것이 아니라 답한 것이 의존하는
    것이라 본체 뒤에 와야 하고, 그 순서는 후보의 rank로 표현된다."""
    found = find_config(start or os.getcwd())
    if not found:
        return [], ""
    root, cfg = found
    if not is_backend_trusted(cfg):
        return [], ""
    query = query[:RECALL_QUERY_MAX_CHARS]
    # 턴 시작 자동 주입은 원격 장애로 대화를 붙잡지 않는다. 명시 MCP 조회의 긴 timeout과 분리.
    operation_timeout = inject_timeout(cfg)
    # raw source artifact가 긴 코드 조각으로 budget을 선점하지 않도록, 더 넓게 검색한 뒤
    # 승인된 구조화 record를 먼저 배치한다. 각 그룹 내부 backend 순위는 유지한다.
    hits = server_recall(
        cfg,
        query,
        max_results=max(8, max_results * 2),
        operation_timeout=operation_timeout,
        tags=INJECTABLE_TAGS,
    )
    hits = sorted(
        enumerate(hits),
        key=lambda pair: (
            0 if isinstance(pair[1].get("metadata"), dict) and pair[1]["metadata"].get("record_id") else 1,
            pair[0],
        ),
    )
    project_id = _neutralize(str(cfg.get("project_id") or cfg.get("bank") or ""))[:120]
    filtered, _ = filter_project_hits(root, cfg, [hit for _, hit in hits], max_results=max_results, query=query)
    rows = [f"{body}{hit_provenance(hit['metadata'])}" for hit in filtered if (body := hit_body(hit))]
    seed_ids = {
        str(hit["metadata"].get("record_id") or "") for hit in filtered if isinstance(hit.get("metadata"), dict)
    }
    rows += [
        f"{_neutralize(content)[:300]} [via {_neutralize(edge)[:120]}; record: {_neutralize(record_id)[:120]}]"
        for record_id, edge, content in _relation_neighbors(root, {rid for rid in seed_ids if rid})
    ]
    return rows, project_id


def project_recall_note(query: str, *, start: str | None = None, max_results: int = 5) -> str:
    """현재 프로젝트 backend를 검색한다. 불능·미신뢰·무적중은 빈 문자열로 fail-open.

    이 레인 혼자 쓰는 표면용이다 — 여섯 레인을 같이 넣는 자리는 조립기로 간다."""
    try:
        from .memory.assemble import Candidate, Lane, assemble

        rows, project_id = project_recall_rows(query, start=start, max_results=max_results)
        if not rows:
            return ""
        lane = Lane(
            "project",
            PROJECT_PREFIX_TEMPLATE.format(project_id=project_id),
            PROJECT_SUFFIX,
            PROJECT_RECALL_BUDGET,
        )
        if len(lane.prefix + lane.suffix) > PROJECT_RECALL_BUDGET:
            return ""
        return assemble(
            [Candidate("project", body, rank=index) for index, body in enumerate(rows)],
            (lane,),
            budget=PROJECT_RECALL_BUDGET,
        )
    except Exception:
        return ""


SYNTHESIS_BUDGET = 1100  # 종합층 상한 — 정본 회수(PROJECT_RECALL_BUDGET)를 밀어내면 안 된다
SYNTHESIS_SECTION_CAP = 420


def _synthesis_sections(content: str) -> list[str]:
    """markdown 종합문을 제목 단위 구획으로 쪼갠다 — 통째로 넣지 않기 위해서다.

    제목만 있고 본문이 없는 구획은 버린다: 질의어는 제목에서도 걸리므로, 걸러내지 않으면
    한 줄을 통째로 목차에 내주고 정작 답은 예산 밖으로 밀린다 (실측 26-07-29)."""
    sections: list[str] = []
    current: list[str] = []
    for line in content.splitlines():
        if line.lstrip().startswith("#") and current:
            sections.append("\n".join(current).strip())
            current = []
        current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    return [
        section
        for section in sections
        if any(line.strip() and not line.lstrip().startswith("#") for line in section.splitlines())
    ]


def project_synthesis_rows(query: str, *, start: str | None = None) -> list[str]:
    """승인 record에서 파생된 종합층(mental model)의 질의 관련 구획 — 비권위, fail-open.

    왜 별도 레인인가: 이 글은 사람이 쓴 정본이 아니라 backend LLM이 **승인된 record만**
    보고 쓴 요약이다. 정본과 같은 칸에 섞으면 근거와 요약의 구분이 사라진다 (Canon: 회수는
    힌트지 증거가 아니다). 그래서 scope를 갈라 붙이고 예산도 따로 준다.

    왜 굳이 붙이는가: 이 층은 이미 만들어지고 있었고 (`asgard memory project-learn`),
    `doctor`가 개수만 세고, 어떤 프롬프트에도 한 글자도 안 들어갔다. 대조군(hermes)이
    같은 backend로 "알아서 아는" 느낌을 내는 자리가 정확히 이 통합 계층이다.

    lexical 문턱을 둔다: 질의 도메인어가 하나도 안 걸리면 기권한다. 종합문은 프로젝트
    전체를 요약하므로 무조건 주입하면 매 턴 같은 글이 실려 잡음이 된다.

    게이트 셋은 형제 레인과 같은 것을 쓴다. 이 레인만 빠뜨렸던 자리라 근거를 적어 둔다:
    ① 킬스위치(`inject_enabled`) — 로컬 레인(documents·episodes)이 자기 안에서 한 번 더 보는
      이유와 같다. 호출부가 이미 `inject_allowed`로 막지만, 게이트를 호출부에만 두면 새 호출부가
      생길 때 조용히 새는 자리가 된다.
    ② 신뢰(`is_backend_trusted`) — 이 파일의 내용은 로컬에 있지만 **출처는 backend** 다
      (`snapshot()`이 `list_mental_models()`를 받아 적는다). 사용자가 명시적으로 connect 하지
      않은 backend의 글이 clone 만으로 주입되면 안 된다. 신뢰 저장소는 리포 밖(`~/.asgard`)이라
      저장소가 자기 자신을 신뢰하게 만들 수 없다 — 소유권 필드 대조와 달리 이건 못 위조한다.
    ③ 오염 검사(`scan_threats`) — 종합문은 backend LLM이 쓴 글이고 사람이 문장까지 승인한 것이
      아니다. 형제 레인이 원문에 거는 검사를 여기라고 뺄 근거가 없다."""
    try:
        from .project_memory.learning import load_synthesis

        if not memory.inject_enabled():
            return []
        found = find_config(start or os.getcwd())
        if not found:
            return []
        root, cfg = found
        if cfg.get("inject_synthesis") is False or not is_backend_trusted(cfg):
            return []
        models = load_synthesis(
            root,
            project_uid=str(cfg.get("project_uid") or ""),
            binding_id=str(cfg.get("binding_id") or ""),
        )
        terms = _query_terms(query)
        if not models or not terms:
            return []
        scored: list[tuple[int, int, int, str, str]] = []
        for model_index, model in enumerate(models):
            name = str(model.get("name") or model.get("id") or "")
            for section_index, section in enumerate(_synthesis_sections(str(model.get("content") or ""))):
                if memory.scan_threats(section, name):
                    continue  # 원문 유래 오염 구간 — 주입 제외
                haystack = section.lower()
                score = sum(1 for term in set(terms) if term in haystack)
                if score:
                    scored.append((-score, model_index, section_index, name, section))
        if not scored:
            return []
        scored.sort()
        return [
            f"[{_neutralize(name)[:60]}] {' '.join(_neutralize(section).split())[:SYNTHESIS_SECTION_CAP]}"
            for _score, _mi, _si, name, section in scored
        ]
    except Exception:
        return []  # 종합층 불능이 회수를 막지 않는다 (fail-open)


SYNTHESIS_PREFIX = (
    '\n\n<memory-recall scope="synthesis">\n'
    "승인 record에서 파생된 프로젝트 종합 (요약이다 — 정본도 완료 증거도 아니다):\n"
)
SYNTHESIS_SUFFIX = "\n</memory-recall>"


def project_synthesis_note(query: str, *, start: str | None = None) -> str:
    """종합층 주입 블록 — 이 레인 혼자 쓰는 표면용 (조립기가 여섯을 같이 넣는다)."""
    try:
        from .memory.assemble import Candidate, Lane, assemble

        rows = project_synthesis_rows(query, start=start)
        if not rows:
            return ""
        lane = Lane("synthesis", SYNTHESIS_PREFIX, SYNTHESIS_SUFFIX, SYNTHESIS_BUDGET)
        return assemble(
            [Candidate("synthesis", body, rank=index) for index, body in enumerate(rows)],
            (lane,),
            budget=SYNTHESIS_BUDGET,
        )
    except Exception:
        return ""


LEARNED_SKILLS_CAP = 2  # 스킬 힌트 상한 — skill_bank 라우팅 상한(_CAP)과 같은 근거 (과주입 = 노이즈)


SKILLS_PREFIX = (
    '\n\n<memory-recall scope="skills">\n요청 관련 learned 스킬 (승인된 과거 교훈 — 힌트다, 필요하면 파일을 읽어라):\n'
)
SKILLS_SUFFIX = "\n</memory-recall>"
SKILLS_BUDGET = 460  # 상한 — 포인터 두 줄(이름·설명 160자·경로)이 들어갈 만큼만


_SKILL_ROW_SEP = " — "  # 이름과 설명을 가르는 자리 — `_skill_row`와 `_skill_name`이 같이 쓴다


def _skill_row(name: str, skill: dict, root: str) -> str:
    """스킬 포인터 한 줄 — 이름·설명·경로. 앞의 `- `는 렌더(Candidate.text)가 붙인다."""
    desc = _neutralize(str(skill.get("description") or "").strip())[:160]
    path = str(skill.get("path") or "")
    rel = os.path.relpath(path, root)
    shown = rel if not rel.startswith("..") else path  # 글로벌(~/.asgard) 스킬은 절대경로 유지
    return f"{name}{_SKILL_ROW_SEP}{desc} ({shown})"


def _skill_name(row: str) -> str:
    """`_skill_row`가 만든 행에서 이름을 되읽는다 — 두 함수는 짝이라 한쪽만 고치면 깨진다.

    사용 계수를 조립기 **뒤로** 미루려면 실린 행에서 이름을 되찾아야 한다. 후보 목록을
    따로 들고 다니는 대신 렌더 형식을 한 자리에 묶어 두는 쪽을 골랐다 — 조립기는 문자열만
    돌려주고, 그 문자열이 이 층에서 유일한 진실이다."""
    return row.split(_SKILL_ROW_SEP, 1)[0].strip()


def _record_rendered_skills(chosen: list, *, start: str | None = None) -> None:
    """조립기가 **실제로 실은** 스킬만 사용으로 센다.

    후보를 고르자마자 세면 예산·중복으로 밀린 스킬까지 '쓰인 것'이 되고, `skill_curator`의
    30일/90일 노화 판정은 이 수가 유일한 원료라 보관 전이가 영영 안 열린다. 개인 레인이
    노출 계수에 이미 같은 규율을 쓴다 (`memory.recall.recall_rows`)."""
    try:
        from .skill_bank import record_use

        names = [_skill_name(c.body) for c in chosen if c.lane == "skills"]
        if names:
            record_use(os.path.realpath(start or os.getcwd()), names)
    except Exception:
        pass  # 계수 실패가 회수를 막지 않는다 (fail-open)


def learned_skills_rows(query: str, *, start: str | None = None, cap: int = LEARNED_SKILLS_CAP) -> list[str]:
    """질의 관련 learned 스킬 포인터 목록 — 렌더도 예산도 사용 계수도 없다 (조립기가 건다).

    계수를 여기서 안 올리는 이유는 `_record_rendered_skills`에 적혀 있다."""
    try:
        from .skill_bank import learned_skills

        root = os.path.realpath(start or os.getcwd())
        task = query.lower()
        hits: list[tuple[int, str, dict]] = []
        for name, skill in learned_skills(root).items():
            matched = sum(1 for k in skill["triggers"] if k in task)
            if matched:
                hits.append((-matched, name, skill))
        if not hits:
            return []
        hits.sort(key=lambda row: (row[0], row[1]))
        return [_skill_row(name, skill, root) for _, name, skill in hits[: max(1, cap)]]
    except Exception:
        return []  # 스킬 힌트 불능이 회수를 막지 않는다 (fail-open)


def learned_skills_note(query: str, *, start: str | None = None, cap: int = LEARNED_SKILLS_CAP) -> str:
    """질의 관련 learned 스킬 포인터 — 자가발전 산출물을 회수 계층으로 노출.

    CC 모드에는 네이티브 루프의 디스패치 주입(heimdall resolve_learned)이 닿지 않으므로,
    승인된 스킬을 UserPromptSubmit 회수에 포인터(이름·설명·경로)로 흘린다. 본문 전체는
    주입하지 않는다 — CC 에이전트는 경로를 Read로 열 수 있고, 네이티브 루프와의 이중
    주입도 피한다(recall_note 기본값이 스킬 제외인 이유). Verifier/loki 차단은 호출측
    (memory-activate 감사 매트릭스)이 지킨다 — 스킬 뱅크 헌법과 같은 결.

    이 레인 혼자 쓰는 표면용이다 — 여섯 레인을 같이 넣는 자리는 조립기로 간다.
    `assemble` 대신 `select`+`render`로 푸는 것은 사용 계수가 **실린 것**만 세야 하기
    때문이다 (형제 레인은 셀 것이 없어 `assemble` 한 줄로 끝난다)."""
    try:
        from .memory.assemble import Candidate, Lane, render, select

        root = os.path.realpath(start or os.getcwd())
        rows = learned_skills_rows(query, start=root, cap=cap)
        if not rows:
            return ""
        lanes = (Lane("skills", SKILLS_PREFIX, SKILLS_SUFFIX, SKILLS_BUDGET),)
        chosen = select(
            [Candidate("skills", body, rank=index) for index, body in enumerate(rows)],
            lanes,
            budget=SKILLS_BUDGET,
        )
        _record_rendered_skills(chosen, start=root)
        return render(chosen, lanes)
    except Exception:
        return ""  # 스킬 힌트 불능이 회수를 막지 않는다 (fail-open)


def project_document_note(query: str, *, start: str | None = None) -> str:
    """로컬 레인 문서 구간 — 그래프가 감당 못 해 저장소 정본으로 내려온 큰 문서들.

    프로젝트 backend 연결과 무관하게 돈다: 정본이 저장소에 있고 인덱스가 로컬이라
    서버가 죽어 있어도, 오프라인에서도 회수된다 (project_memory.documents 참고)."""
    try:
        from .project_memory import documents

        root = start or os.getcwd()
        found = find_config(root)
        return documents.note(query, found[0] if found else os.path.realpath(root))
    except Exception:
        return ""  # fail-open — 문서 레인 불능이 회수를 막지 않는다


def episode_recall_note(query: str, *, start: str | None = None) -> str:
    """과거 세션 원문의 관련 구간 — 승격 메모리가 못 덮는 층 (비권위, fail-open).

    이 레인 혼자 쓰는 표면용이다 — 여섯 레인을 같이 넣는 자리는 `recall_note(include_episodes=True)`로
    간다 (네이티브 루프도 그쪽을 쓴다)."""
    try:
        from .agent.episodes import episode_note

        return episode_note(query, os.path.realpath(start or os.getcwd()))
    except Exception:
        return ""  # 에피소드 불능이 회수를 막지 않는다


def recall_total_budget() -> int:
    """여섯 레인의 총 상한 = **레인 명세의 바닥 합**. 이 함수 말고 다른 자리에서 정하지 않는다.

    **천장은 안 낮춘다** — 줄이는 것은 별개의 결정이고 계측 없이 하면 회수 품질을 조용히
    깎는다. 여기서 바뀌는 것은 천장이 아니라 같은 천장 아래 무엇이 실리느냐다 (중복이 빠진
    자리에 다른 증거가 들어온다).

    합을 `_lanes`에서 파생시키는 이유: 전에는 여섯 항 중 둘(문서 900·에피소드 700)이 형제
    상수의 **숫자 복사본**이었다. 그쪽을 고치면 총 예산이 조용히 어긋나고, 어긋난 결과가
    주입면 크기라 아무도 즉시 못 본다. 레인 하나를 더하거나 빼도 이제 여기가 따라온다."""
    return sum(max(0, lane.floor) for lane in _lanes(""))


def _lanes(project_id: str) -> tuple:
    """레인 명세 — **순서가 곧 읽는 순서이자 바닥 배분 순서**다.

    개인·프로젝트가 앞이고 요약·에피소드가 뒤인 것은 값의 순서다: 앞의 둘은 사람이 승인한
    정본이고, 뒤의 둘은 파생·비권위다. 종합(요약)이 정본 뒤에 오는 이유는
    `project_synthesis_rows`가 적어 둔 그대로 — 요약은 근거가 먼저 놓인 다음에 읽혀야 한다."""
    from .agent import episodes as _episodes
    from .memory.assemble import Lane
    from .project_memory import documents as _documents

    return (
        Lane("personal", memory.RECALL_PREFIX, memory.RECALL_SUFFIX, memory.RECALL_BUDGET),
        Lane(
            "project",
            PROJECT_PREFIX_TEMPLATE.format(project_id=project_id),
            PROJECT_SUFFIX,
            PROJECT_RECALL_BUDGET,
        ),
        Lane("document", _documents.NOTE_PREFIX, _documents.NOTE_SUFFIX, _documents.DOCUMENT_BUDGET),
        Lane("synthesis", SYNTHESIS_PREFIX, SYNTHESIS_SUFFIX, SYNTHESIS_BUDGET),
        Lane("skills", SKILLS_PREFIX, SKILLS_SUFFIX, SKILLS_BUDGET),
        Lane("episode", _episodes.NOTE_PREFIX, _episodes.NOTE_SUFFIX, _episodes.EPISODE_BUDGET),
    )


def recall_candidates(
    query: str,
    *,
    start: str | None = None,
    personal_k: int = 3,
    project_k: int = 5,
    include_skills: bool = False,
    include_episodes: bool = False,
) -> tuple[list, str]:
    """여섯 레인의 후보 전량 + project_id. 레인 하나의 고장이 나머지를 막지 않는다.

    레인마다 try로 감싸는 것이 의도다: 이 자리의 fail-open은 "메모리가 없어도 대화는
    계속된다"인데, 한 레인의 예외가 통째로 올라오면 나머지 다섯도 같이 죽는다."""
    from .memory.assemble import Candidate

    out: list[Candidate] = []
    project_id = ""

    def _collect(lane: str, produce) -> None:
        try:
            rows = produce()
        except Exception:
            return  # 레인 하나의 고장 — 나머지는 계속 (fail-open)
        out.extend(Candidate(lane, body, rank=index) for index, body in enumerate(rows) if body)

    _collect("personal", lambda: memory.recall_rows(query, k=personal_k))
    try:
        rows, project_id = project_recall_rows(query, start=start, max_results=project_k)
        out.extend(Candidate("project", body, rank=index) for index, body in enumerate(rows) if body)
    except Exception:
        pass
    # 로컬 레인은 backend 연결과 무관하게 항상 조회한다 — 정본이 저장소에 있기 때문이다.
    _collect("document", lambda: _document_rows(query, start=start))
    _collect("synthesis", lambda: project_synthesis_rows(query, start=start))
    if include_skills:
        _collect("skills", lambda: learned_skills_rows(query, start=start))
    if include_episodes:
        _collect("episode", lambda: _episode_rows(query, start=start))
    return out, project_id


def _document_rows(query: str, *, start: str | None = None) -> list[str]:
    from .project_memory import documents

    root = start or os.getcwd()
    found = find_config(root)
    return documents.rows(query, found[0] if found else os.path.realpath(root))


def _episode_rows(query: str, *, start: str | None = None) -> list[str]:
    from .agent.episodes import episode_rows

    return episode_rows(query, os.path.realpath(start or os.getcwd()))


def recall_note(
    query: str,
    *,
    start: str | None = None,
    personal_k: int = 3,
    project_k: int = 5,
    include_skills: bool = False,
    include_episodes: bool = False,
) -> str:
    """한 질의로 모든 메모리를 조회하되 결과 scope를 절대 섞지 않는다.

    **여섯 레인이 하나의 예산 위에서 겨룬다** (26-07-29). 이전에는 문자열 여섯 개를 그냥
    이어 붙였고, 그래서 (a) 같은 사실이 여러 레인으로 여러 번 들어갔고 (b) 한 레인이 자기
    예산을 안 써도 다른 레인은 자기 상한에서 잘렸다. 조립은 `memory.assemble`이 한다 —
    레인 바닥으로 굶주림을 막고, 남은 자리는 순위(RRF)로 전역 경쟁시키고, 레인 **간**
    중복은 포함계수로 제거한다. 왜 레인 안에서는 안 지우는지는 `assemble._redundant` 참조.

    include_skills는 CC 훅 표면(run_recall)만 켠다 — 네이티브 루프는 디스패치 라우팅이
    스킬 본문을 직접 주입하므로 여기서 또 흘리면 이중 주입이 된다.
    include_episodes는 에피소드를 쓰는 표면이 전부 켠다 (CC 훅·네이티브 루프 둘 다). 전에는
    네이티브가 이 인자를 끄고 `episode_note`를 결과 뒤에 따로 이어 붙였는데, 그러면 그 경로만
    천장이 에피소드 예산만큼 높아지고 에피소드 구간이 중복 판정을 한 번도 안 거쳤다 — 조립기가
    생긴 이유가 그 경로에서만 무효였다.

    `assemble` 대신 `select`+`render`로 푸는 것은 스킬 사용 계수가 **실제로 실린 것**만
    세야 하기 때문이다 (`_record_rendered_skills`)."""
    try:
        from .memory.assemble import render, select

        candidates, project_id = recall_candidates(
            query,
            start=start,
            personal_k=personal_k,
            project_k=project_k,
            include_skills=include_skills,
            include_episodes=include_episodes,
        )
        if not candidates:
            return ""
        lanes = _lanes(project_id)
        chosen = select(candidates, lanes, budget=recall_total_budget())
        if include_skills:
            _record_rendered_skills(chosen, start=start)
        return render(chosen, lanes)
    except Exception:
        return ""  # fail-open — 조립 실패가 대화를 막지 않는다
