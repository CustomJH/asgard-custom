// recall — 2차 메모리(프로젝트 메모리) 백엔드의 **회수** 경로. 아스가르드가 실제로 치는
// 요청 모양 그대로다.
//
// 재는 자리가 여기인 이유: 등록(retain)은 사람이 승인할 때 한 번이지만 회수는 대화마다 돈다.
// 그리고 이 백엔드는 팀이 공유하는 원격 서비스라 한 사람의 지연으로는 보이지 않는 것이 있다.
//
//   asgard k6 run recall --target http://host.docker.internal:18890 --env BANK=<bank>
//
// 빈 뱅크에 걸면 의미가 없다 — 회수가 0건이면 리랭커가 아무 일도 안 하고 끝나 실제보다
// 빠르게 나온다. `recall_empty` 비율이 그 착시를 표면에 남긴다.

import http from 'k6/http'
import { check } from 'k6'
import { Trend, Rate } from 'k6/metrics'
import { summarize, target, envInt, envFloat, pickQuery, TREND_STATS } from '../lib/asgard.js'

const BASE = target('http://host.docker.internal:18890')
const BANK = __ENV.ASGARD_K6_BANK || __ENV.BANK || ''
const NAMESPACE = __ENV.ASGARD_K6_NAMESPACE || 'default'
const PEAK = envInt('ASGARD_K6_VUS', 50)
const P95_MAX = envFloat('ASGARD_K6_P95_MAX', 3000)

const hits = new Trend('recall_hits')
const empty = new Rate('recall_empty')

export const options = {
  summaryTrendStats: TREND_STATS,
  scenarios: {
    ramp: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: '20s', target: Math.max(1, Math.round(PEAK * 0.1)) },
        { duration: '30s', target: Math.max(1, Math.round(PEAK * 0.4)) },
        { duration: '20s', target: PEAK },
        { duration: '20s', target: 0 },
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: [`p(95)<${P95_MAX}`],
  },
}

const QUERIES = [
  'ledger renderer', 'render_ledger', 'invoice settlement', 'payments entry point',
  'operator console rows', 'settle_invoice', 'widget', 'project artifact component',
]

export default function () {
  const query = pickQuery(QUERIES, __ITER)
  const res = http.post(
    `${BASE}/v1/${NAMESPACE}/banks/${BANK}/memories/recall`,
    JSON.stringify({
      query,
      types: ['world', 'experience'],
      budget: 'mid',
      max_tokens: 2048,
      include: { entities: null, chunks: { max_tokens: 4096 } },
    }),
    { headers: { 'Content-Type': 'application/json' }, timeout: '60s' },
  )
  check(res, { 'status 200': (r) => r.status === 200 })
  if (res.status === 200) {
    try {
      const n = (res.json('results') || []).length
      hits.add(n)
      empty.add(n === 0)
    } catch (_) {
      empty.add(true)
    }
  }
}

export function handleSummary(data) {
  return summarize(data, {
    scenario: 'recall',
    target: `${BASE} · bank=${BANK || '(unset)'}`,
    custom: { recall_hits: 'recall_hits', recall_empty: 'recall_empty' },
  })
}
