# 메모리 전수 점검 — 2026-08-20

대상: `asgard-custom` 저장소의 개인 메모리(1차)와 프로젝트 메모리(2차) 전부.
2차 뱅크는 `asgard-custom`, 엔진은 Hindsight 0.8.3, asgard 0.10.19.

여섯 갈래로 나눠 동시에 쟀다. 각 갈래의 원본 기록은 세션 스크래치패드의 `audit/U0.md` ~ `U5.md`
에 있고, 이 문서는 그것을 합친 것이다. 모든 수치는 실행한 명령의 출력에서 나왔고, 추론은
추론이라고 적었다.

---

## 한 줄

배관은 멀쩡하다. **이 저장소의 2차 메모리는 8월 13일부터 프롬프트에 한 번도 안 실렸고, 화면에서
그것이 정상과 구분되지 않았다.**

---

## 1. 헤드라인 — 아무도 못 알아챈 한 주

### 무슨 일이 있었나

2026-08-06 커밋 `4669fe7a25e4`("🔥 chore(asgard): 프로젝트 메모리 정본과 설정 제거", 8 files,
248 deletions)가 `.asgard/memory/records/` 아래 Git 정본 record 4건과 소유권 마커를 지웠다.
마커는 나중에 복구됐고 record 는 안 돌아왔다.

자동 주입 게이트는 백엔드 응답을 그 Git 정본과 **바이트 대조**한 뒤에만 통과시킨다
(`src/asgard/memory_context.py:386-389`). 정본 디렉터리가 없으면
`load_canonical_records()`(`src/asgard/project_memory/canonical.py:189-192`)가 빈 리스트를
돌려주고, 뱅크에 무엇이 있든 전량 `mismatch` 가 된다.

### 얼마나 오래

Claude Code 기록 1,479개를 전수로 훑어 실측했다. 주입 블록은 `type="attachment"` 레코드의
`.attachment.content[]` 에 원문으로 남는다.

| scope | 전체 기록의 블록 수 | 최근 10개 기록 |
| --- | --- | --- |
| `personal` | 576 | 34 (본문 없는 것 0) |
| `episode/session` | 388 | 19 |
| `project-document` | 298 | 31 |
| `skills` | 129 | 13 |
| **`project`** | **119** | **0** |
| `synthesis` | 56 | 7 |

`scope="project"` 를 실은 마지막 기록은
`~/.claude/projects/-Users-yun-develop-personal-space-project-asgard-custom/598f0240-2cb7-4b52-80fe-358ed7ec4ed5.jsonl`,
mtime **2026-08-13 04:11**. 그 뒤 최근 30개 세션이 전부 0건이고, 같은 구간에 개인 레인은
계속 1~24건씩 흘렀다.

날짜가 둘이다 — **정본 삭제 08-06, 마지막 주입 08-13.** 그 7일의 간격은 못 밝혔다.
가설(그 말 그대로 가설이다): 그 사이 블록은 `origin=deterministic` 인 project-scan 투영이었고
(`memory_context.py:392-395` 는 이 갈래만 정본 대조를 건너뛴다), 소스가 바뀌자
`_deterministic_projection_is_current` 가 거짓이 되며 같은 mismatch 로 떨어졌다. 확인하려면
`598f0240` 기록의 project 블록 provenance 줄을 열면 된다.

### 왜 아무도 몰랐나

주입 조립기 `recall_note`(`memory_context.py:947-957`)가 후보 0건인 레인을 **통째로 뺀다.**
훅은 남은 것만 싣는다(`.claude/hooks/memory-activate.py:307-310`). 그래서 "프로젝트 레인이
6건 중 4건을 mismatch 로 버렸다"는 문장이 프롬프트에도 화면에도 안 나온다. 탈락 사유를 조립하는
`drop_note`(`memory_context.py:252`)는 존재하지만 `project-recall` CLI 표면에서만 쓰인다.

정상(기억할 게 없는 프로젝트)과 병리(정본 유실로 전량 탈락)가 화면에서 똑같다.

### 막는 것이 두 겹이다 — 한쪽만 고치면 여전히 0건

백엔드를 직접 열어 재고를 셌다. 필터가 독립적으로 두 자리에 있다.

**① 백엔드 태그 사전 필터.** `INJECTABLE_TAGS = ("status:active", "confidence:verified")`
(`memory_context.py:262`)를 `tags_match="all_strict"` 로 건다
(`project_memory_backends/__init__.py:395-397`). 07-28 적재분 record 3건에는
`confidence:verified` **태그 자체가 없다** — 값이 틀린 게 아니라 축이 없다. `GET /tags` 실측으로
`record` 13건 대 `confidence:verified` 2건이고, 그 2건은 오늘 감사가 넣은 것이다. 태그가 없으면
리랭커에 오르지도 못한다.

**② 결과 판정.** `filter_project_hits`(`memory_context.py:380`)가 같은 술어를 metadata 로 다시
본다. 여기서 Git 정본 바이트 대조가 걸린다.

세 record 의 metadata 는 셋 다 `scope=project`·`status=active`·`confidence=verified` 이고
`project_uid`·`binding_id` 도 `binding.json` 과 일치한다. 소유권 검사는 통과하고 바이트 대조에서
떨어진다.

| document_id | record_id | 사유 |
| --- | --- | --- |
| `asgard:record:22525e471d532687d1dfc2d2` | `contract.memory-two-tier-boundary` | 정본 불일치 |
| `asgard:record:4c5650236b59636a826c2df8` | `policy.project-bank-selection` | 정본 불일치 |
| `asgard:record:3ec1f34125c3535b3b68989c` | `policy.hindsight-approved-learning` | 정본 불일치 |
| `asgard:project-binding:v1` | (kind=binding) | 기타 — `memory_context.py:371` 이 접두로 무조건 뺀다 |

