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
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from collections.abc import Callable
from urllib.parse import quote

from .. import memory, ui
from ..memory_bridge import (
    backend_target,
    find_config,
    is_backend_trusted,
)
from ..project_memory import commit_approved_record, propose_completion, retain_turn

_PLAN_ID = re.compile(r"^[0-9a-f]{64}$")
_PLAN_THREAD_LOCK = threading.Lock()
PERSONAL_CLAIM_LEASE_SECONDS = 300


def _pending_dir() -> str:
    d = os.path.join(memory.ensure_home(), ".pending-plans")
    if os.path.islink(d):
        raise ValueError("personal approval directory must not be a symlink")
    os.makedirs(d, mode=0o700, exist_ok=True)
    memory._chmod(d, 0o700)
    return d


def _save_plan(text: str, kind: str, plan: dict) -> str:
    text_sha256 = hashlib.sha256(text.encode()).hexdigest()
    raw = _json.dumps(
        {"text_sha256": text_sha256, "kind": kind, "plan": plan},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
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
    text_matches = payload.get("text") == text or hmac.compare_digest(
        str(payload.get("text_sha256") or ""), hashlib.sha256(text.encode()).hexdigest()
    )
    if not text_matches or payload.get("kind") != kind or not isinstance(payload.get("plan"), dict):
        raise ValueError("approval plan does not match text/kind — re-run ingest")
    return payload["plan"]


@contextlib.contextmanager
def _personal_plan_guard():
    """개인 approval 파일의 프로세스·스레드 공통 claim lock."""
    with _PLAN_THREAD_LOCK:
        with memory._lock(_pending_dir()):
            yield


def _claimed_path(plan_id: str, token: str) -> str:
    return os.path.join(_pending_dir(), f"{plan_id}.{token}.claimed.json")


def _recover_stale_claim(plan_id: str) -> None:
    """lease가 만료된 crash claim을 pending으로 되돌린다. 호출자는 plan guard를 보유한다."""
    pending = _pending_dir()
    original = os.path.join(pending, f"{plan_id}.json")
    if os.path.exists(original):
        return
    prefix, suffix = f"{plan_id}.", ".claimed.json"
    for name in sorted(os.listdir(pending)):
        if not (name.startswith(prefix) and name.endswith(suffix)):
            continue
        claimed = os.path.join(pending, name)
        try:
            if time.time() - os.stat(claimed, follow_symlinks=False).st_mtime > PERSONAL_CLAIM_LEASE_SECONDS:
                os.replace(claimed, original)
                return
        except OSError:
            continue


def _claim_plan(plan_id: str, text: str, kind: str) -> tuple[dict, str]:
    """approval ID를 원자 claim한다. ingest 실패 시 _finish_plan(..., success=False)로 복구한다."""
    with _personal_plan_guard():
        _recover_stale_claim(plan_id)
        plan = _load_plan(plan_id, text, kind)
        token = secrets.token_hex(8)
        os.replace(
            os.path.join(_pending_dir(), f"{plan_id}.json"),
            _claimed_path(plan_id, token),
        )
        return plan, token


def _finish_plan(plan_id: str, token: str, *, success: bool) -> None:
    with _personal_plan_guard():
        claimed = _claimed_path(plan_id, token)
        if success:
            with contextlib.suppress(OSError):
                os.remove(claimed)
            return
        original = os.path.join(_pending_dir(), f"{plan_id}.json")
        if os.path.exists(claimed) and not os.path.exists(original):
            os.replace(claimed, original)


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
        # 사용자 정정 신호 채굴 (제2 채굴원) — 개인/진화 스코프라 프로젝트 메모리 연결과 무관하게
        # 항상 시도한다. 탐지 실패·중복·오염 = 조용히 False (턴을 막지 않는다).
        with contextlib.suppress(Exception):
            from ..evolution import record_correction

            record_correction(
                os.getcwd(), str(payload.get("user_text") or ""), str(payload.get("assistant_text") or "")
            )
        found = find_config(os.getcwd())
        if not found:
            print(_json.dumps({"status": "skipped", "reason": "project memory not connected"}))
            return 0
        root, cfg = found
        output: dict[str, object]
        auto_retain = bool(cfg.get("auto_retain_turns", False))
        backend_trusted = is_backend_trusted(cfg) if auto_retain else False
        if auto_retain and backend_trusted:
            result = retain_turn(
                root,
                cfg,
                session_id=str(payload.get("session_id") or mode),
                turn_id=str(payload.get("turn_id") or "turn"),
                user_text=str(payload.get("user_text") or ""),
                assistant_text=str(payload.get("assistant_text") or ""),
                mode=mode,
            )
            output = {
                "status": result.status,
                "document_id": result.document_id,
                "reason": result.reason,
            }
        else:
            output = {
                "status": "skipped",
                "document_id": "",
                "reason": (
                    "automatic raw-turn retain is disabled"
                    if not auto_retain
                    else "project memory backend is not trusted on this machine"
                ),
            }
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
    """Native/CLI 사용자 승인을 Git 정본 → backend 순서로 실행한다."""

    def _do() -> int:
        found = find_config(os.getcwd())
        if not found:
            raise ValueError("project memory is not connected")
        root, cfg = found
        if not is_backend_trusted(cfg):
            raise ValueError("project memory backend is not trusted on this machine; run asgard memory connect")
        target = backend_target(cfg)
        result = commit_approved_record(root, cfg, approval_id)
        if result.get("canonical_path"):
            ui.ok(f"project memory canonical saved → {result['canonical_path']} (commit this file)")
        ui.ok(f"project memory saved → engine={target['engine']} project_id={target['project_id']}")
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
        claim_token = None
        if plan_id:
            plan, claim_token = _claim_plan(plan_id, text, kind)
        else:
            plan = memory.plan_ingest(text)
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
        try:
            action, slug = memory.ingest(text, kind=kind, plan=plan)  # 승인한 그 계획 그대로
        except Exception:
            if plan_id and claim_token:
                _finish_plan(plan_id, claim_token, success=False)
            raise
        if plan_id and claim_token:
            _finish_plan(plan_id, claim_token, success=True)
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


def run_episodes(text: str, k: int, quest: str, json_out: bool) -> int:
    """세션 원문(에피소드) 검색 표면 — 비권위 참고. 빈 질의는 인덱스 현황만 보인다."""

    def _do() -> int:
        from ..agent import episodes

        root = os.getcwd()
        if not text.strip() and not quest.strip():
            s = episodes.stats(root)
            if json_out:
                print(_json.dumps(s, ensure_ascii=False))
            else:
                ui.step(f"episodes: {s['turns']} turns · {s['quests']} quests · raw {s['raw_bytes']} bytes")
            return 0
        if quest.strip() and not text.strip():
            turns = episodes.turns_for_quest(root, quest.strip())
            if json_out:
                print(_json.dumps(turns, ensure_ascii=False, indent=1))
                return 0
            if not turns:
                ui.step("no turns for quest")
                return 0
            for t_ in turns:
                print(f"t{t_['seq']}  {t_['request'][:80]}")
            return 0
        hits = episodes.search(root, text, k=k, quest=quest.strip() or None)
        if json_out:
            print(_json.dumps(hits, ensure_ascii=False, indent=1))
            return 0
        if not hits:
            ui.step("no matches")
            return 0
        for h in hits:
            tag = f"  quest:{h['quest']}" if h["quest"] else ""
            print(f"t{h['seq']}{tag}\n    {h['request']}\n    → {h['excerpt']}")
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


def run_export_okf(destination: str) -> int:
    def _do() -> int:
        count = memory.export_okf(destination)
        ui.ok(f"exported {count} personal memory pages → {os.path.abspath(os.path.expanduser(destination))}")
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

        # include_skills: CC 훅 표면 한정 — learned 스킬 포인터를 회수에 동봉 (자가발전×메모리 결합).
        print(recall_note(text, start=os.getcwd(), include_skills=True), end="")
    return 0


def run_path(directory: str | None = None, reset: bool = False) -> int:
    def _do() -> int:
        if directory and reset:
            raise ValueError("use either --set or --reset")
        if directory or reset:
            from ..settings import load_global, save_global

            configured = dict(load_global().get("memory") or {})
            if reset:
                configured.pop("directory", None)
            else:
                path = os.path.abspath(os.path.expanduser(directory or ""))
                memory.ensure_home(path)
                configured["directory"] = path
            save_global("memory", configured)
            if os.environ.get(memory.MEMORY_ENV):
                ui.warn(f"{memory.MEMORY_ENV} overrides the saved directory")
        print(memory.memory_dir())
        return 0

    return _guard(_do)


def run_obsidian() -> int:
    def _do() -> int:
        vault = memory.ensure_home()
        if not os.path.isdir(os.path.join(vault, ".obsidian")):
            raise ValueError(f"open this folder as an Obsidian vault once, then retry: {vault}")
        uri = f"obsidian://open?path={quote(os.path.join(vault, memory.INDEX), safe='')}"
        if sys.platform == "darwin":
            subprocess.run(["open", uri], check=True)
        elif os.name == "nt":  # pragma: no cover - Windows 전용
            os.startfile(uri)  # type: ignore[attr-defined]
        elif not webbrowser.open(uri):  # pragma: no cover - Linux desktop 환경 의존
            raise OSError("could not open the Obsidian URI")
        ui.ok(f"opened personal memory in Obsidian → {vault}")
        return 0

    return _guard(_do)


def _backend_options(values: list[str]) -> dict:
    options = {}
    for value in values:
        key, separator, raw = value.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ValueError(f"invalid backend option {value!r}; expected KEY=VALUE")
        if re.search(r"(?:secret|password|passwd|token|api[_-]?key|credential)", key, re.I):
            raise ValueError(f"backend option {key!r} looks secret; use an environment variable in the adapter")
        try:
            options[key] = _json.loads(raw)
        except Exception:
            options[key] = raw
    return options


def run_connect(
    endpoint: str,
    project_id: str | None,
    *,
    engine: str = "hindsight",
    option_values: list[str] | None = None,
    claim: bool = False,
    adopt_existing: bool = False,
    timeout: int | None = None,
) -> int:
    """프로젝트를 선택된 shared-memory backend에 연결하고 통합 설정에 기록한다."""

    def _do() -> int:
        from .. import memory_bridge
        from ..project_memory_backends import ProjectMemoryBinding, get_backend
        from ..settings import load_project

        root = os.getcwd()
        previous = dict(memory_bridge.project_memory_section(load_project(root)) or {})
        previous_uid = str(previous.get("project_uid") or "").strip()
        project_uid = previous_uid or str(uuid.uuid4())
        explicit_project_id = bool(project_id and project_id.strip())
        pid = str(project_id or previous.get("project_id") or previous.get("bank") or "").strip()
        if not pid:
            slug = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(root)).strip("-.") or "project"
            pid = f"{slug}-{project_uid[:8]}"
        selected_engine = engine.strip().lower()
        selected_options = _backend_options(option_values or [])
        same_target = (
            str(previous.get("engine") or "hindsight").strip().lower() == selected_engine
            and str(previous.get("endpoint") or previous.get("server") or "").rstrip("/") == endpoint.rstrip("/")
            and str(previous.get("project_id") or previous.get("bank") or "").strip() == pid
        )
        binding_id = str(previous.get("binding_id") or "").strip() if same_target else ""
        config = {
            "engine": selected_engine,
            "endpoint": endpoint.rstrip("/"),
            "project_id": pid,
            "options": selected_options,
            "project_uid": project_uid,
            "binding_id": binding_id,
        }
        if timeout is not None:
            # 동기 retain 이 backend LLM 추출을 기다린다 — 느린 게이트웨이는 기본 15s 를 넘긴다
            # (실측 26-07-24: qwen3:8b 로컬 추출 ~16s → binding write 가 기본값에서 항상 timeout)
            config["timeout"] = int(timeout)
        backend = get_backend(config)
        try:
            readiness = backend.readiness()
            if readiness.status != "ready":
                raise ValueError(
                    f"backend is not ready ({readiness.detail or readiness.status}); binding was not trusted or saved"
                )
            marker = backend.read_binding()
            if marker is not None:
                if marker.project_id != pid or marker.project_uid != project_uid:
                    raise ValueError("selected project-memory namespace is already bound to a foreign project")
                if binding_id and marker.binding_id != binding_id:
                    raise ValueError("selected project-memory namespace binding has drifted")
                if not binding_id and not adopt_existing:
                    raise ValueError(
                        "existing bound namespace requires --adopt-existing for this project configuration"
                    )
                binding_id = marker.binding_id
            else:
                count = backend.namespace_document_count()
                if count > 0 and not adopt_existing:
                    raise ValueError(
                        f"unbound namespace already contains {count} document(s); use a new bank or --adopt-existing explicitly"
                    )
                if count == 0 and explicit_project_id and not claim and not adopt_existing:
                    # 빈 뱅크의 명시 이름은 곧 새 뱅크 개설 의사 — 별도 --claim 을 요구하던 마찰 제거
                    # (오딘 결정 26-07-23: connect 한 줄이면 아스가르드가 알아서). 데이터가 있는 뱅크의
                    # 입양(--adopt-existing)만 명시 동의로 남긴다.
                    ui.step(f"빈 네임스페이스 '{pid}' — 새 뱅크로 클레임")
                if not binding_id:
                    binding_id = str(uuid.uuid4())
                marker = ProjectMemoryBinding(project_uid=project_uid, binding_id=binding_id, project_id=pid)
                result = backend.write_binding(marker)
                if not result.success:
                    raise ValueError(result.error or "project-memory binding write was rejected")
                if backend.read_binding() != marker:
                    raise ValueError("project-memory binding verification failed after write")
        finally:
            backend.close()
        config["binding_id"] = binding_id
        ui.ok(f"backend ready and bound: {selected_engine} @ {config['endpoint']}")
        p = memory_bridge.write_config(
            root,
            str(config["endpoint"]),
            pid,
            engine=selected_engine,
            options=selected_options,
            project_uid=project_uid,
            binding_id=binding_id,
            timeout=timeout,
        )
        memory_bridge.trust_backend(config)
        ui.ok(f"connected: engine={selected_engine} project_id={pid} → {p} (커밋해서 팀과 공유)")
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
    return [
        candidate
        for candidate in project_memory.scan_project(root, changed_paths=changed)
        if candidate.path in selected
    ]


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
    all_files: bool = False, yes: bool = False, json_out: bool = False, plan_id: str | None = None
) -> int:
    """중요 artifact를 stable record ID로 선택된 프로젝트 backend에 projection한다."""

    def _do() -> int:
        from .. import project_memory
        from ..memory_bridge import find_config

        root = os.getcwd()
        found = find_config(root)
        if not found:
            raise ValueError("project memory is not connected — run `asgard memory connect <endpoint>`")
        _, cfg = found
        if not is_backend_trusted(cfg):
            raise ValueError("project memory backend is not trusted on this machine; run asgard memory connect")
        target = backend_target(cfg)
        engine = str(target["engine"])
        project_id = str(target["project_id"])
        candidates = _project_candidates(root, all_files)
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


