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
from ..memory_bridge import claim_retain, find_config, finish_retain, server_retain_items
from ..project_memory import propose_completion, retain_turn

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


def run_sync_turn(mode: str) -> int:
    """hook 전용 JSON stdin 표면 — 자동 turn retain과 완료 proposal을 한 lifecycle 호출로 처리."""
    try:
        raw = sys.stdin.read(200_001)
        if len(raw) > 200_000:
            raise ValueError("turn payload too large")
        payload = _json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("turn payload must be a JSON object")
        found = find_config(os.getcwd())
        if not found:
            print(_json.dumps({"status": "skipped", "reason": "project memory not connected"}))
            return 0
        root, cfg = found
        result = retain_turn(
            root,
            cfg,
            session_id=str(payload.get("session_id") or mode),
            turn_id=str(payload.get("turn_id") or "turn"),
            user_text=str(payload.get("user_text") or ""),
            assistant_text=str(payload.get("assistant_text") or ""),
            mode=mode,
        )
        output: dict = {"status": result.status, "document_id": result.document_id, "reason": result.reason}
        if cfg.get("auto_propose_completion", True) and payload.get("verified"):
            proposal = propose_completion(
                root,
                cfg,
                session_id=str(payload.get("session_id") or mode),
                request=str(payload.get("user_text") or ""),
                response=str(payload.get("assistant_text") or ""),
                changed_files=list(payload.get("changed_files") or []),
                evidence=list(payload.get("evidence") or []),
                verified=True,
            )
            if proposal.status == "proposed":
                output["proposal"] = {
                    "approval_id": proposal.approval_id,
                    "record_id": proposal.record_id,
                    "preview": proposal.preview,
                }
        print(_json.dumps(output, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(_json.dumps({"status": "failed", "reason": type(exc).__name__}))
        return 0  # lifecycle 메모리 장애가 host turn을 막으면 안 된다


def run_project_approve(approval_id: str) -> int:
    """Native/CLI 사용자 승인을 기존 claim/finish 원자적 commit 경로로 실행한다."""

    def _do() -> int:
        found = find_config(os.getcwd())
        if not found:
            raise ValueError("project memory is not connected")
        root, cfg = found
        claimed = claim_retain(root, approval_id)
        if claimed is None:
            raise ValueError("invalid, expired, claimed, or already consumed approval id")
        item, token = claimed
        try:
            result = server_retain_items(cfg, [item] if isinstance(item, dict) else [{"content": item}])
            if result.get("success") is not True:
                raise ValueError(str(result.get("error") or "project memory retain rejected"))
        except Exception:
            finish_retain(root, approval_id, token, success=False)
            raise
        finish_retain(root, approval_id, token, success=True)
        ui.ok(f"project memory saved → bank={cfg['bank']}")
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
    """개인+프로젝트 범위 회수 — UserPromptSubmit 훅 전용, provider gate 적용."""
    if memory.inject_allowed(provider):
        from ..memory_context import recall_note

        print(recall_note(text, start=os.getcwd()), end="")
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


def _project_candidates(root: str, all_files: bool):
    from .. import project_memory

    if all_files:
        return project_memory.scan_project(root, changed_paths=[])
    changed = project_memory.changed_paths(root)
    if not changed:
        return []
    selected = set(changed)
    return [candidate for candidate in project_memory.scan_project(root, changed_paths=changed) if candidate.path in selected]


def run_project_scan(all_files: bool = False, json_out: bool = False) -> int:
    """등록 기준을 통과한 중요 artifact 후보를 읽기 전용으로 출력한다."""

    def _do() -> int:
        root = os.getcwd()
        candidates = _project_candidates(root, all_files)
        rows = [
            {
                "path": candidate.path,
                "kind": candidate.kind,
                "importance": candidate.importance,
                "score": candidate.score,
                "reasons": list(candidate.reasons),
                "content_hash": candidate.content_hash,
                "structural_hash": candidate.structural_hash,
                "extractor": candidate.extractor,
                "symbols": list(candidate.symbols),
                "imports": list(candidate.imports),
            }
            for candidate in candidates
        ]
        if json_out:
            print(_json.dumps({"root": root, "mode": "all" if all_files else "changed", "candidates": rows}, ensure_ascii=False, indent=2))
        else:
            ui.head(f"project memory scan · {'all' if all_files else 'changed'}")
            for row in rows:
                ui.step(f"{row['path']} · {row['kind']} · {row['importance']} · score={row['score']}")
            if not rows:
                ui.ok("등록 기준을 통과한 후보 없음")
        return 0

    return _guard(_do)


def run_project_sync(all_files: bool = False, yes: bool = False, json_out: bool = False, plan_id: str | None = None) -> int:
    """중요 artifact를 stable document_id로 Hindsight에 replace projection한다."""

    def _do() -> int:
        from .. import project_memory
        from ..memory_bridge import find_config

        root = os.getcwd()
        found = find_config(root)
        if not found:
            raise ValueError("project memory is not connected — run `asgard memory connect <server>`")
        _, cfg = found
        changed = project_memory.changed_paths(root)
        candidates = project_memory.scan_project(root, changed_paths=changed)
        if not yes:
            revision = project_memory.source_revision(root)
            plan = project_memory.projection_plan(root, str(cfg["bank"]), candidates, force=all_files)
            approved_plan_id = project_memory.projection_plan_id(str(cfg["bank"]), plan, revision, force=all_files)
            upsert_paths = [candidate.path for candidate in plan["upserts"]]
            removed = [
                {
                    "path": path,
                    "status": "renamed" if path in plan["renamed"] else "deleted",
                    "renamed_to": plan["renamed"].get(path, ""),
                }
                for path in plan["removed"]
            ]
            payload = {
                "action": "project-sync",
                "bank": cfg["bank"],
                "mode": "force-all" if all_files else "manifest-diff",
                "source_revision": revision,
                "plan_id": approved_plan_id,
                "items": upsert_paths,
                "removed": removed,
                "approved": False,
            }
            if json_out:
                print(_json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                ui.head(f"project memory sync plan · bank={cfg['bank']}")
                for path in payload["items"]:
                    ui.step(f"upsert · {path}")
                for row in removed:
                    detail = f" → {row['renamed_to']}" if row["renamed_to"] else ""
                    ui.step(f"{row['status']} · {row['path']}{detail}")
                ui.warn(f"아직 저장하지 않음 — 검토 후 --yes --plan-id {approved_plan_id} 추가")
            return 0
        if not plan_id:
            raise ValueError("--yes requires the --plan-id from a fresh preview")
        result = project_memory.sync_artifacts(root, cfg, candidates, force=all_files, expected_plan_id=plan_id)
        output = {
            "success": result.get("success") is True,
            "bank": cfg["bank"],
            "items_count": int(result.get("items_count", 0)),
            "upserted_count": int(result.get("upserted_count", 0)),
            "deleted_count": int(result.get("deleted_count", 0)),
            "renamed_count": int(result.get("renamed_count", 0)),
            "plan_id": result.get("plan_id", ""),
            "paths": list(result.get("paths", [])),
            "removed": list(result.get("removed", [])),
            "error": str(result.get("error") or ""),
        }
        if json_out:
            print(_json.dumps(output, ensure_ascii=False, indent=2))
        elif not output["success"]:
            ui.fail(f"project memory sync failed: {output['error'] or 'server rejected publication'}")
        else:
            ui.ok(f"project memory synced: {output['items_count']} item(s) → bank={cfg['bank']}")
        return 0 if output["success"] else 1

    return _guard(_do)