담긴 내용은 실재한다. 예: `"Personal memory is canonical only under ~/.asgard/memory/pages and
must never be retained in Hindsight."` 두 경로 모두에서 도달 불가일 뿐이다.

### 되돌릴 동사가 없다

코드는 정본 → 뱅크 방향만 안다. 뱅크 → 정본 방향의 동사가 어디에도 없다.
`--recover-binding`(`memory_bridge/config.py:64-101`)은 신원만 되찾고 record 는 안 되찾는다.

복구 경로는 `git show 4669fe7a^:<record 경로>` 로 정본 4건을 되살린 뒤 전체 rehydrate 다.
**쓰기이므로 이 감사에서는 실행하지 않았다 — 오딘의 결정 사항이다.**

---

## 2. 그 위에 올라탄 결함 — 높음

### H1 — 빈 정본에 대고 rehydrate 가 초록을 낸다

```
asgard memory project-rehydrate --tags-only --yes --plan-id d6920d3ee0b9fec39884a043c11a2a455a8951fa9f2ccc6eb2cbf639e0d27bf5
#   ✔ project memory retagged: 0 record(s) → engine=hindsight project_id=asgard-custom
# exit 0
```

원인: `src/asgard/project_memory/canonical.py:304-305` 가 빈 plan 을 성공으로 조기 반환한다.
뱅크가 record 3건을 든 채 정본이 0건인 상태를 "할 일 없음"과 구분하지 않는다.

**AGENTS.md 와 `commands/doctor/memory.py:234` 가 이 명령을 태그 복구 수단으로 처방한다.**
지시를 따른 에이전트는 초록 체크와 exit 0 을 받고 아무것도 못 고친다. 위의 한 주가 살아남은
통로가 이것이다.

### H2 — 자격 미달을 사람이 볼 신호가 주입 경로에 없다

위 §1 "왜 아무도 몰랐나"가 그대로 결함이다. `recall_note` 가 빈 레인을 삭제하고, 훅이 남은 것만
싣고, 어디에도 탈락 개수가 안 나온다. H1 이 조용했던 직접 원인이고, 아래 M6(콜드 타임아웃)이
조용한 이유이기도 하다.

### H3 — 기본 `project-sync` 가 안 바뀐 artifact 전부를 묘비로 덮는다

`removed = set(previous) - set(current)`(`src/asgard/project_memory/projection.py:323`)인데
기본 모드의 `current` 는 working-tree 가 바뀐 파일만 담는다
(`src/asgard/commands/memory/project.py:56-62`).

격리 루트 재현(원격 쓰기 없음): 매니페스트 243건 + changed 후보 19건 →
**upserts 17 / removed 241**. `--all` 로 같은 매니페스트에 돌리면 0/0.
묘비는 `update_mode=replace` 라 본문이 사라진다(`projection.py:385-423`).

지금 이 저장소는 `.asgard/state/project-memory-manifest.json` 이 없어 `previous` 가 비었고,
그래서 미리보기가 `removed: []` 를 낸다. **결함이 가려져 있을 뿐이다.**
미리보기가 241줄의 `deleted ·` 를 찍고 `--plan-id` 를 요구하므로 사람이 막을 수는 있다.

### H4 — artifact 문에는 뱅크를 지키는 크기 상한이 없다

`ingest` 는 8,060자(13 units)를 넘기면 로컬 레인으로 돌린다
(`src/asgard/project_memory/ingest.py:110-126`; 주석에 초과 시 서버 RestartCount 1→4 실측이
적혀 있다). 그런데 `project-sync` 가 보내는 artifact 는 같은 `strategy: "document"` 를 쓰면서
그 판정을 하지 않는다(`projection.py:80`).

실측: full 계층 243건 중 **28건이 상한 초과**, 최대 65,934자 = 예측 107 units(상한의 8배),
`--all` 한 번의 총량 1,686 units.

### H5 — 로컬 레인 문서는 어느 사용자 표면에도 없다

대형 문서 로컬 FTS 레인은 살아 있고 채워져 있다 — 문서 2건·조각 18개·12,423바이트, 질의 왕복
0.0018~0.006초. 그런데 그것을 찾는 표면이 하나도 없다. `run_project_recall`
(`src/asgard/commands/memory/project.py:286`)은 `server_recall` 하나만 부르고,
`documents.stats()`(`documents.py:480`)의 호출자는 테스트뿐이며, `asgard doctor` 에 행이 없다.
소비처는 턴 시작 주입 하나다.

```
asgard memory project-recall "1차·2차 메모리 동작 검증" --json   # 문서 0건
# 같은 질의를 documents.search 로 넣으면 2건 적중
```

### H6 — 1차 회수 융합이 유일한 정답을 41위로 밀어낸다

`approval round trip for saving memories` 로 물으면 정답 페이지가 안 나온다. 그런데 벡터 색인은
그 페이지를 1위로 준다 — 코사인 **0.429**, 2위 0.166, 문턱 0.20 을 넘는 페이지가 그것 하나뿐이다.
융합에서 52건 중 **41위**로 내려간다. 리랭커를 꺼도 그대로다.

원인은 동점 처리다. 어휘 스캔이 2글자 이상 부분문자열을 전수로 맞추는데
(`src/asgard/memory/recall/search.py:146-149`), 영어 기능어 `for` 가 57장 중 39장에 걸린다.
그리고 `_add_ranks`(`:231-236`)가 동점 전체에 같은 순위 1을 준다. 39장이 전부
1/(60+1)=0.016393 을 받고 유일한 의미 증거도 같은 값을 받아, 타이브레이크(`:299`)에서 밀린다.

오딘의 규칙이 "LLM 행 기본 프롬프트는 영어"이므로 이것은 드문 경로가 아니다.

### H7 — 노른 검토 화면이 `link` op 을 "contradiction" 으로 부른다