def run_project_rehydrate(yes: bool = False, plan_id: str | None = None, json_out: bool = False) -> int:
    """프로젝트 `.asgard/memory/records/` 정본을 현재 backend에 stable replace한다."""

    def _do() -> int:
        from .. import project_memory

        found = find_config(os.getcwd())
        if not found:
            raise ValueError("project memory is not connected — run `asgard memory connect <endpoint>`")
        root, cfg = found
        if not is_backend_trusted(cfg):
            raise ValueError("project memory backend is not trusted on this machine; run asgard memory connect")
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
                for row in plan["records"]:
                    ui.step(f"replace · {row['record_id']} · {row['path']}")
                if not plan["records"]:
                    ui.step("canonical records 없음")
                ui.warn(f"아직 저장하지 않음 — 검토 후 --yes --plan-id {plan['plan_id']} 추가")
            return 0
        if not plan_id:
            raise ValueError("--yes requires the --plan-id from a fresh preview")
        result = project_memory.rehydrate_records(root, cfg, plan_id)
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
                f"project memory rehydrated: {output['items_count']} record(s) → "
                f"engine={target['engine']} project_id={target['project_id']}"
            )
        else:
            ui.fail(f"project memory rehydrate failed: {output['error'] or 'backend rejected publication'}")
        return 0 if output["success"] else 1

    return _guard(_do)


