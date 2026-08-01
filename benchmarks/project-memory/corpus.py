"""2차(프로젝트) 메모리 벤치의 **합성** 코퍼스 — 정의와 생성이 한 파일에 있다.

**왜 합성인가.** 이 저장소의 정본(`.asgard/memory/records/`)은 4건뿐이고 그 4건은 관계가
전부 비어 있다(`relations: []`). 관계 1홉 확장을 재려면 관계가 있는 그래프가 있어야 하고,
문서 레인 hit@k 를 재려면 정답을 아는 질의가 여러 개 있어야 한다. 그래서 지어냈다 —
**지어냈다는 사실이 산출물에 남는다** (`results.json` 의 `corpus`, REPORT.md 의 머리말).

절대 수치를 제품 품질로 읽으면 안 된다. 이 코퍼스가 답하는 것은 "얼마나 좋은가"가 아니라
**"확장을 얹었을 때 기본 사실이 안 깎였는가"** 같은 arm 간 비교다.

가공의 프로젝트를 쓴다(비프로스트 게이트웨이). 실제 asgard 정본과 섞이면 어느 쪽 수치인지
알 수 없어지기 때문이다.
"""

from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

REVISION = "HEAD=0000000000000000000000000000000000000000;SYNTHETIC=benchmarks/project-memory"


# ── 문서 레인 코퍼스 ──────────────────────────────────────────────────────────
#
# 로컬 문서 레인(`project_memory/documents.py`)은 절 제목에서 먼저 자르므로, 정답을 **절**
# 단위로 둘 수 있다. 그래서 질의의 정답은 (문서 이름, 절 제목) 쌍이다.

