"""memory 커맨드 — 위생 검사. 문법 린트·모순 적발·제안 목록."""

import json as _json
import time

from ... import errors, memory, ui
from ._core import _emit, _fail, _guard


def _open_contradiction_findings(d: str) -> list[dict]:
    """미해결 모순을 lint 판정 줄 모양으로 — 없으면 빈 리스트. 읽기만 한다.

    lint 에 얹는 이유: 이 물음("이 위키에 지금 사람이 볼 것이 있는가")에 답하는 표면이 이미
    있는데 모순만 거기 없었다. 죽은 링크·부패 후보·중복은 다 여기서 말하면서 서로 어긋나는
    두 페이지는 리포트 파일 안에만 적혀 있었고, 리포트는 런마다 새로 생기는 파생물이라
    아무도 안 읽는다. 새 표면을 만들면 볼 자리가 하나 더 느는 것이고, 지금 고장이 정확히
    "볼 자리가 흩어져 있다"는 것이다.

    level 이 warn 인 것에 뜻이 있다 — 종료 코드를 흔들지 않는다. 모순은 이 위키의 결함이
    아니라 사람이 판단할 물음이고, CI 를 빨갛게 만들 일이 아니다 (`memory.contradiction`).
    슬러그 두 개가 한 줄에 다 나와야 사람이 무엇끼리 어긋났는지 목록을 안 열고도 안다."""
    rows = memory.open_contradictions(d)
    out: list[dict] = []
    for row in rows:
        seen = f" · {row['count']}번째 감지" if int(row.get("count") or 0) > 1 else ""
        stale = " · 그 뒤 페이지가 바뀜" if row.get("changed_since") else ""
        out.append(
            {
                "level": "warn",
                "code": "open-contradiction",
                "slug": row["a"],
                "msg": f"↔ {row['b']} · {row['why'] or '사유 없음'}{seen}{stale}",
            }
        )
    return out


def run_lint(json_out: bool, fix: bool = False) -> int:
    def _do() -> int:
        # ensure_home 이 아니라 memory_dir 이다 — lint 는 읽기다. 건강을 물었을 뿐인데
        # 없던 홈이 생기면, 아무것도 안 고쳤다는 이 명령의 약속이 첫 줄에서 깨진다.
        d = memory.memory_dir()
        # 수리는 판정 **전에** 돈다 — 고친 뒤의 상태를 판정해야 남은 것만 보고된다.
        retitled = memory.retitle(d) if fix else []
        if retitled and not json_out:
            for slug, old_title, new_title in retitled:
                ui.ok(f"retitle {slug}: {old_title} → {new_title}")
        contradictions = _open_contradiction_findings(d)
        findings = memory.lint(d) + contradictions  # 두 판정에 같은 디렉터리를 준다 — 각자 고르면 갈린다
        if json_out:
            payload = {
                "findings": findings,
                "retitled": [{"slug": s, "from": o, "to": n} for s, o, n in retitled],
            }
            print(_json.dumps(payload if fix else findings, ensure_ascii=False, indent=1))
        elif not findings:
            ui.ok("memory healthy — no findings")
        else:
            for f in findings:
                line = f"[{f['level']}] {f['code']}: {f['slug']} — {f['msg']}"
                (ui.fail if f["level"] == "error" else ui.warn if f["level"] == "warn" else ui.step)(line)
        # 0건이면 한 글자도 안 낸다 — 조용한 것이 기본이고, 없는 모순을 "없다"고 말하는 줄은
        # 매번 읽히다가 안 읽히게 되고 그때 있는 모순도 같이 안 읽힌다.
        if contradictions and not json_out:
            ui.step(f"미해결 모순 {len(contradictions)}건 — 자세히: asgard memory contradictions")
        return 1 if any(f["level"] == "error" for f in findings) else 0

    return _guard(_do)