def run_norn(
    apply: bool = False, nudge: bool = False, json_out: bool = False, auto: bool = False, wake: bool = False
) -> int:
    """노른 패스 — LLM 제안 델타를 결정적 검증으로 거른 뒤, --apply 시에만 커밋한다.

    자율 계층 (오딘 결정 26-07-24): --wake(훅)는 due 시 모드에 따라 백그라운드 --auto 를
    분리 스폰하거나(safe/full) 넛지만 남긴다(off). --auto 는 자격 op 만 즉시 자동 적용."""

    def _do() -> int:
        from ..memory import norn as norn_mod

        d = memory.ensure_home()
        if wake:  # 훅 소비 표면 — due 아니면 침묵, due 면 모드별 분기 (latch 는 상태 공유)
            due, reason = norn_mod.norn_due(d)
            if not due:
                return 0
            mode = norn_mod.auto_mode()
            if mode == "off":
                line = norn_mod.nudge_line(d)
                if line:
                    print(line)
                return 0
            state = norn_mod._load_state(d)
            digest = str(norn_mod._log_lines(d))
            if state.get("auto_spawn_digest") == digest:
                return 0  # 같은 누적 상태로 이미 스폰 — 중복 백그라운드 방지
            state["auto_spawn_digest"] = digest
            norn_mod._save_state(d, state)
            exe = shutil.which("asgard") or sys.argv[0]
            subprocess.Popen(  # 분리 스폰 — 훅 타임아웃(10s)과 LLM 소요(수십 s)를 격리한다
                [exe, "memory", "norn", "--auto"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            print(f"위그드라실 노른 자동 통합 시작 — {reason} (모드 {mode}: 추가는 자율, 병합·보관은 제안)")
            return 0
        if auto:  # 자율 실행 본체 — 모드 자격분만 적용, 잔류분은 제안으로 보고
            result = norn_mod.run_auto(os.getcwd(), d)
            if json_out:
                print(_json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            ui.head(f"위그드라실 노른 자동 통합 · 모드 {result['mode']}")
            for op in result["applied"]:
                if op["op"] == "insight":
                    ui.ok(f"insight 기록 · {op['title']} ({op['confidence']}) ← {', '.join(op['sources'])}")
                elif op["op"] == "contradiction":
                    ui.warn(f"contradiction · {op['a']} ↔ {op['b']} — 사람이 해소")
                else:
                    ui.ok(f"{op['op']} · {op.get('slug') or op.get('src', '')}")
            for op in result["proposed"]:
                ui.step(f"제안 잔류 · {op['op']} — asgard memory norn 으로 검토")
            if result["report"]:
                ui.step(f"리포트 · {os.path.relpath(result['report'], d)}")
            if not result["applied"] and not result["proposed"]:
                ui.ok("적용·제안 없음 — 위키가 이미 정돈되어 있다")
            return 0
        if nudge:  # 훅 소비 표면 — due + latch 통과 시 한 줄, 그 외 침묵
            line = norn_mod.nudge_line(d)
            if line:
                print(line)
            return 0
        due, reason = norn_mod.norn_due(d)
        plan = norn_mod.plan_norn(os.getcwd(), d)
        if json_out and not apply:
            print(
                _json.dumps(
                    {"due": due, "reason": reason, **{k: plan[k] for k in ("ops", "dropped")}},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        ui.head(f"위그드라실 노른 · {'due — ' + reason if due else reason}")
        if not plan["ops"] and not plan["dropped"]:
            ui.ok("제안 없음 — 위키가 이미 정돈되어 있다")
            return 0
        for op in plan["ops"]:
            if op["op"] == "merge":
                ui.step(f"merge · {op['src']} → {op['dst']} (sim {op['sim']}) — {op['why']}")
            elif op["op"] == "archive":
                ui.step(f"archive · {op['slug']} — {op['why']}")
            elif op["op"] == "insight":
                ui.step(f"insight · {op['title']} ({op['confidence']}) ← {', '.join(op['sources'])}")
            else:
                ui.warn(f"contradiction · {op['a']} ↔ {op['b']} — {op['why']}")
        for row in plan["dropped"]:
            ui.step(ui.dim(f"기각 · {row['op'].get('op', '?')} — {row['reason']}"))
        if not apply:
            ui.warn("아직 적용하지 않음 — 검토 후 asgard memory norn --apply")
            return 0
        result = norn_mod.apply_norn(d, plan)
        if json_out:
            print(_json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        for op in result["failed"]:
            ui.fail(f"{op['op']} 실패 — {op.get('error', '')}")
        ui.ok(
            f"노른 적용: {len(result['applied'])}건 (실패 {len(result['failed'])}건) · "
            f"리포트 {os.path.relpath(result['report'], d)}"
            + (f" · 백업 {os.path.relpath(result['backup'], d)}" if result["backup"] else "")
        )
        return 0 if not result["failed"] else 1

    return _guard(_do)


def run_norn_restore(slug: str) -> int:
    """노른 archive 복원 — 최신 아카이브 스냅샷을 pages/ 로 되돌린다."""

    def _do() -> int:
        from ..memory.norn import restore_page

        if restore_page(slug):
            ui.ok(f"복원됨: {slug}")
            return 0
        ui.fail(f"아카이브에 없음: {slug}")
        return 1

    return _guard(_do)


def run_project_reflect(question: str, budget: str = "low", json_out: bool = False) -> int:
    """프로젝트 메모리 backend 의 Reflect 합성 답변 — 읽기 전용 자문 (게이트 증거 아님)."""

    def _do() -> int:
        from ..project_memory_backends import get_backend

        found = find_config(os.getcwd())
        if not found:
            raise ValueError("project memory is not connected — run `asgard memory connect <endpoint>`")
        _, cfg = found
        if not is_backend_trusted(cfg):
            raise ValueError("project memory backend is not trusted on this machine; run asgard memory connect")
        backend = get_backend(cfg)
        try:
            reflect = getattr(backend, "reflect", None)
            if not callable(reflect):
                raise ValueError(f"backend '{backend.engine}' does not support reflect")
            output = reflect(question, budget=budget)
        finally:
            backend.close()
        facts = output.get("based_on") or {}
        memories = facts.get("memories") if isinstance(facts, dict) else None
        if json_out:
            print(_json.dumps(output, ensure_ascii=False, indent=2))
            return 0
        ui.head(f"project memory reflect · engine={backend.engine} · project_id={backend.project_id}")
        print(str(output.get("text") or "").strip())
        if isinstance(memories, list) and memories:
            print(ui.dim(f"근거 memories {len(memories)}건 — 자문일 뿐 완료 증거가 아니다"))
        return 0

    return _guard(_do)
