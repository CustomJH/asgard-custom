# 훅 바깥 CPU·디스크 표면 — 실측 (2026-08-14)

측정 도구: `python3 benchmarks/cpu-profile/resident.py --json` (읽기 전용, 수치는 이 실행 시점의 스냅샷).
저장소: `/Users/yun/develop/personal_space/project/asgard-custom`.

## 상주 프로세스

| 프로세스 | PID | 상주 시간 | 누적 CPU | 시간당 CPU초 | RSS |
|---|---|---|---|---|---|
| `node .../asgard-serve.mjs` (포트 4590) | 44444 | 9일 22.2시간 | 457.09초 | 1.92초 | 46.7MB |
| `asgard memory mcp` uv 래퍼 × 11 세션 | 11개 pid | 6.9분~11.2시간 | 각 0.02~0.03초 | 각 0.003~0.17초 | 합 336.7MB |
| `asgard memory mcp` python 자식 × 11 세션 | 11개 pid | 6.9분~11.2시간 | 각 0.12~0.14초 | 각 0.003~1.20초 | 합 441.5MB |

**PID 44444 는 이 저장소 소속이 아니다.** `lsof -p 44444` 의 `cwd` 는
`/Users/yun/develop/work_space/vn_onm/helios-application` 이고, `.claude/scripts/asgard-serve.mjs`
도 그 저장소에만 있다 — `asgard-custom` 에는 `justfile` 도 `.claude/scripts/` 도 없고,
`asgard-system`·포트 `4590` 을 언급하는 파일이 벤더 참조 사본(`ref/asgard-helios/`) 밖에는 하나도
없다. 9일 22시간 상주·457초 누적 CPU 는 실측이지만, 이 저장소가 아니라 옆 저장소가 낸 값이다.
그 저장소를 기준으로 봐도 시간당 1.92초는 사실상 유휴다(가동률 0.005%).

`asgard memory mcp` 는 열어 둔 편집기 세션 하나당 한 쌍(uv 실행기 + 실제 python 프로세스)이 떠서
세션이 살아 있는 한 상주한다. 22개 프로세스 모두 CPU 는 시간당 1.2초를 넘지 않아 폴링 흔적이
없고(요청이 올 때만 깨는 유휴 MCP 서버), 그 순간 RSS 합이 약 778MB(336.7+441.5MB) 였다.

> **정정 (항목 6, 같은 날 재측정).** 위 문장의 첫 판은 "세션을 안 닫으면 쌓이기만 한다"고 적었다.
> 그 추세 주장이 틀렸다 — 세션이 닫히면 쌍도 사라진다. 열린 세션이 2개일 때 다시 재니 프로세스가
> 정확히 4개(쌍 2개, 132.8MB)였고, 각 쌍의 조상이 그 세션 프로세스(`claude --resume <세션 id>`)다.
> 778MB 는 편집기 세션 11개가 동시에 열려 있던 순간의 값이지 누적이 아니다. 세션 하나가 약 66MB 를
> 쥔다는 것만 남는다. `findings-item67-design.md` 참조.

같은 스냅샷에 `pytest` 워커 2개가 함께 잡혔다(다른 세션의 시험 실행) — 제품 표면이 아니라 위
표에서 제외했다.

## Docker

| 컨테이너 | 상태 | CPU% | 메모리 |
|---|---|---|---|
| `asgard-project-memory-hindsight-1` (2차 기억 백엔드, 18890/19990) | Up 2일 (healthy) | 0.26% | 2.57GiB / 8GiB (32.1%) |
| `asgard-project-memory-postgres-1` (pgvector) | Up 5일 (healthy) | 0.07% | 78MB / 15.66GiB (0.49%) |

이름이 `asgard-` 로 시작하지 않는 컨테이너(`hermes-hindsight-memory`, `wams-local-*`, `ai-study-jupyter` 등)
는 다른 프로젝트 소속이라 제외했다. ollama 프로세스는 없음(`pgrep -f ollama` 빈 결과).

## 디스크 상태

| 대상 | 크기 | 비고 |
|---|---|---|
| `.asgard/orchestration.db` | 176KB | runs 45·tasks 167·dispatches 158·messages 18·gates 0 (388행) |
| `.asgard/memory/documents.db` | 164KB | 프로젝트 문서 색인, doc 18건 |
| `.asgard/quest/*.jsonl` | 54개, 총 1.23MB | 최대: `asgard-coherence-refactor-260812.jsonl` 172.6KB |
| `.asgard/map/` | 55KB | |
| `.asgard/` 전체 | 4.58MB | |
| `~/.asgard/` | **9.26GiB** | 이 저장소 하나가 아니라 이 기기의 모든 저장소가 공유하는 개인 기억 계층 전체 |

`.asgard/asgard-setting-project.json`(2.5KB)과 `MANUAL.md`(3.8KB)는 매 턴 여러 훅이 반복해서 여는
파일이지만 크기 자체는 작다 — 세금은 바이트가 아니라 호출 횟수 쪽에 있다.

### 매 훅 호출마다 `.asgard/` 를 여는 지점 (`.claude/hooks/*.py` grep 결과)

아래 목록은 `resident.py` 의 `hook_read_frequency()` 를 그대로 돌린 결과다 — 손으로 옮겨 적지 마라.

- **UserPromptSubmit** (프롬프트마다 1회씩) — 9개: `agent-activate`, `budget-guard`,
  `charter-activate`, `lagom-tracker`, `manual-activate`, `map-activate`, `memory-activate`,
  `siege-inbox`, `tutor-note`. `.asgard/asgard-setting-project.json` 또는
  `.asgard/orchestration.db`(`siege-inbox`)를 연다.
- **SubagentStart** (서브에이전트 호출마다 1회씩) — 9개: `agent-activate`, `charter-activate`,
  `dispatch-context`, `lagom-subagent`, `manual-activate`, `map-activate`, `memory-activate`,
  `subagent-gate`, `verifier-context`. 이 중 `dispatch-context` 와 `subagent-gate` 가
  `.asgard/orchestration.db` 를 연다.
- 나머지 이벤트: SessionStart 6개, Stop 5개, PostToolUse 3개, SubagentStop 2개, PreToolUse 2개
  (`budget-guard`, `subagent-gate`).
- 파일 자체는 작아서(설정 2.5KB, DB 176KB) 한 번 여는 비용은 작지만, 프로세스 기동(uv+python)
  비용이 호출 횟수만큼 반복된다 — 이건 디스크가 아니라 프로세스 경계 비용이라 이 벤치의 범위
  밖이다(참고: 개인 기록 "훅 값은 프로세스 경계").

## 판정

**훅 세금 말고 CPU 를 먹는 것은 없다.** 상주 프로세스 전원이 시간당 CPU 1.2초를 넘지 않고
(가장 오래 켜진 PID 44444 도 시간당 1.92초, 그나마 이 저장소 소속도 아니다), docker 컨테이너 둘도
CPU 0.3% 아래다 — 폴링으로 의심할 값이 아니라 요청이 올 때만 깨는 유휴 프로세스의 모양이다.
대신 값이 큰 쪽은 CPU 가 아니라 **메모리·디스크**다: 계측 시점에 열려 있던 세션 11개의 유휴 MCP
서버가 RSS 778MB, `~/.asgard/` 가 9.26GiB. 앞의 것은 쌓이는 값이 아니라 동시에 열린 세션 수에
비례하는 값이고(위 정정 참조), 뒤의 것은 이 저장소만의 상태가 아니라 기기 전체의 개인 기억
계층이 공유하는 값이라 이 저장소를 정리해도 줄지 않는다.