DOCUMENTS: list[tuple[str, str]] = [
    (
        "운영-정책.md",
        """# 비프로스트 게이트웨이 운영 정책

## 1 배포 창

배포는 화요일·수요일·목요일 오전에만 연다. 금요일 배포를 막는 이유는 되돌릴 사람이
주말에 없기 때문이지 금요일이 특별히 위험해서가 아니다. 창 밖 배포는 온콜 책임자의
서면 승인이 있어야 하고, 그 승인은 사후에 회고에 남긴다. 긴급 수정(hotfix)은 이 창을
따르지 않지만 배포 뒤 24시간 안에 회고를 연다.

## 2 비밀 회전

접근 키는 90일마다 갈아 끼운다. 회전은 자동으로 돌지만 실패하면 조용히 넘어가지 않고
온콜을 깨운다. 옛 키는 회전 뒤 7일 동안 살려 두고 그 사이에 쓰이면 경보를 올린다.

## 3 롤백 절차

롤백은 배포 역순으로 되돌린다. 스키마 이행이 낀 배포는 롤백 전에 이행을 먼저 되감아야
하고, 되감을 수 없는 이행은 애초에 배포와 같은 창에 넣지 않는다.
""",
    ),
    (
        "지연-예산.md",
        """# 주입 지연 예산

## 1 총 예산

턴 시작 주입은 5초 안에 끝나야 한다. 이 값은 사람이 기다린다고 느끼기 시작하는 자리에서
왔고, 레인이 늘어도 총량은 안 늘린다. 늘려야 한다면 늘리는 게 아니라 무엇을 뺄지 정한다.

## 2 레인별 배분

여섯 레인이 이 예산을 나눈다. 한 레인이 자기 몫을 넘기면 그 레인 안에서 잘리지 다른
레인의 몫을 먹지 않는다. 문자 예산은 3000자이고 순위가 낮은 후보부터 밀린다.

## 3 초과 시 거동

예산을 넘긴 레인은 조용히 잘린다. 잘렸다는 사실은 계기에 남지만 주입면에는 안 적는다 —
모델이 그것으로 할 수 있는 판단이 없다.
""",
    ),
    (
        "gateway-auth.md",
        """# Gateway authentication component

## 1 Token exchange

The gateway exchanges a short-lived bearer token for a session handle. The exchange is
stateless on the gateway side; the session store owns expiry. A failed exchange returns
401 without a body so that error text never leaks the reason.

## 2 Credential storage

Credentials never touch disk on the gateway. They live in the process for the duration of
one exchange and are zeroed afterwards. The rotation schedule is owned by the operations
policy, not by this component.

## 3 Failure modes

When the session store is unreachable the gateway fails closed. A read-only degraded mode
was considered and rejected: a gateway that admits traffic it cannot authorize is worse
than one that admits nothing.
""",
    ),
    (
        "queue-backend.md",
        """# Queue backend decision

## 1 Chosen backend

We run the work queue on Redis streams. The deciding factor was operational familiarity,
not throughput; both candidates cleared the throughput bar with room to spare.

## 2 Rejected alternative

RabbitMQ was the previous choice and served for two years. It was replaced because the
operational surface was larger than the workload justified, not because it failed.

## 3 Consumer contract

Consumers acknowledge after the side effect, never before. A consumer that acknowledges
first and then crashes silently drops work, and silent loss is the one failure the queue
exists to prevent.
""",
    ),
    (
        "스키마-이행.md",
        """# 스키마 v3 이행

## 1 이행 순서

읽기 경로를 먼저 양쪽 스키마에 열고, 쓰기를 옮기고, 마지막에 옛 칸을 지운다. 세 단계
사이에 배포가 들어가야 하며 한 배포에 두 단계를 묶지 않는다.

## 2 되감기

첫 두 단계는 되감을 수 있다. 세 번째 단계는 못 되감으므로 앞 두 단계가 최소 한 주 동안
운영에서 조용했던 뒤에만 연다.

## 3 계측

이행 중에는 두 스키마의 행 수를 매 시간 대조한다. 어긋나면 이행을 멈추고 원인을 찾는다.
""",
    ),
    (
        "oncall-runbook.md",
        """# On-call runbook

## 1 Paging policy

The on-call engineer is paged for customer-visible failures only. Internal degradation
raises a ticket, not a page. Anything that pages twice in one week becomes a ticket to fix
the alert, not just the incident.

## 2 First fifteen minutes

Acknowledge, then declare severity out loud in the channel before investigating. The
declaration is what starts the clock and tells everyone else whether to join.

## 3 Handover

A shift never ends mid-incident. The outgoing engineer stays until the incoming one has
restated the current hypothesis in their own words.
""",
    ),
    (
        "감사-로그.md",
        """# 감사 로그 계약

## 1 남기는 것

권한이 바뀌는 모든 행위는 누가·언제·무엇을 세 가지를 남긴다. 읽기는 안 남긴다 — 읽기까지
남기면 로그가 본문보다 커지고, 그 크기가 정작 필요한 행을 못 찾게 만든다.

## 2 보관 기간

감사 로그는 2년 보관한다. 이 값은 법이 아니라 우리 계약이며, 줄이려면 계약을 먼저 고친다.

## 3 접근

감사 로그 자체에 대한 접근도 감사 대상이다. 예외는 없다.
""",
    ),
    (
        "embedding-tier.md",
        """# Embedding tier experiment

## 1 Question

Does a heavier embedding model change recall enough to justify a torch dependency? The
current model is a static 256-dimension embedder that runs without torch.

## 2 Method

Two arms over the same corpus, same fusion, same k. Only the embedder differs. Ranking
code is untouched between arms so the difference is attributable.

## 3 Status

Observed, not verified. The measurement ran once on a single corpus and the result has not
been reproduced, so it does not gate any decision yet.
""",
    ),
]

