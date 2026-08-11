"""memory 커맨드 — 프로젝트 기억. Git 정본 훑기·동기화·재수화·문서 담기."""

import json as _json
import os
from collections.abc import Callable

from ... import errors, ui
from ...memory_bridge import (
    backend_target,
    find_config,
    is_backend_trusted,
)
from ...project_memory import commit_approved_record
from ._core import _emit, _guard


def run_project_approve(approval_id: str, json_out: bool = False) -> int:
    """Native/CLI 사용자 승인을 Git 정본 → backend 순서로 실행한다."""
    errors.set_json_surface(json_out)

    def _do() -> int:
        found = find_config(os.getcwd())
        if not found:
            raise errors.Unavailable("project memory is not connected")
        root, cfg = found
        if not is_backend_trusted(cfg):
            raise errors.Unavailable("project memory backend is not trusted on this machine; run asgard memory connect")
        target = backend_target(cfg)
        result = commit_approved_record(root, cfg, approval_id)
        if json_out:
            _emit(
                {
                    "approval_id": approval_id,
                    "approved": True,
                    "canonical_path": result.get("canonical_path") or "",
                    "engine": target["engine"],
                    "project_id": target["project_id"],
                }
            )
            return 0
        if result.get("canonical_path"):
            ui.ok(f"project memory canonical saved → {result['canonical_path']} (commit this file)")
        ui.ok(f"project memory saved → engine={target['engine']} project_id={target['project_id']}")
        return 0

    return _guard(_do)


def _project_candidates(root: str, all_files: bool, inventory: bool = False):
    from ... import project_memory

    if all_files:
        return project_memory.scan_project(root, changed_paths=[], inventory=inventory)
    changed = project_memory.changed_paths(root)
    if not changed:
        return []
    selected = set(changed)
    return [
        candidate
        for candidate in project_memory.scan_project(root, changed_paths=changed, inventory=inventory)
        if candidate.path in selected
    ]


