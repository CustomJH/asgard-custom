"""memory 커맨드 — 개인 위키(LLM Wiki) 운영면. 로직은 asgard.memory, 여기는 표면만.

승인 게이트: ingest 는 계획(create/merge 대상)을 먼저 보여주고 확인받은 뒤, **그 동일
계획을 그대로** 실행에 넘긴다 (TOCTOU 차단 — 승인 대상과 실행 대상이 갈라지지 않음).
비대화형(파이프·CI)에서는 --yes 없이는 저장하지 않는다.

모든 run_* 는 예외를 안정적인 종료 코드(사용자 메시지 + 1)로 변환한다 — traceback 노출 금지.
"""

import contextlib
import hashlib
import hmac
import json as _json
import os
import re
import sys
from collections.abc import Callable

from .. import memory, ui

_PLAN_ID = re.compile(r"^[0-9a-f]{64}$")


def _pending_dir() -> str:
    d = os.path.join(memory.ensure_home(), ".pending-plans")
    os.makedirs(d, mode=0o700, exist_ok=True)
    memory._chmod(d, 0o700)
    return d


def _save_plan(text: str, kind: str, plan: dict) -> str:
    raw = _json.dumps(
        {"text": text, "kind": kind, "plan": plan}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    plan_id = hashlib.sha256(raw.encode()).hexdigest()
    memory._atomic_write(os.path.join(_pending_dir(), f"{plan_id}.json"), raw)
    return plan_id


def _load_plan(plan_id: str, text: str, kind: str) -> dict:
    if not _PLAN_ID.fullmatch(plan_id):
        raise ValueError("invalid approval plan id")
    path = os.path.join(_pending_dir(), f"{plan_id}.json")
    try:
        raw = open(path, encoding="utf-8").read()
    except OSError as e:
        raise ValueError("approval plan not found or already consumed — re-run ingest") from e
    if not hmac.compare_digest(hashlib.sha256(raw.encode()).hexdigest(), plan_id):
        raise ValueError("approval plan integrity check failed — re-run ingest")
    payload = _json.loads(raw)
    if payload.get("text") != text or payload.get("kind") != kind or not isinstance(payload.get("plan"), dict):
        raise ValueError("approval plan does not match text/kind — re-run ingest")
    return payload["plan"]


def _consume_plan(plan_id: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(os.path.join(_pending_dir(), f"{plan_id}.json"))


def _guard(fn: Callable[[], int]) -> int:
    """공통 예외 변환 — ValueError 는 처방 메시지, 그 외는 짧은 오류 한 줄 (traceback 금지)."""
    try:
        return fn()
    except ValueError as e:
        ui.fail(str(e))
        return 1
    except Exception as e:  # 파일 권한·손상 등 — 사용자용 한 줄로
        ui.fail(f"{type(e).__name__}: {e}")
        return 1


def run_add(text: str, title: str | None, kind: str, links: str, force: bool) -> int:
    def _do() -> int:
        slug, path = memory.add(text, title=title, kind=kind, links=links, force=force)
        ui.ok(f"added {slug} → {path}")
        return 0

    return _guard(_do)


def run_ingest(text: str, kind: str, yes: bool, plan_id: str | None = None) -> int:
    def _do() -> int:
        threat = memory.scan_threats(text)
        if threat:
            ui.fail(f"injection scan: {threat}")
            return 1
        if plan_id and not yes:
            raise ValueError("--plan-id requires --yes")
        plan = _load_plan(plan_id, text, kind) if plan_id else memory.plan_ingest(text)
        if plan["action"] == "merge":
            ui.step(f"plan: merge into '{plan['title']}' ({plan['slug']}, sim={plan['sim']})")
        else:
            ui.step("plan: create new page")
        if not yes:
            if not sys.stdin.isatty():
                approval_id = _save_plan(text, kind, plan)
                ui.step(f"approval-id: {approval_id}")
                ui.warn("non-interactive without --yes — not saved (ask-before-save)")
                return 1
            if input("save? [y/N] ").strip().lower() not in ("y", "yes"):
                ui.step("skipped")
                return 0
        action, slug = memory.ingest(text, kind=kind, plan=plan)  # 승인한 그 계획 그대로
        if plan_id:
            _consume_plan(plan_id)
        ui.ok(f"{action}: {slug}")
        return 0

    return _guard(_do)


def run_query(text: str, k: int, json_out: bool) -> int:
    def _do() -> int:
        hits = memory.query(text, k=k)
        if json_out:
            print(_json.dumps(hits, ensure_ascii=False, indent=1))
            return 0
        if not hits:
            ui.step("no matches")
            return 0
        for h in hits:
            print(f"{h['slug']}  `{h['kind']}`  {h['title']}\n    {h['snippet']}")
        return 0

    return _guard(_do)


def run_lint(json_out: bool) -> int:
    def _do() -> int:
        findings = memory.lint()
        if json_out:
            print(_json.dumps(findings, ensure_ascii=False, indent=1))
        elif not findings:
            ui.ok("memory healthy — no findings")
        else:
            for f in findings:
                line = f"[{f['level']}] {f['code']}: {f['slug']} — {f['msg']}"
                (ui.fail if f["level"] == "error" else ui.warn if f["level"] == "warn" else ui.step)(line)
        return 1 if any(f["level"] == "error" for f in findings) else 0

    return _guard(_do)


def run_reindex() -> int:
    def _do() -> int:
        n = memory.reindex()
        ui.ok(f"reindexed {n} pages → index.md + state.db")
        return 0

    return _guard(_do)


def run_show(slug: str, unsafe: bool = False) -> int:
    def _do() -> int:
        if not memory.valid_slug(slug):
            ui.fail(f"invalid slug: {slug!r}")
            return 1
        pg = memory._read(memory.memory_dir(), slug)
        if not pg:
            ui.fail(f"no page: {slug}")
            return 1
        meta, body = pg
        threat = memory.poisoned(meta, body)
        if threat and not unsafe:
            # 오염 페이지 출력도 컨텍스트 유입 경로다 (2차 리뷰 ②) — 수리용 열람은 --unsafe 로만
            ui.fail(f"threat detected: {threat} — inspect with --unsafe, then fix the file or `memory remove {slug}`")
            return 1
        if threat:
            ui.warn(f"⚠ poisoned page (quarantined from injection/query): {threat}")
        for k, v in meta.items():
            print(f"{k}: {v}")
        print(f"\n{body}")
        return 0

    return _guard(_do)


def run_remove(slug: str) -> int:
    def _do() -> int:
        if memory.remove(slug):
            ui.ok(f"removed {slug}")
            return 0
        ui.fail(f"no page: {slug}")
        return 1

    return _guard(_do)


def run_merge(src: str, dst: str) -> int:
    def _do() -> int:
        memory.merge(src, dst)
        ui.ok(f"merged {src} → {dst}")
        return 0

    return _guard(_do)


def run_snapshot(provider: str | None = None) -> int:
    """주입 스냅샷 출력 — CC memory-activate 훅이 subprocess 로 소비 (단일 출처: 훅 재구현 금지).
    킬스위치 off·페이지 0 = 빈 출력 + exit 0 (훅이 무주입으로 통과)."""
    if memory.inject_allowed(provider):
        print(memory.snapshot_note(), end="")
    return 0


def run_recall(text: str, provider: str | None = None) -> int:
    """요청 관련 회수 블록 출력 — UserPromptSubmit 훅 전용, provider gate 적용."""
    if memory.inject_allowed(provider):
        print(memory.recall_note(text), end="")
    return 0


def run_path() -> int:
    print(memory.memory_dir())
    return 0


def run_connect(server: str, bank: str | None) -> int:
    """프로젝트 ↔ 중앙 메모리 서버 연결 — .asgard/memory-server.json (커밋 대상, 팀 공유)."""

    def _do() -> int:
        import urllib.request

        from .. import memory_bridge

        root = os.getcwd()
        b = (bank or os.path.basename(root)).strip()
        s = server.rstrip("/")
        try:  # 도달성 사전 점검 — 실패해도 기록은 한다 (서버가 나중에 뜰 수 있음)
            urllib.request.urlopen(f"{s}/openapi.json", timeout=5)
            ui.ok(f"server reachable: {s}")
        except Exception:
            ui.warn(f"server unreachable now: {s} — 설정은 기록함 (기동 후 doctor 로 재확인)")
        p = memory_bridge.write_config(root, s, b)
        ui.ok(f"connected: bank={b} → {p} (커밋해서 팀과 공유)")
        ui.step("팀원 1회 등록: claude mcp add --scope user asgard-memory -- asgard memory mcp")
        return 0

    return _guard(_do)


def run_mcp() -> int:
    """stdio MCP 브릿지 — Claude Code 등 MCP 클라이언트가 command 타입으로 기동."""
    from .. import memory_bridge

    return memory_bridge.serve()
