// selftest — 하네스가 자기 자신을 재는 시나리오. 표적은 pacer(거동을 아는 서버)다.
//
// 여기서 던지는 부하는 **정답이 미리 계산된다**: 반복 횟수는 고정(shared-iterations),
// 지연은 pacer 가 정확히 재우고, 실패는 확률이 아니라 주기다. 그래서 이 시나리오의
// 결과는 "느린가 빠른가"가 아니라 **"하네스가 참을 말하는가"**를 판정하는 데 쓰인다.
//
// 임계값은 환경에서 주입한다 — 같은 표적에 통과할 임계값과 떨어질 임계값을 각각 걸어
// 게이트가 양방향으로 움직이는지 본다. 절대 안 떨어지는 게이트는 장식이다.

import http from 'k6/http'
import { check } from 'k6'
import { Counter } from 'k6/metrics'
import { summarize, target, envInt, envFloat, TREND_STATS } from '../lib/asgard.js'

const BASE = target()
const ITERATIONS = envInt('ASGARD_K6_ITERATIONS', 60)
const VUS = envInt('ASGARD_K6_VUS', 4)
const P95_MAX = envFloat('ASGARD_K6_P95_MAX', 5000)
const FAIL_MAX = envFloat('ASGARD_K6_FAIL_MAX', 1)

const serverErrors = new Counter('pacer_5xx')

export const options = {
  summaryTrendStats: TREND_STATS,
  scenarios: {
    // 고정 반복 — 요청 수가 설정값과 정확히 같아야 한다. 이 등식이 깨지면 부하 생성기가
    // 요청을 흘렸거나 요약이 다른 수를 읽은 것이고, 둘 다 조용히 넘어가면 안 된다.
    fixed: {
      executor: 'shared-iterations',
      vus: VUS,
      iterations: ITERATIONS,
      maxDuration: '5m',
    },
  },
  thresholds: {
    http_req_duration: [`p(95)<${P95_MAX}`],
    http_req_failed: [`rate<${FAIL_MAX}`],
  },
}

export default function () {
  const res = http.get(`${BASE}/ok`, { timeout: '60s' })
  check(res, { 'status 200': (r) => r.status === 200 })
  if (res.status >= 500) serverErrors.add(1)
}

export function handleSummary(data) {
  return summarize(data, {
    scenario: 'selftest',
    target: BASE,
    custom: { pacer_5xx: 'pacer_5xx' },
  })
}