def run_project_scan(all_files: bool = False, json_out: bool = False, inventory: bool = False) -> int:
    """등록 기준을 통과한 중요 artifact 후보를 읽기 전용으로 출력한다."""

    def _do() -> int:
        root = os.getcwd()
        candidates = _project_candidates(root, all_files, inventory)
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
                "tier": candidate.tier,
            }
            for candidate in candidates
        ]
        if json_out:
            print(
                _json.dumps(
                    {"root": root, "mode": "all" if all_files else "changed", "candidates": rows},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            ui.head(f"project memory scan · {'all' if all_files else 'changed'}")
            for row in rows:
                ui.step(f"{row['path']} · {row['kind']} · {row['importance']} · score={row['score']}")
            if not rows:
                ui.ok("등록 기준을 통과한 후보 없음")
        return 0

    return _guard(_do)


def run_project_sync(
    all_files: bool = False,
    yes: bool = False,
    json_out: bool = False,
    plan_id: str | None = None,
    inventory: bool = False,
) -> int:
    """중요 artifact를 stable record ID로 선택된 프로젝트 backend에 projection한다."""

    def _do() -> int:
        from ... import project_memory
        from ...memory_bridge import find_config

        root = os.getcwd()
        found = find_config(root)
        if not found:
            raise errors.Unavailable("project memory is not connected — run `asgard memory connect <endpoint>`")
        _, cfg = found
        if not is_backend_trusted(cfg):
            raise errors.Unavailable("project memory backend is not trusted on this machine; run asgard memory connect")
        target = backend_target(cfg)
        engine = str(target["engine"])
        project_id = str(target["project_id"])
        candidates = _project_candidates(root, all_files, inventory)
        if not yes:
            revision = project_memory.source_revision(root)
            plan = project_memory.projection_plan(root, project_id, candidates, force=all_files, target=target)
            approved_plan_id = project_memory.projection_plan_id(project_id, plan, revision, force=all_files)
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
                "engine": engine,
                "project_id": project_id,
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
                ui.head(f"project memory sync plan · engine={engine} · project_id={project_id}")
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
            "engine": engine,
            "project_id": project_id,
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
            ui.fail(f"project memory sync failed: {output['error'] or 'backend rejected publication'}")
        else:
            ui.ok(f"project memory synced: {output['items_count']} item(s) → engine={engine} project_id={project_id}")
        return 0 if output["success"] else 1

    return _guard(_do)


def run_project_rehydrate(
    yes: bool = False, plan_id: str | None = None, json_out: bool = False, tags_only: bool = False
) -> int:
    """프로젝트 `.asgard/memory/records/` 정본을 현재 backend에 stable replace한다.

    `tags_only` 는 본문을 다시 보내지 않고 태그만 현재 스키마로 맞춘다 — 태그 축이 늘어난
    뒤(예: `confidence:`) 기존 뱅크를 서버 재추출 없이 따라오게 하는 길이다."""

    def _do() -> int:
        from ... import project_memory

        found = find_config(os.getcwd())
        if not found:
            raise errors.Unavailable("project memory is not connected — run `asgard memory connect <endpoint>`")
        root, cfg = found
        if not is_backend_trusted(cfg):
            raise errors.Unavailable("project memory backend is not trusted on this machine; run asgard memory connect")
        if plan_id and not yes:
            raise ValueError("--plan-id requires --yes")
        plan = project_memory.rehydration_plan(root, cfg)
        target = plan["target"]
        if not yes:
            payload = {
                "action": "project-rehydrate",
                "engine": target["engine"],
                "project_id": target["project_id"],
                "canonical_digest": plan["canonical_digest"],
                "plan_id": plan["plan_id"],
                "records": plan["records"],
                "approved": False,
            }
            if json_out:
                print(_json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                ui.head(
                    f"project memory rehydrate plan · engine={target['engine']} · project_id={target['project_id']}"
                )
                verb = "retag" if tags_only else "replace"
                for row in plan["records"]:
                    ui.step(f"{verb} · {row['record_id']} · {row['path']}")
                if not plan["records"]:
                    ui.step("canonical records 없음")
                ui.warn(f"아직 저장하지 않음 — 검토 후 --yes --plan-id {plan['plan_id']} 추가")
            return 0
        if not plan_id:
            raise ValueError("--yes requires the --plan-id from a fresh preview")
        result = project_memory.rehydrate_records(root, cfg, plan_id, tags_only=tags_only)
        output = {
            "success": result.get("success") is True,
            "engine": target["engine"],
            "project_id": target["project_id"],
            "items_count": int(result.get("items_count", 0)),
            "plan_id": result.get("plan_id", ""),
            "error": str(result.get("error") or ""),
        }
        if json_out:
            print(_json.dumps(output, ensure_ascii=False, indent=2))
        elif output["success"]:
            ui.ok(
                f"project memory {'retagged' if tags_only else 'rehydrated'}: {output['items_count']} record(s) → "
                f"engine={target['engine']} project_id={target['project_id']}"
            )
        else:
            ui.fail(f"project memory rehydrate failed: {output['error'] or 'backend rejected publication'}")
        return 0 if output["success"] else 1

    return _guard(_do)


def run_project_recall(
    query: str,
    max_results: int = 8,
    *,
    unfiltered: bool = False,
    json_out: bool = False,
) -> int:
    """프로젝트 메모리 조회 — MCP `memory_recall` 과 같은 게이트를 CLI 에서 통과시킨다.

    MCP 서버는 사용자가 열어야 열리므로 조회가 그쪽에만 있으면 닫힌 세션에서는 2차 메모리를
    아예 못 본다. 두 표면은 같은 `filter_project_hits` 를 쓴다 — 여기서만 무엇을 왜 뺐는지
    사유별로 같이 낸다 (`--unfiltered` 는 태그 사전 필터 없이 저장소가 무엇을 들고 있는지 본다)."""
    errors.set_json_surface(json_out)

    def _do() -> int:
        from ...memory_bridge import server_recall
        from ...memory_context import INJECTABLE_TAGS, drop_note, filter_project_hits, hit_body, hit_provenance

        found = find_config(os.getcwd())
        if not found:
            raise errors.Unavailable("project memory is not connected — run `asgard memory connect <endpoint>`")
        root, cfg = found
        if not is_backend_trusted(cfg):
            raise errors.Unavailable("project memory backend is not trusted on this machine; run asgard memory connect")
        target = backend_target(cfg)
        hits = server_recall(cfg, query, max_results, tags=None if unfiltered else INJECTABLE_TAGS)
        filtered, dropped = filter_project_hits(root, cfg, hits, max_results=max_results, query=query)
        rows = [
            {
                "text": body,
                "record_id": str((hit.get("metadata") or {}).get("record_id") or ""),
                "kind": str((hit.get("metadata") or {}).get("kind") or ""),
                "provenance": hit_provenance(hit["metadata"]),
            }
            for hit in filtered
            if (body := hit_body(hit))
        ]
        if json_out:
            _emit(
                {
                    "query": query,
                    "engine": target["engine"],
                    "project_id": target["project_id"],
                    "returned": len(rows),
                    "candidates": len(hits),
                    "dropped": dropped,
                    "results": rows,
                }
            )
            return 0
        ui.head(f"project memory recall · engine={target['engine']} · project_id={target['project_id']}")
        for row in rows:
            print(f"  {row['text']}{row['provenance']}")
        note = drop_note(dropped)
        if not rows:
            ui.warn("주입 자격을 갖춘 기억 없음" + note)
            ui.step(
                "저장소에 무엇이 있는지 보려면 --unfiltered, 자격은 scope=project·status=active·confidence=verified 셋이에요"
            )
            return 0
        print(ui.dim(f"후보 {len(hits)}건 중 {len(rows)}건{note} — 힌트일 뿐, 다 됐다는 증거는 아니에요"))
        return 0

    return _guard(_do)


def run_project_retain(
    content: str,
    *,
    record_id: str,
    kind: str,
    title: str,
    source: str,
    source_revision: str,
    importance: str = "normal",
    confidence: str = "observed",
    status: str = "active",
    approve: bool = False,
    json_out: bool = False,
) -> int:
    """프로젝트 record 적재 — MCP `memory_retain` 과 같은 검증·승인 경로를 CLI 에서 연다.

    `--approve` 없이는 승인 대기로만 남고 approval_id 를 낸다. 자동저장이 켜져 있으면
    (`project_memory.autosave`) 대기 없이 바로 커밋한다 — MCP 쪽과 같은 규칙이다."""
    errors.set_json_surface(json_out)

    def _do() -> int:
        from ...memory_bridge import autosave_enabled, stage_retain
        from ...project_memory import ProjectRecord, record_item, validate_record

        found = find_config(os.getcwd())
        if not found:
            raise errors.Unavailable("project memory is not connected — run `asgard memory connect <endpoint>`")
        root, cfg = found
        if not is_backend_trusted(cfg):
            raise errors.Unavailable("project memory backend is not trusted on this machine; run asgard memory connect")
        target = backend_target(cfg)
        record = ProjectRecord(
            record_id=record_id,
            kind=kind,
            title=title,
            content=content,
            source=source,
            source_revision=source_revision,
            importance=importance,
            confidence=confidence,
            status=status,
        )
        validation = validate_record(record, root)
        if not validation.accepted:
            raise errors.InvalidInput("등록 기준 위반: " + "; ".join(validation.reasons))
        item = record_item(
            record,
            target["project_id"],
            project_uid=str(cfg.get("project_uid") or ""),
            binding_id=str(cfg.get("binding_id") or ""),
        )
        approval_id = stage_retain(root, item, target=target)
        if approve or autosave_enabled(cfg):
            result = commit_approved_record(root, cfg, approval_id)
            canonical = result.get("canonical_path") or ""
            if json_out:
                _emit({"record_id": record_id, "approval_id": approval_id, "committed": True, "canonical": canonical})
                return 0
            if canonical:
                ui.ok(f"project memory canonical saved → {canonical} (commit this file)")
            ui.ok(f"project memory saved → engine={target['engine']} project_id={target['project_id']}")
            return 0
        if json_out:
            _emit({"record_id": record_id, "approval_id": approval_id, "committed": False, "canonical": ""})
            return 0
        ui.ok(f"승인 대기 · approval_id={approval_id}")
        ui.step(f"내용을 확인한 뒤 `asgard memory project-approve {approval_id}`")
        return 0

    return _guard(_do)


def run_project_reflect(question: str, budget: str = "low", json_out: bool = False) -> int:
    """프로젝트 메모리 회고 — backend LLM 우선, 없으면 이쪽 provider 합성 (읽기 전용 자문)."""

    def _do() -> int:
        from ...project_memory.reflect import ReflectUnavailable, reflect
        from ...project_memory_backends import get_backend

        found = find_config(os.getcwd())
        if not found:
            raise errors.Unavailable("project memory is not connected — run `asgard memory connect <endpoint>`")
        root, cfg = found
        if not is_backend_trusted(cfg):
            raise errors.Unavailable("project memory backend is not trusted on this machine; run asgard memory connect")
        backend = get_backend(cfg)
        try:
            output = reflect(root, backend, question, budget=budget, cfg=cfg)
        except ReflectUnavailable as exc:
            ui.fail(str(exc))
            ui.step('서버 LLM 없이 답하려면 provider를 연결하거나 [project_memory].reflect를 "local"로 둬 주세요')
            return 1
        finally:
            backend.close()
        facts = output.get("based_on") or {}
        memories = facts.get("memories") if isinstance(facts, dict) else None
        if json_out:
            print(_json.dumps(output, ensure_ascii=False, indent=2))
            return 0 if str(output.get("text") or "").strip() else 1
        ui.head(
            f"project memory reflect · engine={backend.engine} · project_id={backend.project_id} "
            f"· source={output.get('source', 'backend')}"
        )
        text = str(output.get("text") or "").strip()
        if not text:
            ui.warn(f"답을 못 만들었어요 — {output.get('detail') or '근거 없음'}")
            return 1
        print(text)
        if isinstance(memories, list) and memories:
            print(ui.dim(f"근거 memories {len(memories)}건 — 자문일 뿐, 다 됐다는 증거는 아니에요"))
        if output.get("source") == "local":
            print(ui.dim(f"backend LLM 없이 이쪽 provider가 합성 · {output.get('detail', '')}"))
        return 0

    return _guard(_do)


def run_project_evolve(apply: bool = False, json_out: bool = False) -> int:
    """프로젝트 메모리 진화 패스 — 낡은 record를 찾아 승인 대기로 올린다 (기본 dry-run)."""

    def _do() -> int:
        from ...project_memory import evolve as evolve_mod

        found = find_config(os.getcwd())
        if not found:
            raise errors.Unavailable("project memory is not connected — run `asgard memory connect <endpoint>`")
        root, cfg = found
        if apply and not is_backend_trusted(cfg):
            raise errors.Unavailable("project memory backend is not trusted on this machine; run asgard memory connect")
        try:
            plan = evolve_mod.plan_evolve(root)
        except RuntimeError as exc:  # provider 미충족 — 신호만 보여주고 물러난다
            sig = evolve_mod.signals(root)
            ui.warn(f"제안을 만들 provider가 없어요 — {exc}")
            ui.step(
                f"결정론 신호만: 사라진 출처 {len(sig['missing_sources'])}건 · 근사 중복 {len(sig['near_duplicates'])}건"
            )
            return 1
        if not apply:
            if json_out:
                print(_json.dumps(plan, ensure_ascii=False, indent=2, default=str))
                return 0
            sig = plan["signals"]
            ui.head(f"project memory evolve · record {sig.get('active', 0)}/{sig.get('total', 0)} active")
            for record_id in sig.get("missing_sources", []):
                ui.step(f"신호 · 출처가 사라진 record — {record_id}")
            for row in sig.get("near_duplicates", []):
                ui.step(f"신호 · 근사 중복 {row['a']} ≈ {row['b']} ({row['overlap']})")
            for op in plan["ops"]:
                if op["op"] == "retire":
                    ui.step(f"retire · {op['record_id']} — {op['source']} 사라짐")
                elif op["op"] == "insight":
                    ui.step(f"insight · {op['title'][:70]} ← {', '.join(op['sources'])}")
                else:
                    ui.warn(f"contradiction · {op['a']} ↔ {op['b']} — {op['why']}")
            for row in plan["dropped"]:
                ui.warn(f"기각 · {row['op'].get('op', '?')} — {row['reason']}")
            if not plan["ops"]:
                ui.ok(plan.get("reason") or "제안 없음")
            else:
                ui.ok(f"{len(plan['ops'])}건 제안 — 승인 대기로 올리려면 --apply")
            return 0
        result = evolve_mod.apply_evolve(root, cfg, plan)
        if json_out:
            print(_json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0 if not result["failed"] else 1
        for row in result["failed"]:
            ui.fail(f"{row['op']} 실패 — {row.get('error', '')}")
        for row in result["staged"]:
            ui.ok(f"{row['op']} 승인 대기 · {row['record_id']} — asgard memory project-approve {row['approval_id']}")
        for row in result["reported"]:
            ui.warn(f"contradiction · {row['a']} ↔ {row['b']} — 사람이 해소 (자동 쓰기 없음)")
        ui.step(
            f"승인 {len(result['staged'])}건 대기 · 실패 {len(result['failed'])}건 · 보고 {len(result['reported'])}건"
        )
        return 0 if not result["failed"] else 1

    return _guard(_do)


def run_project_learn(apply_changes: bool = False, json_out: bool = False) -> int:
    """승인 project record를 Hindsight observation·mental model 학습층으로 올린다."""

    def _do() -> int:
        from ...memory_bridge import verify_backend_binding
        from ...project_memory import learning
        from ...project_memory_backends import get_backend

        found = find_config(os.getcwd())
        if not found:
            raise errors.Unavailable("project memory is not connected — run `asgard memory connect <endpoint>`")
        root, cfg = found
        if not is_backend_trusted(cfg):
            raise errors.Unavailable("project memory backend is not trusted on this machine; run asgard memory connect")
        backend = get_backend(cfg)
        try:
            verify_backend_binding(cfg, backend=backend)
            output = learning.apply(backend) if apply_changes else learning.plan(backend)
            # 종합층 로컬 사본을 갱신한다 — 회수는 이 파일만 읽는다 (턴마다 두 번째 왕복 금지).
            # apply 직후에는 아직 refresh가 도는 중일 수 있다: 그때는 준비된 것만 내려가고,
            # 다음 실행이 나머지를 집는다.
            output["synthesis_models"] = learning.snapshot(
                backend,
                root,
                project_uid=str(cfg.get("project_uid") or ""),
                binding_id=str(cfg.get("binding_id") or ""),
            )
            verify_backend_binding(cfg, backend=backend)
        finally:
            backend.close()
        if json_out:
            print(_json.dumps(output, ensure_ascii=False, indent=2))
            return 0
        ui.head("project memory · Hindsight learning")
        if apply_changes:
            ui.ok("observation 정책과 mental model을 적용했어요")
            ui.step(f"consolidation operation · {output['consolidation_operation_id']}")
            for row in output["models"]:
                ui.step(f"{row['id']} · {row['action']} · operation {row['operation_id']}")
            if not output["models"]:
                ui.step("mental models · already current")
            ui.step(f"synthesis 로컬 사본 · {output['synthesis_models']}개 (회수 주입 대상)")
        else:
            ui.step(f"observation config · {'ready' if output['configured'] else 'drifted'}")
            ui.step(
                f"mental models · missing {len(output['missing_models'])} · drifted {len(output['drifted_models'])}"
            )
            for row in output["models"]:
                state = "stale" if row["stale"] else "ready" if row["ready"] else "building"
                ui.step(f"{row['id']} · {state}")
            ui.step(f"synthesis 로컬 사본 · {output['synthesis_models']}개 (회수 주입 대상)")
            if not output["configured"] or output["missing_models"] or output["drifted_models"]:
                ui.warn("적용하려면 `asgard memory project-learn --apply`")
        return 0

    return _guard(_do)


_FINDING_KINDS = {"secret": "비밀", "injection": "인젝션"}
_MAX_SHOWN_FINDINGS = 5  # 한 문서가 화면을 통째로 먹지 않게 — 나머지는 셈으로만 말한다
_EXCERPT_COLS = 120


def _quote(text: str) -> str:
    """문서 원문 조각을 **무력하게** 그린다 — 이 문자열은 남이 쓴 것이고 우리 말이 아니다.

    발췌와 사유는 검사에 걸린 문서에서 나온다. 걸린 문서는 정의상 인젝션 문구를 담고 있을 수
    있으므로, 화면에 우리 안내와 같은 모양으로 앉으면 그 자체가 두 번째 주입면이 된다. 그래서
    한 줄로 눕히고 인용부호로 가둔 뒤 폭을 자른다 (B가 이미 `<`·`>`를 바꿔 두었고, 비밀 값은
    걸린 스팬이 [redacted-credential]로 가려진 채로 온다 — 여기서 다시 가리지 않는다)."""
    flat = " ".join(str(text).split())
    return "「" + ui.fit(flat, _EXCERPT_COLS) + "」" if flat else "「」"


def _show_failed_document(row: dict, level: Callable[[str], None] = ui.warn) -> None:
    """못 들어간 문서 한 건 — 사유와 **걸린 자리**를 보여준다.

    조용히 건너뛰면 사람은 문서가 저장된 줄 안다. 사유 한 줄만 내면 "무엇이 어디서 걸렸는지"를
    못 물어보고 통째 거절과 통째 승인 중 하나만 고르게 되는데, 그건 고르는 게 아니다."""
    findings = row.get("findings") or []
    head = "검사에 걸려 막힘" if findings else "읽지 못함"
    level(f"{head} · {os.path.basename(str(row.get('path') or ''))} — {row.get('error') or ''}")
    for finding in findings[:_MAX_SHOWN_FINDINGS]:
        kind = _FINDING_KINDS.get(str(finding.get("kind")), str(finding.get("kind") or "?"))
        line, column = int(finding.get("line") or 0), int(finding.get("column") or 0)
        where = f"{line}행 {column}열" if line else "위치 미상"
        ui.step(f"  {kind} · {where} · {finding.get('reason') or ''}")
        if finding.get("excerpt"):
            ui.step(f"    {_quote(finding['excerpt'])}")
    if len(findings) > _MAX_SHOWN_FINDINGS:
        ui.step(f"  … 외 {len(findings) - _MAX_SHOWN_FINDINGS}건")


def run_project_ingest(
    paths: list[str],
    strategy: str = "",
    yes: bool = False,
    json_out: bool = False,
    lane: str = "",
) -> int:
    """던진 문서를 파싱·판정해 프로젝트 메모리 승인 대기로 올린다 (기본 미리보기)."""

    def _do() -> int:
        from ...k6 import project_root
        from ...project_memory import ingest

        ready, failed = ingest.plan(list(paths), strategy=strategy or None, lane=lane or None)
        # 연결을 묻는 것은 graph 레인뿐이다. local 레인은 저장소 정본(.asgard/memory/documents/)과
        # 로컬 색인만 쓰므로 백엔드가 없어도, 죽어 있어도 돈다 — 그게 그 레인이 있는 이유다.
        # 입구에서 무조건 물으면 오프라인으로 쓰라고 만든 길이 오프라인에서 막힌다.
        graph_bound = any(document.lane == ingest.LANE_GRAPH for document in ready)
        found = find_config(os.getcwd())
        if graph_bound and not found:
            raise errors.Unavailable(
                "project memory is not connected — run `asgard memory connect <endpoint>` "
                "(백엔드 없이 넣으려면 --lane local)"
            )
        root, cfg = found if found else (str(project_root()), {})
        if yes and graph_bound and not is_backend_trusted(cfg):
            raise errors.Unavailable("project memory backend is not trusted on this machine; run asgard memory connect")
        rows: list[dict] = [
            {
                "name": d.name,
                "path": d.path,
                "kind": d.kind,
                "strategy": d.strategy,
                "lane": d.lane,
                "graph_units": d.graph_units,
                "auto_strategy": d.signals.get("auto_strategy"),
                "overridden": d.signals.get("overridden"),
                "chars": len(d.text),
                "entities": [name for name, _kind in d.entities],
                "document_id": d.document_id,
                "signals": d.signals,
            }
            for d in ready
        ]
        if not yes:
            payload = {"documents": rows, "failed": failed, "approved": False}
            if json_out:
                print(_json.dumps(payload, ensure_ascii=False, indent=2))
                return 0
            # 준비된 것만 세면 막힌 문서가 머리글에서 사라진다 — 던진 개수와 안 맞는 순간
            # 사람은 나머지가 통과한 줄 안다.
            blocked = sum(1 for row in failed if row.get("findings"))
            counted = f"{len(ready)} document(s)" + (f" · 막힘 {blocked}건" if blocked else "")
            ui.head(f"project memory ingest · {counted}")
            for row in rows:
                mark = " (지정)" if row["overridden"] else ""
                ui.step(
                    f"{row['name']} · {row['kind']} · 전략 {row['strategy']}{mark} · "
                    f"{row['chars']:,}자 · 엔티티 {len(row['entities'])} · 레인 {row['lane']}"
                )
                if row["lane"] == ingest.LANE_LOCAL:
                    ui.warn(
                        f"  {row['name']}은 그래프 수용 상한을 넘어요 "
                        f"(예측 unit {row['graph_units']} > {ingest.GRAPH_UNIT_CEILING}) — "
                        "저장소 정본 + 로컬 인덱스로 갈게요 (검색은 되고, 뱅크도 지켜요)"
                    )
            for row in failed:
                _show_failed_document(row)
            if ready:
                ui.warn("아직 저장 안 했어요 — 보시고 --yes를 붙여 주세요")
            return 0 if ready or not failed else 1
        if any(d.lane == ingest.LANE_GRAPH for d in ready):
            ingest.ensure_strategies(cfg)
        staged = ingest.stage_documents(root, cfg, ready)
        if json_out:
            print(_json.dumps({"staged": staged, "failed": failed}, ensure_ascii=False, indent=2))
            return 0 if not failed else 1
        for row in staged:
            if row["lane"] == ingest.LANE_LOCAL:
                ui.ok(f"{row['name']} · 저장소 정본 → {row['canonical_path']} (커밋하면 팀과 나눠 가져요)")
            else:
                ui.ok(f"{row['name']} · 승인 대기 — asgard memory project-approve {row['approval_id']}")
        for row in failed:
            _show_failed_document(row, level=ui.fail)
        return 0 if not failed else 1

    return _guard(_do)