`link` 는 두 페이지의 frontmatter 를 **실제로 다시 쓰는** op 이다(`norn/apply.py:160`, 백업 대상에도
들어간다 `:137`). `contradiction` 은 코드 주석이 "보고 전용, 아무것도 안 고친다"라고 못 박은
종류다(`:163`). 화면이 전자를 후자의 이름으로 찍으므로, 오딘은 "아무것도 안 바뀐다"고 읽고
`--apply` 를 누르게 된다.

원인: `src/asgard/commands/memory/evolution.py:79` 가 `merge`/`archive`/`insight` 만 분기하고
나머지를 `else` 로 떨어뜨린다. 자율 실행 화면(`:37`)도 같다.

실물 재현: `asgard memory norn` 이 낸 "contradiction" 4줄 중 3쌍이 다른 회차 `--json` 에서
`"op": "link"` 로 나온다.

부작용: 감사 표면이 오염된다. 이 화면만 보고 "모순 4건"이라고 세면 틀린다.

---

## 3. 중간

**M1 — 라틴 문자 질의가 2차 적합성 게이트를 통째로 우회한다.** 같은 뱅크, 같은 순간에 무의미
질의 둘이 반대 답을 낸다: `"뷁뷁 쀍쀍 냐냐냐"` → 0건, `"qqqq wwww eeee"` → 1건 주입.
`memory_context.py:179-180` 이 질의와 본문의 주 문자체계가 다르면 무조건 통과시킨다. Hindsight
0.8.x 에 relevance score 가 없어 어휘 겹침이 유일한 문턱인데, 교차언어에는 그 문턱이 없다.
본문이 한국어인 이 저장소에서 영어 질의는 항상 무언가를 받아 온다. H6 과 방향이 반대인 같은 축이다.

**M2 — `project-reflect` 의 로컬 대체 레인이 안 뜬다.** 한국어·영어 둘 다
`"I don't have information."` + `based_on.memories: []`. 로컬 레인은 근거를 찾는다
(`canonical_evidence` 직접 호출 → 1건). 원인은 `project_memory/reflect.py:180-182` 의 대체 조건이
`text` 가 **빈 문자열**일 때뿐이라, "모른다"는 답이 좋은 답으로 계산되는 것이다. 모델이 모른다고
말한 것과 서버가 죽은 것만 구분하고, "모른다"와 "정본에 답이 있다"는 구분하지 않는다.

**M3 — 대기 중인 2차 제안을 볼 동사가 없다.** `project-retain` 이 approval_id 를 한 번 찍고
끝난다. `asgard memory proposals` 는 1차 위키만 읽고, `project-proposals` 류 동사가 없다.
저장 위치는 `~/.asgard/state/project-memory-pending-<key>.json`, TTL 3600초
(`memory_bridge/config.py:25`). 실측으로 다른 프로젝트 파일 하나에 만료된 제안 5건이 그대로
쌓여 있다 — 아무도 못 보고 아무도 못 지운다.

**M4 — 개인 `memory_propose` 에 최소 검증이 없다.** 같은 서버에서 MCP
`memory_retain {"content":"too short"}` 는 "record is not self-contained"로 거부되는데
`memory_propose {"text":"short"}` 는 5자짜리 페이지를 개인 정본에 남겼다(`asgard memory show short`
로 확인). `memory/propose.py:228-243` 에 2차의 `validate_record`(`records.py:139`, 20자 하한)에
해당하는 검사가 없고, 개인 autosave 가 on 이라 사람의 검토도 없다.

**M5 — 개인 메모리 sync 원격이 존재하지 않는 임시 시험 경로다.** `asgard memory sync --status` 가
`…/asgard-custom/../.tmp-mem-test/bare` 를 가리키는데
`git -C ~/.asgard/memory remote show origin` 은 `does not appear to be a git repository` 다.
커밋 0건, tracked 0/59. 오딘은 sync 를 켜 놨다고 볼 텐데 한 번도 동기화되지 않았고, 성공하는
날에는 개인 위키 전체가 프로젝트 트리 옆 임시 폴더로 나간다. 실전송은 하지 않았다.
이름으로 보아 어느 시험이 남긴 설정이라는 것이 가설이고, 출처는 확인하지 못했다.

**M6 — 콜드 상태의 회수가 내부 상한을 넘긴다.** 상한은 이 저장소에서 5초가 아니라 **10초**다
(`INJECT_TIMEOUT_DEFAULT`, `memory_context.py:27`, 천장 30초, 적용 `:508`·`:533`). 훅 바깥 상한은
20초(`memory-activate.py:307`). 웜 중앙값은 프로젝트 레인 0.505초·훅 end-to-end 0.662초로
여유가 크지만, 콜드 배치에서 11.818초가 나왔고 무태그 회수를 7연발하면 12.5~14.5초까지 벌어진다.
넘어가면 예외를 `recall_candidates`(`:894`)가 fail-open 으로 삼켜 **프로젝트 레인만 조용히 빠진다**
— H2 와 겹쳐 흔적이 안 남는다. 지금 실사용이 0.6초대인 것은 필터 때문에 후보가 1건뿐이라서다.
§1 을 고쳐 후보가 늘면 이 축이 살아난다.

**M7 — `norn --json` 이 모델 출력 파싱 실패로 exit 2, 재시도 없음.** 4회 중 1회.
`✘ Expecting ',' delimiter: line 1 column 1763` 한 줄만 나오고 norn 이라는 말도 LLM 이라는 말도
없다. `norn/plan.py:103` 의 `json.loads` 가 감싸이지 않아 원시 `JSONDecodeError` 가 CLI 가드까지
올라간다. 같은 함수의 다른 실패는 `ValueError("norn: …")` 로 이름을 달고 나간다. 절단 가설:
`plan.py:116` 이 `max_tokens=3000` 으로 부르고, 응답이 상한에서 잘리면 `raw.rfind("}")` 가 중첩
객체의 닫는 괄호를 집는다. **원시 응답을 안 남겨 확인하지 못했다 — 가설이다.**