# (질의, 정답 (문서이름, 절제목) 집합, 언어)
DOCUMENT_QUERIES: list[tuple[str, list[tuple[str, str]], str]] = [
    ("금요일에 배포해도 되나", [("운영-정책.md", "1 배포 창")], "ko"),
    ("접근 키는 얼마나 자주 갈아 끼우나", [("운영-정책.md", "2 비밀 회전")], "ko"),
    ("스키마 이행이 낀 배포를 어떻게 되돌리나", [("운영-정책.md", "3 롤백 절차"), ("스키마-이행.md", "2 되감기")], "ko"),
    ("주입 지연 예산은 몇 초인가", [("지연-예산.md", "1 총 예산")], "ko"),
    ("레인이 자기 몫을 넘기면 어떻게 되나", [("지연-예산.md", "2 레인별 배분")], "ko"),
    ("스키마 v3 이행 순서", [("스키마-이행.md", "1 이행 순서")], "ko"),
    ("이행 중에 무엇을 계측하나", [("스키마-이행.md", "3 계측")], "ko"),
    ("감사 로그는 얼마나 보관하나", [("감사-로그.md", "2 보관 기간")], "ko"),
    ("읽기도 감사 로그에 남기나", [("감사-로그.md", "1 남기는 것")], "ko"),
    ("what happens when the session store is unreachable", [("gateway-auth.md", "3 Failure modes")], "en"),
    ("where are gateway credentials stored", [("gateway-auth.md", "2 Credential storage")], "en"),
    ("which queue backend did we choose", [("queue-backend.md", "1 Chosen backend")], "en"),
    ("why was rabbitmq replaced", [("queue-backend.md", "2 Rejected alternative")], "en"),
    ("when do consumers acknowledge", [("queue-backend.md", "3 Consumer contract")], "en"),
    ("when is the on-call engineer paged", [("oncall-runbook.md", "1 Paging policy")], "en"),
    ("what happens at a shift handover", [("oncall-runbook.md", "3 Handover")], "en"),
    ("does a heavier embedding model justify torch", [("embedding-tier.md", "1 Question")], "en"),
]


# ── 관계 그래프 코퍼스 ────────────────────────────────────────────────────────
#
# record 는 (id, kind, title, content, status, confidence, relations) 로 짓는다.
# `superseded`·`observed` 둘은 일부러 넣었다 — `_injectable_knowledge` 가 이웃도 같은 술어로
# 거르는지 확인하는 자리다 (그 게이트가 옆문으로 새면 막아 둔 것이 아니다).

