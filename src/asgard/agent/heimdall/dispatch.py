"""딜리버리 디스패치 — 전문가 위임 + thor 편대 fan-out.

DeliveryDispatch 는 Heimdall 이 소유하는 협력자다: 세션 생성·모델 선택·토큰 계측은
오케스트레이터(hd)에 위임하고, 여기는 위임 계약(스킬 주입·격리 workspace·scope 검증)만 진다.
"""

from __future__ import annotations

import json
import os
import re

from ... import theme, ui
from ..session import TurnCancelled, ql
from .roles import _DELIVERY, _DELIVERY_READONLY, _LEAD_BASE, _skill_support
from .toolspec import THOR_SQUAD_TOOL


def _checked_run(session, prompt: str):
    """child 세션 실행 + 취소 승격 — 취소된 산출이 편입(capture/apply)되기 전에 끊는다.
    child.run 직호출은 core._run_turn 의 TurnCancelled 승격을 우회한다 (Codex 교차 리뷰 지적)."""
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

    def thor_squad_handler(self, sid: str, worker_result_writes: list[str], cwd: str | None = None):
        """thor-lead → thor N기 병렬 fan-out. 자식에는 coordinate 도구를 주지 않아 깊이 1을 봉인한다.

        split = 브리프 scope(파일 범위) 비중첩을 계약으로 검증하고 병합 — 부품 분담의 암묵 충돌 차단.
        tournament = 같은 난제 N-버전을 격리 시도하고 패치만 회수(본류 미적용) — 승자 선정·적용·검증은
        대장 몫이다 (에인헤랴르: 검증 통과분 중 승자 1개만 본류)."""
        hd = self._hd

        def handler(inp: dict) -> str:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            from ..unit_workspace import UnitWorkspace, WorkspaceError

            mode = str(inp.get("mode") or "split")
            if mode not in ("split", "tournament"):
                raise ValueError("Thor squad mode must be split | tournament")
            tasks = list(inp.get("tasks") or [])
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
                # 파일 비중첩은 에인헤랴르 분할 계약 — 선언 시점에 프리픽스 교차를 차단한다
                flat = [(tid, s) for tid, ss in scopes.items() for s in ss]
                for i, (ta, sa) in enumerate(flat):
                    for tb, sb in flat[i + 1 :]:
                        if ta != tb and (sa == sb or sa.startswith(sb + "/") or sb.startswith(sa + "/")):
                            raise ValueError(f"Split squad scope overlap: {ta}:{sa} ↔ {tb}:{sb}")
            squad_root = cwd or hd.root

            def in_scope(path: str, allowed: list[str]) -> bool:
                return any(path == s or path.startswith(s + "/") for s in allowed)

            def run_one(index: int, spec: dict):
                task, why = str(spec["task"]), str(spec["why"])
                allowed = scopes[str(spec["id"])]
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
                catalog, skill_tools, skill_handlers = _skill_support(
                    "thor", hd.root, exclude=("asgard-thor-einherjar",)
                )
                system += catalog
                with UnitWorkspace(squad_root, f"thor-{spec['id']}") as workspace:
                    child = hd._session(
                        system,
                        extra_tools=skill_tools,
                        handlers=skill_handlers,
                        model=hd._delivery_model("thor"),
                        role="thor",
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
                    outside = [path for path in patch.paths if not in_scope(path, allowed)]
                    if outside:
                        raise WorkspaceError("scope violation: " + ", ".join(sorted(outside)))
                return index, spec, result, patch

            completed = []
            failures: list[dict] = []
            with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
                futures = {pool.submit(run_one, i, spec): spec for i, spec in enumerate(tasks)}
                for future in as_completed(futures):
                    spec = futures[future]
                    try:
                        completed.append(future.result())
                    except TurnCancelled:
                        raise  # 취소는 편대 실패가 아니다 — 공유 이벤트로 나머지도 곧 멈춘다
                    except Exception as exc:
                        failures.append({"id": spec["id"], "error": f"{type(exc).__name__}: {exc}"})

            completed.sort(key=lambda item: item[0])
            payload = []
            for _, spec, result, patch in completed:
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
                    continue
                try:
                    UnitWorkspace(squad_root, f"thor-{spec['id']}").apply(patch)
                except Exception as exc:
                    failures.append({"id": spec["id"], "error": f"{type(exc).__name__}: {exc}"})
                    continue
                writes = list(patch.paths)
                worker_result_writes.extend(w for w in writes if w not in worker_result_writes)
                payload.append({"id": spec["id"], "writes": writes, "summary": result.text[-1200:]})
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
                # "코어 계약 전부 상속"을 선언이 아니라 최종 system bytes 로 강제한다.
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
            # claude_cli: 부모 worker 가 spawn permit 을 쥔 채 이 핸들러를 기다린다 —
            # 자식이 permit 을 재요구하면 재진입 데드락 (CUS-246). 재획득 없이 실행.
            child._nested_dispatch = True
            r = _checked_run(child, task)
            hd._track_cache(r)
            worker_result_writes.extend(r.writes)
            return f"[{agent}] {r.text[-2000:]}"

        return handler