**M8 — pattern 의 deductive 관측이 grounding 문턱을 통과하지 않는다.** 세 실행 모두에서
`GROUNDING_FLOOR`(0.34) 아래인 deductive 관측이 승격 대기에 올랐다. 최악은 **grounding 0.0 에
confidence "medium"** 이었다("오딘은 배경 설명 없이 한두 문장짜리 한국어 명령형으로 지시한다",
인용 턴 4개, 내용어 일치 0%). `memory/pattern.py:315-321` 의 문턱 비교가 `if kind == "explicit"`
안에만 있고 `else` 는 점수를 계산만 하고 버린다. 수동 `--apply` 경로(`:391-402`)는 kind 별 게이트
없이 전부 페이지로 쓴다 — deductive 는 `kind=insight` 페이지가 되고 peer card 재료가 된다.
자율 경로에는 바닥이 있고 수동 경로에는 없다.

**M9 — 노른 리포트의 `link` 줄에 양쪽 slug 가 비어 있다.** 디스크의 리포트 4장 전부가
`- (제안) link:  →  ` 를 담고 있고, 20260803 리포트는 그 줄이 전부다. `norn/apply.py:229` 가
`op.get("slug") or f"{op.get('src','')} → {op.get('dst','')}"` 인데 `link` op 의 키는 `a`/`b` 다.
어떤 두 페이지를 이으려 했는지 기록이 안 남아 지난 패스를 되짚을 수 없다. H7 과 같은 실패 기제다.

**M10 — 고아 뱅크와 꺼진 감사 로그.** 이 Postgres 를 13개 뱅크가 공유한다(최대는 `vn_onm_yun`
2,046 units). 그중 `asgard-custom-bc3bb244`(08-19 18:34)는 binding 문서 한 장뿐이고 그 안의
uid·binding_id 가 이 저장소 것과 다르다 — 재초기화가 판 흔적이고 이후 아무것도 안 쓰였다.
그리고 이 배포는 `audit_log: false` 라 `audit_log` 테이블이 0행이다. 여러 단위가 같은 뱅크에
동시에 쓰면 사후 귀속이 불가능하다.

---

## 4. 낮음

- **뱅크가 07-28 이후 3주간 정지해 있었다.** `last_consolidated_at` = 2026-07-28T13:23:30Z,
  mental_models 3개 전부 `updated_at: null`. 오늘 감사 적재 전까지 신규 지식 0건.
- **소유권이 어긋나면 recall 이 조용히 0을 낸다.** cfg 변조 5케이스 실측(뱅크 미변경): uid 불일치·
  binding 불일치·둘 중 하나 누락 넷 다 `kept=0`. 술어(`memory_context.py:288-295`)는 fail-closed 라
  옳다. 다만 사용자에게 나가는 말은 `주입 자격을 갖춘 기억 없음` 하나뿐이고 안내는
  status/confidence 만 짚는다 — 소유권을 원인으로 지목하는 문장이 없다.
- **미리보기 plan_id 가 `--tags-only` 를 구분하지 않는다.** 전체 재적재와 `--tags-only` 가 같은
  plan_id 를 낸다. `rehydration_plan`(`canonical.py:275-295`)이 `tags_only` 를 안 받아, 미리 본 것과
  다른 연산을 승인할 수 있다.
- **artifact 문에 부르는 손이 없다.** `sync_artifacts` 호출자는 CLI 뿐이고 훅도 자동 패스도
  doctor 행도 없다. `automation.wake()`(`automation.py:91`)는 `project-learn` 만 7일 주기로 띄운다.
  결과: 매니페스트 부재, 스캔은 243건을 고르는데 뱅크에는 artifact 0건.
- **스캔이 생성물·보관 폴더를 고른다.** `_SKIP_DIRS`(`scan.py:17`)에 `gen`·`archive` 가 없다.
  full 243건 중 2건이 `studio-shell/src-tauri/gen/schemas/`(그 중 하나가 H4 의 최대 파일),
  `--inventory` 5,486건 중 681건이 `archive/` 아래다.
- **문서 이름으로 검색되지 않는다.** FTS 에서 `name` 이 UNINDEXED(`documents.py:242`), 스캔
  스트림도 heading+body 만 본다(`:393`). 본문에 없고 파일명에만 있는 낱말은 어느 스트림에도 안 걸린다.
- **같은 문서의 옛 개정판이 주입 슬롯을 먹는다.** `search` 가 `name`/`document_id` 로 묶지 않아
  (`documents.py:414`) 두 개정판의 같은 절이 나란히 올라온다. 이 저장소에서 `rows(k=2)` 의 두 줄이
  바이트 단위로 동일하다.
- **문서 레인의 고장이 "적중 없음"과 구분되지 않는다.** `sync()` 는 모든 예외에 0, `search()` 는 []
  (`documents.py:327`, `:384`). 관측 표면이 H5 처럼 없어 침묵이 드러나는 자리도 없다.
- **`remove`·`merge` 가 파생 표의 행을 남긴다.** `memory/pages.py:394-399` 가 `fts`·`vec` 만 지우고
  `clean`·`vec_passage` 는 안 지운다. `reindex` 한 번이면 정리된다. 축적성 누수이지 오답은 아니다.
- **없는 페이지 오류 코드가 명령마다 다르다.** `show`·`remove` 는 `not_found` + remedy + slug 인데
  `merge` 만 `invalid_input` 이고 둘 중 어느 쪽이 없는지도 안 알려준다.
- **OKF 번들 안에 형식 표시가 없다.** `--json` 은 `"format": "okf-0.1"` 이라 말하는데 번들에는
  `index.md` 와 `pages/` 뿐이고 매니페스트가 없다(`memory/okf.py:89-97`). 받는 쪽이 번들만 보고
  형식을 가릴 수 없다.
