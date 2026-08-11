---
chars: 3418
content_hash: f63032e22741348eba8e69b47288fd3f937e3575245479047603799218cfc5c4
document_id: asgard:doc:de166e1d86fa26f495af4d74
entities: []
kind: artifact
lane: local
name: memory-tier-verification-2026-08-11.md
schema: asgard-project-document-v1
strategy: document
---

# 1차·2차 메모리 동작 검증 — 2026-08-11

측정 대상: asgard-custom (세션 저장소), helios-asgard·helios-application (짝 저장소),
Hindsight 백엔드 `asgard-project-memory-hindsight-1` (127.0.0.1:18890, image 0.8.3).

## 1차(개인) 메모리 — 돈다

`asgard memory recall` 이 매 턴 개인 위키를 읽고 `<memory-recall scope="personal">` 로 주입한다.
`asgard doctor` 기준: inject on · provider=claude-native · autosave=on · semantic on
(minishlab/potion-multilingual-128M, 256d, 색인 28/28). 내구성만 ⚠ — 백업 0건이고 sync 원격이
사라진 경로를 가리킨다.

## 2차(프로젝트) 메모리 — 네 자리에서 끊겨 있었다

### ① 리랭커 후보 상한이 도는 컨테이너에 없었다

`docker-compose.yml` 은 `HINDSIGHT_API_RERANKER_MAX_CANDIDATES=80` 과
`HINDSIGHT_API_RERANKER_LOCAL_BUCKET_BATCHING=true` 를 선언한다. 도는 컨테이너의 env 에는
둘 다 없었다 — 컨테이너 생성 시각이 2026-07-28T13:29:49 이고 그 선언은 그 뒤에 들어왔다.
서버 로그가 상한 없이 도는 것을 그대로 보여 준다.

    [4] Reranking [cross-encoder]: 300 candidates scored in 33.979s (pre-filtered 608)

뱅크 `vn_onm_yun` 은 fact 2,085건이고 recall 벽시계가 44.3~44.9초였다 (3회 측정). 같은 서버의
24건짜리 뱅크는 2.3초였으므로 서버 자체의 문제가 아니라 후보 수의 문제다. `budget` 을 low 로
낮춰도 33.2초로 거의 안 변한다 — 그 값은 사전 필터만 좁히고 리랭크 후보 300은 그대로다.

같은 태그(0.8.3)로 `docker compose up -d --no-deps hindsight` 하여 선언을 적용한 뒤:

    [4] Reranking [cross-encoder]: 80 candidates scored in 6.390s (pre-filtered 828)

5개 질의 실측 5.5 · 6.1 · 6.5 · 8.8 · 9.9초. 44.9초 → 중앙값 6.5초.

### ② 자동 주입 상한 5초가 그 아래에 있었다

`memory_context.project_recall_rows` 는 턴 시작 회수의 대기를 `min(cfg.timeout, 5)` 로 잘랐다.
6.5초짜리 백엔드는 이 상한에서 죽은 백엔드와 구별되지 않는다. `project_recall_note` 가 그
예외를 삼켜 빈 문자열을 내므로 화면에는 아무 흔적도 안 남는다 — "2차가 안 먹힌다"의 정체다.

`client.py` 의 회로차단기는 이 상황을 못 줄인다. 상태가 프로세스 안 dict 인데 훅은 턴마다
`asgard memory recall` 을 새 프로세스로 띄우므로, 차단기는 턴을 못 넘긴다.

### ③ 설정 탐색이 첫 `.asgard` 에서 멈췄다

`memory_bridge.find_config` 는 `.asgard/asgard-setting-project.json` 을 가진 첫 디렉터리에서
탐색을 끝냈다. `project_memory` 가 아직 `_comment`·`_example` 뿐인 빈 시드도 그 자리에서
"없음"으로 확정됐다. 결과가 두 가지다.

- 모노레포 하위 폴더가 부모의 연결을 못 본다.
- 짝 저장소는 애초에 위쪽에 없어서 어떤 경로로도 안 보인다.

실물 형상이 정확히 뒤쪽이었다. 연결과 정본 record 는 helios-application 에 있고
(`project_id=vn_onm_yun`, `.asgard/memory/records/` 다수), 세션을 여는 helios-asgard 와
asgard-custom 은 둘 다 빈 시드다.

### ④ 게이트가 문서에 없는 식별자를 요구한다

`project-ingest` 의 graph 레인이 백엔드에 넣은 문서는 회수에는 잡히는데 주입에서 전부 떨어진다.
`memory_context._automatic_context_drop_reason` 이 `record_id`·`source`·`source_revision` 셋을
다 요구하는데, `ingest.document_item` 은 앞의 둘만 발급한다 — 문서에는 record_id 가 없다.
실측 metadata (오딘이 넣은 문서):

    scope=project status=active confidence=verified kind=decision origin=ingest
    record_id=None source=document:roof-diagram-string-view-background-image-2026-08-11.md
    source_revision=5f21636b87659a35 → drop reason = other

같은 질의의 나머지 9건은 `confidence=observed` 라서 떨어진다. 이쪽은 의도된 동작이다 —
LLM 추론은 자동 승격하지 않는다.

게이트는 신뢰 경계라 이번 작업에서 넓히지 않았다. graph 레인 문서는 로컬 정본이 없어
바이트 대조를 할 수 없고, 그것을 주입한다는 결정은 오딘의 몫이다. 지금 도는 길은 local
레인이다 — `.asgard/memory/documents/` 에 Git 정본으로 적히고 로컬 FTS 색인으로 주입되며
백엔드 없이도 돈다.

## 이번에 고친 것

- `find_config` — 빈 시드는 답이 아니라고 보고 위로 계속 걸어간다. 그래도 못 찾으면 이
  프로젝트가 `asgard root add` 로 연 작업 뿌리를 본다. 반환하는 뿌리는 설정이 사는
  디렉터리라 소유권 검증과 Git 정본 record 가 따라온다. 꺼짐(`enabled: false`)과 깨진
  설정은 부재가 아니라 정지다 — 오타 하나로 남의 뱅크를 읽지 않는다.
- 자동 주입 대기가 `project_memory.inject_timeout` 설정이 됐다. 기본 5초, 천장 30초.
- `asgard doctor` 가 미연결일 때도 2차 메모리 한 줄을 낸다. 전에는 행 자체가 사라져서
  화면에 개인 메모리 다섯 줄만 남았다.

## 아직 열려 있는 것

- 6.5초는 여전히 기본 5초 위다. 이 기계에서 자동 주입을 켜려면 `inject_timeout` 을 8~10으로
  올리거나 리랭커 후보를 80보다 낮춰야 한다. 후자는 회수 품질을 깎는 선택이다.
- 회로차단기가 프로세스를 못 넘긴다. 죽은 백엔드는 매 턴 상한만큼 대기한다.
- graph 레인 문서의 주입 여부는 미결이다.
