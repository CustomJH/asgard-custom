"""씨 뿌린 코퍼스 — 두 게이트의 재현율과 **막는 오탐**을 표 하나로 못박는다.

실행: uv run pytest tests/test_thor_corpus.py

`test_craft.py`·`test_thor_gate.py` 가 규칙마다 앵커 한둘을 두는 것과 역할이 다르다. 저쪽은
"이 규칙이 이렇게 동작한다"를 고정하고, 이쪽은 **전체 판정기를 하나의 수치로** 잰다. 규칙이
스무 개가 되면 개별 앵커만으로는 "그래서 지금 얼마나 잡고 얼마나 틀리나"에 답할 수 없다.

계약 셋:

① **짝(matched pair)이 단위다.** 결함 표본마다 그 결함의 **정답 수정**이 음성 표본으로 붙는다.
   정답 쪽에서 판정이 뜨면 그것은 게이트가 자기 처방과 결함을 구분 못 한다는 뜻이고, 이 저장소가
   가장 비싸다고 부르는 오탐이 정확히 그것이다.

② **막는 오탐은 0 이어야 한다.** 알림 오탐은 허용치가 있지만(설계상 알림으로 낮춘 것들이 있다)
   막는 판정은 반례가 없어야 한다는 것이 게이트의 정의다. 여기서 1건이라도 나면 실패다.

③ **규칙을 더할 때 음성 대조군을 같이 넣지 않으면 테스트가 깨진다.** `test_rule_coverage` 가
   막는 규칙마다 진양성 1건과 음성 3건을 요구한다. 이것이 이 파일의 진짜 값어치다 — 재현율
   숫자는 코퍼스를 쓴 사람이 규칙을 알고 썼으므로 위로 편향되지만, 커버리지 강제는 편향되지
   않는다.

**숫자를 읽는 법.** 여기 재현율 100% 는 "이 판정기가 결함의 100% 를 잡는다"가 아니다. 표본을
규칙에서 역으로 지어냈기 때문에 위로 편향되고, 표본끼리 독립도 아니라서 신뢰구간을 붙일 수
없다. 이 파일이 지키는 것은 **복귀 방지**다 — 한 번 잡던 것을 못 잡게 되거나, 한 번 통과시키던
정답을 막게 되면 그 자리에서 깨진다. 판정기의 정밀도를 알고 싶으면 실코퍼스에서 막는 판정을
전수 손검사해야 하고, 그것은 이 파일이 하는 일이 아니다.

문서화된 미검출(`EXPECTED_MISS`)은 표에 남겨 둔다. 지우면 "왜 이건 안 잡히지"를 다음 사람이
다시 발견하게 된다 — 못 잡는 것과 안 잡기로 한 것은 다르고, 그 차이는 기록으로만 남는다.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from asgard import craft, craft_c, craft_lex, craft_rules, health, thor_gate, thor_lex, thor_rules
from asgard.craft_rules import Finding

# 판정기가 **일부러** 안 잡기로 한 것 — 근거는 각 모듈 주석에 있다. 재현율 계산에서 뺀다.
EXPECTED_MISS = {
    "leak-socket": "socket·connect 는 Qt 시그널·기존 소켓 메서드와 이름이 겹친다 (craft_rules._ACQUIRE)",
    "cost-param-unknown": "매개변수는 타입 미상이다 — set 일 수 있고, 걸면 정답이 막힌다",
    "leak-passed-to-call": "인자로 넘어간 뒤의 수명은 이 분석이 못 따라간다",
}

CASES: list[tuple[str, str, str | None, bool, str]] = []


def bad(sid: str, lang: str, rule: str, source: str, *, blocking: bool = True) -> None:
    CASES.append((sid, lang, rule, blocking, source))


def good(sid: str, lang: str, source: str) -> None:
    CASES.append((sid, lang, None, False, source))


# ── ① sql-interpolated ──────────────────────────────────────────────
bad("sql-py-fstring", "python", "sql-interpolated", 'q = f"SELECT id FROM users WHERE id = {uid}"')
bad("sql-py-percent", "python", "sql-interpolated", 'q = "SELECT id FROM t WHERE id = %s" % uid')
bad("sql-py-concat", "python", "sql-interpolated", 'q = "SELECT id FROM t WHERE name = " + name')
bad("sql-py-format", "python", "sql-interpolated", 'q = "DELETE FROM s WHERE uid = {}".format(uid)')
bad("sql-py-update", "python", "sql-interpolated", 'q = "UPDATE t SET a = 1 WHERE id = %d" % uid')
bad("sql-py-like", "python", "sql-interpolated", 'q = f"SELECT a FROM b WHERE n LIKE {pat}"')
bad("sql-py-ident", "python", "sql-interpolated", 'q = f"SELECT id FROM {table} WHERE ok = 1"', blocking=False)
bad(
    "sql-java-concat",
    "java",
    "sql-interpolated",
    'class R { void f(String u) { String q = "SELECT id FROM t WHERE id = " + u; } }',
)
bad(
    "sql-kt-template",
    "kotlin",
    "sql-interpolated",
    'class R { fun f(u: String) { val q = "SELECT id FROM t WHERE id = $u" } }',
)
bad(
    "sql-ts-template",
    "ts",
    "sql-interpolated",
    "export function f(id: string) { return db.q(`SELECT id FROM t WHERE id = ${id}`); }",
)
bad(
    "sql-cs-interp",
    "csharp",
    "sql-interpolated",
    'class R { void F() { var q = $"SELECT id FROM t WHERE id = {0}"; } }',
)
bad(
    "sql-go-sprintf",
    "go",
    "sql-interpolated",
    'func f(u string) { q := fmt.Sprintf("SELECT id FROM t WHERE id = %s", u) }',
)
good("sql-py-bound", "python", 'cur.execute("SELECT id FROM t WHERE id = ?", (uid,))')
good("sql-py-bound-pct", "python", 'cur.execute("SELECT id FROM t WHERE id = %s", (uid,))')
good("sql-py-const", "python", 'QUERY = "SELECT id FROM users WHERE active = 1"')
good("sql-py-prose", "python", 'msg = f"Selected {n} rows from the {kind} view"')
good("sql-py-literal-hole", "python", 'q = f"SELECT id FROM t WHERE id = {1}"')
good("sql-java-prepared", "java", 'class R { void f() { c.prepareStatement("SELECT id FROM t WHERE id = ?"); } }')
good(
    "sql-java-placeholders",
    "java",
    'class R { String f(String h) { return "SELECT id FROM t WHERE id IN (" + h + ")"; } }',
)
good("sql-java-values", "java", 'class R { String f(String h) { return "INSERT INTO t (a) VALUES (" + h + ")"; } }')
good("sql-java-comment", "java", 'class R { void f() { /* SELECT id FROM t WHERE id = " + x */ int a = 1; } }')
good("sql-ts-param", "ts", 'export function f(id: string) { return db.q("SELECT id FROM t WHERE id = $1", [id]); }')
good("sql-ts-cli-usage", "ts", "const s = `Usage: cli --from <file> --merge --locale <${LOCALES.join('|')}>`;")
good("sql-ts-interp-expr", "ts", "const s = `updated ${rows.join(', ')} rows`;")
good("sql-ts-clause-only-in-hole", "ts", "const s = `update count = ${rows.join(',')} done`;")
good("sql-ts-not-sql", "ts", "const s = `deleted ${n} entries from cache`;")
good("sql-go-param", "go", 'func f(u string) { db.Query("SELECT id FROM t WHERE id = $1", u) }')
good("sql-kt-const", "kotlin", 'class R { val q = "SELECT id FROM users WHERE active = 1" }')
# 실코퍼스에서 손검사로 건져 온 산문 — 동사와 절을 **함께** 가졌지만 질의문이 아닌 것들.
# (자사 트리 2건 · helios 2건 · pi 3건 · platty 1건. pi 의 `tool-stats.ts` 는 HTML 대시보드
#  템플릿인데 **막는** 판정이 떴다 — 산문 하나가 작업을 세울 수 있었다는 뜻이다.)
good("sql-py-ui-merge-into", "python", "ui.step(f\"plan: merge into '{title}' ({slug}, {why})\")")
good("sql-py-prose-mid-select", "python", 'body = f"Before work, select and load {name} — run it directly from PATH"')
good(
    "sql-ts-error-merge-into",
    "ts",
    "export function f(a: string, b: string) { throw new Error(`edits ${a} and ${b} overlap. "
    "Merge them into one edit or target disjoint regions.`); }",
)
good(
    "sql-ts-html-delete",
    "ts",
    'export function f(id: string) { return `<button data-id="${id}">Delete</button>'
    '<p class="from-cache">cached</p>`; }',
)
# 동사가 문장 첫머리에 서는 자리 넷 — 좁힌 자가 이것들까지 놓치면 규칙이 죽은 것이다.
bad("sql-py-multiline", "python", "sql-interpolated", 'q = f"""\n    SELECT id\n    FROM t\n    WHERE id = {uid}\n"""')
bad("sql-py-cte", "python", "sql-interpolated", 'q = f"WITH r AS (SELECT id FROM u WHERE k = {key}) SELECT a FROM t"')
bad("sql-py-explain", "python", "sql-interpolated", 'q = f"EXPLAIN SELECT a FROM t WHERE id = {uid}"')
bad(
    "sql-java-second-literal",  # 한 문장에 리터럴이 둘 — 질의를 **여는** 리터럴이 첫째가 아니다
    "java",
    "sql-interpolated",
    'class R { String f(String u) { return log("q: ") + "SELECT id FROM t WHERE id = " + u; } }',
)

# ── ② swallowed-exception ───────────────────────────────────────────
bad(
    "exc-py-broad",
    "python",
    "swallowed-exception",
    "def f():\n    try:\n        g()\n    except Exception:\n        pass\n",
)
bad("exc-py-bare", "python", "swallowed-exception", "def f():\n    try:\n        g()\n    except:\n        pass\n")
bad(
    "exc-py-base",
    "python",
    "swallowed-exception",
    "def f():\n    try:\n        g()\n    except BaseException:\n        pass\n",
)
bad(
    "exc-py-ellipsis",
    "python",
    "swallowed-exception",
    "def f():\n    try:\n        g()\n    except Exception:\n        ...\n",
)
bad(
    "exc-py-narrow",
    "python",
    "swallowed-exception",
    "def f():\n    try:\n        g()\n    except ValueError:\n        pass\n",
    blocking=False,
)
bad("exc-java-empty", "java", "swallowed-exception", "class J { void f() { try { g(); } catch (Exception e) { } } }")
bad("exc-kt-empty", "kotlin", "swallowed-exception", "class J { fun f() { try { g() } catch (e: Exception) { } } }")
bad("exc-ts-empty", "ts", "swallowed-exception", "export function f() { try { g(); } catch (e) { } }")
bad("exc-cs-empty", "csharp", "swallowed-exception", "class J { void F() { try { G(); } catch (Exception e) { } } }")
good(
    "exc-py-reraise",
    "python",
    "def f():\n    try:\n        g()\n    except OSError as e:\n        raise RuntimeError('x') from e\n",
)
good(
    "exc-py-logged",
    "python",
    "import logging\n\ndef f():\n    try:\n        g()\n    except Exception:\n        logging.exception('x')\n",
)
good(
    "exc-py-justified",
    "python",
    "def f():\n    try:\n        g()\n    except Exception:\n        pass  # shutdown path, nothing to report to\n",
)
good("exc-py-fallback", "python", "def f():\n    try:\n        return g()\n    except KeyError:\n        return None\n")
good("exc-py-finally", "python", "def f(h):\n    try:\n        return h.read()\n    finally:\n        h.close()\n")
good(
    "exc-java-rethrow",
    "java",
    "class J { void f() { try { g(); } catch (IOException e) { throw new IllegalStateException(e); } } }",
)
good(
    "exc-java-justified",
    "java",
    "class J { void f() { try { g(); } catch (Exception e) { // nothing left to report to\n } } }",
)
good("exc-java-string", "java", 'class J { String h() { return "write catch (Exception e) { } with a reason"; } }')
good("exc-ts-handled", "ts", 'export function f() { try { g(); } catch (e) { throw new Error("x " + String(e)); } }')
good("exc-ts-justified", "ts", "export function f() { try { g(); } catch (e) { /* best effort */ } }")
good("exc-go-none", "go", "func f() error {\n\tif err := g(); err != nil {\n\t\treturn err\n\t}\n\treturn nil\n}\n")
good("exc-rust-none", "rust", "fn f() -> Result<(), E> {\n    g()?;\n    Ok(())\n}\n")

# ── ③ call-no-timeout ───────────────────────────────────────────────
bad("to-requests-get", "python", "call-no-timeout", "import requests\n\ndef f(u):\n    return requests.get(u)\n")
bad(
    "to-requests-post",
    "python",
    "call-no-timeout",
    "import requests\n\ndef f(u, d):\n    return requests.post(u, json=d)\n",
)
bad("to-httpx", "python", "call-no-timeout", "import httpx\n\ndef f(u):\n    return httpx.get(u)\n")
bad(
    "to-urlopen",
    "python",
    "call-no-timeout",
    "from urllib.request import urlopen\n\ndef f(u):\n    return urlopen(u)\n",
)
good("to-with-timeout", "python", "import requests\n\ndef f(u):\n    return requests.get(u, timeout=5)\n")
good("to-post-timeout", "python", "import requests\n\ndef f(u, d):\n    return requests.post(u, json=d, timeout=3)\n")
good("to-kwargs", "python", "import requests\n\ndef f(u, **kw):\n    return requests.get(u, **kw)\n")
good("to-dict-get", "python", "def f(cache, k):\n    return cache.get(k)\n")
good("to-session-attr", "python", "def f(s, u):\n    return s.get(u, timeout=2)\n")

# ── ④ secret-literal ────────────────────────────────────────────────
bad("sec-py-apikey", "python", "secret-literal", 'API_KEY = "sk9fJ2kdlQ8vNzXr41mPq7"')
bad("sec-py-password", "python", "secret-literal", 'db_password = "Zq81mHt4vRn07wLc"')
bad("sec-py-annotated", "python", "secret-literal", 'access_key: str = "AK1a2B3c4D5e6F7g8H9i"')
bad(
    "sec-java-camel",
    "java",
    "secret-literal",
    'class C { static final String clientSecret = "Zx91kdLQ8vNzXr41mPq7aa"; }',
)
bad("sec-ts-token", "ts", "secret-literal", 'export const authToken = "gh7pQ2wErTy8uIo9pAsD4f";')
bad("sec-kt-secret", "kotlin", "secret-literal", 'class C { val apiKey = "kt8sLm2QwErTy91pAsDf" }')
good("sec-py-env", "python", 'import os\n\nAPI_KEY = os.environ["API_KEY"]')
good("sec-py-placeholder", "python", 'API_KEY = "changeme"')
good("sec-py-angle", "python", 'API_KEY = "<your-key-here>"')
good("sec-py-short", "python", 'API_KEY = "abc123"')
good("sec-py-sentence", "python", 'API_KEY_HELP = "set the api key in your environment"')
good("sec-py-url", "python", 'TOKEN_URL = "https://auth.example.com/oauth2/token/v1"')
good("sec-py-path", "python", 'TOKEN_PATH = "/var/run/secrets/token12345"')
good("sec-java-env", "java", 'class C { static final String clientSecret = System.getenv("CLIENT_SECRET"); }')
good("sec-ts-env", "ts", "export const authToken = process.env.AUTH_TOKEN!;")
good("sec-py-name-only", "python", 'API_KEY_HEADER = "X-Api-Key"')

# ── ⑤ tx-external-io ────────────────────────────────────────────────
bad(
    "tx-py-with",
    "python",
    "tx-external-io",
    "import requests\n\ndef f(db, o):\n    with db.atomic():\n        db.save(o)\n        requests.post('https://x', timeout=2)\n",
)
bad(
    "tx-py-decorator",
    "python",
    "tx-external-io",
    "from django.db import transaction\n\n@transaction.atomic\ndef f(db, o, bus):\n    db.save(o)\n    bus.publish(o)\n",
)
bad(
    "tx-java-annot",
    "java",
    "tx-external-io",
    'class S { @Transactional public void f(Order o) { repo.save(o); restTemplate.postForObject("u", o, Void.class); } }',
)
bad(
    "tx-kt-annot",
    "kotlin",
    "tx-external-io",
    'class S { @Transactional fun f(o: Order) { repo.save(o); kafkaTemplate.send("t", o) } }',
)
good(
    "tx-py-outbox",
    "python",
    "def f(db, o, outbox):\n    with db.atomic():\n        db.save(o)\n        outbox.record(o)\n",
)
good(
    "tx-py-after",
    "python",
    "from django.db import transaction\n\ndef f(db, o, bus):\n    with transaction.atomic():\n        db.save(o)\n    bus.publish(o)\n",
)
good("tx-py-no-tx", "python", "import requests\n\ndef f(o):\n    requests.post('https://x', json=o, timeout=2)\n")
good("tx-java-outbox", "java", "class S { @Transactional public void f(Order o) { repo.save(o); outbox.record(o); } }")
good("tx-java-iface", "java", "interface S { @Transactional void f(Order o); }")
good(
    "tx-java-no-annot", "java", 'class S { public void f(Order o) { restTemplate.postForObject("u", o, Void.class); } }'
)

# ── ⑥ money-float ───────────────────────────────────────────────────
bad("money-py-annot", "python", "money-float", "class O:\n    amount: float = 0.0\n")
bad("money-py-arg", "python", "money-float", "def charge(price: float) -> None:\n    pass\n")
bad("money-py-cast", "python", "money-float", "def f(balance):\n    return float(balance)\n")
bad("money-java-double", "java", "money-float", "class O { private double amount; }")
bad("money-java-float", "java", "money-float", "class O { private float invoice; }")
bad("money-kt-double", "kotlin", "money-float", "class O { val price: Double = 0.0 }")
good("money-py-decimal", "python", "from decimal import Decimal\n\nclass O:\n    amount: Decimal = Decimal('0')\n")
good("money-py-minor", "python", "class O:\n    amount_cents: int = 0\n")
good("money-py-rate", "python", "def f(usd_to_vnd_rate: float) -> float:\n    return usd_to_vnd_rate\n")
good("money-py-count", "python", "def f(total: float, factor: float) -> float:\n    return total * factor\n")
good("money-py-ratio", "python", "def f(discount_percent: float) -> float:\n    return discount_percent\n")
good("money-java-bigdecimal", "java", "class O { private BigDecimal amount; }")
good("money-java-rate", "java", "class O { private double usdToVndRate; }")
good("money-java-count", "java", "class O { private double totalWeight; }")

# ── ⑦ naive-now ─────────────────────────────────────────────────────
bad(
    "now-utcnow",
    "python",
    "naive-now",
    "from datetime import datetime\n\ndef f():\n    return datetime.utcnow()\n",
    blocking=False,
)
bad(
    "now-bare",
    "python",
    "naive-now",
    "from datetime import datetime\n\ndef f():\n    return datetime.now()\n",
    blocking=False,
)
good(
    "now-aware",
    "python",
    "from datetime import datetime, timezone\n\ndef f():\n    return datetime.now(timezone.utc)\n",
)
good("now-monotonic", "python", "import time\n\ndef f():\n    return time.monotonic()\n")
good("now-other-now", "python", "def f(clock):\n    return clock.now()\n")

# ── ⑧ unclosed-acquire ──────────────────────────────────────────────
bad("leak-open", "python", "unclosed-acquire", "def f(p):\n    h = open(p)\n    return h.read()\n")
bad("leak-open-chained", "python", "unclosed-acquire", "import json\n\ndef f(p):\n    return json.load(open(p))\n")
bad(
    "leak-popen",
    "python",
    "unclosed-acquire",
    "import subprocess\n\ndef f(c):\n    p = subprocess.Popen(c)\n    return 1\n",
)
bad(
    "leak-alias-only",
    "python",
    "unclosed-acquire",
    "import subprocess\n\ndef f(c):\n    p = subprocess.Popen(c)\n    q = p\n",
)
bad(
    "leak-pool",
    "python",
    "unclosed-acquire",
    "from concurrent.futures import ThreadPoolExecutor\n\ndef f():\n    e = ThreadPoolExecutor()\n    return 1\n",
)
bad(
    "leak-socket",
    "python",
    "unclosed-acquire",
    "import socket\n\ndef f(h):\n    s = socket.socket()\n    s.connect((h, 80))\n",
)
bad("leak-passed-to-call", "python", "unclosed-acquire", "def f(p, sink):\n    h = open(p)\n    sink(h)\n")
good("leak-with", "python", "def f(p):\n    with open(p) as h:\n        return h.read()\n")
# 여는 실패와 읽는 실패를 따로 다루려면 획득이 `with` 밖으로 나온다 — 그래도 닫히는 형상이다.
good(
    "leak-with-held-name",
    "python",
    "def f(p, log):\n    try:\n        h = open(p)\n    except OSError:\n        log('open failed')\n"
    "        return None\n    with h:\n        return h.read()\n",
)
good(
    "leak-try-finally",
    "python",
    "def f(p):\n    h = open(p)\n    try:\n        return h.read()\n    finally:\n        h.close()\n",
)
good("leak-returned", "python", "def f(p):\n    return open(p)\n")
good(
    "leak-attribute",
    "python",
    "import subprocess\n\nclass S:\n    def f(self, c):\n        p = subprocess.Popen(c)\n        self.p = p\n",
)
good("leak-subscript", "python", "import subprocess\n\ndef f(c, t):\n    p = subprocess.Popen(c)\n    t['proc'] = p\n")
good(
    "leak-alias-then-handoff",
    "python",
    "import subprocess\n\nclass S:\n    def f(self, c):\n        p = subprocess.Popen(c)\n        q = p\n        self.p = p\n",
)
good(
    "leak-dict-literal",
    "python",
    "import subprocess\n\ndef f(c):\n    p = subprocess.Popen(c)\n    return {'proc': p}\n",
)
good(
    "leak-list-append",
    "python",
    "import subprocess\n\ndef f(c, pool):\n    p = subprocess.Popen(c)\n    pool.append(p)\n",
)
good("leak-os-open", "python", "import os\n\ndef f(p):\n    fd = os.open(p, os.O_RDONLY)\n    os.close(fd)\n")
good(
    "leak-webbrowser",
    "python",
    "import webbrowser\n\ndef f(u):\n    if not webbrowser.open(u):\n        raise OSError\n",
)
good(
    "leak-detached",
    "python",
    "import subprocess\n\ndef f(e):\n    subprocess.Popen([e], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)\n",
)
good(
    "leak-attr-assign-direct",
    "python",
    "import subprocess\n\nclass S:\n    def f(self, c):\n        self.p = subprocess.Popen(c)\n",
)

# ── ⑨ cache-unbounded / unbounded-accumulator ───────────────────────
bad(
    "cache-none",
    "python",
    "cache-unbounded",
    "from functools import lru_cache\n\n@lru_cache(maxsize=None)\ndef f(t):\n    return t.split()\n",
)
bad(
    "cache-plain",
    "python",
    "cache-unbounded",
    "from functools import cache\n\n@cache\ndef f(t):\n    return t.split()\n",
)
bad("grow-list", "python", "unbounded-accumulator", "SEEN = []\n\ndef note(x):\n    SEEN.append(x)\n", blocking=False)
bad("grow-dict", "python", "unbounded-accumulator", "SEEN = {}\n\ndef note(k, v):\n    SEEN[k] = v\n", blocking=False)
good(
    "cache-bounded",
    "python",
    "from functools import lru_cache\n\n@lru_cache(maxsize=512)\ndef f(t):\n    return t.split()\n",
)
good("cache-no-args", "python", "from functools import cache\n\n@cache\ndef f():\n    return 1\n")
good("cache-plain-function", "python", "def f(t):\n    return t.split()\n")
good(
    "cache-manual-dict",
    "python",
    "def f(t, memo):\n    if t not in memo:\n        memo[t] = t.split()\n    return memo[t]\n",
)
good(
    "grow-deque-maxlen",
    "python",
    "from collections import deque\n\nSEEN = deque(maxlen=100)\n\ndef note(x):\n    SEEN.append(x)\n",
)
good("grow-cleared", "python", "SEEN = {}\n\ndef note(k, v):\n    SEEN[k] = v\n\ndef reset():\n    SEEN.clear()\n")
good("grow-const-table", "python", "RULES = []\nRULES.append(('a', 1))\nRULES.append(('b', 2))\n")
good("grow-local", "python", "def f(xs):\n    out = []\n    for x in xs:\n        out.append(x)\n    return out\n")

# ── ⑩ quadratic-scan ────────────────────────────────────────────────
bad(
    "cost-list-in-loop",
    "python",
    "quadratic-scan",
    "def f(xs):\n    seen = []\n    for x in xs:\n        if x in seen:\n            continue\n        seen.append(x)\n    return seen\n",
)
bad(
    "cost-param-unknown",
    "python",
    "quadratic-scan",
    "def f(xs, allowed):\n    return [x for x in xs if x in allowed]\n",
)
good(
    "cost-set", "python", "def f(xs, allowed):\n    lookup = set(allowed)\n    return [x for x in xs if x in lookup]\n"
)
good(
    "cost-set-literal",
    "python",
    "def f(xs):\n    seen = set()\n    for x in xs:\n        if x in seen:\n            continue\n        seen.add(x)\n    return seen\n",
)
good(
    "cost-const-tuple",
    "python",
    "SUFFIX = ('.py', '.ts')\n\ndef f(xs):\n    return [x for x in xs if x.endswith(SUFFIX)]\n",
)
good("cost-no-loop", "python", "def f(x, xs):\n    return x in xs\n")

# ── ⑪ C 계열 ────────────────────────────────────────────────────────
bad(
    "c-alloc-leak",
    "c",
    "c-alloc-unfreed",
    "int f(int n) {\n    char *b = malloc(n);\n    if (!b) return -1;\n    b[0] = 0;\n    return 0;\n}\n",
)
bad(
    "c-alloc-leak-return-use",
    "c",
    "c-alloc-unfreed",
    "int f(int n) {\n    char *b = malloc(n);\n    if (!b) return -1;\n    return b[0];\n}\n",
)
bad(
    "c-alloc-unchecked",
    "c",
    "c-alloc-unchecked",
    "int f(int n) {\n    char *b = malloc(n);\n    b[0] = 0;\n    free(b);\n    return 0;\n}\n",
)
bad(
    "c-realloc-self",
    "c",
    "c-realloc-self-assign",
    "int f(char *p, int n) {\n    p = realloc(p, n);\n    free(p);\n    return 0;\n}\n",
)
bad(
    "c-handle-leak",
    "c",
    "c-handle-unclosed",
    'int f(const char *p) {\n    FILE *h = fopen(p, "r");\n    if (!h) return -1;\n    fgetc(h);\n    return 0;\n}\n',
)
bad(
    "c-handle-leak-return-use",
    "c",
    "c-handle-unclosed",
    'int f(const char *p) {\n    FILE *h = fopen(p, "r");\n    if (!h) return -1;\n    return fgetc(h);\n}\n',
)
bad("c-copy-strcpy", "c", "c-unbounded-copy", "void f(char *d, const char *s) {\n    strcpy(d, s);\n}\n")
bad("c-copy-sprintf", "c", "c-unbounded-copy", 'void f(char *d, int n) {\n    sprintf(d, "%d", n);\n}\n')
bad(
    "c-quadratic",
    "c",
    "c-quadratic-scan",
    "void f(char *s) {\n    for (size_t i = 0; i < strlen(s); i++) {\n        s[i] = 0;\n    }\n}\n",
)
good(
    "c-alloc-freed",
    "c",
    "int f(int n) {\n    char *b = malloc(n);\n    if (!b) return -1;\n    free(b);\n    return 0;\n}\n",
)
good(
    "c-alloc-returned", "c", "char *f(int n) {\n    char *b = malloc(n);\n    if (!b) return NULL;\n    return b;\n}\n"
)
good(
    "c-alloc-returned-cast",
    "c",
    "char *f(int n) {\n    char *b = malloc(n);\n    if (!b) return NULL;\n    return (char *)b;\n}\n",
)
good(
    "c-alloc-returned-ternary",
    "c",
    "char *f(int n, int c) {\n    char *b = malloc(n);\n    if (!b) return NULL;\n    return c ? b : NULL;\n}\n",
)
good("c-alloc-out-param", "c", "int f(int n, char **out) {\n    *out = malloc(n);\n    return *out ? 0 : -1;\n}\n")
good(
    "c-alloc-handed-off",
    "c",
    "int f(int n) {\n    char *b = malloc(n);\n    if (!b) return -1;\n    take(b);\n    return 0;\n}\n",
)
good(
    "c-realloc-tmp",
    "c",
    "int f(char **p, int n) {\n    char *t = realloc(*p, n);\n    if (!t) return -1;\n    *p = t;\n    return 0;\n}\n",
)
good(
    "c-realloc-other-name",
    "c",
    "int f(char *a, char *b, int n) {\n    b = realloc(a, n);\n    if (!b) return -1;\n    free(b);\n    return 0;\n}\n",
)
good(
    "c-realloc-none",
    "c",
    "int f(int n) {\n    char *b = malloc(n);\n    if (!b) return -1;\n    free(b);\n    return 0;\n}\n",
)
good(
    "c-handle-closed",
    "c",
    'int f(const char *p) {\n    FILE *h = fopen(p, "r");\n    if (!h) return -1;\n    int c = fgetc(h);\n    fclose(h);\n    return c;\n}\n',
)
good("c-handle-returned", "c", 'FILE *f(const char *p) {\n    FILE *h = fopen(p, "r");\n    return h;\n}\n')
good(
    "c-handle-field",
    "c",
    'int f(struct S *s, const char *p) {\n    s->fp = fopen(p, "r");\n    return s->fp ? 0 : -1;\n}\n',
)
good("c-copy-snprintf", "c", 'void f(char *d, size_t n, const char *s) {\n    snprintf(d, n, "%s", s);\n}\n')
good("c-copy-strncat", "c", "void f(char *d, size_t n, const char *s) {\n    strncat(d, s, n);\n}\n")
good("c-copy-memcpy-sized", "c", "void f(char *d, const char *s, size_t n) {\n    memcpy(d, s, n);\n}\n")
good(
    "c-linear",
    "c",
    "void f(char *s) {\n    size_t n = strlen(s);\n    for (size_t i = 0; i < n; i++) {\n        s[i] = 0;\n    }\n}\n",
)
good(
    "c-strlen-not-in-header",
    "c",
    "void f(char *s) {\n    for (size_t i = 0; i < 10; i++) {\n        size_t n = strlen(s);\n        (void)n;\n    }\n}\n",
)
good(
    "c-strlen-while", "c", "void f(char *s) {\n    size_t n = strlen(s);\n    while (n > 0) {\n        n--;\n    }\n}\n"
)

# ── ⑫ unit-oversize / unit-deep ─────────────────────────────────────
bad("shape-oversize", "python", "unit-oversize", "def big():\n" + "".join(f"    x{i} = f({i})\n" for i in range(90)))
bad(
    "shape-deep",
    "python",
    "unit-deep",
    "def deep(rows):\n    for a in rows:\n        for b in a:\n            for c in b:\n                for d in c:\n                    for e in d:\n                        if e:\n                            return e\n    return None\n",
)
good("shape-small", "python", "def f():\n    return 1\n")
good(
    "shape-guarded",
    "python",
    "def f(rows):\n    if not rows:\n        return None\n    for a in rows:\n        if a:\n            return a\n    return None\n",
)
good(
    "shape-data-literal",
    "python",
    "def table():\n    return {\n" + "".join(f"        'k{i}': {i},\n" for i in range(90)) + "    }\n",
)


# ── 판정 ────────────────────────────────────────────────────────────


def judge(source: str, lang: str) -> list[Finding]:
    """게이트 두 개가 이 원문에 대해 내는 판정 전체. git 도 파일시스템도 안 탄다 (순수 함수만)."""
    if lang == "python":
        units = craft_rules.units(source)
        if units is None:
            return []
        spans = list(units.values())
        found = craft_rules.shape_findings("p.py", units, None)
        found += craft_rules.pattern_findings(source, "p.py", spans)
        found += thor_rules.findings(source, "p.py", spans) or []
        return found
    units = craft_lex.units(source, lang)
    if units is None:
        return []
    spans = list(units.values())
    found = craft_rules.shape_findings("p", units, None)
    if lang in craft_lex.C_FAMILY:
        found += craft_c.pattern_findings(source, "p", spans, lang)
    found += thor_lex.findings(source, "p", spans, lang) or []
    return found


_JUDGED: dict[str, list[Finding]] = {}


def _for(sid: str, source: str, lang: str) -> list[Finding]:
    if sid not in _JUDGED:
        _JUDGED[sid] = judge(source, lang)
    return _JUDGED[sid]


BLOCKING_RULES = frozenset(
    {
        "sql-interpolated", "swallowed-exception", "call-no-timeout", "secret-literal",
        "tx-external-io", "money-float", "unclosed-acquire", "cache-unbounded",
        "quadratic-scan", "unit-oversize", "unit-deep", "c-alloc-unfreed",
        "c-alloc-unchecked", "c-realloc-self-assign", "c-handle-unclosed",
        "c-unbounded-copy", "c-quadratic-scan",
    }
)  # fmt: skip

# 음성 표본이 어느 규칙의 대조군인가 — 접두사로 잇는다. 표를 두 벌 들고 다니지 않기 위해서다.
FAMILY: tuple[tuple[str, frozenset[str]], ...] = (
    ("sql-", frozenset({"sql-interpolated"})),
    ("exc-", frozenset({"swallowed-exception"})),
    ("to-", frozenset({"call-no-timeout"})),
    ("sec-", frozenset({"secret-literal"})),
    ("tx-", frozenset({"tx-external-io"})),
    ("money-", frozenset({"money-float"})),
    ("now-", frozenset({"naive-now"})),
    ("leak-", frozenset({"unclosed-acquire"})),
    ("cache-", frozenset({"cache-unbounded"})),
    ("grow-", frozenset({"unbounded-accumulator"})),
    ("cost-", frozenset({"quadratic-scan"})),
    ("shape-", frozenset({"unit-oversize", "unit-deep"})),
    ("c-alloc-", frozenset({"c-alloc-unfreed", "c-alloc-unchecked"})),
    ("c-realloc-", frozenset({"c-realloc-self-assign"})),
    ("c-handle-", frozenset({"c-handle-unclosed"})),
    ("c-copy-", frozenset({"c-unbounded-copy"})),
    ("c-quadratic", frozenset({"c-quadratic-scan"})),
    ("c-linear", frozenset({"c-quadratic-scan"})),
    ("c-strlen-", frozenset({"c-quadratic-scan"})),
)


def family_of(sid: str) -> frozenset[str]:
    for prefix, rules in sorted(FAMILY, key=lambda kv: -len(kv[0])):
        if sid.startswith(prefix):
            return rules
    raise AssertionError(f"{sid} 에 대조군 규칙이 없다 — FAMILY 에 접두사를 등록해라")


POSITIVES = [c for c in CASES if c[2] is not None]
NEGATIVES = [c for c in CASES if c[2] is None]


class CorpusIdentity(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = [c[0] for c in CASES]
        self.assertEqual(len(ids), len(set(ids)), "표본 id 가 겹치면 캐시가 서로를 덮는다")

    def test_every_sample_parses(self):
        """미판정(⊥)으로 떨어진 표본은 아무것도 재지 못한다 — 조용히 통과하면 코퍼스가 거짓말한다."""
        for sid, lang, _rule, _blocking, source in CASES:
            with self.subTest(sid=sid):
                units = craft_rules.units(source) if lang == "python" else craft_lex.units(source, lang)
                self.assertIsNotNone(units, f"{sid} 의 구문을 읽지 못했다")

    def test_every_negative_has_a_family(self):
        for sid, _lang, rule, _blocking, _source in CASES:
            if rule is None:
                with self.subTest(sid=sid):
                    self.assertTrue(family_of(sid))


class Recall(unittest.TestCase):
    """잡아야 할 것을 잡는가. 문서화된 미검출은 표에 남기되 계산에서 뺀다."""

    def test_every_positive_fires_its_rule(self):
        missed = []
        for sid, lang, rule, _blocking, source in POSITIVES:
            if sid in EXPECTED_MISS:
                continue
            if not any(f.rule == rule for f in _for(sid, source, lang)):
                missed.append(f"{sid} (기대 {rule}, 실제 {[f.rule for f in _for(sid, source, lang)] or '없음'})")
        self.assertEqual([], missed, "재현율이 떨어졌다")

    def test_documented_misses_are_still_missed(self):
        """안 잡기로 한 것이 잡히기 시작하면 그것도 변화다 — 좋은 변화일 수 있으니 표를 갱신해라."""
        for sid, lang, rule, _blocking, source in POSITIVES:
            if sid not in EXPECTED_MISS:
                continue
            with self.subTest(sid=sid):
                self.assertFalse(
                    any(f.rule == rule for f in _for(sid, source, lang)),
                    f"{sid} 이 이제 잡힌다 — EXPECTED_MISS 에서 빼고 이유({EXPECTED_MISS[sid]})를 지워라",
                )

    def test_severity_is_what_the_table_says(self):
        for sid, lang, rule, blocking, source in POSITIVES:
            if sid in EXPECTED_MISS:
                continue
            hits = [f for f in _for(sid, source, lang) if f.rule == rule]
            with self.subTest(sid=sid):
                self.assertEqual(blocking, max(f.blocking for f in hits), f"{sid} 의 심각도가 바뀌었다")


class FalsePositives(unittest.TestCase):
    """정답 쪽에서 판정이 뜨는가. 막는 오탐은 0 이어야 한다 — 게이트의 정의가 그것이다."""

    def test_no_negative_is_blocked(self):
        blocked = []
        for sid, lang, _rule, _blocking, source in NEGATIVES:
            for finding in _for(sid, source, lang):
                if finding.blocking and finding.rule in family_of(sid):
                    blocked.append(f"{sid}: {finding.rule} — {finding.detail}")
        self.assertEqual([], blocked, "정답 코드가 막혔다 — 게이트가 자기 처방을 결함으로 읽는다")

    def test_note_level_false_positives_stay_where_they_are(self):
        """알림 오탐은 설계상 남아 있는 것들이다. 늘어나면 알아야 하므로 수를 못박는다.

        지금 남은 둘은 근거 주석이 달린 침묵(알림으로 낮춘 것)과 물음표 목록 조립(식별자 자리)이다.
        """
        noted = sorted(
            sid
            for sid, lang, _rule, _blocking, source in NEGATIVES
            for f in _for(sid, source, lang)
            if not f.blocking and f.rule in family_of(sid)
        )
        self.assertEqual(
            [
                "exc-java-justified",  # 근거 주석이 있는 침묵 — 지우지 않고 알림으로 낮춘다
                "exc-py-justified",
                "exc-ts-justified",
                "sql-java-placeholders",  # 물음표 목록 조립 — 식별자 자리로 읽어 알림에 그친다
                "sql-java-values",
            ],
            noted,
        )


class BorrowedCode(unittest.TestCase):
    """남의 코드는 이 변경의 책임이 아니다 — 그러나 **안 봤다**고 말해야 한다.

    래칫이 여기서 안 통하는 이유: 래칫은 base 와 비교하는데 추적되지 않은 파일에는 base 가 없다.
    벤더링 한 벌을 새로 떨구면 그 전부가 이번 변경의 책임이 된다 (실측 52건).
    """

    def test_vendored_paths_are_not_judged(self):
        for rel in (
            "src/app/vendor/lib/x.py",
            "web/node_modules/pkg/index.js",
            "app/dist/assets/index-BkFzql5p.js",
            "third_party/zlib/zlib.c",
            "ref/other-repo/src/main.py",
        ):
            with self.subTest(rel=rel):
                self.assertIsNotNone(health.borrowed(rel))

    def test_first_party_paths_are_still_judged(self):
        """제외가 넓어지면 게이트가 조용히 꺼진다 — 특히 우리 스킬 코드가 사는 자리."""
        for rel in (
            "src/asgard/craft_rules.py",
            "src/asgard/assets/skill_plugins/hwpx-skill/skills/hwpx/asgard_hwpx.py",
            "tests/test_craft.py",
            "app/distribution/main.py",  # `dist` 로 시작할 뿐 `dist/` 가 아니다
        ):
            with self.subTest(rel=rel):
                self.assertIsNone(health.borrowed(rel))

    def test_exclusion_reports_as_undetermined_not_as_clean(self):
        """조용히 통과시키면 게이트가 아니라 알리바이가 된다 — 두 게이트 모두에서 고정한다."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        rel = "vendor/lib.py"
        os.makedirs(os.path.join(root, "vendor"), exist_ok=True)
        with open(os.path.join(root, rel), "w", encoding="utf-8") as handle:
            handle.write("def f():\n    try:\n        g()\n    except Exception:\n        pass\n")
        for report in (craft.judge(root, [rel], "NOBASE"), thor_gate.judge(root, [rel], "NOBASE")):
            self.assertEqual((), report.judged)
            self.assertEqual(1, len(report.undetermined))
            self.assertEqual((), report.blocking)

    def test_the_same_code_outside_a_vendor_path_is_judged(self):
        """제외가 경로 때문인지 내용 때문인지 헷갈리면 안 된다 — 같은 원문으로 대조한다."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        rel = "app/lib.py"
        os.makedirs(os.path.join(root, "app"), exist_ok=True)
        with open(os.path.join(root, rel), "w", encoding="utf-8") as handle:
            handle.write("def f():\n    try:\n        g()\n    except Exception:\n        pass\n")
        report = thor_gate.judge(root, [rel], "NOBASE")
        self.assertEqual((rel,), report.judged)
        self.assertEqual(1, len(report.blocking))


class Coverage(unittest.TestCase):
    """이 파일의 진짜 값어치 — 규칙을 더할 때 음성 대조군을 강제한다.

    재현율 숫자는 코퍼스를 쓴 사람이 규칙을 알고 썼으므로 위로 편향된다. 커버리지 강제는
    편향되지 않는다: 대조군 없는 규칙은 오탐률을 아무도 모르는 규칙이고, 그런 규칙이 막기
    시작하면 게이트 전체의 신뢰가 같이 무너진다.
    """

    NEGATIVES_PER_RULE = 3

    def test_every_blocking_rule_has_a_positive(self):
        covered = {c[2] for c in POSITIVES}
        self.assertEqual(set(), BLOCKING_RULES - covered, "막는 규칙인데 진양성 표본이 없다")

    def test_every_blocking_rule_has_enough_negatives(self):
        counts = {rule: 0 for rule in BLOCKING_RULES}
        for sid, _lang, _rule, _blocking, _source in NEGATIVES:
            for rule in family_of(sid) & BLOCKING_RULES:
                counts[rule] += 1
        thin = {r: n for r, n in counts.items() if n < self.NEGATIVES_PER_RULE}
        self.assertEqual({}, thin, f"음성 대조군이 {self.NEGATIVES_PER_RULE}개 미만인 규칙")

    def test_the_corpus_did_not_shrink(self):
        """표본이 줄면 위 숫자들의 뜻도 같이 줄어든다 — 줄이려면 의도적으로 이 수를 내려라."""
        self.assertGreaterEqual(len(POSITIVES), 60)
        self.assertGreaterEqual(len(NEGATIVES), 80)


if __name__ == "__main__":
    unittest.main()
