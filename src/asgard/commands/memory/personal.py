"""memory 커맨드 — 개인 위키 운영. 담기·찾기·보이기·지우기·내보내기."""

import contextlib
import json as _json
import os
import subprocess
import sys
import webbrowser
from urllib.parse import quote

from ... import errors, memory, ui
from ._core import _claim_plan, _emit, _fail, _finish_plan, _guard, _save_plan
from .backends import COVERAGE_NUDGE_FLAG


def run_add(text: str, title: str | None, kind: str, links: str, json_out: bool = False) -> int:
    errors.set_json_surface(json_out)

    def _do() -> int:
        slug, path = memory.add(text, title=title, kind=kind, links=links)
        if json_out:
            _emit({"slug": slug, "path": path, "kind": kind, "added": True})
        else:
            ui.ok(f"added {slug} → {path}")
        return 0

    return _guard(_do)


def run_ingest(
    text: str, kind: str, yes: bool, plan_id: str | None = None, json_out: bool = False, title: str | None = None
) -> int:
    errors.set_json_surface(json_out)

    def _do() -> int:
        threat = memory.scan_threats(text)
        if threat:
            return _fail(f"injection scan: {threat}", code="invalid_input", detail={"threat": threat})
        if plan_id and not yes:
            raise ValueError("--plan-id requires --yes")
        claim_token = None
        if plan_id:
            plan, claim_token = _claim_plan(plan_id, text, kind)
        else:
            plan = memory.plan_ingest(text)
        absorb = [
            (entry[0] if isinstance(entry, list | tuple) and entry else entry) for entry in plan.get("absorb") or []
        ]
        if json_out:
            # 계획을 먼저 낸다 — 사람이 화면에서 보고 판단하는 것과 같은 사실이다.
            plan_view = {"action": plan["action"], "absorb": absorb}
            if plan["action"] == "merge":
                plan_view |= {"slug": plan["slug"], "title": plan["title"], "slot": plan.get("slot", "")}
        elif plan["action"] == "merge":
            why = f"slot={plan['slot']}" if plan.get("slot") else f"sim={plan['sim']}"
            ui.step(f"plan: merge into '{plan['title']}' ({plan['slug']}, {why})")
        else:
            ui.step("plan: create new page")
        # 흡수는 페이지 삭제다 — 승인 전에 반드시 눈에 보여야 한다. 갈래 **밖**에 두는 것이
        # 요점이다: 오늘은 흡수가 merge 계획에만 실리지만(`pages._plan_identity_slot`), 그
        # 사실에 기대면 계획이 넓어지는 날 삭제 고지만 조용히 빠진다. 툴 레인
        # (`propose.outcome_text`)도 action을 안 보고 목록만 본다 — 판정을 맞춰 둔다.
        if not json_out:
            for slug in absorb:
                ui.warn(f"plan: absorb (archive) contradicting page — {slug}")
        # 자동저장은 이 표면에도 같은 답을 해야 한다 — 툴에서는 바로 저장되는데 CLI 에서만
        # 되묻는다면, 사용자가 켠 설정이 어디서 듣는지를 매번 기억해야 한다.
        auto = memory.autosave_enabled()
        if auto and not yes and not json_out:
            ui.step("autosave on — 이제 승인 없이 저장해요 (끄려면: asgard memory autosave off --tier personal)")
        if not yes and not auto:
            # `--json`은 물을 자리가 아니다 — 프롬프트를 띄우면 산출물 스트림에 질문이 섞이고,
            # 부른 쪽은 답할 수 없다. 대기 승인으로 남기고 그 id를 값으로 돌려준다: 다음 호출의
            # 재료라 오류 봉투로 안 갈아치우고, 종료 코드만 정본을 따른다 (`--yes`로 풀리므로 2).
            if json_out or not sys.stdin.isatty():
                approval_id = _save_plan(text, kind, plan)
                if json_out:
                    _emit({"saved": False, "approval_id": approval_id, "plan": plan_view, "reason": "needs --yes"})
                    return errors.Conflict.exit_code
                ui.step(f"approval-id: {approval_id}")
                ui.warn("non-interactive without --yes — not saved (ask-before-save)")
                ui.step(f"이어서 저장하려면: asgard memory ingest --plan-id {approval_id} --yes")
                return errors.Conflict.exit_code
            if input("save? [y/N] ").strip().lower() not in ("y", "yes"):
                ui.step("skipped")
                return 0
        try:
            action, slug = memory.ingest(text, kind=kind, plan=plan, title=title)  # 승인한 그 계획 그대로
        except Exception:
            if plan_id and claim_token:
                _finish_plan(plan_id, claim_token, success=False)
            raise
        if plan_id and claim_token:
            _finish_plan(plan_id, claim_token, success=True)
        if json_out:
            _emit({"saved": True, "action": action, "slug": slug, "kind": kind, "plan": plan_view})
        else:
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
            # 제목과 발췌가 같은 문장에서 왔으면 하나로 잇는다 — 주입면과 같은 규율이다
            # (`recall.rows._fuse`). 화면에서만 같은 문장을 두 번 읽을 이유가 없다.
            fused = memory.recall._fuse(str(h["title"]), str(h["snippet"]))
            if fused:
                print(f"{h['slug']}  `{h['kind']}`  {fused}")
            else:
                print(f"{h['slug']}  `{h['kind']}`  {h['title']}\n    {h['snippet']}")
        return 0

    return _guard(_do)


