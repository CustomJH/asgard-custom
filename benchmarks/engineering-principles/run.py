#!/usr/bin/env python3
"""엔지니어링 원칙 배터리 — 아스가르드의 결정론 게이트가 무엇을 잡고 무엇을 놓치는지 잰다.

**왜 산문이 아니라 배터리인가.** "아스가르드는 소프트웨어 엔지니어링 원칙을 지킨다"는 문장은
반증할 수 없다. 반증할 수 있는 형태는 이것이다 — 널리 쓰이는 원칙 목록에서 반례를 하나씩
만들고, 실제 게이트에 그대로 통과시켜, 어느 것이 막히고 어느 것이 조용히 지나가는지 센다.
숫자가 나오는 순간 "지킨다"는 주장은 잡힌 원칙의 목록으로 바뀐다.

**자기가 쓴 배터리는 자기를 잰다.** 규칙을 아는 사람이 사례를 쓰면 무의식적으로 규칙을 비껴간
사례를 쓰게 된다. 그래서 이미 규칙이 있는 원칙을 **양성 대조**(`control`)로 섞어 둔다 — 그것이
안 잡히면 게이트가 아니라 이 배터리가 고장 난 것이고, 실행이 그 자리에서 실패한다. 사례 목록은
게이트 소스가 아니라 널리 쓰이는 코드 리뷰 축에서 뽑았다.

**한 사례가 걸렸다고 그 원칙이 덮인 것은 아니다.** 중복 사례가 함수 길이 규칙에 걸리는 것은
중복을 잡은 것이 아니다. 그래서 규칙마다 어느 원칙을 재는지 표(`_RULE_PRINCIPLE`)로 두고,
사례의 원칙과 발화한 규칙의 원칙이 같을 때만 덮였다고 센다.

못 재는 것: 게이트가 판정하지 않는 축(설계 대안 선택, 요구사항 해석, 이름이 사람에게 좋은지)과,
규칙은 있지만 파이썬 밖 언어에서만 도는 것. 그 둘은 보고서에 미달로 남는다.

실행: `uv run --no-project python benchmarks/engineering-principles/run.py [--json]`
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

# 규칙 하나가 재는 원칙. 사례가 걸렸을 때 "그 원칙을 잡은 것"인지 "다른 이유로 걸린 것"인지
# 가르는 표다 — 이게 없으면 함수 길이 규칙 하나가 모든 원칙을 덮은 것처럼 보인다.
_RULE_PRINCIPLE = {
    "unit-oversize": "complexity-size",
    "unit-deep": "complexity-nesting",
    "unit-branchy": "complexity-branching",
    "file-growth": "complexity-size",
    "quadratic-scan": "performance",
    "c-quadratic-scan": "performance",
    "cache-on-method": "resource-management",
    "cache-unbounded": "resource-management",
    "unclosed-acquire": "resource-management",
    "unbounded-accumulator": "resource-management",
    "c-alloc-unfreed": "resource-management",
    "c-handle-unclosed": "resource-management",
    "c-alloc-unchecked": "error-handling",
    "c-realloc-self-assign": "error-handling",
    "c-unbounded-copy": "security-input",
    "swallowed-exception": "error-handling",
    "call-no-timeout": "error-handling",
    "tx-external-io": "error-handling",
    "secret-literal": "security-secret",
    "sql-interpolated": "security-injection",
    "money-float": "correctness",
    "naive-now": "correctness",
    "note-metaphor": "readability-comment",
    "note-jargon": "readability-comment",
    "duplicate-block": "duplication",
    "dead-private": "dead-code",
    "wide-signature": "interface-width",
    "undocumented-public": "documentation",
}

# 자격증명 표본은 조각으로 적는다 — 이름도 값도 통째로 적으면 이 파일 자체가 시크릿 가드에
# 막힌다(Canon 4). 사례 파일에는 이어 붙인 온전한 꼴이 쓰이므로 판정 대상은 그대로다.
_FAKE_NAME = "API" + "_KEY"
_FAKE_VALUE = "sk-live-" + "51H8xQ2eZvKYlo2CdefghijklmnopqrstuvwxyzABCDEF"


@dataclass(frozen=True)
class Case:
    """원칙 하나를 어기는 최소 표본. `control` 이 있으면 그 규칙이 반드시 잡아야 한다."""

    principle: str
    name: str
    source: str
    control: str = ""

    @property
    def path(self) -> str:
        return "case_%s.py" % self.name.replace("-", "_")


# 원칙 분류는 널리 쓰이는 코드 리뷰 축을 따랐다 — 정확성, 오류 처리, 자원, 복잡도, 결합도,
# 중복, 죽은 코드, 이름, 문서, 보안, 성능, 동시성.
CASES: tuple[Case, ...] = (
    Case(
        "error-handling",
        "swallowed-exception",
        control="swallowed-exception",
        source="""
