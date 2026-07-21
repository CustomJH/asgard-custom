"""딜리버리 디스패치 — 전문가 위임 + freyja/thor 편대 fan-out (일반 depth 1, lead 만 봉인된 depth 2).

DeliveryDispatch 는 Heimdall 이 소유하는 협력자다: 세션 생성·모델 선택·토큰 계측은
오케스트레이터(hd)에 위임하고, 여기는 위임 계약(스킬 주입·격리 workspace·scope 검증·
two-stage visual gate)만 진다. 순수 게이트 판정은 모듈 함수 — 테스트가 직접 찌른다.
"""

from __future__ import annotations

import json
import os
import re

from ... import theme, ui
from ..session import TurnCancelled, ql
from .roles import _DELIVERY, _DELIVERY_READONLY, _LEAD_BASE, _skill_support
from .toolspec import FREYJA_SQUAD_TOOL, FREYJA_VERDICT_TOOL, THOR_SQUAD_TOOL, VISUAL_VERDICT_SUBMIT_TOOL


def _checked_run(session, prompt: str):
    """child 세션 실행 + 취소 승격 — 취소된 산출이 편입(capture/apply)되기 전에 끊는다.
    child.run 직호출은 core._run_turn 의 TurnCancelled 승격을 우회한다 (Codex 교차 리뷰 지적)."""
    result = session.run(prompt)
    if getattr(result, "stop_reason", "") == "cancelled":
        raise TurnCancelled()
    return result


def _freyja_final_writes(paths) -> list[str]:
    """deliverables 아래 `final` 디렉터리의 쓰기만 two-stage gate 대상으로 고른다."""
    found: list[str] = []
    for raw in paths:
        path = str(raw).replace(os.sep, "/")
        parts = path.split("/")
        if parts and parts[0] == "deliverables" and "final" in parts[1:-1]:
            found.append(path)
    return sorted(found)


def _derived_from_pass(path: str, passed: list[str]) -> bool:
    """final/<exact-pass-id>/... 구조만 인정한다. 파일명 부분 문자열은 provenance 가 아니다."""
    parts = str(path).replace(os.sep, "/").split("/")
    if len(parts) < 4 or parts[:2] != ["deliverables", "final"]:
        return False
    return parts[2] in set(passed)


def _safe_candidates(root: str, raw) -> tuple[str, str, tuple[str, ...]]:
    """deliverables/ 아래 실제 후보 디렉터리를 확정하고 symlink 탈출을 막는다."""
    rel = os.path.normpath(str(raw or "")).replace(os.sep, "/").strip("/")
    if not rel or rel == "." or rel.startswith("..") or rel.split("/")[0] != "deliverables":
        raise ValueError("candidates_dir 는 프로젝트의 deliverables/ 하위 상대 경로여야 한다")
    real_root = os.path.realpath(root)
    real = os.path.realpath(os.path.join(root, rel))
    try:
        inside = os.path.commonpath((real_root, real)) == real_root
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("candidates_dir 가 심볼릭 링크로 프로젝트 경계를 벗어난다")
    if not os.path.isdir(real):
        raise ValueError(f"candidates_dir 가 없다: {rel}")
    candidates: list[str] = []
    with os.scandir(real) as entries:
        for entry in entries:
            if entry.is_symlink():
                raise ValueError(f"후보 디렉터리는 심볼릭 링크일 수 없다: {entry.name}")
            if not entry.is_dir(follow_symlinks=False):
                continue
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", entry.name):
                raise ValueError(f"안전하지 않은 후보 id: {entry.name}")
            candidates.append(entry.name)
    if not candidates:
        raise ValueError("candidates_dir 에 판정할 후보 디렉터리가 없다")
    return rel, real, tuple(sorted(candidates))


def _freyja_gate_rejection(final_paths: list[str], verdict_state: dict) -> str | None:
    if not final_paths:
        return None
    if not verdict_state.get("written"):
        return "dispatch_visual_verdict 판정 없이 final 산출"
    passed = verdict_state.get("passed") or []
    if not passed:
        return "PASS 후보 0 — REJECT/UNVERIFIED 만으로는 final 불가"
    underived = [path for path in final_paths if not _derived_from_pass(path, passed)]
    if underived:
        return f"final 이 PASS 후보({passed})의 exact-id 경로가 아님: " + ", ".join(underived)
    return None