def run_episodes(text: str, k: int, quest: str, json_out: bool) -> int:
    """세션 원문(에피소드) 검색 표면 — 비권위 참고. 빈 질의는 인덱스 현황만 보인다."""

    def _do() -> int:
        from ...agent import episodes

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


def run_approve(proposal_id: str, json_out: bool = False) -> int:
    """제안 하나를 승인해 정본에 쓴다.

    `propose.commit`의 거절을 여기서 따로 잡지 않는다. 잡아서 `ui.fail`로 내던 동안 `--json`
    실행의 실패만 사람 문장으로 샜다 — 부른 쪽은 파싱할 것을 못 찾는다. `_guard`가 같은 사유를
    이 실행의 얼굴로 낸다."""
    errors.set_json_surface(json_out)

    def _do() -> int:
        from ...memory import propose

        action, slug = propose.commit(proposal_id)
        if json_out:
            print(_json.dumps({"action": action, "slug": slug}, ensure_ascii=False))
            return 0
        ui.ok(f"{action} · {slug}")
        return 0

    return _guard(_do)


def run_discard(proposal_id: str, json_out: bool = False) -> int:
    """제안 하나를 버린다."""
    errors.set_json_surface(json_out)

    def _do() -> int:
        from ...memory import propose

        if propose.discard(proposal_id):
            if json_out:
                _emit({"id": proposal_id, "discarded": True})
            else:
                ui.ok(f"버림 · {proposal_id}")
            return 0
        return _fail(
            f"없거나 이미 처리된 제안 id · {proposal_id}",
            code="not_found",
            remedy="asgard memory proposals로 대기 중인 제안을 보세요",
            detail={"id": proposal_id},
        )

    return _guard(_do)


def run_reindex(json_out: bool = False) -> int:
    errors.set_json_surface(json_out)

    def _do() -> int:
        d = memory.ensure_home()
        n = memory.reindex(d)
        coverage = memory.vec_coverage(d)
        # 고쳤으면 표시를 지운다 — 안 지우면 넛지가 영영 침묵해 다음 드리프트를 못 알린다.
        with contextlib.suppress(OSError):
            os.remove(os.path.join(d, COVERAGE_NUDGE_FLAG))
        from ... import memory_semantic as sem

        mode = sem.mode()
        if json_out:
            _emit({"directory": d, "pages": n, "semantic": mode, "coverage": coverage})
            return 0
        ui.ok(f"reindexed {n} pages → index.md + state.db")
        if mode == "off":
            ui.step("시맨틱이 꺼져 있어서 벡터는 안 만들었어요 (lexical 2경로)")
        elif coverage["ok"]:
            ui.ok(f"시맨틱 색인 · {coverage['fresh']}/{coverage['pages']} 페이지")
        else:
            ui.warn(f"시맨틱 색인 · {coverage['fresh']}/{coverage['pages']} 페이지 — 임베더를 못 불렀어요")
        return 0

    return _guard(_do)


