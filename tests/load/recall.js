// Hindsight 회수 부하 — Asgard 가 실제로 치는 요청 모양 그대로.
// 우리가 매 턴 부르는 경로는 recall 이다. 등록은 사람이 승인할 때 한 번이지만
// 회수는 대화마다 돈다 — 그래서 부하를 재야 하는 쪽은 여기다.
import http from 'k6/http';
import { check } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const BASE = __ENV.HS_BASE || 'http://host.docker.internal:18890';
const BANK = __ENV.HS_BANK;
const hits = new Trend('recall_hits');
const empty = new Rate('recall_empty');

export const options = {
  scenarios: {
    ramp: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: '20s', target: 5 },
        { duration: '30s', target: 20 },
        { duration: '20s', target: 50 },
        { duration: '20s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<3000'],
  },
};

const QUERIES = [
  'ledger renderer', 'render_ledger', 'invoice settlement', 'payments entry point',
  'operator console rows', 'settle_invoice', 'widget', 'project artifact component',
];

export default function () {
  const query = QUERIES[Math.floor(Math.random() * QUERIES.length)];
  const res = http.post(
    `${BASE}/v1/default/banks/${BANK}/memories/recall`,
    JSON.stringify({
      query,
      types: ['world', 'experience'],
      budget: 'mid',
      max_tokens: 2048,
      include: { entities: null, chunks: { max_tokens: 4096 } },
    }),
    { headers: { 'Content-Type': 'application/json' }, timeout: '60s' },
  );
  check(res, { 'status 200': (r) => r.status === 200 });
  if (res.status === 200) {
    try {
      const n = (res.json('results') || []).length;
      hits.add(n);
      empty.add(n === 0);
    } catch (_) { empty.add(true); }
  }
}