- **`graph path` 가 "같은 노드"와 "길 없음"에 같은 `hops: 0` 을 준다.** `path` 배열 길이로만 갈린다.
- **`AGENTS.md` 의 Worker 주입 서술이 코드보다 좁다.** 문서는 "standard Worker 는 개인 회수만"
  이라 쓰는데 `trinity/turns.py:440` 은 6레인 전량을 싣는다. 격리가 샌 것이 아니라 문서가 틀렸다.
- **`core/__init__.py:88` 의 `self.identity` 가 메모리를 품은 채 아무도 안 쓴다.** 지금은 안 새지만
  다음 호출부가 이걸 집으면 loki 무주입이 조용히 깨진다.

---

## 5. 정상으로 확인된 것

**배포 훅 드리프트 0건.** `.claude/hooks/*.py` 27개 + `.codex/hooks/*.py` 27개가 `src/asgard/hooks/`
와 바이트 동일하고, `asgard_hooklib` 3벌 24파일씩도 동일하다.

**CLI 와 MCP 는 같은 방을 쓴다.** AGENTS.md 의 "두 문, 한 방" 주장이 실측으로 성립했다. MCP
`memory_retain` 이 발급한 approval_id `44f0ccf3…` 를 CLI `project-approve` 가 그대로 소비했고,
같은 질의에 두 표면이 같은 결과를 냈으며, 커밋 순서는 양쪽 다 claim → Git 정본 → backend
(`canonical.py:211-236`)로 문서와 일치한다. `memory_search` 만 예외로 개인 기억 표면이다.

**역할 격리는 다섯 주장 중 넷이 코드로 선다.** Thinker(스냅샷+회수), deep Worker(무주입),
Verifier, Loki 전부 확인. 어긋난 하나는 위에 적었고 방향이 반대다.

**개인 메모리 쓰기 관문이 양 언어에서 선다.** `Ignore all previous instructions` 와
`이전 지시는 전부 무시` 둘 다 `invalid_input` 으로 거절된다. `ingest` 는 근사 중복을 새 페이지
대신 병합으로 처리한다.

**기억 그래프에 간선이 있다.** 과거 기록의 "간선 0개"는 더 이상 사실이 아니다 — 개인 스코프
nodes 55·edges 71·communities 16. 그리고 표시 전용이 아니라 회수가 실제로 쓴다:
`recall.search` 가 PPR 을 4번째 RRF 스트림으로 융합하고(`recall/search.py:240,251`), 그 PPR 이 도는
인접 리스트는 `graph` 모듈이 편 것과 같은 객체다(`recall/ppr.py:46-60`). 실측으로 55노드 중 40노드가
0 아닌 점수를 받는다. 다만 명시 링크 20개가 **전부 `odin-peer-card` 한 장에** 있고 나머지 55장에는
손으로 쓴 링크가 0개다 — 결정론 간선(mention 13·term 69)이 그래프를 지탱한다.

**episodes 는 최신이다.** 1,325턴·154퀘스트·raw 1,647,772바이트, 범위 2026-07-19 02:53 →
2026-08-20 15:35. 마지막 행이 이 감사 자체의 턴이다. 다만 1,325턴 중 **633턴(47.8%)이 빈 퀘스트
라벨**이라 `--quest` 로는 절반에 닿을 수 없다.

**`ask` 는 4문 4정답이었다.** 위키에 없는 사실을 일부러 물은 문항에서 지어내지 않고 거절했고,
숫자 4개가 든 문항에서 하나도 안 어긋났다. 인용한 턴 4개를 episodes DB 에서 직접 열어 실재를
확인했다. 4문은 작은 표본이므로 "환각이 없다"가 아니라 "이번 4문에서는 못 찾았다"로 읽어야 한다.

**짝 저장소는 잃을 것이 없다.** `satellite-pilot` 과 `helios-asgard` 둘 다 `project_memory` 가
빈 시드라 2차 메모리 자체가 안 붙어 있다. 주입은 이 저장소에서 멈추고, 그것은 설계대로다.

**모순 장부는 비어 있고, 그것은 배선 때문이다.** 열린 모순 0건·접어 둔 것 포함 0건.
모순은 `apply_norn` 안에서만 접수되고(`norn/apply.py:178`) dry-run 은 아무것도 적지 않는다.
`log.md` 221줄에 `norn:` 항목이 0건이다 — 지금까지 어떤 norn op 도 적용된 적이 없고,
`~/.asgard/memory/archive/` 디렉터리도 존재하지 않는다. 따라서 `norn-restore` 는 지금 어떤
slug 로도 실패한다. `lint` 가 광고하는 "open contradictions" 칸은 이 위키에서 한 번도 값을 가진
적이 없다.

**lint 는 1건만 낸다 — `index-over-budget: index.md#user — 2496/1400 chars`.** 12종 판정 중
나머지 11종이 0건이다. 다만 그중 `decay-candidate` 0건은 건강이 아니라 도달 불가다: 가장 오래된
페이지가 25일인데 문턱이 90일이고(`pages.py:44`), usage 행이 있는 55장 전부 `uses > 0` 이라 두
번째 조건도 막는다. 이 레인은 아직 한 번도 켜질 수 없었다. `vec-stale` 0건은 진짜 초록이다
(56/56 신선, orphan 0, model_mismatch False).

초과한 `user` 칸을 채운 것이 누구인지도 셌다 — `kind: user` 37장 중 **35장**이 `pattern: explicit`
을 달고 있다. 초과분은 pattern 레인이 승격한 관측이다.

---

## 6. 메모리 밖에서 나온 것 — 하네스와 장부

점검 대상은 아니었지만 이번 작업을 돌리는 과정에서 재현이 확실하게 나온 것들이다.