def load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        pass
""",
    ),
    Case(
        "error-handling",
        "ignored-return",
        source='''
import subprocess


def deploy(target):
    """반환 상태를 아무도 안 본다 — 실패해도 배포가 성공으로 보고된다."""
    subprocess.run(["deploy", target], capture_output=True)
    return "deployed"
''',
    ),
    Case(
        "resource-management",
        "unclosed-handle",
        control="unclosed-acquire",
        source="""
def read_config(path):
    handle = open(path, encoding="utf-8")
    body = handle.read()
    return body
""",
    ),
    Case(
        "complexity-size",
        "long-function",
        control="unit-oversize",
        source="def render(rows):\n    out = []\n"
        + "".join("    out.append(rows[%d])\n" % i for i in range(90))
        + "    return out\n",
    ),
    Case(
        "complexity-nesting",
        "deep-nesting",
        control="unit-deep",
        source="""
def walk(tree):
    for branch in tree:
        if branch:
            for leaf in branch:
                if leaf:
                    for twig in leaf:
                        if twig:
                            return twig
    return None
""",
    ),
    Case(
        "complexity-branching",
        "many-branches",
        source="def route(kind):\n"
        + "".join('    if kind == "k%d":\n        return %d\n' % (i, i) for i in range(18))
        + "    return -1\n",
    ),
    Case(
        "performance",
        "quadratic-scan",
        control="quadratic-scan",
        source="""
def overlap(rows):
    seen = list(rows)
    hits = []
    for item in rows:
        if item in seen:
            hits.append(item)
    return hits
""",
    ),
    # 같은 형상인데 훑는 대상이 매개변수다. 규칙이 **일부러** 안 잡는 자리라 양성 대조가 아니다 —
    # 타입을 모르면 set 일 수도 있고, 걸면 올바른 코드를 막는다 (craft_rules._dynamic_sequences).
    # 지우면 다음 사람이 "왜 이건 안 잡히지"를 다시 발견한다.
    Case(
        "performance",
        "quadratic-scan-on-a-parameter",
        source="""
def overlap(left, right):
    hits = []
    for item in left:
        if item in right:
            hits.append(item)
    return hits
""",
    ),
    Case(
        "performance",
        "n-plus-one",
        source='''
def load_authors(session, posts):
    """글마다 질의를 한 번씩 던진다 — 글이 열 배면 왕복도 열 배다."""
    out = []
    for post in posts:
        out.append(session.fetch_author(post.author_id))
    return out
''',
    ),
    Case(
        "security-secret",
        "hardcoded-secret",
        control="secret-literal",
        source='%s = "%s"\n\n\ndef client():\n    return {"Authorization": "Bearer " + %s}\n'
        % (_FAKE_NAME, _FAKE_VALUE, _FAKE_NAME),
    ),
    Case(
        "security-injection",
        "sql-interpolation",
        control="sql-interpolated",
        source="""
def find(session, name):
    return session.execute("SELECT * FROM users WHERE name = '%s'" % name)
""",
    ),
    Case(
        "security-input",
        "unvalidated-path",
        source='''
import os


def serve(root, requested):
    """요청자가 준 경로를 그대로 이어 붙인다 — `../../etc/passwd` 가 막히지 않는다."""
    with open(os.path.join(root, requested), encoding="utf-8") as handle:
        return handle.read()
''',
    ),
    Case(
        "duplication",
        "copy-pasted-block",
        source="""
def build_user(row):
    name = row["name"].strip().lower()
    mail = row["mail"].strip().lower()
    age = int(row.get("age") or 0)
    tags = sorted(set(row.get("tags") or []))
    active = bool(row.get("active"))
    return {"name": name, "mail": mail, "age": age, "tags": tags, "active": active}


def build_admin(row):
    name = row["name"].strip().lower()
    mail = row["mail"].strip().lower()
    age = int(row.get("age") or 0)
    tags = sorted(set(row.get("tags") or []))
    active = bool(row.get("active"))
    return {"name": name, "mail": mail, "age": age, "tags": tags, "active": active}
""",
    ),
    Case(
        "dead-code",
        "unreferenced-private",
        source='''
def public(rows):
    return len(rows)


def _legacy_normalize(rows):
    """아무도 안 부른다 — 옛 경로가 사라진 뒤 남았다."""
    return [r.strip() for r in rows]
''',
    ),
    Case(
        "interface-width",
        "wide-signature",
        source="""
def render(title, rows, width, height, theme, locale, dense, footer, header, sort, page, total):
    return (title, rows, width, height, theme, locale, dense, footer, header, sort, page, total)
""",
    ),
    Case(
        "documentation",
        "undocumented-public",
        source="""
class Ledger:
    def settle(self, run, outcome, at):
        return {"run": run, "outcome": outcome, "at": at}
