"""memory 커맨드 — 개인 위키(LLM Wiki) 운영면. 로직은 asgard.memory, 여기는 표면만.

승인 게이트: ingest 는 계획(create/merge 대상)을 먼저 보여주고 확인받은 뒤, **그 동일
계획을 그대로** 실행에 넘긴다 (TOCTOU 차단 — 승인 대상과 실행 대상이 갈라지지 않음).
비대화형(파이프·CI)에서는 --yes 없이는 저장하지 않는다.

모든 run_* 는 예외를 안정적인 종료 코드(사용자 메시지 + 1)로 변환한다 — traceback 노출 금지.
"""

import json as _json
import sys
from collections.abc import Callable

from .. import memory, ui


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


def run_ingest(text: str, kind: str, yes: bool) -> int:
    def _do() -> int:
        threat = memory.scan_threats(text)
        if threat:
            ui.fail(f"injection scan: {threat}")
            return 1
        plan = memory.plan_ingest(text)  # 한 번만 계산
        if plan["action"] == "merge":
            ui.step(f"plan: merge into '{plan['title']}' ({plan['slug']}, sim={plan['sim']})")
        else:
            ui.step("plan: create new page")
        if not yes:
            if not sys.stdin.isatty():
                ui.warn("non-interactive without --yes — not saved (ask-before-save)")
                return 1
            if input("save? [y/N] ").strip().lower() not in ("y", "yes"):
                ui.step("skipped")
                return 0
        action, slug = memory.ingest(text, kind=kind, plan=plan)  # 승인한 그 계획 그대로
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


def run_snapshot() -> int:
    """주입 스냅샷 출력 — CC memory-activate 훅이 subprocess 로 소비 (단일 출처: 훅 재구현 금지).
    킬스위치 off·페이지 0 = 빈 출력 + exit 0 (훅이 무주입으로 통과)."""
    print(memory.snapshot_note(), end="")
    return 0


def run_path() -> int:
    print(memory.memory_dir())
    return 0