### C1 — 2차 메모리의 Git 정본이 판정이 볼 수 없는 자리에 있다

`.asgard/memory/records/` 는 gitignore 되지 않는다 — `git status --porcelain --ignored=matching`
이 `??` 로 내고(`!!` 가 무시 표시), `.asgard/.gitignore:8` 의 `!memory/records/**` 부정 규칙이
제대로 선다.

막는 것은 하네스다. `.claude/hooks/asgard_hooklib/tree.py:61` 이 퀘스트 시작 트리를 뜰 때 색인에서
`.asgard` 를 통째로 뺀다:

```
git rm --cached -r -q --ignore-unmatch -- .asgard :(exclude).asgard/map
```

지도만 남고 나머지는 판정의 물리 diff 에서 사라진다. 그래서 record 를 쓴 퀘스트는 그 사실에 대한
증거를 못 남긴다. 같은 경로를 `readonly-guard` 가 Bash 에서 — 읽기까지 포함해 — 막는다.
자동으로 커밋하는 손도 없다.

**§1 의 삭제가 복구되지 않은 구조적 이유가 이것이다.** 팀이 나눠 갖도록 설계된 정본이, 정본을
쓰는 일이 증거로 남지 않는 자리에 있다.

### C2 — 판정 게이트가 "진행 중"을 표현하지 못한다

퀘스트를 열고 비동기 서브에이전트를 배차한 뒤 턴을 끝내면 `verifier-gate` 가 `[gate:no-verdict]`
로 막는다. 같은 시점에 `quest-log.py next` 는 `next_role: WORKER` 를 주고 `contracts_unmet` 에 아직
안 쓴 산출물을 들고 있다. 게이트와 전이 함수가 어긋난다. 비동기 결과는 턴이 끝난 뒤에 오므로
유닛이 도는 동안의 모든 턴이 걸리고, 게이트가 보기엔 버려진 퀘스트와 결과를 기다리는 퀘스트가
같다. 이번 세션에서 세 번 막혔다.

우회로는 있다(이웃 세션이 같은 자리를 밟고 찾았다): 배차한 뒤 턴을 끝내지 않고, 판정 이벤트가
로그에 나타날 때까지 도는 조건 대기 루프로 전경에서 붙든다. 판정이 턴 안에서 떨어지므로 게이트가
통과한다. 다만 이것은 우회이지 수리가 아니다 — 근본은 게이트가 배차 중인 퀘스트를 구분 못 하는 것이다.

### C3 — 공유 트리에서 판정 해시가 남의 손에 움직인다

이웃 세션의 퀘스트 `tutor-alter-1on1-260820c` 는 판정자가 PASS 를 냈고 `contracts_unmet` 도
비었는데 닫히지 않았다. `completion_decision`(`transition.py:54`)이 `pass_hash_match` 를 보는데
판정 시점 해시 `54658e05` 가 그 뒤 `192a0728` 로 움직였기 때문이다. 움직인 것은 이 감사가 쓴
`docs/MEMORY-AUDIT-260820.md` 이고, 그 문서에 tutor 언급은 0건이다.

게이트는 **누가** 움직였는지도 **무엇을** 움직였는지도 안 가린다. 세션 둘이 서로 창을 양보해서
우회할 문제가 아니라 변경을 귀속시키지 못하는 문제다.

이번에 두 세션이 실제로 창을 맞춰 봤고 **닫혔다** — 이웃 세션의 `tutor-alter-1on1-260820c` 가
turn 8 에서 PASS, `forced: false` 로 닫혔다. 겹친 두 파일(`commands/setup.py`,
`tests/test_sync.py`)에서 양쪽 케이스가 다 서는 것까지 확인됐다.

**그러나 닫힌 것은 조율이지 게이트가 아니다.** 성립 조건이 넷이었고, 넷 중 하나만 빠져도 안
닫혔다.

1. 이웃이 정확히 **하나**였다. 셋이었으면 각자의 조용한 구간이 겹쳐야 하는데 그 교집합은 세션
   수가 늘수록 빠르게 0으로 간다.
2. 그 이웃이 자기 쓰기를 **멈출 수 있었다**.
3. 무엇을 건드렸는지 **목록으로 줄 수 있었다** — 그래서 재판정을 델타 축으로 좁혀 창을 짧게 썼다.
4. 자기 판정을 상대 뒤로 **미뤄 줬다**.

반대 방향도 성립하지 않았다. 이웃이 "thor 를 멈춰 달라"고 요청했다면 오딘이 방금 시킨 일이
남의 장부 정리 때문에 섰을 것이다. 이웃은 그것을 알고 기다리는 쪽을 골랐다.

그리고 이번 재판정은 요식이 아니었다. 이 감사 중에 `src/asgard/memory_bridge/config.py` 와
`src/asgard/commands/setup.py` 가 움직였고, 그것은 이웃의 PASS 를 형식만이 아니라 **내용으로도**
낡게 만든다. 게이트가 틀린 것은 재판정을 요구한다는 사실이 아니라, **재판정이 필요한 변경과
무관한 변경을 구분하지 못한다**는 점이다. 게이트가 변경을 귀속시키면 위 조건 넷이 전부 필요 없다.

한 가지 덧붙인다: 해시가 낡는 것은 형식만의 문제가 아니다. 이 감사 중에 `src/asgard/settings.py`
가 움직였고, 그것은 이웃의 PASS 를 **내용으로도** 낡게 만든다. 그러니 재판정은 요식이 아니라
옳은 순서다. 게이트가 틀린 것은 재판정을 요구한다는 사실이 아니라, 재판정이 필요한 변경과
무관한 변경을 구분하지 못한다는 점이다.

### C4 — `siege plan` 이 그린 그래프와 호스트 배차가 서로 다른 작업으로 앉는다