def run_contradictions(json_out: bool = False, include_seen: bool = False) -> int:
    """미해결 모순 장부 — 노른이 찾아 사람에게 넘긴 어긋남. 읽기 전용.

    노른은 모순을 만나면 아무것도 안 고치고 보고만 한다. 정체성 슬롯 다섯 밖에서는 두 기록이
    어긋나 보여도 대개 둘 다 참이라(다른 시기·다른 맥락·다른 대상) 자동 해소가 곧 데이터
    소실이기 때문이다 — 흡수는 삭제다. 그래서 이 명령은 보여 주기만 한다."""

    def _do() -> int:
        from ...memory.contradiction import ACKNOWLEDGED  # 상태 이름은 장부가 정한다 — 여기서 베끼면 갈린다

        d = memory.memory_dir()  # 읽기 전용 — 목록을 보는 것이 홈을 만드는 일이 되면 안 된다
        rows = memory.open_contradictions(d, include_acknowledged=include_seen)
        if json_out:
            print(_json.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        if not rows:
            ui.step("확인한 것까지 통틀어도 장부가 비어 있어요" if include_seen else "아직 안 풀린 모순은 없어요")
            return 0
        # --all 은 확인한 것까지 담는다 — 그걸 "미해결"이라고 부르면 머리글이 거짓말한다.
        ui.head(
            f"위그드라실 · 모순 {len(rows)}건 (확인한 것 포함)"
            if include_seen
            else f"위그드라실 · 미해결 모순 {len(rows)}건"
        )
        ui.step("노른이 찾아서 넘긴 어긋남이에요 — 어느 쪽도 자동으로 고치거나 지우지 않았어요.")
        for row in rows:
            ui.warn(f"{row['a']} ↔ {row['b']}")
            ui.step(f"  {row['a_title']}  ↔  {row['b_title']}")
            ui.step(f"  {row['why'] or '사유 없음'}")
            marks = [f"처음 {row['detected']}", f"마지막 {row['last_seen']}", f"{row['count']}번 감지"]
            if row["status"] == ACKNOWLEDGED:
                marks.append(f"확인함 {row['acknowledged']}" + (f" · {row['note']}" if row["note"] else ""))
            if row["changed_since"]:
                # 장부가 본 판본 이후로 페이지가 바뀌었다 — 위의 사유가 지금 본문을 안 가리킬 수 있다.
                marks.append("그 뒤 페이지가 바뀜 — 사유가 낡았을 수 있어요")
            ui.step(ui.dim("  " + " · ".join(marks)))
        ui.step("본문 대조: asgard memory show <slug>")
        # "봤다"와 "고쳤다"를 여기서 갈라 두지 않으면 사람은 확인 명령을 해소로 읽는다.
        ui.step("봤다고 표시(해소 아님): asgard memory contradiction-seen <a> <b> [--note ...]")
        return 0

    return _guard(_do)


def run_contradiction_seen(a: str, b: str, note: str = "", json_out: bool = False) -> int:
    """모순 하나에 "봤다"를 표시한다 — **해소가 아니다.**

    표시가 하는 일은 하나뿐이다: 다음 손질에서 이 쌍을 다시 안 보여 준다. 페이지는 한 글자도
    안 바뀌고 어느 쪽이 참인지도 안 적힌다 — 해소는 사람이 정본을 고쳐서 한다. 두 페이지 중
    하나가 나중에 바뀌면 표시는 저절로 풀린다 (넘긴 판단은 그때의 두 문장에 대한 것이다)."""
    errors.set_json_surface(json_out)

    def _do() -> int:
        d = memory.memory_dir()
        row = memory.acknowledge_contradiction(memory.contradiction_key(a, b), note=note, d=d)
        if row is None:
            return _fail(
                f"장부에 없는 쌍 · {a} ↔ {b}",
                code="not_found",
                remedy="목록에 있는 슬러그를 그대로 적어 주세요: asgard memory contradictions",
                detail={"a": a, "b": b},
            )
        if json_out:
            # 표시는 해소가 아니다 — 그 사실을 기계도 읽을 수 있어야 소비자가 "고쳐졌다"고 안 읽는다.
            _emit({"a": row["a"], "b": row["b"], "acknowledged": True, "resolved": False, "note": note})
            return 0
        ui.ok(f"봤다고 표시함 · {row['a']} ↔ {row['b']}")
        ui.warn("해소된 건 아니에요 — 두 페이지는 그대로고, 어느 쪽이 맞는지도 안 적혔어요.")
        ui.step("고치려면 정본을 직접 고쳐 주세요 (asgard memory show <slug>로 본문 확인).")
        ui.step("두 페이지 중 하나가 바뀌면 이 표시는 자동으로 풀리고 다시 목록에 떠요.")
        return 0

    return _guard(_do)


def run_proposals(json_out: bool = False) -> int:
    """에이전트가 올린 개인 기억 제안 대기열 — 사람이 읽고 승인하는 자리."""

    def _do() -> int:
        from ...memory import propose

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
            # 흡수는 페이지 삭제다 — 승인 전에 반드시 눈에 보여야 한다. `run_ingest`가 즉석
            # 계획에 대해 내는 것과 **같은 줄**이다: 같은 일을 두 화면이 다르게 말하면 한쪽을
            # 본 사람은 다른 쪽에서 무슨 일이 일어나는지 모른다. 제안 대기줄은 계획을 이미
            # 세워 두고(`propose.stage`의 plan_absorb) 며칠 뒤에 승인받는 자리라, 여기서
            # 침묵하면 사라진 페이지를 나중에 발견하게 된다.
            for slug in row.get("plan_absorb") or []:
                ui.warn(f"  plan: absorb (archive) contradicting page — {slug}")
        ui.step("승인: asgard memory approve <id>   ·   버림: asgard memory discard <id>")
        ui.step("매번 승인이 번거로우면: asgard memory autosave on --tier personal")
        return 0

    return _guard(_do)