RECORDS: list[dict] = [
    {
        "record_id": "policy.deploy-window",
        "kind": "policy",
        "title": "Deploys open on Tuesday through Thursday only",
        "content": "배포 창은 화요일·수요일·목요일 오전이다. 금요일을 막는 이유는 되돌릴 사람이 주말에 없어서다. 창 밖 배포는 온콜 책임자의 서면 승인을 받는다.",
        "relations": [],
    },
    {
        "record_id": "contract.latency-budget",
        "kind": "contract",
        "title": "Turn-start injection finishes within five seconds",
        "content": "턴 시작 주입의 총 예산은 5초이며 레인이 늘어도 총량은 안 늘린다. 문자 예산은 3000자이고 순위가 낮은 후보부터 밀린다.",
        "relations": [],
    },
    {
        "record_id": "decision.rerank-cpu",
        "kind": "decision",
        "title": "The reranker runs on CPU",
        "content": "구절 리랭커를 CPU 에서 돌리기로 한다. GPU 를 요구하면 설치 문턱이 올라가고, 그 문턱이 이 기능의 이득보다 크다고 판정했다.",
        "relations": [{"type": "dependsOn", "target": "contract.latency-budget"}],
    },
    {
        "record_id": "migration.schema-v3",
        "kind": "migration",
        "title": "Schema v3 rolls out in three deploys",
        "content": "읽기를 양쪽에 열고, 쓰기를 옮기고, 옛 칸을 지운다. 세 단계를 한 배포에 묶지 않는다. 마지막 단계는 되감을 수 없다.",
        "relations": [{"type": "dependsOn", "target": "contract.latency-budget"}],
    },
    {
        "record_id": "policy.secret-rotation",
        "kind": "policy",
        "title": "Access keys rotate every ninety days",
        "content": "Access keys are replaced every ninety days. Rotation runs automatically; a failed rotation pages the on-call engineer instead of passing silently. Retired keys stay live for seven days and any use of them raises an alarm.",
        "relations": [],
    },
    {
        "record_id": "component.gateway-auth",
        "kind": "component",
        "title": "Gateway authentication component",
        "content": "The gateway exchanges a bearer token for a session handle and fails closed when the session store is unreachable. Credentials never touch disk.",
        "relations": [{"type": "dependsOn", "target": "policy.secret-rotation"}],
    },
    {
        "record_id": "contract.audit-trail",
        "kind": "contract",
        "title": "Permission changes are always audited",
        "content": "Every action that changes permission records who, when, and what. Reads are not recorded. Audit logs are kept for two years and access to them is itself audited.",
        "relations": [{"type": "supportedBy", "target": "policy.secret-rotation"}],
    },
    {
        "record_id": "incident.friday-outage",
        "kind": "incident",
        "title": "Gateway outage during a Friday deploy",
        "content": "금요일 저녁 배포 뒤 게이트웨이가 인증을 못 해 40분간 트래픽을 막았다. 되돌릴 사람이 없어 복구가 늦어졌다.",
        "relations": [{"type": "causedBy", "target": "component.gateway-auth"}],
    },
    {
        "record_id": "runbook.rollback",
        "kind": "runbook",
        "title": "Rollback procedure for gateway deploys",
        "content": "롤백은 배포 역순으로 되돌린다. 스키마 이행이 낀 배포는 이행을 먼저 되감아야 하고, 못 되감는 이행은 배포와 같은 창에 넣지 않는다.",
        "relations": [{"type": "resolvedBy", "target": "incident.friday-outage"}],
    },
    {
        "record_id": "runbook.oncall",
        "kind": "runbook",
        "title": "On-call paging and handover",
        "content": "The on-call engineer is paged for customer-visible failures only. A shift never ends mid-incident; handover requires the incoming engineer to restate the hypothesis.",
        "relations": [{"type": "documents", "target": "component.gateway-auth"}],
    },
    {
        "record_id": "decision.queue-redis",
        "kind": "decision",
        "title": "The work queue runs on Redis streams",
        "content": "We run the work queue on Redis streams. Operational familiarity decided it; both candidates cleared the throughput bar.",
        "relations": [{"type": "supersedes", "target": "decision.queue-rabbitmq"}],
    },
    {
        "record_id": "decision.queue-rabbitmq",
        "kind": "decision",
        "title": "The work queue runs on RabbitMQ",
        "content": "RabbitMQ carries the work queue. It served for two years before the operational surface outgrew the workload.",
        "status": "superseded",  # 이웃으로도 주입되면 안 된다
        "relations": [],
    },
    {
        "record_id": "experiment.embed-tier",
        "kind": "experiment",
        "title": "Heavier embedding tier trial",
        "content": "A heavier embedder was tried against the static 256-dimension model. The result ran once and has not been reproduced, so it gates nothing.",
        "confidence": "observed",  # 이웃으로도 주입되면 안 된다
        "relations": [{"type": "appliesTo", "target": "contract.latency-budget"}],
    },
    {
        "record_id": "policy.korean-surface",
        "kind": "policy",
        "title": "User-facing surfaces are written in Korean",
        "content": "사용자가 읽는 표면은 한국어로 적는다. 코드 식별자와 로그는 예외이며, 차용 약어는 쓰지 않는다.",
        "relations": [],
    },
]

