// 스크립트 공통 인자 파서와 출력 헬퍼.

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
