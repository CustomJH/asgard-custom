// asgard-k6 시나리오 계약 — 모든 시나리오가 **같은 모양**의 요약을 뱉게 하는 자리.
//
// 부하 시험 결과가 사람 손으로 표에 옮겨 적히는 동안은 감사할 수 없다. 스크립트마다
// 메트릭 이름과 요약 형식이 다르면 더더욱 그렇다. 그래서 요약의 정본은 하나다:
// `asgard-k6-summary-v1`. 파이썬 쪽 파서는 이 모양 하나만 안다.
//
// 시나리오가 할 일은 두 줄이다:
//   import { summarize, target, pickQuery } from '../lib/asgard.js'
//   export function handleSummary(data) { return summarize(data, { scenario: 'x' }) }

export const SCHEMA = 'asgard-k6-summary-v1'

// 요약이 나갈 자리 — 러너가 이 경로를 rw 로 마운트한다. 파일 이름은 계약이다.
export const OUT = __ENV.ASGARD_K6_OUT || '/asgard/out/summary.json'

// p(99) 는 k6 기본 요약에 없다. 꼬리를 못 보면 "평균은 괜찮다"는 착시가 남는다.
export const TREND_STATS = ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max', 'count']

export function target(fallback) {
  return __ENV.ASGARD_K6_TARGET || fallback || 'http://host.docker.internal:8799'
}

export function envInt(name, fallback) {
  const raw = __ENV[name]
  if (raw === undefined || raw === '') return fallback
  const n = parseInt(raw, 10)
  return Number.isFinite(n) ? n : fallback
}

export function envFloat(name, fallback) {
  const raw = __ENV[name]
  if (raw === undefined || raw === '') return fallback
  const n = parseFloat(raw)
  return Number.isFinite(n) ? n : fallback
}

// 질의는 결정론으로 돈다 — 난수를 쓰면 같은 명령이 매번 다른 코퍼스 경로를 재고,
// 두 실행의 차이가 코드 변경 때문인지 운 때문인지 영영 갈라내지 못한다.
export function pickQuery(pool, index) {
  return pool[index % pool.length]
}

function values(data, metric) {
  const m = data.metrics && data.metrics[metric]
  return (m && m.values) || {}
}

function thresholdRows(data) {
  const rows = []
  for (const [metric, body] of Object.entries(data.metrics || {})) {
    for (const [expression, result] of Object.entries((body && body.thresholds) || {})) {
      rows.push({ metric, expression, ok: !!(result && result.ok) })
    }
  }
  return rows
}

function checkRows(group, prefix, out) {
  for (const check of (group && group.checks) || []) {
    out.push({ name: prefix + check.name, passes: check.passes, fails: check.fails })
  }
  for (const child of (group && group.groups) || []) {
    checkRows(child, prefix + (child.name || '') + '::', out)
  }
  return out
}

/**
 * k6 요약 객체 → asgard 정본 요약. handleSummary 에서 그대로 return 한다.
 *
 * 함정 하나를 여기서 흡수한다: `http_req_failed` 는 Rate 이고, 그 `passes` 는
 * **실패한 요청 수**다(판정식이 "실패했는가"이므로). 이름 그대로 읽으면 성공/실패가
 * 뒤집힌 보고서가 나온다.
 */
export function summarize(data, meta) {
  const reqs = values(data, 'http_reqs')
  const dur = values(data, 'http_req_duration')
  const failed = values(data, 'http_req_failed')
  const checks = values(data, 'checks')
  const vus = values(data, 'vus_max')
  const iters = values(data, 'iterations')
  const count = reqs.count || 0
  const failedCount = failed.passes || 0
  const durationMs = (data.state && data.state.testRunDurationMs) || 0

  const summary = {
    schema: SCHEMA,
    scenario: (meta && meta.scenario) || __ENV.ASGARD_K6_SCENARIO || 'unnamed',
    target: (meta && meta.target) || __ENV.ASGARD_K6_TARGET || '',
    run_id: __ENV.ASGARD_K6_RUN_ID || '',
    duration_ms: durationMs,
    requests: {
      count: count,
      failed: failedCount,
      failed_rate: failed.rate || 0,
      rate_per_s: reqs.rate || 0,
    },
    latency_ms: {
      avg: dur.avg || 0,
      min: dur.min || 0,
      med: dur.med || 0,
      p90: dur['p(90)'] || 0,
      p95: dur['p(95)'] || 0,
      p99: dur['p(99)'] || 0,
      max: dur.max || 0,
    },
    iterations: iters.count || 0,
    // k6 가 **할당한** VU 총합이다. 계단형 시나리오에서는 단계들의 합이라 동시 접속자 수가
    // 아니고, 1초 미만 실행에서는 표집이 없어 0 이다 — 둘 다 표면에서 그대로 말해야 한다.
    vus_max: vus.max || vus.value || 0,
    checks: {
      passes: checks.passes || 0,
      fails: checks.fails || 0,
      rows: checkRows(data.root_group, '', []),
    },
    thresholds: thresholdRows(data),
    custom: {},
  }
  summary.thresholds_ok = summary.thresholds.every((row) => row.ok)

  // 시나리오가 자기만의 계측을 얹는 자리 (회수 적중 수 같은 것) — 정본 필드는 안 건드린다.
  for (const [name, metric] of Object.entries((meta && meta.custom) || {})) {
    summary.custom[name] = values(data, metric)
  }

  const out = {}
  out[OUT] = JSON.stringify(summary, null, 2)
  // stdout 요약은 사람이 붙어 있을 때만 쓸모가 있다 — 파이썬 쪽은 파일만 읽는다.
  out.stdout = renderText(summary)
  return out
}

function ms(n) {
  return `${n.toFixed(1)}ms`
}

export function renderText(s) {
  const lines = [
    ``,
    `  ${s.scenario} → ${s.target || '(target unset)'}`,
    `  requests ${s.requests.count} · failed ${s.requests.failed} (${(s.requests.failed_rate * 100).toFixed(2)}%) · ${s.requests.rate_per_s.toFixed(2)} req/s · vus ${s.vus_max}`,
    `  latency  avg ${ms(s.latency_ms.avg)} · med ${ms(s.latency_ms.med)} · p95 ${ms(s.latency_ms.p95)} · p99 ${ms(s.latency_ms.p99)} · max ${ms(s.latency_ms.max)}`,
  ]
  for (const row of s.thresholds) {
    lines.push(`  threshold ${row.ok ? 'pass' : 'FAIL'}  ${row.metric} ${row.expression}`)
  }
  lines.push('')
  return lines.join('\n')
}
