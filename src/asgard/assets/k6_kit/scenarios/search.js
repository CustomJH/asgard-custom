// search — 1차 메모리(개인 메모리) 회수 `/api/search` 의 지연.
//
// 사람이 기다리는 자리다. 그래서 두 국면을 나눠 잰다: 경합 없는 단독 지연(기준선)과
// 동시 요청이 붙었을 때(단일 프로세스 서버가 무너지는지). 한 실행에 섞으면 둘 다 잃는다.
//
//   asgard k6 run search --target http://host.docker.internal:8791
//
// 질의는 한국어·영어·구절을 섞는다 — 한 종류만 던지면 코퍼스가 아니라 운 좋은 경로
// 하나를 재게 된다.

import http from 'k6/http'
import { check } from 'k6'
import { Trend, Rate } from 'k6/metrics'
import { summarize, target, envFloat, pickQuery, TREND_STATS } from '../lib/asgard.js'

const BASE = target('http://host.docker.internal:8791')
const SOLO_P95_MAX = envFloat('ASGARD_K6_P95_MAX', 100)
const K = __ENV.ASGARD_K6_K || '5'

const searchLatency = new Trend('search_latency', true)
const emptyHits = new Rate('empty_hits')

const QUERIES = [
  '금요일 배포', '배포 전에 무엇을 하나', '커밋 메시지 규약', '문서는 어디에 두나',
  '테스트는 어떻게 돌리나', '리뷰 습관', '에디터 설정', 'CI 통과 조건',
  '마이그레이션 원칙', '비밀값 관리', '회의 방식', 'gitmoji',
  'deployment policy', 'how do I run tests', 'commit convention', 'friday deploy',
]

export const options = {
  summaryTrendStats: TREND_STATS,
  scenarios: {
    solo: {
      executor: 'constant-vus',
      vus: 1,
      duration: '20s',
      tags: { phase: 'solo' },
    },
    concurrent: {
      executor: 'ramping-vus',
      startTime: '22s',
      startVUs: 1,
      stages: [
        { duration: '10s', target: 4 },
        { duration: '20s', target: 8 },
        { duration: '10s', target: 0 },
      ],
      tags: { phase: 'concurrent' },
      gracefulRampDown: '5s',
    },
  },
  thresholds: {
    // 판정은 단독 국면에만 건다 — 경합 국면은 관측 대상이지 계약이 아니다.
    'search_latency{phase:solo}': [`p(95)<${SOLO_P95_MAX}`],
    http_req_failed: ['rate<0.01'],
    empty_hits: ['rate<0.05'],
  },
}

// 서버가 어느 코퍼스로 떠 있는지는 URL 로 구분되지 않는다 — 실행에 표를 붙여 둔다.
const PROFILE = __ENV.ASGARD_K6_PROFILE || ''

export default function () {
  const q = pickQuery(QUERIES, __ITER)
  const res = http.get(`${BASE}/api/search?q=${encodeURIComponent(q)}&k=${K}`, {
    timeout: '60s',
    tags: { profile: PROFILE },
  })
  searchLatency.add(res.timings.duration)
  const ok = check(res, {
    'status 200': (r) => r.status === 200,
    'json body': (r) => (r.headers['Content-Type'] || '').includes('json'),
  })
  if (ok && res.status === 200) {
    let hits = []
    try {
      hits = JSON.parse(res.body).hits || []
    } catch (_) {
      hits = []
    }
    emptyHits.add(hits.length === 0)
  }
}

export function handleSummary(data) {
  return summarize(data, {
    scenario: 'search',
    target: BASE,
    custom: { search_latency: 'search_latency', empty_hits: 'empty_hits' },
  })
}