class DeliveryDispatch:
    """딜리버리 위임 협력자 — dispatch 툴 핸들러 팩토리 묶음.

    hd(Heimdall)의 세션·모델·계측 표면만 사용한다: _session/_delivery_model/_learned_note/
    _track_cache/on_text/root/delivery_identity."""

    def __init__(self, hd):
        self._hd = hd

    def freyja_squad_handler(self, sid: str, worker_result_writes: list[str], cwd: str | None = None):
        """freyja-lead → freyja N기 병렬 fan-out. 자식에는 coordinate 도구를 주지 않아 깊이 1을 봉인한다."""
        hd = self._hd

        def handler(inp: dict) -> str:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            tasks = list(inp.get("tasks") or [])
            if not 2 <= len(tasks) <= 5:
                raise ValueError("프레이야 편대는 한 배치에 2~5기여야 한다")
            ids = [str(t.get("id") or "") for t in tasks]
            if any(not i for i in ids) or len(ids) != len(set(ids)):
                raise ValueError("편대 task id 는 비어 있지 않고 서로 달라야 한다")
            if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", task_id) for task_id in ids):
                raise ValueError("편대 task id 는 안전한 파일명 문자만 사용해야 한다")
            squad_root = cwd or hd.root

            def run_one(index: int, spec: dict):
                from ..unit_workspace import UnitWorkspace, WorkspaceError

                task, axis, why = str(spec["task"]), str(spec["axis"]), str(spec["why"])
                output_dir = f"deliverables/variations/{spec['id']}"
                ql(
                    hd.root,
                    "append",
                    session=sid,
                    stdin=json.dumps(
                        {
                            "role": "worker",
                            "event": "delegate",
                            "commands": [
                                {"cmd": f"dispatch:freyja:{spec['id']} — {axis}: {why[:100]}", "exit_code": 0}
                            ],
                        }
                    ),
                )
                system = _DELIVERY["freyja"] + "\n\n" + hd.delivery_identity + hd.map_note
                catalog, skill_tools, skill_handlers = _skill_support("freyja", hd.root)
                system += catalog
                with UnitWorkspace(squad_root, f"freyja-{spec['id']}") as workspace:
                    child = hd._session(
                        system,
                        extra_tools=skill_tools,
                        handlers=skill_handlers,
                        model=hd._delivery_model("freyja"),
                        role="freyja",
                        cwd=workspace.path,
                        quiet=True,
                    )
                    child._nested_dispatch = True
                    result = _checked_run(
                        child,
                        f"편대 변주 {spec['id']}\n변주 축: {axis}\n과업: {task}\n근거: {why}\n"
                        f"전용 출력 루트: {output_dir}\n이 디렉터리 밖은 수정하지 마라.",
                    )
                    hd._track_cache(result)
                    patch = workspace.capture(extra_paths=tuple(result.writes))
                    outside = [
                        path
                        for path in patch.paths
                        if path != output_dir and not path.startswith(output_dir.rstrip("/") + "/")
                    ]
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
                try:
                    from ..unit_workspace import UnitWorkspace

                    UnitWorkspace(squad_root, f"freyja-{spec['id']}").apply(patch)
                except Exception as exc:
                    failures.append({"id": spec["id"], "error": f"{type(exc).__name__}: {exc}"})
                    continue
                writes = list(patch.paths)
                worker_result_writes.extend(w for w in writes if w not in worker_result_writes)
                payload.append(
                    {"id": spec["id"], "axis": spec["axis"], "writes": writes, "summary": result.text[-1200:]}
                )
            return json.dumps({"results": payload, "failures": failures}, ensure_ascii=False)

        return handler

    def visual_verdict_handler(self, sid: str, worker_result_writes: list[str], cwd: str, verdict_state: dict):
        """read-only 판정자의 구조화 제출만 신뢰하고 런타임이 판정문을 작성한다."""
        hd = self._hd

        def handler(inp: dict) -> str:
            rel, real, candidate_ids = _safe_candidates(cwd, inp.get("candidates_dir"))
            focus = str(inp.get("focus") or "")
            ql(
                hd.root,
                "append",
                session=sid,
                stdin=json.dumps(
                    {
                        "role": "worker",
                        "event": "delegate",
                        "commands": [{"cmd": f"dispatch:visual-verdict — {rel} {focus[:80]}", "exit_code": 0}],
                    }
                ),
            )
            submitted: dict = {"verdicts": None}

            def submit(payload: dict) -> str:
                rows = list(payload.get("verdicts") or [])
                clean: list[dict[str, str]] = []
                seen: set[str] = set()
                for row in rows:
                    candidate_id = str(row.get("id") or "").strip()
                    verdict = str(row.get("verdict") or "").strip().upper()
                    why = str(row.get("why") or "").strip()[:400]
                    if candidate_id not in candidate_ids:
                        raise ValueError(f"실제 후보가 아닌 판정 id: {candidate_id}")
                    if candidate_id in seen:
                        raise ValueError(f"중복 판정 id: {candidate_id}")
                    if verdict not in ("PASS", "REJECT", "UNVERIFIED") or not why:
                        raise ValueError("각 판정은 유효한 verdict 와 빈 값이 아닌 why 를 가져야 한다")
                    seen.add(candidate_id)
                    clean.append({"id": candidate_id, "verdict": verdict, "why": why})
                missing = sorted(set(candidate_ids) - seen)
                if missing:
                    raise ValueError("판정에서 누락된 후보: " + ", ".join(missing))
                submitted["verdicts"] = clean
                return json.dumps({"received": len(clean)}, ensure_ascii=False)

            from ...templates.freyja import FREYJA_SKILLS

            bodies = dict(FREYJA_SKILLS)
            system = _DELIVERY["freyja"] + "\n\n" + hd.delivery_identity
            system += "\n\n# 전용 스킬 (판정 주입)\n\n" + "\n\n".join(
                bodies[name].split("---", 2)[2].lstrip()
                for name in ("asgard-freyja-valshamr", "asgard-freyja-hildisvini")
            )
            judge = hd._session(
                system,
                extra_tools=[VISUAL_VERDICT_SUBMIT_TOOL],
                handlers={"submit_visual_verdict": submit},
                model=hd._delivery_model("freyja"),
                role="freyja",
                readonly=True,
                cwd=cwd,
                quiet=True,
            )
            judge._nested_dispatch = True
            result = _checked_run(
                judge,
                f"시각 판정 (read-only): `{rel}` 아래 실제 후보 {list(candidate_ids)} 전부를 채점하고 "
                "submit_visual_verdict 도구로 중복·누락 없이 제출하라. "
                + (f"판정 초점: {focus}. " if focus else "")
                + "16/24/32px 렌더 수단이 없으면 UNVERIFIED, common glyph/object 자기반증은 REJECT다.",
            )
            hd._track_cache(result)
            verdicts = submitted["verdicts"]
            if not verdicts:
                return "[visual-verdict] ⚠ 판정 미제출 — 게이트는 잠긴 채다."
            passed = [row["id"] for row in verdicts if row["verdict"] == "PASS"]
            lines = "\n".join(f"- `{row['id']}` — **{row['verdict']}** — {row['why']}" for row in verdicts)
            verdict_rel = f"{rel}/VISUAL-VERDICT.md"
            body = (
                "<!-- authored-by: dispatch_visual_verdict (runtime) -->\n\n"
                f"# VISUAL VERDICT — {rel}\n\nPASS {len(passed)}/{len(verdicts)}\n\n{lines}\n"
            )
            path = os.path.join(real, "VISUAL-VERDICT.md")
            temporary = f"{path}.{os.getpid()}.tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(body)
            os.replace(temporary, path)
            verdict_state.update({"written": True, "passed": passed, "verdicts": verdicts})
            if verdict_rel not in worker_result_writes:
                worker_result_writes.append(verdict_rel)
            return f"[visual-verdict] {verdict_rel} 기록됨 — PASS {len(passed)}/{len(verdicts)}: {passed}"

        return handler

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
                raise ValueError("토르 편대 mode 는 split | tournament 다")
            tasks = list(inp.get("tasks") or [])
            if not 2 <= len(tasks) <= 4:
                raise ValueError("토르 편대는 한 배치에 2~4기여야 한다")
            ids = [str(t.get("id") or "") for t in tasks]
            if any(not i for i in ids) or len(ids) != len(set(ids)):
                raise ValueError("편대 task id 는 비어 있지 않고 서로 달라야 한다")
            if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", task_id) for task_id in ids):
                raise ValueError("편대 task id 는 안전한 파일명 문자만 사용해야 한다")
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
                        raise ValueError(f"안전하지 않은 편대 scope: {raw!r}")
                    norm.append(s)
                if not norm:
                    raise ValueError(f"편대 단위 {spec.get('id')} 에 scope 가 없다")
                scopes[str(spec["id"])] = norm
            if mode == "split":
                # 파일 비중첩은 에인헤랴르 분할 계약 — 선언 시점에 프리픽스 교차를 차단한다
                flat = [(tid, s) for tid, ss in scopes.items() for s in ss]
                for i, (ta, sa) in enumerate(flat):
                    for tb, sb in flat[i + 1 :]:
                        if ta != tb and (sa == sb or sa.startswith(sb + "/") or sb.startswith(sa + "/")):
                            raise ValueError(f"분할 편대 scope 중첩: {ta}:{sa} ↔ {tb}:{sb}")
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
                        f"편대 단위 {spec['id']} ({mode})\n과업: {task}\n근거: {why}\n"
                        f"허용 파일 범위: {', '.join(allowed)}\n이 범위 밖은 수정하지 마라. "
                        "단위 한정 검증만 실행하고(전역 게이트는 대장 몫), "
                        "반환 = 변경 파일 + 결정 요약 + 검증 증거 + 블로커.",
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
                    "패치는 본류 미적용 — 검증 통과분 중 승자 1개만 git apply 로 적용하고 합집합 검증을 실행하라"
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
                system += f"\n\n# 상속된 {base} 코어 계약\n\n" + _DELIVERY[base]
            system += "\n\n" + hd.delivery_identity
            if agent != "loki":
                system += getattr(hd, "map_note", "")
            catalog, skill_tools, skill_handlers = _skill_support(
                agent, hd.root, include_learned=agent not in _DELIVERY_READONLY
            )
            system += catalog
            if agent == "freyja-lead":
                return self.run_freyja_lead(sid, worker_result_writes, cwd, system, task, skill_tools, skill_handlers)
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

    def reject_freyja_final(self, sid: str, reason: str) -> str:
        ql(
            self._hd.root,
            "append",
            session=sid,
            stdin=json.dumps(
                {
                    "role": "worker",
                    "event": "delegate",
                    "commands": [{"cmd": "gate:visual-verdict — " + reason[:200], "exit_code": 1}],
                }
            ),
        )
        return f"[freyja-lead] ⛔ two-stage visual gate 위반 — {reason}. 본류 미반영."

    def run_freyja_lead(
        self,
        sid: str,
        worker_result_writes: list[str],
        cwd: str | None,
        system: str,
        task: str,
        skill_tools: list[dict],
        skill_handlers: dict,
    ):
        """편대장 전체를 Git 기반 격리 공간에서 실행하고 게이트 통과 후에만 병합한다.

        Git HEAD 가 없으면 기존 final 덮어쓰기를 안전하게 롤백할 수 없으므로 fail-closed 한다.
        """
        from ..unit_workspace import UnitWorkspace, _git

        hd = self._hd
        base = cwd or hd.root
        if _git(base, "rev-parse", "--verify", "HEAD", check=False).returncode:
            return self.reject_freyja_final(sid, "안전한 격리를 위한 Git HEAD 가 없어 freyja-lead 실행 불가")
        with UnitWorkspace(base, "freyja-lead") as workspace:
            verdict_state: dict = {}
            lead_writes: list[str] = []
            handlers = {
                **skill_handlers,
                "dispatch_freyja_squad": self.freyja_squad_handler(sid, lead_writes, workspace.path),
                "dispatch_visual_verdict": self.visual_verdict_handler(sid, lead_writes, workspace.path, verdict_state),
            }
            child = hd._session(
                system,
                extra_tools=[*skill_tools, FREYJA_SQUAD_TOOL, FREYJA_VERDICT_TOOL],
                handlers=handlers,
                model=hd._delivery_model("freyja-lead"),
                role="freyja-lead",
                cwd=workspace.path,
            )
            child._nested_dispatch = True
            result = _checked_run(child, task)
            hd._track_cache(result)
            patch = workspace.capture(extra_paths=tuple(result.writes))
            final_paths = _freyja_final_writes(patch.paths)
            reason = _freyja_gate_rejection(final_paths, verdict_state)
            if reason:
                return self.reject_freyja_final(sid, reason)
            workspace.apply(patch)
            worker_result_writes.extend(path for path in patch.paths if path not in worker_result_writes)
            return f"[freyja-lead] {result.text[-2000:]}"
