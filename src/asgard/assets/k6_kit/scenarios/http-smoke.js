// http-smoke — 표적 하나를 GET 으로 램프. 전용 시나리오를 쓰기 전에 "이 주소가 부하를
// 받기는 하는가"를 먼저 보는 자리다.
//
//   asgard k6 run http-smoke --target http://127.0.0.1:8080/health --vus 10 --duration 30s

import http from 'k6/http'
import { check } from 'k6'
import { summarize, target, envInt, envFloat, TREND_STATS } from '../lib/asgard.js'

const BASE = target()
const VUS = envInt('ASGARD_K6_VUS', 5)
const DURATION = __ENV.ASGARD_K6_DURATION || '30s'
const P95_MAX = envFloat('ASGARD_K6_P95_MAX', 1000)
const FAIL_MAX = envFloat('ASGARD_K6_FAIL_MAX', 0.01)

export const options = {
  summaryTrendStats: TREND_STATS,
  scenarios: {
    ramp: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: '5s', target: VUS },
        { duration: DURATION, target: VUS },
        { duration: '5s', target: 0 },
      ],
      gracefulRampDown: '5s',
    },
  },
  thresholds: {
    http_req_duration: [`p(95)<${P95_MAX}`],
    http_req_failed: [`rate<${FAIL_MAX}`],
  },
}

export default function () {
  const res = http.get(BASE, { timeout: '60s' })
  check(res, { 'status 2xx': (r) => r.status >= 200 && r.status < 300 })
}

export function handleSummary(data) {
  return summarize(data, { scenario: 'http-smoke', target: BASE })
}