# (질의, 정답 record 집합, 유형, 언어)
#   relation — 정답 중 하나가 **어휘로는 안 닿고** 관계로만 닿는다 (확장이 값을 해야 하는 자리)
#   fact     — 정답이 어휘로 바로 닿는다 (확장이 **안 깎아야** 하는 자리, HippoRAG 2 의 경고)
RECORD_QUERIES: list[tuple[str, list[str], str, str]] = [
    ("리랭커를 CPU 로 돌리는 결정이 무엇에 매여 있나", ["decision.rerank-cpu", "contract.latency-budget"], "relation", "ko"),
    ("스키마 v3 이행이 무엇에 매여 있나", ["migration.schema-v3", "contract.latency-budget"], "relation", "ko"),
    ("what does the gateway authentication component require", ["component.gateway-auth", "policy.secret-rotation"], "relation", "en"),
    ("what supports the permission audit contract", ["contract.audit-trail", "policy.secret-rotation"], "relation", "en"),
    ("금요일 저녁 장애는 무엇 때문이었나", ["incident.friday-outage", "component.gateway-auth"], "relation", "ko"),
    ("롤백 절차가 어느 사건에서 나왔나", ["runbook.rollback", "incident.friday-outage"], "relation", "ko"),
    ("배포 창은 언제인가", ["policy.deploy-window"], "fact", "ko"),
    ("주입 예산은 몇 초인가", ["contract.latency-budget"], "fact", "ko"),
    ("사용자 표면은 어느 언어로 적나", ["policy.korean-surface"], "fact", "ko"),
    ("how often do access keys rotate", ["policy.secret-rotation"], "fact", "en"),
    ("which queue backend do we run", ["decision.queue-redis"], "fact", "en"),
    ("when is the on-call engineer paged", ["runbook.oncall"], "fact", "en"),
]


# ── 동언어 렉시컬 기권 코퍼스 ─────────────────────────────────────────────────
#
# `memory_context._same_language_lexical_admission(query, text)` 는 순수 함수다 — backend 도
# 파일도 필요 없다. admit=true 는 "주입해도 된다", false 는 "기권한다"이다.
# 정답 라벨은 **사람이 보기에 이 본문이 이 질의에 관련이 있는가**로 붙였다.

