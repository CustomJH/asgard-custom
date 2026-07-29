# asgard-k6 — 부하 시험 러너 이미지

부하 시험 레인의 **도커 쪽 집**이다. 이미지 정의(`Dockerfile`)와 수동 운용 스택
(`docker-compose.yml`)이 여기 살고, `docker/asgard-project-memory/` 와 나란히 관리된다.

레인의 사용 표면은 CLI 다:

```bash
asgard k6 doctor      # 지금 어느 이미지·어느 k6 로 재는지
asgard k6 selftest    # 하네스 정합성 — 녹색이 아니면 어떤 부하 수치도 근거가 아니다
asgard k6 run <시나리오> --target ... --p95-max 300
```

## 왜 우리 이름의 이미지인가

부하 수치는 도구의 판에 딸려 있다. `grafana/k6:latest` 로 잰 값이 나중에 어느 k6 였는지는
복원되지 않고, 태그가 움직이면 같은 명령이 다른 도구로 돈다. 이미지에 우리 이름을 붙이면
판이 고정되고, 그 이름이 실행마다 보고서에 새겨진다.

```bash
# 컨텍스트는 저장소 루트 — 시나리오 키트가 src/ 아래 있기 때문이다
docker build -f docker/asgard-k6/Dockerfile -t asgard-k6:local .
```

굽고 나면 `asgard k6` 가 **자동으로 이 이미지를 잡는다**(`asgard-k6:<버전>` → `asgard-k6:local`
→ 공개 `grafana/k6:latest` 순). 자동 빌드는 하지 않는다: 설치본에는 빌드 컨텍스트가 없고,
부하를 재려던 명령이 몇 분짜리 이미지 빌드로 바뀌면 그 자체가 측정 방해다.
`ASGARD_K6_IMAGE` 로 어떤 이미지든 고정할 수 있다.

이미지에는 시나리오 키트가 함께 구워져 있어 마운트 없이도 단독으로 돈다:

```bash
docker run --rm asgard-k6:local run /asgard/scenarios/http-smoke.js
```

다만 **정본은 배송되는 `src/asgard/assets/k6_kit/`** 이다. 아스가르드가 이 이미지를 몰 때는
같은 키트를 읽기 전용으로 덮어 마운트하므로, 구운 판이 오래돼도 실제로 도는 시나리오는
언제나 배송본 쪽이다. `tests/test_k6.py` 가 Dockerfile 의 COPY 원본이 그 경로인지 봉인한다.

## 볼륨은 프로젝트 것이다

마운트 원본은 이 디렉터리도, 셸의 현재 위치도, 휠이 풀린 설치 접두사도 아니다 —
**부하를 재는 그 프로젝트의 `.asgard/k6/`** 다.

```
<프로젝트>/.asgard/k6/
  kit/        배송 키트의 실물 — 컨테이너의 `/asgard` (읽기 전용)
  out/        수동 compose 실행의 요약
  runs/       CLI 실행 기록 (`asgard k6 run`)
  scenarios/  이 프로젝트가 직접 쓴 시나리오
```

이유는 설치본이 `src/` 를 안 들고 다니기 때문만이 아니다. 한 설치본을 여러 프로젝트가
함께 쓰는 이상, 마운트 원본이 프로젝트 밖에 있으면 **"이 실행이 어떤 키트를 봤나"가
프로젝트 밖에서 정해진다.** 안으로 내려 두면 그 답이 파일로 남고, CLI 와 수동 스택이
같은 실물을 본다. `asgard k6 sync` 가 그 자리를 세우고 (`asgard k6 run` 은 매 실행
자동으로 부른다), `asgard k6 doctor` 의 `mount` 줄이 지금 무엇이 걸려 있는지 말한다.

## 수동 스택

`docker-compose.yml` 은 pacer(거동을 아는 기준 표적) + k6 를 함께 띄운다. 표적을 바꿔 가며
여러 번 두들기거나, pacer 를 세워 둔 채 다른 도구를 붙일 때 쓴다.

```bash
# 이 저장소 자신을 잴 때 — 볼륨 기본값이 저장소 루트의 .asgard/k6 다
asgard k6 sync
docker compose -f docker/asgard-k6/docker-compose.yml up pacer -d
ASGARD_K6_IMAGE=asgard-k6:local \
  docker compose -f docker/asgard-k6/docker-compose.yml run --rm k6 run /asgard/scenarios/selftest.js
```

다른 프로젝트를 잴 때는 그 프로젝트의 레인을 가리킨다 (`asgard k6 sync` 가 마지막 줄에
이 값을 찍어 준다):

```bash
export ASGARD_K6_LANE=/path/to/project/.asgard/k6
docker compose -f docker/asgard-k6/docker-compose.yml up pacer -d
```

pacer 는 난수를 안 쓴다 — 지연은 정확히 `--latency-ms`, 실패는 확률이 아니라 주기
(`--error-rate 0.25` = 4번째마다), 동시성은 세마포어 상한이다. 그래서 정답이 미리 계산되고,
하네스가 참을 말하는지 대조할 수 있다.

| 환경 변수 | 기본 | 뜻 |
|---|---|---|
| `ASGARD_K6_LANE` | `../../.asgard/k6` (저장소 루트) | 볼륨의 집 — 잴 프로젝트의 레인 |
| `ASGARD_K6_OUT_DIR` | `<레인>/out` | 요약이 떨어지는 자리 |
| `ASGARD_K6_IMAGE` | (자동 해석) | 러너 이미지 고정 |
| `ASGARD_K6_PACER_LATENCY_MS` | 80 | 표적이 재우는 시간 |
| `ASGARD_K6_PACER_ERROR_RATE` | 0 | 주기적 실패 비율 |
| `ASGARD_K6_PACER_CONCURRENCY` | 0 (무제한) | 동시 처리 상한 |
| `ASGARD_K6_TARGET` | `http://pacer:8799` | 부하 대상 |

레인 전체 설명(시나리오 계약·요약 스키마·마운트 배치)은
`src/asgard/assets/k6_kit/README.md` 에 있다.