`asgard siege plan` 으로 work 작업 6개를 만들고 Agent 도구로 배차하면 장부에 작업이 16개가 된다.
계획이 만든 6개는 `attempts: 0` 인 채 `ready` 로 남고, 배차 훅이 에이전트 설명을 제목 삼아 새 작업
6개를 따로 열어 `dispatched` 로 올린다. 같은 일이 두 번 앉고, 계획이 붙인 판정 작업은 의존이
영영 안 끝나 `pending` 에서 못 나온다. 유닛 넷이 각자 이 어긋남을 보고했다.

원인 가설: 스킬은 호스트에서 "배차 훅이 spine 을 쓰니 손대지 마라"고 하는데, 훅이 여는 작업을 미리
계획된 작업에 묶는 인자가 없다.

### C5 — `subagent-gate` 가 요구하는 문을 WORKER 역할로는 열 수 없다

한 메시지에서 `asgard-worker` 둘을 unit 표시 없이 배차하면 두 번째가 거부되고, 게이트는 티켓
선언을 요구한다. 그런데 티켓 선언은 thinker 역할 전용이라 WORKER 가 배정된 상태에서는 그 문을
열 수 없다. 이번에는 U4 를 `asgard-thor` 로 다시 배차해 통과시켰다 — 레인이 데이터 저장소 계측이라
thor 표면 안에 들어가고 사다리에서도 아래 방향이지만, 역할을 게이트 회피용으로 고른 것은 사실이다.
결과적으로 게이트가 막는 것은 `asgard-worker` 라는 이름이지 병렬 워커가 아니다.

### C6 — `readonly-guard` 가 연산이 아니라 글자를 본다

명령문에 `.asgard/` 라는 글자가 있으면 Bash 호출 전체가 막힌다. `ls` 도, `git check-ignore` 도
막힌다. 이 세션에서 세 번, 이웃 세션에서 한 번 부딪혔다. `D=$(printf '.%s/memory' asgard)` 로
리터럴을 쪼개면 통과한다. 우회가 이렇게 쉬우면 가드가 실제로 막는 것은 무심코 치는 사람이지
의도한 쓰기가 아니다.

---

## 7. 남긴 잔여물 — 아무것도 지우지 않았다

| 무엇 | 어디 | 지우는 법 |
| --- | --- | --- |
| 2차 record 2건 (`audit.tier2-roundtrip-260820`, `audit.tier2-mcp-260820`) | `.asgard/memory/records/` 아래 두 파일 (untracked) + Hindsight 뱅크 | 파일 삭제 후 뱅크에서도 해당 document 제거. 남길 거면 `git add` 가 필요하다 |
| 1차 페이지 2건 (`audit-260820-u0-mcp-propose-probe`, `short`) | 개인 위키 | `asgard memory remove <slug>` — `short` 는 M4 의 증거이므로 그 결함을 먼저 처리하는 편이 낫다 |
| 백업 아카이브 `20260820T063428Z-audit260820.tar.gz` | `~/.asgard/memory/backups/` | 그 파일 하나만 삭제 (`backup prune` 은 다른 백업도 건드린다) |
| OKF 번들 사본 (개인 페이지 55장) | 세션 스크래치패드 `audit/okf/` | 저장소 밖이라 그냥 두어도 된다 |
| 시험 md·격리 루트·측정 JSON | 세션 스크래치패드 `audit/` | 저장소 밖 |

`log.md` 의 감사 흔적은 기록층이라 그대로 두기를 권한다. 공유 뱅크에는 위 record 2건 외에
아무것도 쓰지 않았고, 컨테이너·설정·다른 뱅크는 건드리지 않았다.

---

## 8. 이 감사가 못 잰 것

- **`connect` 계열은 읽기만 했다.** 재연결과 `--recover-binding` 은 실행하지 않았다.
- **`project-sync --yes`, `project-evolve --apply`, `norn --apply`, `pattern --apply`,
  `backup restore/prune`, `memory sync` 실전송은 전부 안 돌렸다.** 공유 뱅크나 오딘의 정본에
  쓰는 연산이기 때문이다. H3 과 H4 의 숫자는 전송 **예정량**의 실측이지 서버 영향의 관측이 아니다.
- **08-06 삭제와 08-13 마지막 주입 사이 7일**은 가설만 있다(§1).
- **M7 의 절단 원인**은 원시 응답을 안 남겨 확인하지 못했다.
- **M5 의 `.tmp-mem-test` 출처**를 확인하지 못했다.
- **`ask` 정확도는 4문 표본**이다.
- **`norn` 이 회차마다 다른 op 집합을 낸 것**(4회 4종)은 위키가 감사 중 커진 탓일 수 있어 전부를
  모델 변동으로 돌릴 수 없다.
- **뱅크 쪽 문서 삭제·수정 API** 는 건드리지 않았다.

---

## 9. 이 퀘스트가 실제로 바꾼 것 — `project_memory.enabled`

감사 도중 오딘이 얹은 별개 작업이다. 진단이 아니라 코드 변경이므로 따로 적는다.

**요청**: enable 손잡이를 초기 설정에 명시적으로 `false` 로 적어, 새 프로젝트가 꺼진 채 시작하고
사람이 의도적으로 켜게 한다. 오딘이 범위를 좁게 골랐다 — **시드에만 적고, 런타임 부재 판정은
안 건드린다.** 부재를 꺼짐으로 뒤집으면 키가 없는 기존 저장소 전부에서 2차 메모리가 즉시 꺼지고,
그것은 이 문서 §1 이 기록한 실패 모양 그대로다.

**바뀐 자리 다섯**

- `src/asgard/templates/trinity.py:41` — `"enabled": False` 가 `project_memory` 시드의 첫 키가 됐다.
  `_comment`(`:43-50`)를 다시 썼다: 연결하기 전에는 꺼져 있다는 것, `asgard memory connect` 가
  섹션을 다시 쓰며 켠다는 것, 연결된 섹션에 `enabled: false` 를 적으면 다시 꺼진다는 것.