def run_export_okf(destination: str, json_out: bool = False) -> int:
    errors.set_json_surface(json_out)

    def _do() -> int:
        count = memory.export_okf(destination)
        path = os.path.abspath(os.path.expanduser(destination))
        if json_out:
            _emit({"bundle": path, "pages": count, "format": "okf-0.1"})
        else:
            ui.ok(f"exported {count} personal memory pages → {path}")
        return 0

    return _guard(_do)


def run_show(slug: str, unsafe: bool = False, json_out: bool = False) -> int:
    errors.set_json_surface(json_out)

    def _do() -> int:
        if not memory.valid_slug(slug):
            return _fail(f"invalid slug: {slug!r}", code="invalid_input", detail={"slug": slug})
        pg = memory._read(memory.memory_dir(), slug)
        if not pg:
            return _fail(
                f"no page: {slug}",
                code="not_found",
                remedy="asgard memory query <말>로 찾아보세요",
                detail={"slug": slug},
            )
        meta, body = pg
        threat = memory.poisoned(meta, body)
        if threat and not unsafe:
            # 오염 페이지 출력도 컨텍스트 유입 경로다 (2차 리뷰 ②) — 수리용 열람은 --unsafe 로만
            return _fail(
                f"threat detected: {threat} — inspect with --unsafe, then fix the file or `memory remove {slug}`",
                code="conflict",
                remedy=f"asgard memory show {slug} --unsafe",
                detail={"slug": slug, "threat": threat},
            )
        if json_out:
            _emit({"slug": slug, "meta": dict(meta), "body": body, "threat": threat or ""})
            return 0
        if threat:
            ui.warn(f"⚠ poisoned page (quarantined from injection/query): {threat}")
        for k, v in meta.items():
            print(f"{k}: {v}")
        print(f"\n{body}")
        return 0

    return _guard(_do)


def run_remove(slug: str, json_out: bool = False) -> int:
    errors.set_json_surface(json_out)

    def _do() -> int:
        if memory.remove(slug):
            if json_out:
                _emit({"slug": slug, "removed": True})
            else:
                ui.ok(f"removed {slug}")
            return 0
        return _fail(
            f"no page: {slug}", code="not_found", remedy="asgard memory query <말>로 찾아보세요", detail={"slug": slug}
        )

    return _guard(_do)


def run_merge(src: str, dst: str, json_out: bool = False) -> int:
    errors.set_json_surface(json_out)

    def _do() -> int:
        memory.merge(src, dst)
        if json_out:
            _emit({"source": src, "target": dst, "merged": True})
        else:
            ui.ok(f"merged {src} → {dst}")
        return 0

    return _guard(_do)


def run_snapshot(provider: str | None = None, json_out: bool = False) -> int:
    """주입 스냅샷 출력 — CC memory-activate 훅이 subprocess로 소비 (단일 출처: 훅 재구현 금지).
    킬스위치 off·페이지 0 = 빈 출력 + exit 0 (훅이 무주입으로 통과).

    `--json`이 더하는 것은 **왜 비었는가**다: 훅은 빈 출력만 보면 되지만, 그 밖의 소비자는
    꺼져서 빈 것과 맞는 페이지가 없어서 빈 것을 갈라야 한다."""
    errors.set_json_surface(json_out)
    allowed = memory.inject_allowed(provider)
    text = memory.snapshot_note() if allowed else ""
    if json_out:
        _emit({"allowed": allowed, "text": text})
    elif allowed:
        print(text, end="")
    return 0