ADMISSION_CASES: list[dict] = [
    # 동언어 · 관련 있음 → 통과해야 한다
    {"query": "배포 창은 언제인가", "text": "배포 창은 화요일·수요일·목요일 오전이다.", "relevant": True, "lang": "ko-ko"},
    {"query": "주입 예산은 몇 초인가", "text": "턴 시작 주입의 총 예산은 5초다.", "relevant": True, "lang": "ko-ko"},
    {"query": "롤백은 어떻게 하나", "text": "롤백은 배포 역순으로 되돌린다.", "relevant": True, "lang": "ko-ko"},
    {"query": "감사 로그 보관 기간", "text": "감사 로그는 2년 보관한다.", "relevant": True, "lang": "ko-ko"},
    {"query": "how often do keys rotate", "text": "Access keys rotate every ninety days.", "relevant": True, "lang": "en-en"},
    {"query": "which queue backend", "text": "We run the work queue on Redis streams.", "relevant": True, "lang": "en-en"},
    {"query": "when is on-call paged", "text": "The on-call engineer is paged for customer-visible failures only.", "relevant": True, "lang": "en-en"},
    {"query": "where are credentials stored", "text": "Credentials never touch disk on the gateway.", "relevant": True, "lang": "en-en"},
    # 동언어 · 관련 없음 → 기권해야 한다 (이 게이트가 사는 자리)
    {"query": "배포 창은 언제인가", "text": "감사 로그는 2년 보관하며 접근도 감사 대상이다.", "relevant": False, "lang": "ko-ko"},
    {"query": "주입 예산은 몇 초인가", "text": "사용자가 읽는 표면은 한국어로 적는다.", "relevant": False, "lang": "ko-ko"},
    {"query": "롤백은 어떻게 하나", "text": "접근 키는 90일마다 갈아 끼운다.", "relevant": False, "lang": "ko-ko"},
    {"query": "감사 로그 보관 기간", "text": "리랭커를 CPU 에서 돌리기로 한다.", "relevant": False, "lang": "ko-ko"},
    {"query": "how often do keys rotate", "text": "Consumers acknowledge after the side effect, never before.", "relevant": False, "lang": "en-en"},
    {"query": "which queue backend", "text": "A shift never ends mid-incident.", "relevant": False, "lang": "en-en"},
    {"query": "when is on-call paged", "text": "The gateway exchanges a bearer token for a session handle.", "relevant": False, "lang": "en-en"},
    {"query": "where are credentials stored", "text": "Schema v3 rolls out across three separate deploys.", "relevant": False, "lang": "en-en"},
    # 동언어 · 관련 없는데 **낱말이 우연히 겹친다** → 게이트가 못 막는 자리 (한계 계측)
    {"query": "배포 창은 언제인가", "text": "배포 뒤 24시간 안에 회고를 연다.", "relevant": False, "lang": "ko-ko"},
    {"query": "which queue backend", "text": "The queue exists to prevent silent loss of work.", "relevant": False, "lang": "en-en"},
    # 교차언어 → 어휘가 안 겹치는 것이 정상이라 게이트가 손대면 안 된다 (양쪽 다 통과가 정답)
    {"query": "접근 키는 얼마나 자주 가나", "text": "Access keys rotate every ninety days.", "relevant": True, "lang": "ko-en"},
    {"query": "온콜은 언제 호출되나", "text": "The on-call engineer is paged for customer-visible failures.", "relevant": True, "lang": "ko-en"},
    {"query": "how often is the deploy window open", "text": "배포 창은 화요일·수요일·목요일 오전이다.", "relevant": True, "lang": "en-ko"},
    {"query": "what is the injection budget", "text": "턴 시작 주입의 총 예산은 5초다.", "relevant": True, "lang": "en-ko"},
]


# ── 생성 ─────────────────────────────────────────────────────────────────────


class _Doc:
    """`documents.save_document` 가 읽는 속성만 가진 최소 운반체.

    `ingest.IngestedDocument` 를 안 쓰는 이유: 그쪽은 파일에서 추출한 결과라 `path`·`bytes_in`
    ·`signals` 처럼 이 벤치가 지어낼 수 없는 칸을 요구한다. 지어낸 값을 실제 추출 결과인 척
    채우면 산출물이 자기 출처를 속인다."""

    def __init__(self, name: str, text: str) -> None:
        self.name = name
        self.text = text
        self.kind = "reference"
        self.strategy = "document"
        self.entities: list[tuple[str, str]] = []
        self.content_hash = hashlib.sha256(text.encode()).hexdigest()
        self.document_id = f"asgard:doc:{hashlib.sha256(name.encode()).hexdigest()[:24]}"


def build(root: str) -> dict:
    """합성 코퍼스를 `root` 에 적는다 — 문서 정본과 record 정본. 반환 = 건수."""
    from asgard.project_memory import ProjectRecord, save_canonical_record
    from asgard.project_memory.documents import save_document

    for name, text in DOCUMENTS:
        save_document(root, _Doc(name, text))
    for spec in RECORDS:
        save_canonical_record(
            root,
            ProjectRecord(
                record_id=spec["record_id"],
                kind=spec["kind"],
                title=spec["title"],
                content=spec["content"],
                source="benchmarks/project-memory/corpus.py",
                source_revision=REVISION,
                importance=spec.get("importance", "high"),
                confidence=spec.get("confidence", "verified"),
                status=spec.get("status", "active"),
                relations=tuple(spec.get("relations") or ()),
            ),
        )
    return {"documents": len(DOCUMENTS), "records": len(RECORDS)}


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "/tmp/asgard-pm-corpus"
    os.makedirs(target, exist_ok=True)
    print(build(target), "→", target)
