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
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
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


def run_add(text: str, title: str | None, kind: str, links: str) -> int:
    def _do() -> int:
        slug, path = memory.add(text, title=title, kind=kind, links=links)
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
        # 개인 에피소드 레인 적재 — 네이티브 루프의 `_persist_turn` 이 하는 일을 외부
        # 클라이언트는 여기서 한다. 프로젝트 메모리 연결 **앞**에 두는 것이 핵심이다:
        # 개인 대화 원문은 팀 뱅크와 무관하고, 아래 early-return 뒤에 두면 프로젝트가
        # 안 붙은 저장소에서는 에피소드가 영영 안 쌓인다 (26-07-28 실측 결함).
        # 원문은 credential 편집(turn_store._redact) 후 0600 로컬 파일에만 남는다.
        with contextlib.suppress(Exception):
            from ..agent.turn_store import append_turn

            append_turn(
                os.getcwd(),
                str(payload.get("user_text") or ""),
                str(payload.get("assistant_text") or ""),
                quest_id=str(payload.get("quest_id") or "") or None,
                session_id=str(payload.get("session_id") or mode),
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
            why = f"slot={plan['slot']}" if plan.get("slot") else f"sim={plan['sim']}"
            ui.step(f"plan: merge into '{plan['title']}' ({plan['slug']}, {why})")
            # 흡수는 페이지 삭제다 — 승인 전에 반드시 눈에 보여야 한다
            for slug, _rev in plan.get("absorb") or []:
                ui.warn(f"plan: absorb (delete) contradicting page — {slug}")
        else:
            ui.step("plan: create new page")
        # 자동저장은 이 표면에도 같은 답을 해야 한다 — 툴에서는 바로 저장되는데 CLI 에서만
        # 되묻는다면, 사용자가 켠 설정이 어디서 듣는지를 매번 기억해야 한다.
        auto = memory.autosave_enabled()
        if auto and not yes:
            ui.step("autosave on — 승인 없이 저장합니다 (끄기: asgard memory autosave off --tier personal)")
        if not yes and not auto:
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


def run_proposals(json_out: bool = False) -> int:
    """에이전트가 올린 개인 기억 제안 대기열 — 사람이 읽고 승인하는 자리."""

    def _do() -> int:
        from ..memory import propose

        rows = propose.pending()
        if json_out:
            print(_json.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        if not rows:
            ui.step("대기 중인 기억 제안 없음")
            return 0
        ui.head(f"personal memory · 제안 {len(rows)}건")
        for row in rows:
            verb = "병합" if row.get("plan_action") == "merge" else "새 페이지"
            age = max(0, int((time.time() - float(row.get("created") or 0)) / 60))
            ui.step(f"{row['id']}  `{row['kind']}` · {verb} · {age}분 전 · agent={row.get('agent') or '?'}")
            ui.step(f"  {row['text'][:220]}")
        ui.step("승인: asgard memory approve <id>   ·   버림: asgard memory discard <id>")
        ui.step("매번 승인이 번거로우면: asgard memory autosave on --tier personal")
        return 0

    return _guard(_do)


_AUTOSAVE_TIERS = ("personal", "project", "both")


def _autosave_state() -> tuple[bool, bool | None]:
    """(1차, 2차) 현재 상태 — 2차는 프로젝트 메모리 미연결이면 None (끈 것과 다르다)."""
    from ..memory import autosave_enabled as personal_on
    from ..memory_bridge import autosave_enabled as project_on

    found = find_config(os.getcwd())
    return personal_on(), (project_on(found[1]) if found else None)


def run_autosave(state: str | None, tier: str, json_out: bool = False) -> int:
    """기억 자동저장 토글 — 승인 왕복을 켜고 끄는 하나뿐인 표면 (1차·2차 각각).

    상태만 묻는 호출(state=None)이 기본이다: 설정은 조용히 바뀌면 안 되고, 조용히 켜져 있어도
    안 된다. 켜 놓고 잊은 자동저장은 "왜 이게 저장돼 있지"의 답을 아무 데서도 못 찾게 만든다."""

    def _do() -> int:
        if tier not in _AUTOSAVE_TIERS:
            ui.fail(f"tier 는 {' | '.join(_AUTOSAVE_TIERS)} 중 하나여야 합니다")
            return 1
        if state is not None and state not in ("on", "off"):
            ui.fail("상태는 on 또는 off 여야 합니다")
            return 1
        want = state == "on"
        if state is not None and tier in ("personal", "both"):
            from ..settings import own_global, save_global

            save_global("memory", {**own_global("memory"), "autosave": want})
        if state is not None and tier in ("project", "both"):
            found = find_config(os.getcwd())
            if not found:
                ui.warn("프로젝트 메모리가 연결돼 있지 않아 2차 자동저장은 건너뜁니다 (asgard memory connect)")
            else:
                from ..settings import load_project, save_project

                root = found[0]
                section = dict(load_project(root).get("project_memory") or {})
                save_project(root, "project_memory", {**section, "autosave": want})
        personal, project = _autosave_state()
        if json_out:
            print(_json.dumps({"personal": personal, "project": project}, ensure_ascii=False))
            return 0
        ui.head("memory autosave")
        ui.step(f"1차 개인 기억 (memory.autosave)          · {'on' if personal else 'off'}")
        ui.step(
            "2차 프로젝트 기억 (project_memory.autosave) · "
            + ("미연결" if project is None else ("on" if project else "off"))
        )
        if personal or project:
            ui.step("자동저장이 켜져도 인젝션·credential 스캔과 중복 병합은 그대로 지납니다")
        else:
            ui.step("켜기: asgard memory autosave on [--tier personal|project|both]")
        return 0

    return _guard(_do)


def run_approve(proposal_id: str, json_out: bool = False) -> int:
    """제안 하나를 승인해 정본에 쓴다."""

    def _do() -> int:
        from ..memory import propose

        try:
            action, slug = propose.commit(proposal_id)
        except ValueError as exc:
            ui.fail(str(exc))
            return 1
        if json_out:
            print(_json.dumps({"action": action, "slug": slug}, ensure_ascii=False))
            return 0
        ui.ok(f"{action} · {slug}")
        return 0

    return _guard(_do)


def run_discard(proposal_id: str) -> int:
    """제안 하나를 버린다."""

    def _do() -> int:
        from ..memory import propose

        if propose.discard(proposal_id):
            ui.ok(f"버림 · {proposal_id}")
            return 0
        ui.fail(f"없거나 이미 처리된 제안 id · {proposal_id}")
        return 1

    return _guard(_do)


def run_reindex() -> int:
    def _do() -> int:
        d = memory.ensure_home()
        n = memory.reindex(d)
        coverage = memory.vec_coverage(d)
        ui.ok(f"reindexed {n} pages → index.md + state.db")
        # 고쳤으면 표시를 지운다 — 안 지우면 넛지가 영영 침묵해 다음 드리프트를 못 알린다.
        with contextlib.suppress(OSError):
            os.remove(os.path.join(d, COVERAGE_NUDGE_FLAG))
        from .. import memory_semantic as sem

        if sem.mode() == "off":
            ui.step("시맨틱 꺼짐 — 벡터는 만들지 않았다 (lexical 2경로)")
        elif coverage["ok"]:
            ui.ok(f"시맨틱 색인 · {coverage['fresh']}/{coverage['pages']} 페이지")
        else:
            ui.warn(f"시맨틱 색인 · {coverage['fresh']}/{coverage['pages']} 페이지 — 임베더를 못 불렀다")
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
        # include_episodes: 같은 표면 한정 — 네이티브만 갖고 있던 과거 세션 회상을 외부
        # 클라이언트에도 준다 (쓰기는 run_sync_turn, 읽기는 여기 — 두 반쪽이 짝을 이룬다).
        print(recall_note(text, start=os.getcwd(), include_skills=True, include_episodes=True), end="")
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


def run_obsidian(refresh_only: bool = False, json_out: bool = False) -> int:
    """개인 위키를 Obsidian vault 로 준비하고 연다 — 설정 스캐폴드 + 목차 재생성 + URI 열기."""

    def _do() -> int:
        from ..memory import vault as vault_mod

        state = vault_mod.refresh()
        vault = state["directory"]
        if json_out:
            print(_json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        if state["scaffolded"]:
            ui.step(f"vault 설정 생성 · {', '.join(state['scaffolded'])}")
        ui.step(f"목차 갱신 · {len(state['maps'])}개 지도 · {state['pages']} page(s)")
        if refresh_only:
            ui.ok(f"vault 준비됨 → {vault}")
            return 0
        # Obsidian URI 는 이미 등록된 vault 만 연다. 설정만 심어서는 등록되지 않으므로,
        # 한 번은 사람이 "Open folder as vault" 를 해야 한다 — 그 한 번을 정확히 안내한다.
        uri = f"obsidian://open?path={quote(os.path.join(vault, memory.INDEX), safe='')}"
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", uri], check=True)
            elif os.name == "nt":  # pragma: no cover - Windows 전용
                os.startfile(uri)  # type: ignore[attr-defined]
            elif not webbrowser.open(uri):  # pragma: no cover - Linux desktop 환경 의존
                raise OSError("could not open the Obsidian URI")
        except Exception as exc:
            ui.warn(f"Obsidian URI 열기 실패 ({type(exc).__name__}) — 폴더를 직접 vault 로 연다: {vault}")
            return 1
        ui.ok(f"opened personal memory in Obsidian → {vault}")
        ui.step(f"열리지 않으면 Obsidian 에서 이 폴더를 vault 로 한 번 연다: {vault}")
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
        # 소유권 신원은 설정 파일이 아니라 사이드카(.asgard/memory/binding.json)에 산다 — 설정 섹션만
        # 읽으면 재연결이 매번 새 project_uid 를 발급하고, 서버의 기존 마커와 어긋나 자기 뱅크를
        # "foreign" 으로 거절한다. 그러면 timeout·endpoint 조정도, 설정 변경으로 무효화된 신뢰의
        # 재승인도 불가능해진다 — 그 무효화가 안내하는 수리 명령이 바로 이 connect 다 (26-07-26 실측).
        # find_config 는 이미 같은 사이드카를 병합한다 (단일 신원 출처).
        sidecar = memory_bridge.read_binding_sidecar(root)
        previous_uid = str(previous.get("project_uid") or sidecar.get("project_uid") or "").strip()
        project_uid = previous_uid or str(uuid.uuid4())
        explicit_project_id = bool(project_id and project_id.strip())
        pid = str(
            project_id or previous.get("project_id") or previous.get("bank") or sidecar.get("project_id") or ""
        ).strip()
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
        binding_id = str(previous.get("binding_id") or sidecar.get("binding_id") or "").strip() if same_target else ""
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


def _project_candidates(root: str, all_files: bool, inventory: bool = False):
    from .. import project_memory

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
        if wake:  # 훅 소비 표면 — 판정·등급 분기·latch·스폰은 전부 norn.wake 단일 출처
            line = norn_mod.wake(os.getcwd(), d)
            if line:
                print(line)
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
                flag = f" ⚠ 극성 충돌 [{op['polarity_conflict']}]" if op.get("polarity_conflict") else ""
                ui.step(f"제안 잔류 · {op['op']}{flag} — asgard memory norn 으로 검토")
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
                # 적용 전에 반드시 보여야 하는 표식 — 출처의 주장을 뒤집었을 수 있다는 신호다.
                if flag := op.get("polarity_conflict"):
                    ui.warn(f"  ⚠ 극성 충돌 [{flag}] — 출처와 대조하고 적용할 것")
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
    """프로젝트 메모리 회고 — backend LLM 우선, 없으면 이쪽 provider 합성 (읽기 전용 자문)."""

    def _do() -> int:
        from ..project_memory.reflect import ReflectUnavailable, reflect
        from ..project_memory_backends import get_backend

        found = find_config(os.getcwd())
        if not found:
            raise ValueError("project memory is not connected — run `asgard memory connect <endpoint>`")
        root, cfg = found
        if not is_backend_trusted(cfg):
            raise ValueError("project memory backend is not trusted on this machine; run asgard memory connect")
        backend = get_backend(cfg)
        try:
            output = reflect(root, backend, question, budget=budget, cfg=cfg)
        except ReflectUnavailable as exc:
            ui.fail(str(exc))
            ui.step('서버 LLM 없이 답하려면 provider 를 연결하거나 [project_memory].reflect 를 "local" 로 둔다')
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
            ui.warn(f"답을 만들지 못했다 — {output.get('detail') or '근거 없음'}")
            return 1
        print(text)
        if isinstance(memories, list) and memories:
            print(ui.dim(f"근거 memories {len(memories)}건 — 자문일 뿐 완료 증거가 아니다"))
        if output.get("source") == "local":
            print(ui.dim(f"backend LLM 없이 이쪽 provider 가 합성 · {output.get('detail', '')}"))
        return 0

    return _guard(_do)


def run_backup(
    action: str = "create",
    name: str = "",
    label: str = "",
    keep: int = 0,
    json_out: bool = False,
) -> int:
    """개인 메모리 정본 백업 — create/list/restore/verify/prune."""

    def _do() -> int:
        from ..memory import backup as mb

        d = memory.ensure_home()
        keep_n = keep or mb.KEEP_DEFAULT
        if action == "list":
            rows = mb.listing(d)
            if json_out:
                print(_json.dumps({"backups": rows}, ensure_ascii=False, indent=2))
                return 0
            ui.head(f"memory backups · {len(rows)}건 · {os.path.join(d, mb.BACKUPS_DIR)}")
            for row in rows:
                ui.step(f"{row['name']} · {row['bytes'] / 1024:.1f} KiB")
            if not rows:
                ui.warn("백업 없음 — `asgard memory backup` 으로 첫 스냅샷을 만든다")
            return 0
        if action == "verify":
            summary = mb.verify(mb.resolve(d, name or "latest"))
            if json_out:
                print(_json.dumps(summary, ensure_ascii=False, indent=2))
            else:
                ui.ok(f"무결성 확인: {os.path.basename(summary['path'])} · {summary['members']} member(s)")
            return 0
        if action == "restore":
            summary = mb.restore(name or "latest", d)
            if json_out:
                print(_json.dumps(summary, ensure_ascii=False, indent=2))
            else:
                ui.ok(
                    f"복원됨: {summary['restored']} · {summary['pages']} page(s) 재색인 · "
                    f"직전 상태는 {summary['safety_backup']} 로 보관"
                )
            return 0
        if action == "prune":
            removed = mb.prune(d, keep=keep_n)
            if json_out:
                print(_json.dumps({"pruned": removed, "keep": keep_n}, ensure_ascii=False, indent=2))
            else:
                ui.ok(f"정리됨: {len(removed)}건 삭제 · 최신 {keep_n}건 유지")
            return 0
        summary = mb.create(d, label=label, keep=keep_n)
        mb.write_manifest_sidecar(d, summary)
        if json_out:
            print(_json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            ui.ok(
                f"백업됨: {summary['name']} · {summary['pages']} page(s)"
                + (f" · archive {summary['archived']}" if summary["archived"] else "")
            )
        return 0

    return _guard(_do)


def run_sync(
    set_remote: str = "",
    transport: str = "dir",
    branch: str = "main",
    unset: bool = False,
    dry_run: bool = False,
    adopt: bool = False,
    status_only: bool = False,
    json_out: bool = False,
) -> int:
    """개인 메모리 서버 연동 — dir(공유 폴더) 또는 git(원격 저장소) 전송."""

    def _do() -> int:
        from ..memory import sync as ms

        if unset:
            ms.clear_settings()
            ui.ok("동기화 원격 해제됨")
            return 0
        if set_remote:
            saved = ms.save_settings(set_remote, transport=transport, branch=branch)
            ui.ok(f"동기화 원격 설정: transport={saved['transport']} · {saved['remote']}")
            if not status_only:
                return 0
        if status_only:
            state = ms.status()
            if json_out:
                print(_json.dumps(state, ensure_ascii=False, indent=2))
                return 0
            ui.head("memory sync status")
            ui.step(f"remote · {state['remote'] or '미설정'} ({state['transport'] or '-'})")
            ui.step(f"last sync · {state['last_sync'] or '없음'}")
            ui.step(f"tracked · {state['tracked']} / local {state['local_files']}")
            if state["unresolved_conflicts"]:
                ui.warn(f"미해결 충돌 {len(state['unresolved_conflicts'])}건 — conflicts/ 를 확인한다")
            return 0
        result = ms.sync(dry_run=dry_run, adopt=adopt)
        if json_out:
            print(_json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if not result.get("conflict") else 1
        head = "sync plan" if dry_run else "sync"
        ui.head(f"memory {head} · {result['transport']} · {result['remote']}")
        if result["transport"] == "git":
            if result.get("conflict"):
                ui.fail("원격과 갈라졌다 — 메모리 홈에서 직접 정리해야 한다")
                ui.step(f"git -C {memory.memory_dir()} pull --rebase origin {result['branch']}")
                return 1
            if dry_run:
                for path in result.get("pending", []):
                    ui.step(f"pending · {path}")
                if not result.get("pending"):
                    ui.ok("로컬 변경 없음")
                return 0
            ui.ok(
                f"committed={len(result.get('committed', []))} pushed={result.get('pushed')} "
                f"head={result.get('head', '') or '-'}"
            )
            if not result.get("pushed"):
                ui.warn(result.get("detail", "") or "push 실패 — 원격 권한을 확인한다")
                return 1
            return 0
        for key, verb in (
            ("push", "push"),
            ("pull", "pull"),
            ("delete_local", "delete local"),
            ("delete_remote", "delete remote"),
            ("merge", "merge log"),
        ):
            for path in result.get(key, []):
                ui.step(f"{verb} · {path}")
        for path in result.get("conflict", []):
            ui.warn(f"conflict · {path}")
        if result.get("conflict_copies"):
            ui.warn(f"원격본 보존: {len(result['conflict_copies'])}건 → conflicts/ (로컬 정본은 유지)")
        moved = sum(len(result.get(k, [])) for k in ("push", "pull", "delete_local", "delete_remote", "merge"))
        if dry_run:
            ui.ok(f"계획 {moved}건 · 충돌 {len(result.get('conflict', []))}건 — 적용하려면 --dry-run 을 뺀다")
        else:
            ui.ok(f"동기화 완료: {moved}건 반영 · 충돌 {len(result.get('conflict', []))}건")
        return 1 if result.get("conflict") else 0

    return _guard(_do)


def run_provider(set_spec: str = "", clear: bool = False, json_out: bool = False) -> int:
    """개인 메모리를 손질하는 provider 를 보이거나 바꾼다 (기본 = 메인 provider)."""

    def _do() -> int:
        from ..memory import manager

        if clear:
            manager.save_manager("")
            ui.ok("개인 메모리 관리자 해제 — 메인 provider 가 손질한다")
        elif set_spec:
            saved = manager.save_manager(set_spec)
            ui.ok(f"개인 메모리 관리자: {saved['provider']}" + (f" · {saved['model']}" if saved["model"] else ""))
        row = manager.describe(os.getcwd())
        if json_out:
            print(_json.dumps(row, ensure_ascii=False, indent=2))
            return 0 if row.get("ready") else 1
        ui.head("personal memory · manager")
        origin = {"main": "메인 provider", "config": "설정 지정", "env": f"env {manager.MANAGER_ENV}"}
        ui.step(
            f"curator · {row.get('provider') or '미해석'} {row.get('model') or ''} ({origin.get(row['source'], row['source'])})"
        )
        if row.get("configured") and row.get("main_provider"):
            ui.step(f"main · {row['main_provider']} {row.get('main_model', '')}")
        ui.step(f"inject · {'on' if row['inject_enabled'] else 'off (kill switch)'}")
        if not row.get("ready"):
            ui.warn("관리자 호출 불가 — " + "; ".join(row.get("missing") or ["provider 미설정"]))
            ui.step("손질(norn·pattern)만 멈춘다 — 저장·검색·회상은 LLM 없이 그대로 돈다")
            return 1
        if row["inject_enabled"] and not row.get("inject_allowed", True):
            ui.warn(f"주입 차단 — {row.get('provider')} 는 개인 메모리를 읽지 못한다 (관리는 가능)")
            ui.step(f'허용하려면 ~/.asgard 전역 설정 "memory".providers 에 "{row.get("provider")}" 추가')
        return 0

    return _guard(_do)


def run_pattern(apply: bool = False, json_out: bool = False, due_only: bool = False) -> int:
    """패턴 학습 — 대화 원문에서 오딘 관측을 뽑아 개인 위키로 승격 (기본 dry-run)."""

    def _do() -> int:
        from ..memory import pattern
        from ..memory.manager import ManagerUnavailable

        root, d = os.getcwd(), memory.ensure_home()
        if due_only:  # 훅 소비 표면 — due + latch 통과 시 한 줄, 그 외 침묵
            if json_out:
                due, why = pattern.pattern_due(root, d)
                print(_json.dumps({"due": due, "reason": why}, ensure_ascii=False))
                return 0
            line = pattern.nudge_line(root, d)
            if line:
                print(line)
            return 0
        try:
            plan = pattern.plan_pattern(root, d)
        except Exception as exc:
            # 관리자가 없든 호출이 실패했든 패턴 학습만 멈춘다 — 저장·검색·회상은 무LLM 경로다
            reason = str(exc) if isinstance(exc, ManagerUnavailable) else f"{type(exc).__name__}: {exc}"
            ui.warn(f"패턴 학습을 돌리지 못했다 — {reason}")
            ui.step("`asgard memory provider --set <provider>` 로 관리자를 지정하거나 메인 provider 를 고친다")
            return 1
        if not apply:
            if json_out:
                print(_json.dumps(plan, ensure_ascii=False, indent=2, default=str))
                return 0
            ui.head(f"pattern plan · {len(plan.get('turns') or [])} turn(s) 검토")
            for row in plan["observations"]:
                ui.step(
                    f"{row['kind']} · {row['text'][:90]} "
                    f"({row['confidence']}, grounding {row['grounding']}, turns {row['evidence']})"
                )
            for row in plan["dropped"]:
                ui.warn(f"기각 · {str(row['observation'].get('text', ''))[:70]} — {row['reason']}")
            if not plan["observations"]:
                ui.ok(plan.get("reason") or "승격할 관측 없음")
            else:
                ui.ok(f"{len(plan['observations'])}건 승격 대기 — 적용하려면 --apply")
            return 0
        result = pattern.apply_pattern(root, plan, d)
        if json_out:
            print(_json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0 if not result["failed"] else 1
        for row in result["failed"]:
            ui.fail(f"{row['kind']} 실패 — {row.get('error', '')}")
        ui.ok(
            f"패턴 적용: {len(result['applied'])}건 (실패 {len(result['failed'])}건) · "
            f"리포트 {os.path.relpath(result['report'], d)}"
            + (f" · peer card [[{result['peer_card']}]]" if result["peer_card"] else "")
        )
        return 0 if not result["failed"] else 1

    return _guard(_do)


def run_ask(question: str, k: int = 5, json_out: bool = False) -> int:
    """오딘에 대한 자연어 질문 — 개인 관측·에피소드·프로젝트 메모리를 근거로 답한다."""

    def _do() -> int:
        from ..memory import pattern
        from ..memory.manager import ManagerUnavailable

        root, d = os.getcwd(), memory.ensure_home()
        try:
            result = pattern.ask(question, root, d, k=k)
        except Exception as exc:
            # provider 가 없든(ManagerUnavailable) 있는데 실패했든(호출 중 오류) 결과는 같다:
            # 합성은 못 하지만 근거는 이미 손에 있다. 회수까지 같이 죽일 이유가 없다.
            reason = str(exc) if isinstance(exc, ManagerUnavailable) else f"{type(exc).__name__}: {exc}"
            ui.warn(f"답을 합성하지 못했다 — {reason}")
            evidence = pattern.gather_evidence(question, root, d, k=k)
            if json_out:
                print(_json.dumps({"answer": "", "evidence": evidence, "error": reason}, ensure_ascii=False, indent=2))
                return 1
            for rows in evidence.values():
                for row in rows:
                    ui.step(f"[{row['id']}] {row['text'][:160]}")
            ui.step("근거만 보여준다 — 합성은 provider 를 고친 뒤 다시")
            return 1
        if json_out:
            print(_json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["used"] else 1
        if not result["used"]:
            ui.warn("근거 없음 — 개인 위키·에피소드·프로젝트 메모리 어디에도 관련 기록이 없다")
            return 1
        counts = {scope: len(rows) for scope, rows in result["evidence"].items() if rows}
        ui.head("memory ask · " + " · ".join(f"{scope} {n}" for scope, n in counts.items()))
        print(result["answer"])
        return 0

    return _guard(_do)


def run_project_evolve(apply: bool = False, json_out: bool = False) -> int:
    """프로젝트 메모리 진화 패스 — 낡은 record 를 찾아 승인 대기로 올린다 (기본 dry-run)."""

    def _do() -> int:
        from ..project_memory import evolve as evolve_mod

        found = find_config(os.getcwd())
        if not found:
            raise ValueError("project memory is not connected — run `asgard memory connect <endpoint>`")
        root, cfg = found
        if apply and not is_backend_trusted(cfg):
            raise ValueError("project memory backend is not trusted on this machine; run asgard memory connect")
        try:
            plan = evolve_mod.plan_evolve(root)
        except RuntimeError as exc:  # provider 미충족 — 신호만 보여주고 물러난다
            sig = evolve_mod.signals(root)
            ui.warn(f"제안을 만들 provider 가 없다 — {exc}")
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
        from ..memory_bridge import verify_backend_binding
        from ..project_memory import learning
        from ..project_memory_backends import get_backend

        found = find_config(os.getcwd())
        if not found:
            raise ValueError("project memory is not connected — run `asgard memory connect <endpoint>`")
        root, cfg = found
        if not is_backend_trusted(cfg):
            raise ValueError("project memory backend is not trusted on this machine; run asgard memory connect")
        backend = get_backend(cfg)
        try:
            verify_backend_binding(cfg, backend=backend)
            output = learning.apply(backend) if apply_changes else learning.plan(backend)
            # 종합층 로컬 사본을 갱신한다 — 회수는 이 파일만 읽는다 (턴마다 두 번째 왕복 금지).
            # apply 직후에는 아직 refresh 가 도는 중일 수 있다: 그때는 준비된 것만 내려가고,
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
            ui.ok("observation 정책과 mental model을 적용했다")
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


SEMANTIC_NUDGE_FLAG = "semantic-warmup-nudged"
# 색인 드리프트는 되풀이될 수 있는 고장이라 표시를 따로 둔다 — reindex 가 지운다.
COVERAGE_NUDGE_FLAG = "semantic-coverage-nudged"


def _semantic_nudge_line(d: str) -> str:
    """시맨틱이 켜져 있는데 모델이 아직 없을 때만 한 줄. 한 번 말하면 다시 말하지 않는다.

    왜 훅이 아니라 여기인가: 훅은 자식의 stderr 를 삼키므로 "준비 중" 메시지가 사용자에게
    닿지 않는다. 그리고 훅은 시간 상한 안에서 도느라 내려받기를 아예 시작하지 않는다
    (memory_semantic.deadline_bound). 그래서 **사람에게 보이는 통로**로 한 번 알려야
    신규 설치가 시맨틱 없이 조용히 계속 도는 일이 없다."""
    from .. import memory_semantic as sem

    if sem.mode() == "off":
        return ""
    # 두 가지 다른 고장을 한 통로로 알린다. ① 모델이 아직 없다 (내려받기 전) ② 모델은 있는데
    # 파생 벡터가 정본을 안 덮는다. ②가 더 조용한 고장이다 — 임베더가 서니 상태 표면은 전부
    # "동작 중"이라고 말하는데 시맨틱 스트림은 매번 빈 리스트를 낸다 (실측 26-07-29:
    # 페이지 2장·vec 0행). 사용자는 모델 로드 비용만 내고 이득은 0을 받는다.
    message = ""
    if not sem.model_cached():
        message = "시맨틱 검색이 아직 준비되지 않았다 (어휘 회수로 도는 중) — asgard memory semantic warmup"
    else:
        coverage = memory.vec_coverage(d)
        if not coverage["ok"] and coverage["pages"]:
            missing = coverage["pages"] - coverage["fresh"]
            message = (
                f"시맨틱 색인이 정본을 못 덮는다 — {coverage['fresh']}/{coverage['pages']} 페이지 "
                f"(미색인·낡음 {missing}건). 임베더는 서 있으니 비용은 내고 이득은 없다 — asgard memory reindex"
            )
    if not message:
        return ""
    # latch 는 사유별로 나눈다: "준비 안 됨"을 한 번 말했다고 그 뒤에 생긴 색인 드리프트까지
    # 침묵하면, 고쳐야 할 두 번째 고장이 첫 번째 고장의 표시에 먹힌다.
    flag = os.path.join(d, SEMANTIC_NUDGE_FLAG if not sem.model_cached() else COVERAGE_NUDGE_FLAG)
    if os.path.exists(flag):
        return ""
    try:
        with open(flag, "w", encoding="utf-8") as handle:
            handle.write(memory._today())
    except OSError:
        return ""  # 표시를 못 남기면 되풀이 말하느니 침묵한다
    return message


def run_semantic(action: str = "status", json_out: bool = False) -> int:
    """시맨틱 검색 상태·워밍업·켜고 끄기. 첫 실행의 긴 내려받기를 여기서 미리 치른다."""

    def _do() -> int:
        from .. import memory_semantic as sem

        if action == "nudge":  # 훅 전용 — 준비 안 됐을 때만 한 줄, latch 는 여기가 소유한다
            line = _semantic_nudge_line(memory.ensure_home())
            if line:
                print(line)
            return 0
        if action in ("on", "off"):
            from ..settings import load_global, save_global

            configured = dict(load_global().get("memory") or {})
            configured["semantic"] = "local" if action == "on" else "off"
            save_global("memory", configured)
            ui.ok(f"시맨틱 검색 {'켬' if action == 'on' else '끔'}")
            if action == "off":
                ui.step("lexical 2경로로 그대로 돈다 — 저장된 기억은 손대지 않는다")
                return 0
        if action in ("on", "warmup"):
            if not sem.model_cached():
                ui.step("임베딩 모델을 처음 내려받는다 — 약 1GB, 수십 초 걸린다 (한 번만)")
            state = sem.warmup()
            if json_out:
                print(_json.dumps(state, ensure_ascii=False, indent=2))
                return 0 if state["active"] else 1
            if not state["active"]:
                ui.fail("임베더를 불러오지 못했다 — lexical 2경로로 계속 돈다")
                ui.step("uv tool install --force asgard (model2vec 이 빠졌을 수 있다)")
                return 1
            ui.ok(f"준비됨: {state['model']} · {state['dim']}d · {state['seconds']}s")
            return 0
        return _emit_semantic_status(json_out)

    return _guard(_do)


def _emit_semantic_status(json_out: bool) -> int:
    """시맨틱 **상태 표시**. 켜고 끄기·워밍업과 갈라 두는 이유는 부수효과다 — 앞의 셋은 설정을
    바꾸거나 1GB 를 내려받고, 이쪽은 아무것도 안 바꾼다. 한 함수에 있으면 "상태를 봤더니
    켜졌다"가 가능한 모양이 되고, 조회가 안전하지 않은 명령은 사람이 안 쓴다."""
    from .. import memory_semantic as sem

    status = sem.status()
    coverage = memory.vec_coverage(memory.ensure_home())
    if json_out:
        print(
            _json.dumps(
                {**status, "model_cached": sem.model_cached(), "coverage": coverage},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if status["active"] and coverage["ok"] else 1
    ui.head("personal memory · semantic")
    ui.step(f"mode · {status['mode']}")
    if status["active"]:
        ui.ok(f"임베더 · {status['model']} · {status['dim']}d")
    elif status["mode"] == "off":
        ui.step("꺼짐 — `asgard memory semantic on` 으로 검색을 켠다")
        return 0
    else:
        ui.warn("켜져 있지만 임베더를 못 불렀다 — lexical 2경로로 폴백 중")
        return 1
    # 임베더가 선다는 것과 시맨틱이 회수에 기여한다는 것은 다른 말이다. 덮지 못한 페이지는
    # 어휘 경로로만 찾히는데, 그 사실이 여기 안 적히면 사용자는 켰다고 믿은 채로 못 받는다.
    if coverage["ok"]:
        ui.ok(f"색인 · {coverage['fresh']}/{coverage['pages']} 페이지 (100%)")
        return 0
    detail = f"{coverage['fresh']}/{coverage['pages']} 페이지 ({coverage['coverage'] * 100:.0f}%)"
    parts = [
        f"낡음 {coverage['stale']}" if coverage["stale"] else "",
        f"고아 {coverage['orphan']}" if coverage["orphan"] else "",
    ]
    suffix = " · " + " · ".join(p for p in parts if p) if any(parts) else ""
    ui.warn(f"색인 · {detail}{suffix} — 덮이지 않은 페이지는 시맨틱으로 안 찾힌다")
    ui.step("asgard memory reindex")
    return 1


def run_project_ingest(
    paths: list[str],
    strategy: str = "",
    yes: bool = False,
    json_out: bool = False,
    lane: str = "",
) -> int:
    """던진 문서를 파싱·판정해 프로젝트 메모리 승인 대기로 올린다 (기본 미리보기)."""

    def _do() -> int:
        from ..project_memory import ingest

        found = find_config(os.getcwd())
        if not found:
            raise ValueError("project memory is not connected — run `asgard memory connect <endpoint>`")
        root, cfg = found
        if yes and not is_backend_trusted(cfg):
            raise ValueError("project memory backend is not trusted on this machine; run asgard memory connect")
        ready, failed = ingest.plan(list(paths), strategy=strategy or None, lane=lane or None)
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
            ui.head(f"project memory ingest · {len(ready)} document(s)")
            for row in rows:
                mark = " (지정)" if row["overridden"] else ""
                ui.step(
                    f"{row['name']} · {row['kind']} · 전략 {row['strategy']}{mark} · "
                    f"{row['chars']:,}자 · 엔티티 {len(row['entities'])} · 레인 {row['lane']}"
                )
                if row["lane"] == ingest.LANE_LOCAL:
                    ui.warn(
                        f"  {row['name']} 은 그래프 수용 상한을 넘는다 "
                        f"(예측 unit {row['graph_units']} > {ingest.GRAPH_UNIT_CEILING}) — "
                        "저장소 정본 + 로컬 인덱스로 간다 (검색은 되고, 뱅크는 지킨다)"
                    )
            for row in failed:
                ui.warn(f"읽지 못함 · {os.path.basename(row['path'])} — {row['error']}")
            if ready:
                ui.warn("아직 저장하지 않음 — 검토 후 --yes 를 붙인다")
            return 0 if ready or not failed else 1
        if any(d.lane == ingest.LANE_GRAPH for d in ready):
            ingest.ensure_strategies(cfg)
        staged = ingest.stage_documents(root, cfg, ready)
        if json_out:
            print(_json.dumps({"staged": staged, "failed": failed}, ensure_ascii=False, indent=2))
            return 0 if not failed else 1
        for row in staged:
            if row["lane"] == ingest.LANE_LOCAL:
                ui.ok(f"{row['name']} · 저장소 정본 → {row['canonical_path']} (커밋하면 팀과 공유된다)")
            else:
                ui.ok(f"{row['name']} · 승인 대기 — asgard memory project-approve {row['approval_id']}")
        for row in failed:
            ui.fail(f"읽지 못함 · {os.path.basename(row['path'])} — {row['error']}")
        return 0 if not failed else 1

    return _guard(_do)
