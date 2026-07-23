"""숏컷 벤치 — recall 주입 on/off A/B로 "메모리가 탐색을 단축하는가"를 실측.

설계 원칙: 메모리 페이지는 사실의 '위치'만 기록하고 '값'은 기록하지 않는다 —
주입 arm 도 파일을 열어야(증거) 답할 수 있고, 절약되는 것은 탐색뿐이다.
(아스가르드 계약: 숏컷은 탐색을 건너뛰는 것이지 증거를 건너뛰는 게 아니다)

사용:
  python3 bench_shortcut.py build        # 샌드박스+메모리 생성, recall 오프라인 사전검증(0-LLM)
  python3 bench_shortcut.py pilot        # task1 x {on,off} x 1런
  python3 bench_shortcut.py full         # 6 task x {on,off} x 3런 (arm 교차 배치)
결과: shortcut-results.jsonl (런마다 append — 중간 유실 없음)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))  # benchmarks/shortcut-recall → repo root
sys.path.insert(0, os.path.join(REPO, "src"))

SANDBOX = os.path.join(HERE, "shortcut-sandbox")
MEMDIR = os.path.join(HERE, "shortcut-mem")
RESULTS = os.path.join(HERE, "shortcut-results.jsonl")
ASGARD = os.path.join(REPO, ".venv", "bin", "asgard")
RUN_TIMEOUT = 360

# (id, 과업 문구, 심는 파일, 심는 코드 조각, 정답 판정 regex, 메모리 포인터 본문)
FACTS = [
    (
        "retry-ceil",
        "이 저장소에서 재시도 한도(최대 재시도 횟수)가 몇으로 설정돼 있는지 실제 코드에서 확인해서 값만 보고해",
        "src/meridian/core/backoff_math.py",
        "_ATTEMPT_CEIL = 37  # 지수 백오프 이후 포기 지점 — 운영 합의값\n",
        r"\b37\b",
        "재시도 한도(최대 재시도 횟수)는 src/meridian/core/backoff_math.py 의 _ATTEMPT_CEIL 상수에 있다. 값은 코드가 정본.",
    ),
    (
        "gateway-port",
        "게이트웨이가 설정이 없을 때 바인드하는 기본 포트 번호를 코드에서 확인해서 보고해",
        "src/meridian/net/relay_boot.py",
        "_FALLBACK_BIND = 8742  # 설정 부재 시 바인드 포트 — 예약대역 회피\n",
        r"\b8742\b",
        "게이트웨이 기본 바인드 포트(설정 부재 시)는 src/meridian/net/relay_boot.py 의 _FALLBACK_BIND 상수에 있다.",
    ),
    (
        "cache-ttl",
        "캐시 항목의 만료 시간이 몇 초로 설정돼 있는지 코드에서 확인해서 보고해",
        "src/meridian/store/evict_policy.py",
        "_EXPIRY_S = 1747  # 항목 만료 초 — 상류 폴링 주기와 결합\n",
        r"\b1747\b",
        "캐시 항목 만료 시간(초)은 src/meridian/store/evict_policy.py 의 _EXPIRY_S 상수에 있다.",
    ),
    (
        "sig-header",
        "요청 서명에 사용하는 HTTP 헤더 이름을 코드에서 확인해서 보고해",
        "src/meridian/auth/hmac_seal.py",
        '_SIG_HEADER = "X-Mrd-Sig-V2"  # v1 은 2025-11 폐기\n',
        r"X-Mrd-Sig-V2",
        "요청 서명 HTTP 헤더 이름은 src/meridian/auth/hmac_seal.py 의 _SIG_HEADER 상수에 있다.",
    ),
    (
        "flush-at",
        "파이프라인이 배치를 배출(플러시)하는 누적 개수 문턱 값을 코드에서 확인해서 보고해",
        "src/meridian/pipeline/drain_ctrl.py",
        "_DRAIN_AT = 233  # 누적 이 개수 도달 시 배출 — 지연/처리량 절충점\n",
        r"\b233\b",
        "파이프라인 배치 배출(플러시) 문턱(누적 개수)은 src/meridian/pipeline/drain_ctrl.py 의 _DRAIN_AT 상수에 있다.",
    ),
    (
        "schema-rev",
        "현재 스토리지 스키마 리비전(버전) 번호를 코드에서 확인해서 보고해",
        "src/meridian/store/rev_ledger.py",
        "_REV = 41  # 마이그레이션 체인 말단 — 부트 시 대조\n",
        r"\b41\b",
        "스토리지 스키마 리비전 번호는 src/meridian/store/rev_ledger.py 의 _REV 상수에 있다.",
    ),
]

FILLER_MEMORY = [
    ("배포 파이프라인 순서", "배포는 스테이징 승인 후 카나리 5% → 50% → 전체 순서로 진행한다."),
    ("로그 보존 정책", "운영 로그는 30일, 감사 로그는 1년 보존한다. 아카이브는 콜드 스토리지."),
    ("코드 리뷰 규칙", "리뷰는 2인 승인, 아키텍처 변경은 설계 문서 선행."),
    ("온콜 로테이션", "온콜은 주 단위 로테이션, 인수인계는 월요일 오전."),
    ("의존성 갱신 주기", "의존성은 분기마다 일괄 갱신, 보안 패치는 즉시."),
    ("테스트 커버리지 기준", "신규 모듈은 커버리지 80% 이상, 핵심 경로는 회귀 테스트 필수."),
    ("네이밍 규약", "모듈 내부 상수는 언더스코어 접두, 공개 API 는 동사-목적어."),
    ("장애 회고 절차", "장애 회고는 48시간 내, 비난 없는 타임라인 정리 우선."),
]

# 디코이 어휘 — 탐색 arm 이 순진한 grep 한 방으로 못 끝나게 오답 아닌 잡음을 깐다
DECOY_SNIPPETS = [
    "# retry 는 상류 어댑터가 소유한다 — 이 모듈은 관여하지 않음",
    "MAX_RETRIES_UI_HINT = 3  # 표시용 힌트 — 실제 재시도 한도 아님",
    "# port 협상은 릴레이 부트 단계 참조",
    "LEGACY_PORT_NOTE = 9090  # 폐기된 v0 데모 포트 — 어디서도 안 씀",
    "# cache ttl 정책은 evict 계층이 단일 소유",
    "TTL_DOC_EXAMPLE = 600  # 문서 예시값 — 런타임과 무관",
    "# flush 문턱은 drain 컨트롤러가 정본",
    "# schema 이력은 rev ledger 참조",
    "SIGNING_NOTE = 'v1 헤더는 폐기됨'  # 헤더 이름은 seal 모듈이 정본",
]

PKGS = ["core", "net", "store", "auth", "pipeline", "ops", "util"]
VERBS = ["merge", "split", "route", "drain", "seal", "probe", "sync", "fold", "trim", "bind"]
NOUNS = ["frame", "ledger", "relay", "bucket", "cursor", "shard", "token", "batch", "policy", "chain"]


def _filler_module(pkg: str, i: int, decoy: str | None) -> str:
    v, n = VERBS[i % len(VERBS)], NOUNS[(i * 3 + 1) % len(NOUNS)]
    lines = [
        f'"""{pkg}.{v}_{n} — {n} {v} 보조 계층."""',
        "",
        "from __future__ import annotations",
        "",
    ]
    if decoy:
        lines.append(decoy)
        lines.append("")
    lines += [
        f"_STRIDE = {3 + (i * 7) % 11}",
        "",
        "",
        f"def {v}_{n}(items: list, limit: int | None = None) -> list:",
        f'    """{n} 목록을 {v} 규칙으로 정렬-절단한다."""',
        "    out = sorted(items, key=repr)",
        "    return out[: limit if limit is not None else _STRIDE]",
        "",
        "",
        f"def {v}_{n}_pairs(items: list) -> list[tuple]:",
        "    out = []",
        "    for a, b in zip(items, items[1:]):",
        "        out.append((a, b))",
        "    return out",
        "",
    ]
    return "\n".join(lines)


def build_sandbox() -> None:
    if os.path.isdir(SANDBOX):
        shutil.rmtree(SANDBOX)
    os.makedirs(SANDBOX)
    di = 0
    for pkg in PKGS:
        pdir = os.path.join(SANDBOX, "src", "meridian", pkg)
        os.makedirs(pdir)
        open(os.path.join(pdir, "__init__.py"), "w").write("")
        for i in range(6):
            decoy = DECOY_SNIPPETS[di % len(DECOY_SNIPPETS)] if (i == 2 or i == 4) else None
            if decoy:
                di += 1
            name = f"{VERBS[(i + di) % len(VERBS)]}_{NOUNS[(i * 2 + di) % len(NOUNS)]}.py"
            open(os.path.join(pdir, name), "w").write(_filler_module(pkg, i + di, decoy))
    for _fid, _task, rel, snippet, _judge, _mem in FACTS:
        path = os.path.join(SANDBOX, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mod = os.path.splitext(os.path.basename(rel))[0]
        body = (
            f'"""meridian {mod} — 정본 상수 소유 모듈."""\n\nfrom __future__ import annotations\n\n'
            + snippet
            + f"\n\ndef current() -> object:\n    return {snippet.split('=')[0].strip()}\n"
        )
        open(path, "w").write(body)
    open(os.path.join(SANDBOX, "README.md"), "w").write(
        "# meridian\n\n내부 릴레이/스토리지 유틸 모음. 규약: 상수는 소유 모듈이 정본.\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=SANDBOX, check=True)
    subprocess.run(["git", "add", "-A"], cwd=SANDBOX, check=True)
    subprocess.run(
        ["git", "-c", "user.email=bench@local", "-c", "user.name=bench", "commit", "-qm", "baseline"],
        cwd=SANDBOX,
        check=True,
    )


def build_memory() -> None:
    if os.path.isdir(MEMDIR):
        shutil.rmtree(MEMDIR)
    os.environ["ASGARD_MEMORY_DIR"] = MEMDIR
    from asgard import memory

    memory.ensure_home(MEMDIR)
    for _fid, _task, _rel, _snippet, _judge, mem in FACTS:
        memory.add(mem, kind="reference", d=MEMDIR)
    for title, body in FILLER_MEMORY:
        memory.add(body, title=title, kind="note", d=MEMDIR)


def precheck() -> bool:
    """0-LLM 사전검증 — 각 과업 문구로 recall 시 포인터 페이지가 실리는지."""
    os.environ["ASGARD_MEMORY_DIR"] = MEMDIR
    from asgard import memory

    ok = True
    for fid, task, rel, _snippet, _judge, _mem in FACTS:
        note = memory.recall_note(task, k=3)
        hit = rel in note
        print(f"  recall[{fid}]: {'HIT' if hit else 'MISS'}")
        ok = ok and hit
    return ok


def _fresh_state() -> None:
    """런 간 독립 — 퀘스트 로그·route-priors·저널 잔재 제거 (학습 전이 차단)."""
    st = os.path.join(SANDBOX, ".asgard")
    if os.path.isdir(st):
        shutil.rmtree(st)
    os.makedirs(st)
    open(os.path.join(st, ".gitignore"), "w").write("*\n")


def _usage_total() -> int:
    import sqlite3

    try:
        conn = sqlite3.connect(os.path.join(MEMDIR, "state.db"))
        n = conn.execute("SELECT COALESCE(SUM(uses),0) FROM usage").fetchone()[0]
        conn.close()
        return int(n)
    except Exception:
        return -1


def run_one(fid: str, task: str, judge: str, arm: str, rep: int) -> dict:
    _fresh_state()
    env = dict(os.environ)
    env["ASGARD_MEMORY_DIR"] = MEMDIR
    env["ASGARD_MEMORY_INJECT"] = "on" if arm == "on" else "off"
    u0 = _usage_total()
    t0 = time.time()
    stdout = ""
    stderr = ""
    exit_code: int | None = None
    try:
        p = subprocess.run(
            [ASGARD, "run", task, "--provider", "claude-native", "--json"],
            cwd=SANDBOX,
            env=env,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
        )
        timeout = False
        stdout = p.stdout or ""
        stderr = p.stderr or ""
        exit_code = p.returncode
    except subprocess.TimeoutExpired as e:
        timeout = True
        stdout = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
    wall = round(time.time() - t0, 1)
    summary: dict = {}
    for line in reversed(stdout.strip().splitlines() or [""]):
        try:
            summary = json.loads(line)
            break
        except Exception:
            continue
    result_text = str(summary.get("result", ""))
    row = {
        "fid": fid,
        "arm": arm,
        "rep": rep,
        "success": bool(re.search(judge, result_text)),
        "bash_calls": stderr.count("⬢ $"),
        "edit_calls": stderr.count("⬢ ✎"),
        "other_tools": stderr.count("⬢ ⚙"),
        "tokens": summary.get("tokens"),
        "cache_read_tokens": summary.get("cache_read_tokens"),
        "wall_s": summary.get("wall_s", wall),
        "exit": exit_code,
        "timeout": timeout,
        "misroute": "DIRECT 분류였지만" in stderr,
        "recall_used": (_usage_total() - u0) if u0 >= 0 else None,
        "result_head": result_text[:160],
    }
    with open(RESULTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    if mode == "build":
        build_sandbox()
        build_memory()
        ok = precheck()
        print(f"sandbox+memory built — precheck {'PASS' if ok else 'FAIL'}")
        sys.exit(0 if ok else 1)
    plan = []
    if mode == "pilot":
        fid, task, _rel, _s, judge, _m = FACTS[0]
        plan = [(fid, task, judge, arm, 0) for arm in ("on", "off")]
    elif mode == "full":
        for rep in range(3):
            for fid, task, _rel, _s, judge, _m in FACTS:
                for arm in ("on", "off"):
                    plan.append((fid, task, judge, arm, rep))
    done = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS, encoding="utf-8"):
            try:
                r = json.loads(line)
                done.add((r["fid"], r["arm"], r["rep"]))
            except Exception:
                pass
    for fid, task, judge, arm, rep in plan:
        if (fid, arm, rep) in done:
            print(f"skip {fid}/{arm}/r{rep} (already done)")
            continue
        row = run_one(fid, task, judge, arm, rep)
        print(
            f"{fid}/{arm}/r{rep}: ok={row['success']} bash={row['bash_calls']} "
            f"tok={row['tokens']} wall={row['wall_s']}s misroute={row['misroute']}"
        )


if __name__ == "__main__":
    main()
