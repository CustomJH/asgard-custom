// 스크립트 공통 인자 파서와 출력 헬퍼.

// `node tool.mjs --json | head` 처럼 소비자가 먼저 닫으면 node 는 EPIPE 를 던지고, 기본 동작은
// 처리되지 않은 예외로 죽는 것이다. 스택 트레이스가 도구의 결함처럼 보여서 실제로 한 번 헷갈렸다.
// 파이프가 닫힌 것은 오류가 아니라 소비자가 다 읽었다는 뜻이므로 조용히 끝낸다. 다른 쓰기 오류는
// 그대로 올린다 — 디스크가 찼는데 침묵하면 그것이 진짜 사고다.
for (const stream of [process.stdout, process.stderr]) {
  stream.on("error", (error) => {
    if (error?.code === "EPIPE") process.exit(0);
    throw error;
  });
}

export function parseArgs(argv, { flags = [] } = {}) {
  const positional = [];
  const options = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) {
      positional.push(token);
      continue;
    }
    const [name, inline] = token.slice(2).split("=");
    if (inline !== undefined) options[name] = inline;
    else if (flags.includes(name)) options[name] = true;
    else if (argv[i + 1] !== undefined && !argv[i + 1].startsWith("--")) options[name] = argv[(i += 1)];
    else options[name] = true;
  }
  return { positional, options };
}

export function fail(message, code = 2) {
  process.stderr.write(`${message}\n`);
  process.exit(code);
}

/** 사람이 읽는 표와 기계가 읽는 JSON 중 하나만 낸다 — 증거는 항상 파일로 남긴다. */
export function emit(payload, asJson, renderText) {
  if (asJson) process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
  else process.stdout.write(`${renderText(payload)}\n`);
}

export function round(value, digits = 3) {
  return Number.isFinite(value) ? Number(value.toFixed(digits)) : null;
}
