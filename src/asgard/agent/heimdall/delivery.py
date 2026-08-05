"""딜리버리 위임 — 전문가 child 세션 + thor 편대 fan-out.

DeliveryDispatch는 Heimdall이 소유하는 협력자다: 세션 생성·모델 선택·토큰 계측은
오케스트레이터(hd)에 위임하고, 여기는 위임 계약(스킬 주입·격리 workspace·scope 검증)만 진다.

`orchestration.dispatch`와 다른 것이다. 저기는 Task 한 번의 시도(수명 권한·회로 차단)를 다루고,
여기는 전문가에게 일을 넘기는 계약을 다룬다. 모델이 부르는 툴 이름이 `dispatch`라서 핸들러·툴
스키마는 그 이름을 그대로 쓰지만, 모듈 이름은 클래스 이름(DeliveryDispatch)을 따라간다.
"""

from __future__ import annotations

import json
import os
import re

from ... import theme, ui
from ..quest_bridge import ql
from ..session import TurnCancelled
from .roles import _DELIVERY, _DELIVERY_READONLY, _LEAD_BASE, _skill_support
from .todo import TodoBoard, files_note
from .toolspec import THOR_SQUAD_TOOL


def _squad_scopes(mode: str, tasks: list[dict]) -> dict[str, list[str]]:
    """편대 브리프를 받아들일지 여기서 정하고, 단위별 파일 범위를 정규화해 돌려준다.

    자식을 띄우기 **전에** 전부 거른다: 한 기라도 띄운 뒤에 브리프가 틀렸다고 알면 이미 남의
    자리에 손댄 워크스페이스를 되돌려야 한다. 거르는 것은 넷이다 — 모드, 인원(2~4), id(빈 값·
    중복·파일명으로 못 쓰는 글자), 그리고 범위(저장소 밖·`.git`·`.asgard`).

    split은 여기에 하나를 더 건다: 단위끼리 파일이 안 겹쳐야 한다. 겹친 채로 넷을 병렬로
    띄우면 마지막에 적은 놈이 이기고, 그 손실은 화면 어디에도 안 남는다 (에인헤랴르 분할 계약).
    """
    if mode not in ("split", "tournament"):
        raise ValueError("Thor squad mode must be split | tournament")
    if not 2 <= len(tasks) <= 4:
        raise ValueError("A Thor squad batch must have 2-4 members")
    ids = [str(t.get("id") or "") for t in tasks]
    if any(not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Squad task ids must be non-empty and mutually distinct")
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", task_id) for task_id in ids):
        raise ValueError("Squad task ids must use only safe filename characters")
    scopes: dict[str, list[str]] = {}
    for spec in tasks:
        norm: list[str] = []
        for raw in list(spec.get("scope") or []):
            s = os.path.normpath(str(raw)).replace(os.sep, "/").strip("/")
            unsafe = (
                not s
                or s == "."
                or s.startswith("..")
                or s in (".git", ".asgard")
                or s.startswith((".git/", ".asgard/"))
            )
            if unsafe:
                raise ValueError(f"Unsafe squad scope: {raw!r}")
            norm.append(s)
        if not norm:
            raise ValueError(f"Squad unit {spec.get('id')} has no scope")
        scopes[str(spec["id"])] = norm
    if mode == "split":
        # 프리픽스 교차까지 본다 — `src`와 `src/api`는 다른 문자열이지만 같은 파일을 덮는다
        flat = [(tid, s) for tid, ss in scopes.items() for s in ss]
        for i, (ta, sa) in enumerate(flat):
            for tb, sb in flat[i + 1 :]:
                if ta != tb and (sa == sb or sa.startswith(sb + "/") or sb.startswith(sa + "/")):
                    raise ValueError(f"Split squad scope overlap: {ta}:{sa} ↔ {tb}:{sb}")
    return scopes


def _in_scope(path: str, allowed: list[str]) -> bool:
    """편대 단위가 만진 파일이 그 단위에 허용된 범위 안인지."""
    return any(path == s or path.startswith(s + "/") for s in allowed)


def _checked_run(session, prompt: str):
    """child 세션 실행 + 취소 승격 — 취소된 산출이 편입(capture/apply)되기 전에 끊는다.
    child.run 직호출은 core._run_turn의 TurnCancelled 승격을 우회한다 (Codex 교차 리뷰 지적)."""
    result = session.run(prompt)
    if getattr(result, "stop_reason", "") == "cancelled":
        raise TurnCancelled()
    return result


class DeliveryDispatch:
    """딜리버리 위임 협력자 — dispatch 툴 핸들러 팩토리 묶음.

    hd(Heimdall)의 세션·모델·계측 표면만 사용한다: _session/_delivery_model/_learned_note/
    _track_cache/on_text/root/delivery_identity."""

    def __init__(self, hd):
        self._hd = hd

    def _squad_unit(self, sid: str, spec: dict, mode: str, allowed: list[str], squad_root: str):
        """편대 한 기 — 격리 workspace에서 thor child를 돌리고 (결과, 패치)를 돌려준다.

        범위 검증도 여기서 끝낸다. 허용 범위 밖을 건드린 패치는 회수 전에 끊어야 한다 — 한 번
        회수되면 그 다음은 병합이고, 병합 뒤에는 누가 남의 자리에 썼는지 diff에 안 남는다."""
        from ..unit_workspace import UnitWorkspace, WorkspaceError

        hd = self._hd
        task, why = str(spec["task"]), str(spec["why"])
        ql(
            hd.root,
            "append",
            session=sid,
            stdin=json.dumps(
                {
                    "role": "worker",
                    "event": "delegate",
                    "commands": [{"cmd": f"dispatch:thor:{spec['id']} — {mode}: {why[:100]}", "exit_code": 0}],
                }
            ),
        )
        system = _DELIVERY["thor"] + "\n\n" + hd.delivery_identity + hd.map_note
        # 서브에 편대 프로토콜 무주입 — 깊이 1 봉인은 도구만이 아니라 지식 표면에서도 유지한다
        catalog, skill_tools, skill_handlers = _skill_support("thor", hd.root, exclude=("asgard-thor-einherjar",))
        system += catalog
        with UnitWorkspace(squad_root, f"thor-{spec['id']}") as workspace:
            child = hd._session(
                system,
                extra_tools=skill_tools,
                handlers=skill_handlers,
                model=hd._delivery_model("thor"),
                role="thor",
                # 관측 이름에만 단위를 적는다. 편대는 같은 `thor` 넷이 동시에 도는데
                # 이름이 같으면 독의 상태 행에 `thor ⋮ thor ⋮ thor`가 서고, 그건 넷이
                # 돈다는 것 말고는 아무 말도 안 한다. `role`은 안 건드린다 — 그건 provider
                # 배치·도구 가시성·프롬프트 계층이 함께 읽는 키라서, 여기서 바꾸면 라벨
                # 하나 고치려다 편대의 모델과 권한이 같이 움직인다.
                label=f"thor:{spec['id']}",
                cwd=workspace.path,
                quiet=True,
            )
            child._nested_dispatch = True
            result = _checked_run(
                child,
                f"Squad unit {spec['id']} ({mode})\nQuest: {task}\nRationale: {why}\n"
                f"Allowed file scope: {', '.join(allowed)}\nDo not modify anything outside "
                "this scope. Run unit-scoped verification only (the global gate belongs to "
                "the lead). Return = changed files + decision summary + verification "
                "evidence + blockers.",
            )
            hd._track_cache(result)
            patch = workspace.capture(extra_paths=tuple(result.writes))
            outside = [path for path in patch.paths if not _in_scope(path, allowed)]
            if outside:
                raise WorkspaceError("scope violation: " + ", ".join(sorted(outside)))
        return result, patch

    def _settle_squad(
        self,
        mode: str,
        completed: list[tuple],
        squad_root: str,
        worker_result_writes: list[str],
        board: TodoBoard,
        failures: list[dict],
    ) -> list[dict]:
        """자식이 끝난 뒤 산출물을 정착시킨다 — split은 본류 적용까지, tournament는 패치 회수까지.

        한 과업이 done이 되는 시점은 자식이 끝난 때가 아니라 여기를 지난 때다. 적용에 실패한
        단위는 done이 아니라 failed로 적고 나머지는 계속 간다 — 하나 때문에 전부 버리지 않는다."""
        from ..unit_workspace import UnitWorkspace

        payload: list[dict] = []
        for spec, result, patch in completed:
            if mode == "tournament":
                rel = f"deliverables/thor-tournament/{spec['id']}.patch"
                dest = os.path.join(squad_root, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as fh:
                    fh.write(patch.data)
                if rel not in worker_result_writes:
                    worker_result_writes.append(rel)
                payload.append(
                    {"id": spec["id"], "patch": rel, "paths": list(patch.paths), "summary": result.text[-1200:]}
                )
                board.mark(spec["id"], "done", rel)
                continue
            try:
                UnitWorkspace(squad_root, f"thor-{spec['id']}").apply(patch)
            except Exception as exc:
                board.mark(spec["id"], "failed", type(exc).__name__)
                failures.append({"id": spec["id"], "error": f"{type(exc).__name__}: {exc}"})
                continue
            writes = list(patch.paths)
            worker_result_writes.extend(w for w in writes if w not in worker_result_writes)
            payload.append({"id": spec["id"], "writes": writes, "summary": result.text[-1200:]})
            board.mark(spec["id"], "done", files_note(len(writes)))
        return payload

    def thor_squad_handler(self, sid: str, worker_result_writes: list[str], cwd: str | None = None):
        """thor-lead → thor N기 병렬 fan-out. 자식에는 coordinate 도구를 주지 않아 깊이 1을 봉인한다.

        split = 브리프 scope(파일 범위) 비중첩을 계약으로 검증하고 병합 — 부품 분담의 암묵 충돌 차단.
        tournament = 같은 난제 N-버전을 격리 시도하고 패치만 회수(본류 미적용) — 승자 선정·적용·검증은
        대장 몫이다 (에인헤랴르: 검증 통과분 중 승자 1개만 본류).

        여기는 fan-out/fan-in 만 진다: 한 기의 실행은 `_squad_unit`, 산출물 정착은 `_settle_squad`."""
        hd = self._hd

        def handler(inp: dict) -> str:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            mode = str(inp.get("mode") or "split")
            tasks = list(inp.get("tasks") or [])
            scopes = _squad_scopes(mode, tasks)
            squad_root = cwd or hd.root

            def run_one(index: int, spec: dict):
                result, patch = self._squad_unit(sid, spec, mode, scopes[str(spec["id"])], squad_root)
                return index, spec, result, patch

            # 편대 브리프도 배정 단위와 같은 성격의 목록이다 — 대장이 뭘 몇 개로 나눠 던졌는지를
            # 오딘 쪽 표면에 세운다. 자식 세션은 quiet라 여기 말고는 진행이 보이지 않는다.
            board = TodoBoard(hd.on_text, head_key="todo_squad_head")
            board.plan((spec["id"], str(spec.get("task") or "")) for spec in tasks)
            completed = []
            failures: list[dict] = []
            payload: list[dict] = []
            try:
                board.start(spec["id"] for spec in tasks)
                with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
                    futures = {pool.submit(run_one, i, spec): spec for i, spec in enumerate(tasks)}
                    for future in as_completed(futures):
                        spec = futures[future]
                        try:
                            completed.append(future.result())
                        except TurnCancelled:
                            raise  # 취소는 편대 실패가 아니다 — 공유 이벤트로 나머지도 곧 멈춘다
                        except Exception as exc:
                            board.mark(spec["id"], "failed", type(exc).__name__)
                            failures.append({"id": spec["id"], "error": f"{type(exc).__name__}: {exc}"})

                completed.sort(key=lambda item: item[0])  # 완료 순서가 아니라 브리프 순서로 정착시킨다
                payload = self._settle_squad(
                    mode, [item[1:] for item in completed], squad_root, worker_result_writes, board, failures
                )
            finally:
                board.close()
            out: dict = {"mode": mode, "results": payload, "failures": failures}
            if mode == "tournament":
                out["note"] = (
                    "Patches are NOT applied to the mainline — pick one winner among the "
                    "verification-passing entries, apply it with git apply, and run the combined "
                    "verification"
                )
            return json.dumps(out, ensure_ascii=False)

        return handler

    def dispatch_handler(self, sid: str, worker_result_writes: list[str], cwd: str | None = None):
        hd = self._hd

        def handler(inp: dict) -> str:
            agent, task, why = inp["agent"], inp["task"], inp.get("why", "")
            hd.on_text(
                f"\n  {ui.paint(theme.ansi(theme.PRIMARY), '⤷')} {ui.bold(agent)} {ui.dim('위임 · ' + why[:80])}\n"
            )
            ql(
                hd.root,
                "append",
                session=sid,
                stdin=json.dumps(
                    {
                        "role": "worker",
                        "event": "delegate",
                        "commands": [{"cmd": f"dispatch:{agent} — {why[:120]}", "exit_code": 0}],
                    }
                ),
            )
            # dispatch 툴 미제공 = 재위임 불가. 모델은 딜리버리 티어 (freyja/thor/eitri=standard, loki=fast)
            system = _DELIVERY[agent]
            base = _LEAD_BASE.get(agent)
            if base:
                # "코어 계약 전부 상속"을 선언이 아니라 최종 system bytes로 강제한다.
                system += f"\n\n# Inherited {base} core contract\n\n" + _DELIVERY[base]
            system += "\n\n" + hd.delivery_identity
            if agent != "loki":
                system += getattr(hd, "map_note", "")
            skill_task = "\n".join(part for part in (task, why) if part)
            catalog, skill_tools, skill_handlers = _skill_support(
                agent,
                hd.root,
                task=skill_task if agent == "freyja" else None,
                include_learned=agent not in _DELIVERY_READONLY,
            )
            system += catalog
            extra_tools = list(skill_tools)
            handlers = dict(skill_handlers)
            if agent == "thor-lead":
                extra_tools.append(THOR_SQUAD_TOOL)
                handlers["dispatch_thor_squad"] = self.thor_squad_handler(sid, worker_result_writes, cwd)
            child = hd._session(
                system,
                extra_tools=extra_tools,
                handlers=handlers,
                model=hd._delivery_model(agent),
                readonly=agent in _DELIVERY_READONLY,  # frontmatter tools 선언 파생 — 반례 탐색은 도구로 강제
                role=agent,
                cwd=cwd,
            )
            # claude_cli: 부모 worker가 spawn permit을 쥔 채 이 핸들러를 기다린다 —
            # 자식이 permit을 재요구하면 재진입 데드락 (CUS-246). 재획득 없이 실행.
            child._nested_dispatch = True
            r = _checked_run(child, task)
            hd._track_cache(r)
            worker_result_writes.extend(r.writes)
            return f"[{agent}] {r.text[-2000:]}"

        return handler
