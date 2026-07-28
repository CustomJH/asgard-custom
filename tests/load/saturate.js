// 포화점 탐색 — VU 를 계단식으로 올리며 각 단계의 p95 를 따로 잰다.
// 찾는 답: "hindsight 인스턴스 하나가 동시 사용자 몇 명까지 우리 타임아웃(15s) 안에 답하나".
import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const BASE = __ENV.HS_BASE, BANK = __ENV.HS_BANK;
const byStage = {};
[1, 2, 5, 10, 20].forEach((n) => { byStage[n] = new Trend(`dur_vu${n}`); });

export const options = {
  scenarios: Object.fromEntries([1, 2, 5, 10, 20].map((n, i) => [
    `vu${n}`,
    { executor: 'constant-vus', vus: n, duration: '20s', startTime: `${i * 22}s`, env: { LEVEL: String(n) } },
  ])),
  thresholds: { http_req_failed: ['rate<0.01'] },
};

export default function () {
  const res = http.post(
    `${BASE}/v1/default/banks/${BANK}/memories/recall`,
    JSON.stringify({ query: 'ledger renderer settle invoice', types: ['world', 'experience'], budget: 'mid', max_tokens: 2048 }),
    { headers: { 'Content-Type': 'application/json' }, timeout: '120s' },
  );
  check(res, { 'status 200': (r) => r.status === 200 });
  byStage[Number(__ENV.LEVEL)].add(res.timings.duration);
}