- `src/asgard/commands/setup.py:143·152` — `_memory_configured()` 와 `_memory_with_toggle()` 신설.
- `src/asgard/memory_bridge/config.py:247` — `_config_at` 술어 한 줄 (아래).
- `tests/test_sync.py:367·375·386·395` — 시드가 키를 갖는다 / 옛 시드가 한 번의 sync 로 얻고 두 번째
  sync 가 바이트 동일 / 설정된 섹션은 손 안 탄다 / 손으로 쓴 `enabled: true` 가 살아남는다.
- `tests/test_memory_bridge.py:472·487` — `enabled` 만 든 섹션은 탐색을 계속한다 / 연결된 섹션의
  `enabled: false` 는 여전히 멈춘다.

**설정된 섹션을 안 건드리는 술어**: `_memory_configured(section)` = `_` 로 시작하지 않고 `enabled`
도 아닌 키가 하나라도 있는가. `engine`/`endpoint`/`project_id` 를 든 섹션(이 저장소의 모양)은
"설정됨"이라 그대로 반환된다 — `sync` 가 키를 안 붙이고 안 뒤집는다. 두 번째 가드
`"enabled" in section` 은 이미 시드된 저장소와 사람이 손으로 `true` 를 쓴 저장소의 값을 지킨다.

**딸려 온 의미 하나 — 실측으로 잡았다.** 시드에 진짜 키가 하나 생기니
`project_memory_section(raw)` 이 더 이상 `None` 이 아니게 되면서, `_config_at` 이 빈 시드를
"선언 없음(위로 올라감)"에서 "꺼짐(여기서 멈춤)"으로 읽기 시작했다. 연결된 부모 아래 미설정
자식을 세워 재 보니 `bank=parent-bank` 가 `None` 으로 죽었다. 26-08-11 에 기록된 모노레포·짝
저장소 형상 그대로이고, 지금 시드 상태인 `../satellite-pilot` 과 `~/develop/work_space/vn_onm/helios-asgard`
가 그대로 맞았을 자리다.

수리는 `config.py:247` — **실제 키가 `enabled` 하나뿐인 섹션은 선언이 아니다.** 스캐폴드가 그
모양을 모든 새 저장소에 적으므로 그것은 결정이 아니라 손 안 댄 시드다. 끄겠다는 결정은 연결 키를
함께 든 섹션에 적히고, `project_memory_disabled` 가 그것을 그대로 잡는다.

**명시적 결과 — 이 줄이 이 변경에서 가장 중요하다**: 연결 키 없이 손으로 쓴 `{"enabled": false}`
는 **이제 부모 뱅크를 막지 못한다.** 그 모양이 모든 저장소에 들어가게 되어 "막는다"는 뜻을 가질
수 없어졌기 때문이다. 그 모양을 실제로 차단 용도로 쓰고 있던 저장소가 어딘가 있으면 조용히
뚫린다. 막는 것은 연결된 섹션에서만 된다.

`write_config` 가 섹션을 통째로 갈아 쓰므로 연결하면 시드된 `false` 는 사라진다 — 연결이 곧
켜는 행위다. 연결 시점에 `"enabled": true` 를 명시적으로 적는 것은 요청 범위 밖이라 하지 않았다.

**검증**: `uv run python -m pytest` → exit 0, `6088 passed, 14 skipped, 2757 subtests passed in
219.85s`. `asgard craft` exit 0, `asgard thor gate` exit 0. 임시 디렉터리에서 `run_setup` 두 번
돌려 멱등 확인. 기존 시험 `test_unconnected_seed_does_not_hide_the_parent` 가 실제 시드에서
픽스처를 만들므로 `config.py` 수리 없이는 실패한다 — 위 딸림 의미의 회귀 핀이다.

---

## 10. 오딘이 결정할 것

**하나 — 정본 4건을 되살릴 것인가.** `git show 4669fe7a^:<경로>` 로 꺼내
`.asgard/memory/records/` 에 되돌린 뒤 전체 rehydrate 다. 이것만 해도 §1 의 두 겹 중 한 겹이
풀린다. 나머지 한 겹(태그 축)은 rehydrate 가 붙여 준다.

**둘 — H3(기본 `project-sync` 의 묘비)을 언제 막을 것인가.** 지금은 매니페스트가 없어 가려져
있다. 누군가 `--all --yes` 를 한 번 돌려 매니페스트를 만들면 그다음 기본 sync 가 위험해진다.

**셋 — 감사 잔여물을 지울 것인가** (§7).

**넷 — C1 을 어떻게 다룰 것인가.** 2차 메모리의 Git 정본이 판정의 물리 diff 밖에 있는 것이
설계 의도라면, record 를 쓰는 일에 별도의 증거 경로가 필요하다. 의도가 아니라면 `tree.py:61` 의
제외 목록에 `memory/records` 를 지도처럼 예외로 넣는 것이 한 줄이다.

그 한 줄의 부작용을 같이 본다: 예외로 넣으면 **모든 퀘스트가 record 를 판정 대상으로 끌어들인다.**
메모리와 무관한 작업이 도는 동안 자동 저장이 record 하나를 쓰면 그 퀘스트의 diff 가 움직이고,
판정자는 자기 작업과 상관없는 파일을 읽게 된다. 지금 `.asgard/map/*.md` 가 이미 그 성질을 갖고
있으므로 전례는 있다. 증거를 얻는 대신 판정 표면이 넓어지는 교환이고, 어느 쪽이 나은지는 오딘이
정한다.

수리는 이 퀘스트 범위 밖으로 두었다 — 진단 전수 점검으로 열었고, 결함마다 재현 명령과 원인
위치를 남기는 것까지가 계약이었다.