def run_recall(text: str, provider: str | None = None, json_out: bool = False) -> int:
    """개인+프로젝트 범위 회수 — UserPromptSubmit 훅 전용, provider gate 적용.

    `--json`은 `run_snapshot`과 같은 이유로 있다 — 빈 회수의 사유를 값으로 낸다."""
    errors.set_json_surface(json_out)
    allowed = memory.inject_allowed(provider)
    note = ""
    if allowed:
        from ...memory_context import recall_note

        # include_skills: CC 훅 표면 한정 — learned 스킬 포인터를 회수에 동봉 (자가발전×메모리 결합).
        # include_episodes: 같은 표면 한정 — 네이티브만 갖고 있던 과거 세션 회상을 외부
        # 클라이언트에도 준다 (쓰기는 run_sync_turn, 읽기는 여기 — 두 반쪽이 짝을 이룬다).
        note = recall_note(text, start=os.getcwd(), include_skills=True, include_episodes=True)
    if json_out:
        _emit({"allowed": allowed, "query": text, "text": note})
    elif allowed:
        print(note, end="")
    return 0


def run_path(directory: str | None = None, reset: bool = False, json_out: bool = False) -> int:
    errors.set_json_surface(json_out)

    def _do() -> int:
        if directory and reset:
            raise ValueError("use either --set or --reset")
        overridden = False
        if directory or reset:
            from ...settings import load_global, save_global

            configured = dict(load_global().get("memory") or {})
            if reset:
                configured.pop("directory", None)
            else:
                path = os.path.abspath(os.path.expanduser(directory or ""))
                memory.ensure_home(path)
                configured["directory"] = path
            save_global("memory", configured)
            overridden = bool(os.environ.get(memory.MEMORY_ENV))
            if overridden and not json_out:
                ui.warn(f"{memory.MEMORY_ENV} overrides the saved directory")
        if json_out:
            # 저장한 값과 실제로 쓰이는 값이 갈릴 수 있다 — 환경변수가 이기는 자리를 같이 낸다.
            _emit({"directory": memory.memory_dir(), "env_override": overridden, "env": memory.MEMORY_ENV})
        else:
            print(memory.memory_dir())
        return 0

    return _guard(_do)


def run_obsidian(refresh_only: bool = False, json_out: bool = False) -> int:
    """개인 위키를 Obsidian vault로 준비하고 연다 — 설정 스캐폴드 + 목차 재생성 + URI 열기."""

    def _do() -> int:
        from ...memory import vault as vault_mod

        state = vault_mod.refresh()
        vault = state["directory"]
        if json_out:
            print(_json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        if state["scaffolded"]:
            # 새로 만든 것과 빠진 키를 채운 것이 같은 목록에 온다 — "생성"은 후자를 거짓으로 말한다
            ui.step(f"vault 설정 반영 · {', '.join(state['scaffolded'])}")
        ui.step(f"목차 갱신 · {len(state['maps'])}개 지도 · {state['pages']} page(s)")
        if refresh_only:
            ui.ok(f"vault 준비됨 → {vault}")
            return 0
        # Obsidian URI는 이미 등록된 vault만 연다. 설정만 심어서는 등록되지 않으므로,
        # 한 번은 사람이 "Open folder as vault"를 해야 한다 — 그 한 번을 정확히 안내한다.
        # 여는 문서는 루트 index.md 가 아니라 maps/index.md 다. 루트 쪽은 kind 별 칸 예산에
        # 묶인 주입 카탈로그라 칸이 차면 뒤가 잘린다 — 사람이 처음 보는 화면이 그것이면
        # 없는 페이지를 없다고 읽게 된다. 전체를 지고 있는 쪽은 maps/ 다 (vault 모듈 ②).
        home = os.path.join(vault, vault_mod.MAPS_DIR, "index.md")
        uri = f"obsidian://open?path={quote(home, safe='')}"
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", uri], check=True)
            elif os.name == "nt":  # pragma: no cover - Windows 전용
                os.startfile(uri)  # type: ignore[attr-defined]
            elif not webbrowser.open(uri):  # pragma: no cover - Linux desktop 환경 의존
                raise OSError("could not open the Obsidian URI")
        except Exception as exc:
            ui.warn(f"Obsidian URI를 열지 못했어요 ({type(exc).__name__}) — 폴더를 직접 vault로 열어 주세요: {vault}")
            return 1
        ui.ok(f"opened personal memory in Obsidian → {vault}")
        ui.step(f"열리지 않으면 Obsidian에서 이 폴더를 vault로 한 번 열어 주세요: {vault}")
        return 0

    return _guard(_do)