""",
    ),
    Case(
        "concurrency",
        "unsynchronized-shared-state",
        source='''
import threading

COUNTS = {}


def bump(key):
    """여러 스레드가 같은 dict 를 잠금 없이 고친다."""
    COUNTS[key] = COUNTS.get(key, 0) + 1


def start(keys):
    for key in keys:
        threading.Thread(target=bump, args=(key,)).start()
''',
    ),
    Case(
        "correctness",
        "money-float",
        control="money-float",
        source="""
def total(prices):
    amount = 0.0
    for price in prices:
        amount += float(price)
    return amount
""",
    ),
    Case(
        "readability-comment",
        "metaphor-comment",
        control="note-metaphor",
        source="""
def build(spec):
    # 임베더가 선다
    return spec
""",
    ),
    Case(
        "readability-naming",
        "single-letter-names",
        source="""
def p(a, b, c):
    d = a + b
    e = d * c
    return e
""",
    ),
)


@dataclass
class Result:
    case: Case
    rules: list[str] = field(default_factory=list)

    @property
    def covered(self) -> bool:
        """이 사례의 원칙을 재는 규칙이 실제로 발화했는가 — 다른 이유로 걸린 것은 안 센다."""
        return any(_RULE_PRINCIPLE.get(rule) == self.case.principle for rule in self.rules)

    @property
    def incidental(self) -> list[str]:
        return [r for r in self.rules if _RULE_PRINCIPLE.get(r) != self.case.principle]


def _repo() -> str:
    """사례를 놓을 임시 저장소 — 게이트는 래칫이라 HEAD 라는 기준선이 있어야 돈다."""
    root = tempfile.mkdtemp(prefix="asgard-principles-")
    subprocess.run(["git", "init", "-q", root], check=True, capture_output=True)
    for name, value in (("user.email", "bench@asgard.local"), ("user.name", "bench")):
        subprocess.run(["git", "-C", root, "config", name, value], check=True, capture_output=True)
    with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("# principles battery base\n")
    subprocess.run(["git", "-C", root, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", root, "commit", "-qm", "base"], check=True, capture_output=True)
    return root


def _gate(root: str, verb: list[str], path: str) -> list[str]:
    """게이트 하나를 부르고 막는 판정의 규칙 이름을 준다. 못 부르면 빈 목록."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "asgard", *verb, "--path", path, "--json"],
            cwd=root, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace",
        )  # fmt: skip
        payload = json.loads(proc.stdout or "{}")
    except Exception:
        return []
    found = payload.get("blocking")
    return [str(f.get("rule")) for f in found if isinstance(f, dict)] if isinstance(found, list) else []


GATES = (["craft"], ["thor", "gate"])


def measure() -> list[Result]:
    root = _repo()
    results = []
    for case in CASES:
        with open(os.path.join(root, case.path), "w", encoding="utf-8") as handle:
            handle.write(case.source.lstrip("\n"))
        rules: list[str] = []
        for verb in GATES:
            rules += _gate(root, verb, case.path)
        results.append(Result(case, sorted(set(rules))))
    return results


def controls_missed(results: list[Result]) -> list[str]:
    """양성 대조가 안 잡힌 자리 — 게이트가 아니라 이 배터리가 고장 났다는 뜻이다."""
    return [r.case.name for r in results if r.case.control and r.case.control not in r.rules]


def report(results: list[Result]) -> str:
    covered = [r for r in results if r.covered]
    missed = [r for r in results if not r.covered]
    lines = [
        "engineering principles — %d/%d cases have a rule that measures their principle" % (len(covered), len(results)),
        "",
        "covered:",
    ]
    for row in covered:
        lines.append("  %-22s %-26s %s" % (row.case.principle, row.case.name, ", ".join(row.rules)))
    lines += ["", "missed (no rule measures this principle):"]
    for row in missed:
        tail = "  (tripped %s for another reason)" % ", ".join(row.incidental) if row.incidental else ""
        lines.append("  %-22s %s%s" % (row.case.principle, row.case.name, tail))
    broken = controls_missed(results)
    if broken:
        lines += ["", "BATTERY BROKEN — positive controls not caught: " + ", ".join(broken)]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="engineering principles battery")
    parser.add_argument("--json", action="store_true", help="machine-readable result")
    args = parser.parse_args()
    results = measure()
    if args.json:
        print(
            json.dumps(
                {
                    "cases": len(results),
                    "covered": sum(1 for r in results if r.covered),
                    "controls_missed": controls_missed(results),
                    "results": [
                        {
                            "principle": r.case.principle,
                            "case": r.case.name,
                            "covered": r.covered,
                            "rules": r.rules,
                            "control": r.case.control,
                        }
                        for r in results
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(report(results))
    # 종료 코드는 덮인 비율이 아니라 **계기의 건강**으로 낸다. 못 덮은 원칙은 이 배터리가
    # 보고할 사실이지 실패가 아니다 — 실패로 세면 구멍을 지우는 쪽으로 손이 간다.
    return 1 if controls_missed(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
