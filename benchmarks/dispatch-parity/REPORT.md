# 병렬 배차 실측 — worker 가 딜리버리 전문가를 부르는 길 (2026-08-12)

물음: 화면 작업은 프레이야, 백엔드는 토르 하는 식으로 **워커가 전문가를 불러 병렬로 조율하는
것이 실제로 도는가**. 배선을 grep 으로 확인하면 "표가 그렇게 적혀 있다"까지밖에 못 말한다.
여기 있는 것은 배포본 훅을 실제로 실행하고, 실제 서브에이전트를 띄워 장부에 남은 시각을 읽은
결과다.

## 결과

| 축 | 재는 것 | 결과 |
| --- | --- | --- |
| 위임 경계 | 배포본 훅의 caller×target 판정 165조합 | 전부 표와 일치 |
| 실팬아웃 | 워커 한 명이 프레이야·토르를 한 메시지로 호출 | 둘 다 뜸, 겹침 102.2초 |
| 부른 쪽 기록 | 배차 Task 의 `parent_id` | 둘 다 워커의 Task |
| 모드 B | 단위 티켓 워커 여럿 | 이 형상에서는 열리지 않음 (아래) |

## 돌리는 법

    uv run --no-project python benchmarks/dispatch-parity/gate_probe.py      # 위임 표 전수 판정
    uv run --no-project python benchmarks/dispatch-parity/overlap_probe.py   # 장부에서 겹침 읽기
    uv run --no-project python benchmarks/dispatch-parity/collect.py         # 배차 레코드 JSON
    open benchmarks/dispatch-parity/timeline.html                            # 배차 타임라인 뷰어

`gate_probe.py` 는 퀘스트 포인터가 없는 세션 id 로 훅을 부른다. 훅이 경계 검사를 퀘스트 조회보다
먼저 하므로 판정은 그대로 나오고 배차 장부에는 아무것도 안 남는다.

## 위임 경계 — 165조합

표(`AGENT_TARGETS`) 안 caller 11 + 표 밖 caller 2(메인 조율자, `Explore`) × target 11, 그리고
전이 함수 전용 자리(thinker·verifier) 를 손으로 부르는 11조합. 판정은 서브프로세스 종료 코드로만
읽는다 — allow 0, deny 2.

배포본 `.claude/hooks/subagent-gate.py` 와 패키지 `src/asgard/hooks/subagent_gate.py` 의 표가
같은지, 그리고 두 불변식(층위 단조·읽기 봉인)을 어긴 자리가 있는지도 같은 시험이 본다.

## 실팬아웃 — 장부가 적은 것

퀘스트 `parallel-dispatch-check-260812`, run `run_cad075ffb0cc`:

```
TASK task_90f0d909b32f  parent=-                 agent=asgard-worker
TASK task_06b78e15a15a  parent=task_90f0d909b32f agent=asgard-thor     114.6s
TASK task_4a65bc7599ce  parent=task_90f0d909b32f agent=asgard-freyja  721.4s
```

토르는 `collect.py`, 프레이야는 `timeline.html` 을 썼다. 두 배차의 생존 구간이 102.2초 겹쳤다 —
한 메시지에서 함께 떴다는 주장의 물증은 이 겹침뿐이고, 순차로 떴다면 0 이 된다.

부모 링크가 붙는 경로: 훅이 PreToolUse 에서 `agent_type` 으로 부른 쪽을 읽어 `siege note
--caller` 로 넘기고, `roster` 가 그 이름으로 도는 Task 를 찾아 `parent_id` 에 적는다. 호스트가
`agent_type` 을 안 주면 이 칸이 비고, 그러면 누가 불렀는지가 장부에서 통째로 사라진다.

## 모드 B — 이 형상에서는 열리지 않는다

조율자가 워커 **여럿**을 동시에 돌리는 길은 단위 티켓을 요구하고, 티켓 선언은 thinker 역할
전용이다 (`quest_log._append_rejection`: `ticket_status != "todo" or role != "thinker"` 면 거절).
워커가 배정된 퀘스트에서 손으로 단위를 적으면 이 문구로 끊긴다:

    ticket runtime transitions require ticket-claim/heartbeat/finish/recover;
    raw append only accepts thinker todo definitions

그래서 모드 B 로 들어가는 문은 둘이다 — 퀘스트를 `--parallel-requested` 로 열어 첫 역할을
THINKER 로 받거나, 구조적 FAIL 로 Thinker 가 재계획하거나. 도중에 "병렬로 쪼개자"고 마음을
바꾸는 길은 없다(선언한 위험 플래그는 이후 호출에서 동일해야 한다).

## 이 벤치가 못 재는 것

- 겹침은 **배차 두 건의 생존 구간**이지 두 모델이 동시에 토큰을 쓴 시간이 아니다.
- 판정은 `.claude/hooks/subagent-gate.py` 에 대한 것이다. 이 저장소에는 Cursor·Codex 훅이 깔려
  있지 않아 돌릴 사본이 없었다(`.claude` 사본은 패키지본과 md5 동일).
- 모드 B 의 티켓 수명(claim → heartbeat → finish)은 실행하지 않았다. 위 문단은 그 문이 어디
  있는지까지이고, 문 너머는 안 재봤다.
