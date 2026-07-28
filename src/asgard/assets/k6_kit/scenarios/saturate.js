// saturate — 포화점 탐색. VU 를 계단식으로 올리며 **단계마다 따로** 지연을 잰다.
//
// 램프는 평균을 뭉갠다: 1 VU 구간의 빠름과 20 VU 구간의 느림이 한 p95 로 접히면
// "몇 명까지 되나"라는 질문에 답할 수 없다. 계단은 각 단계를 독립 표본으로 남긴다.
//
//   asgard k6 run saturate --target http://host.docker.internal:18890 --env BANK=<bank>
//
// 단계별 값은 요약의 custom.stage_vu<N> 에 들어간다.

import http from 'k6/http'
import { check } from 'k6'
import { Trend } from 'k6/metrics'
import { summarize, target, TREND_STATS } from '../lib/asgard.js'

const BASE = target('http://host.docker.internal:18890')
const BANK = __ENV.ASGARD_K6_BANK || __ENV.BANK || ''
const NAMESPACE = __ENV.ASGARD_K6_NAMESPACE || 'default'
const STEP_SECONDS = parseInt(__ENV.ASGARD_K6_STEP_SECONDS || '20', 10)
const LADDER = (__ENV.ASGARD_K6_LADDER || '1,2,5,10,20')
  .split(',')
  .map((n) => parseInt(n.trim(), 10))
  .filter((n) => Number.isFinite(n) && n > 0)

const byStage = {}
LADDER.forEach((n) => {
  byStage[n] = new Trend(`stage_vu${n}`, true)
})

export const options = {
  summaryTrendStats: TREND_STATS,
  scenarios: Object.fromEntries(
    LADDER.map((n, i) => [
      `vu${n}`,
      {
        executor: 'constant-vus',
        vus: n,
        duration: `${STEP_SECONDS}s`,
        startTime: `${i * (STEP_SECONDS + 2)}s`,
        env: { LEVEL: String(n) },
      },
    ]),
  ),
  // 계단마다 임계값을 따로 걸지 않는다 — 포화점을 **찾는** 실행이지 판정하는 실행이 아니다.
  // 판정이 필요하면 recall 시나리오에 p95 를 걸어라.
  thresholds: { http_req_failed: ['rate<0.01'] },
}

export default function () {
  const res = http.post(
    `${BASE}/v1/${NAMESPACE}/banks/${BANK}/memories/recall`,
    JSON.stringify({
      query: 'ledger renderer settle invoice',
      types: ['world', 'experience'],
      budget: 'mid',
      max_tokens: 2048,
    }),
    { headers: { 'Content-Type': 'application/json' }, timeout: '120s' },
  )
  check(res, { 'status 200': (r) => r.status === 200 })
  const level = Number(__ENV.LEVEL)
  if (byStage[level]) byStage[level].add(res.timings.duration)
}

export function handleSummary(data) {
  const custom = {}
  LADDER.forEach((n) => {
    custom[`stage_vu${n}`] = `stage_vu${n}`
  })
  return summarize(data, {
    scenario: 'saturate',
    target: `${BASE} · bank=${BANK || '(unset)'}`,
    custom,
  })
}
