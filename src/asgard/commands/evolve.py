"""`asgard evolve` — 진화 인박스 (자가발전 C2, CUS-254).

scan(채굴) → list/show(검토) → approve/reject(처분) → archive(노화 보관).
승인만이 learned 스킬을 활성화하는 유일한 경로 — 자동 활성화는 없다 (CUS-251 헌법).

`--json`은 이 실행의 성질이다: stdout이 기계의 것이 되고, 실패도 `{"error": {...}}`로 나간다.
그래서 실패는 `return 1`이 아니라 예외로 던진다 — `cli.main`이 두 표면을 한 자리에서 그린다.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .. import errors, ui
from .. import evolution as evo


def _root(start: str = ".") -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return str(Path(proc.stdout.strip()).resolve())
    except OSError, subprocess.TimeoutExpired:
        pass
    return str(Path(start).resolve())


def _surface(json_out: bool) -> str:
    """이 실행의 표면을 알리고 저장소 뿌리를 돌려준다.

    `ui.ok`·`ui.warn`은 stdout으로 나가고 `--quiet`이 그것을 막지 않는다. 그래서 `--json`
    분기는 ui를 부르지 않는 쪽으로 갈라야 한다 — 산출물 스트림에 사람 문장이 섞이면
    소비자가 파싱할 것을 못 찾는다."""
    errors.set_json_surface(json_out)
    return _root()


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _draft(root: str, cid: str) -> str:
    """pending 초안 본문 — 없으면 그 자리에서 NotFound."""
    text = evo.show(root, cid)
    if text is None:
        raise errors.NotFound(
            f"그런 후보가 없어요: {cid}",
            remedy="asgard evolve list 로 대기 중인 후보를 보세요",
            detail={"candidate": cid},
        )
    return text


def _draft_name(text: str) -> str:
    from ..skill_bank import parse_skill_md

    parsed = parse_skill_md(text)
    return str(parsed[0].get("name", "")) if parsed else ""


def run_scan(json_out: bool = False) -> int:
    root = _surface(json_out)
    created = evo.mine(root)
    left = evo.unmined_signals(root)
    if json_out:
        _emit({"created": created, "count": len(created), "unmined": left})
        return 0
    if not created:
        print(
            f"새 신호가 없어요 (아직 안 캔 게 {left}건)"
            if left
            else "새 신호가 없어요 — 퀘스트 로그에 아직 배울 만한 게 없네요"
        )
        return 0
    for m in created:
        detail = (
            f"quest {m['quest_id']}, FAIL {m['fail_count']}회 → PASS"
            if m.get("quest_id")
            else "사용자 정정 신호"  # origin: correction — 제2 채굴원 (26-07-24)
        )
        ui.ok(f"후보를 만들었어요 {m['id']} — {m['name']} ({detail})")
    print(ui.dim("검토: asgard evolve list · 승인: asgard evolve approve <id>"))
    return 0


def run_nudge(json_out: bool = False) -> int:
    """훅 소비 표면 — 미채굴 신호가 새로 생겼을 때만 한 줄 출력 (latch), 그 외 침묵.
    memory-activate Stop 훅이 subprocess로 부른다 — 로직은 evolution.nudge_line 단일 출처.

    `--json`은 침묵도 값으로 낸다: 훅이 아닌 소비자는 "출력 없음"과 "명령 실패"를 구별해야 한다."""
    line = evo.nudge_line(_surface(json_out))
    if json_out:
        _emit({"nudge": line})
    elif line:
        print(line)
    return 0


def run_list(json_out: bool = False) -> int:
    root = _surface(json_out)
    items = evo.pending_list(root)
    pending_dir = os.path.join(".asgard", "evolution", "pending")
    if json_out:
        _emit({"pending": items, "count": len(items), "dir": pending_dir})
        return 0
    if not items:
        print("인박스가 비어 있어요 — asgard evolve scan으로 퀘스트 로그를 캐 보세요")
        return 0
    print(ui.bold(f"pending {len(items)}건") + ui.dim(" — 승인 전에 초안 파일을 직접 다듬어도 돼요"))
    for m in items:
        print(
            f"  {ui.bold(m['id'])}  {m.get('name', '?')}  "
            + ui.dim(f"quest {m.get('quest_id', '?')} · FAIL {m.get('fail_count', '?')}회 · {m.get('created', '')}")
        )
    print(ui.dim(f"파일: {pending_dir}/<id>/SKILL.md"))
    return 0


def run_show(cid: str, json_out: bool = False) -> int:
    text = _draft(_surface(json_out), cid)
    if json_out:
        _emit({"id": cid, "name": _draft_name(text), "skill_md": text})
    else:
        print(text)
    return 0


def run_approve(cid: str, json_out: bool = False) -> int:
    root = _surface(json_out)
    name = _draft_name(_draft(root, cid))  # 없는 후보는 여기서 NotFound — 아래는 내용 문제만 남는다
    ok, msg = evo.approve(root, cid)
    if not ok:
        raise errors.InvalidInput(
            msg,
            remedy=f"초안을 고친 뒤 다시: asgard evolve approve {cid}",
            detail={"candidate": cid, "skill": name},
        )
    if json_out:
        _emit({"id": cid, "skill": name, "approved": True, "path": f".asgard/skills/{name}", "message": msg})
    else:
        ui.ok(msg)
    return 0


def run_reject(cid: str, reason: str = "", json_out: bool = False) -> int:
    root = _surface(json_out)
    _draft(root, cid)
    ok, msg = evo.reject(root, cid, reason)
    if not ok:
        raise errors.NotFound(msg, remedy="asgard evolve list 로 대기 중인 후보를 보세요", detail={"candidate": cid})
    if json_out:
        _emit({"id": cid, "rejected": True, "reason": reason, "message": msg})
    else:
        ui.ok(msg)
    return 0


def run_polish(cid: str, json_out: bool = False) -> int:
    root = _surface(json_out)
    _draft(root, cid)
    ok, msg = evo.polish(root, cid)
    if not ok:
        # 후보는 이미 있다고 확인했으므로 남은 실패는 전부 바깥(모델·형식)이다 — 우리 잘못도
        # 사용자 잘못도 아니고, 초안은 결정론 원본 그대로 남는다.
        raise errors.UpstreamError(msg, remedy=f"초안은 그대로예요 — 그대로 승인: asgard evolve approve {cid}")
    if json_out:
        _emit({"id": cid, "polished": True, "message": msg})
    else:
        ui.ok(msg)
    return 0


def run_bench(
    skill: str, cmd: str, metric: str, runs: int, direction: str, timeout: int, json_out: bool = False
) -> int:
    from ..evolution_bench import run_ab

    root = _surface(json_out)
    if not json_out:
        print(ui.dim(f"A/B: {skill} OFF({runs}회) vs ON({runs}회) — METRIC {metric} ({direction})"))
    r = run_ab(root, skill, cmd, metric, runs=runs, direction=direction, timeout=timeout)
    if json_out:
        # 종료 코드 1은 실패가 아니라 판정이다 — payload는 그대로 나가고 verdict가 그것을 말한다.
        _emit({"skill": skill, "metric": metric, "runs": runs, "direction": direction, **r})
        return 0 if r["verdict"] != "discard" else 1
    conf = f"{r['confidence']:.2f}×MAD" if r["confidence"] is not None else "판정 불가 (run<3 또는 MAD=0)"
    print(f"  baseline(OFF) median={r['baseline_median']}  variant(ON) median={r['variant_median']}  conf={conf}")
    mark = {"keep": ui.ok, "discard": ui.warn}.get(r["verdict"], ui.step)
    mark(f"verdict: {r['verdict']}" + (" — asgard evolve archive로 보관 권장" if r["verdict"] == "discard" else ""))
    print(ui.dim("계보: .asgard/evolution/bench.jsonl (판정은 기록 — 처분은 사용자 몫)"))
    return 0 if r["verdict"] != "discard" else 1


def run_curate(apply: bool = False, json_out: bool = False) -> int:
    """learned 스킬 노화 보고 (기본 드라이런) — --apply 시 90일 유휴 후보만 보관 전이."""
    from ..skill_curator import curate

    root = _surface(json_out)
    result = curate(root, apply=apply)
    findings = result["findings"]
    candidates = [f["name"] for f in findings if f["state"] == "archive-candidate"]
    if json_out:
        _emit({"applied": apply, "findings": findings, "candidates": candidates, "archived": result["archived"]})
        return 0
    if not findings:
        print("익힌 스킬이 없어요 — 정리할 게 없네요")
        return 0
    marks = {"active": ui.ok, "stale": ui.warn, "archive-candidate": ui.warn, "unreadable": ui.fail}
    for f in findings:
        mark = marks.get(f["state"], ui.step)
        detail = f.get("reason", "")
        mark(f"{f['name']} · {f['state']}" + (f" — {detail}" if detail else ""))
    if result["archived"]:
        ui.ok(
            f"보관 전이 {len(result['archived'])}건: {', '.join(result['archived'])} (복원: asgard evolve restore <name>)"
        )
    elif candidates:
        ui.warn(f"보관할 만한 게 {len(candidates)}건 있어요 — 보시고 asgard evolve curate --apply")
    return 0


def run_archive(name: str, json_out: bool = False) -> int:
    ok, msg = evo.archive_skill(_surface(json_out), name)
    if not ok:
        raise errors.NotFound(msg, remedy="asgard skills list 로 익힌 스킬을 보세요", detail={"skill": name})
    if json_out:
        _emit({"skill": name, "archived": True, "message": msg})
    else:
        ui.ok(msg)
    return 0


def run_restore(name: str, json_out: bool = False) -> int:
    ok, msg = evo.restore_skill(_surface(json_out), name)
    if not ok:
        # 실패는 둘이다 — 아카이브에 없거나, 같은 이름이 이미 활성이다. 둘 다 사용자가 고친다.
        raise errors.InvalidInput(msg, remedy="asgard skills list 로 지금 있는 스킬을 보세요", detail={"skill": name})
    if json_out:
        _emit({"skill": name, "restored": True, "message": msg})
    else:
        ui.ok(msg)
    return 0
