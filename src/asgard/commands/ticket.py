"""`asgard ticket` — 창을 안 열고 일감을 만지는 손.

같은 워크스페이스를 스튜디오 창·에이전트 툴·이 명령이 함께 본다
(`<에이전트 홈>/studio/workspace.db`). 그래서 여기서 옮긴 칸은 창을 새로 고치면 그 자리에
있고, 에이전트가 스스로 끊은 번호는 `asgard ticket list`에 그대로 뜬다.

**어디서 부르든 워크스페이스 전체를 본다.** 일감은 폴더의 것이 아니라 사람의 것이라, 같은
명령이 선 자리에 따라 다른 답을 내면 안 된다. 좁히고 싶으면 `--team <키>`로 고르고,
`--team .`은 이 폴더에 결속된 팀만 본다.

터미널이라 우선순위는 색이 아니라 **기호**로 말한다(`!!! !! ! ·`): 파이프로 넘기거나 로그에
붙여도 뜻이 남아야 한다.
"""

from __future__ import annotations

import json
import os
import time

from .. import errors, ui
from ..studio import legacy as L
from ..studio import projects as P
from ..studio import teams as TM
from ..studio import tickets as T
from .health import _project_root

_PRIORITY_MARK = {1: "!!!", 2: "!!", 3: "!", 4: "·", 0: " "}
# 활동 줄의 칸 이름 — 저장소는 컬럼 이름으로 적고, 사람 표면은 사람 말로 읽는다
_FIELD_LABEL = {
    "created": "생성",
    "comment": "댓글",
    "status": "상태",
    "priority": "우선순위",
    "assignee": "담당",
    "reporter": "보고",
    "estimate": "추정",
    "title": "제목",
    "body": "설명",
    "labels": "라벨",
    "parent_id": "상위",
    "cycle_id": "주기",
    "due_at": "기한",
    "task_id": "실행",
    "plan_id": "기획",
    "blocks": "차단",
    "relates": "연관",
    "duplicates": "중복",
    "evidence": "부하 근거",
}
_STATUS_WIDTH = 8  # 표시 폭 — '진행 중'은 글자 3개지만 터미널에서 7칸을 먹는다


def _root() -> str:
    return _project_root(os.getcwd())


def _mark(ticket: dict) -> str:
    return _PRIORITY_MARK.get(int(ticket.get("priority") or 0), " ").rjust(3)


def _pad(text: str, cols: int) -> str:
    """터미널 칸 수로 맞춘다. `str.ljust`는 **글자 수**로 세니 한글이 섞이면 줄이 어긋난다."""
    return text + " " * max(0, cols - ui.disp_width(text))


def _line(ticket: dict, width: int = 0) -> str:
    key = ticket["key"].ljust(width or len(ticket["key"]))
    # 팀이 지은 상태 이름이 있으면 그것을 쓴다 — 기본 여섯 칸의 이름표로만 읽으면
    # 팀이 만든 '배포 대기'가 화면에서 KeyError로 죽는다.
    name = ticket.get("status_label") or T.STATUS_LABEL.get(ticket["status"], ticket["status"])
    status = _pad(ui.fit(name, _STATUS_WIDTH), _STATUS_WIDTH)
    tail = []
    if ticket.get("team_key") and ticket.get("_wide"):
        tail.append(ticket["team_key"])
    if ticket["assignee"]:
        tail.append(f"@{ticket['assignee']}")
    if ticket["labels"]:
        tail.append("#" + " #".join(label["name"] for label in ticket["labels"]))
    if ticket["children"]:
        tail.append(f"하위 {ticket['children_done']}/{ticket['children']}")
    if ticket["blocked_by"]:
        tail.append("막힘←" + ",".join(ticket["blocked_by"]))
    suffix = ui.dim("  " + " · ".join(tail)) if tail else ""
    return f"{_mark(ticket)} {ui.bold(key)}  {ui.dim(status)}  {ticket['title']}{suffix}"


def _emitted(payload: object, message: str, json_out: bool) -> int:
    """변경 결과 하나를 낸다 — `--json` 이면 객체, 아니면 사람이 읽는 줄.

    `ui.ok` 는 quiet 을 안 본다(경고·성공은 조용해지면 안 되는 표면이라 의도된 것이다). 그래서
    변경 분기가 `ui.ok` 로 바로 끝나면 `--json` 을 줘도 사람 문장이 stdout 으로 나가고, 그 출력을
    파싱하는 호출자는 exit 0 을 받고도 JSON 을 못 읽는다. 목록·조회는 이미 `_emit` 한 곳을
    지나므로 변경 쪽에도 같은 경유점을 둔다.

    Returns:
        항상 0 — 호출자가 `return _emitted(...)` 로 끝낼 수 있게.
    """
    if json_out:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        ui.ok(message)
    return 0


def _emit(rows: list[dict], json_out: bool) -> None:
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        ui.step(ui.dim("조건에 맞는 티켓이 없어요."))
        return
    width = max(len(row["key"]) for row in rows)
    for row in rows:
        ui.step(_line(row, width))


def run_list(
    status: str,
    assignee: str,
    label: str,
    cycle: str,
    query: str,
    open_only: bool,
    json_out: bool,
    team: str = "",
    project: str = "",
) -> int:
    ui.set_quiet(json_out)
    try:
        rows = T.list_tickets(
            _root(),
            status=[s.strip() for s in status.split(",") if s.strip()] or None,
            assignee=assignee or None,
            label=label or None,
            cycle=cycle or None,
            team=team or None,
            project=project or None,
            query=query,
            open_only=open_only,
        )
    except (T.TicketError, T.StoreError) as exc:
        ui.fail(str(exc))
        return 2
    rows.sort(key=T.sort_key)
    _emit(rows, json_out)
    return 0


def run_board(json_out: bool, team: str = "", project: str = "") -> int:
    """상태별로 접어 보여 준다 — 창의 보드와 같은 순서, 같은 칸."""
    ui.set_quiet(json_out)
    root = _root()
    try:
        view = T.board(root, team=team or None, project=project or None)
        summary = T.summary(root, team=team or None)
    except (T.TicketError, T.StoreError) as exc:
        ui.fail(str(exc))
        return 2
    if json_out:
        print(json.dumps({"board": view, "summary": summary}, ensure_ascii=False, indent=2))
        return 0
    # 머리줄이 부르는 이름 — 팀이 하나도 없을 때 "워크스페이스 전체"라고 말하면, 전체를
    # 봤더니 비어 있다는 뜻인지 아직 아무것도 없다는 뜻인지 사람이 못 가른다.
    if summary.get("team"):
        where = summary["team"]["name"]
    elif summary.get("teams"):
        where = "워크스페이스 전체"
    else:
        where = "아직 팀 없음"
    triage = summary.get("triage") or 0
    ui.head(
        f"{where} · {summary['prefix'] or '—'} · 열림 {summary['open']} · 진행 {summary['started']} · "
        f"막힘 {summary['blocked']}" + (f" · 트리아지 {triage}" if triage else "")
    )
    for column in view["columns"]:
        if not column["tickets"]:
            continue
        ui.phase(f"{column['label']} ({len(column['tickets'])})")
        width = max(len(t["key"]) for t in column["tickets"])
        for ticket in column["tickets"]:
            ui.step(_line(ticket, width))
    if not view["total"]:
        # 처음 오는 사람에게는 "없다"보다 **어떻게 생겼는지**가 먼저다 — 번호가 어디서 나오고
        # 어디에 사는지를 모르면, 첫 티켓을 만들고도 그것을 자기 것으로 안 읽는다.
        ui.step(ui.dim('아직 티켓이 없어요 — `asgard ticket new "할 일"`로 첫 건을 남겨 보세요.'))
        if not summary.get("team"):
            ui.step(ui.dim(f"  첫 티켓은 {summary['prefix']}-1이 되고, 그때 팀도 하나 생겨요."))
        ui.step(ui.dim("  일감은 워크스페이스에 있어요 — 번호는 팀의 것이고, 프로젝트는 팀을 가로질러요."))
        ui.step(ui.dim("  기본은 늘 전체예요 — `--team <키>`로 좁힐 수 있고, `--team .`은 이 폴더의 팀이에요."))
        if L.pending_roots([root]):
            ui.warn("이 폴더에 예전 방식의 보드가 남아 있어요 — `asgard ticket import`로 그대로 들여오세요.")
    return 0


def run_new(
    title: str,
    body: str,
    status: str,
    priority: int,
    assignee: str,
    labels: str,
    parent: str,
    estimate: int | None,
    json_out: bool,
    team: str = "",
    project: str = "",
    milestone: str = "",
) -> int:
    ui.set_quiet(json_out)
    try:
        ticket = T.create_ticket(
            _root(),
            title,
            body=body,
            status=status,
            priority=priority,
            assignee=assignee,
            estimate=estimate,
            labels=[x.strip() for x in labels.split(",") if x.strip()],
            parent=parent or None,
            team=team or None,
            project=project or None,
            milestone=milestone or None,
            reporter="cli",
            actor="cli",
        )
    except (T.TicketError, T.StoreError) as exc:
        ui.fail(str(exc))
        return 2
    if json_out:
        print(json.dumps(ticket, ensure_ascii=False, indent=2))
    else:
        where = ticket["team"]["name"] if ticket.get("team") else ""
        ui.ok(f"{ticket['key']} 발급 — {ticket['title']}" + (f"  ({where})" if where else ""))
    return 0


def run_show(ref: str, json_out: bool) -> int:
    ui.set_quiet(json_out)
    try:
        ticket = T.get_ticket(_root(), ref)
    except (T.TicketError, T.StoreError) as exc:
        ui.fail(str(exc))
        return 2
    if json_out:
        print(json.dumps(ticket, ensure_ascii=False, indent=2))
        return 0
    ui.head(f"{ticket['key']} · {ticket['title']}")
    ui.step(_line(ticket))
    if ticket["body"]:
        ui.step("")
        for line in ticket["body"].splitlines():
            ui.step(f"  {line}")
    if ticket["parent"]:
        ui.phase("상위")
        ui.step(f"  {ticket['parent']['key']} · {ticket['parent']['title']}")
    if ticket["children_list"]:
        ui.phase(f"하위 {ticket['children_done']}/{ticket['children']}")
        for child in ticket["children_list"]:
            ui.step(_line(child))
    if ticket["blocked_by"] or ticket["blocks"]:
        ui.phase("관계")
        if ticket["blocked_by"]:
            ui.step(ui.dim("  막힘 ← " + ", ".join(ticket["blocked_by"])))
        if ticket["blocks"]:
            ui.step(ui.dim("  막고 있음 → " + ", ".join(ticket["blocks"])))
    if ticket.get("evidence"):
        ui.phase(f"부하 근거 {len(ticket['evidence'])}")
        _show_evidence(ticket["evidence"])
    if ticket["comments_list"]:
        ui.phase(f"댓글 {len(ticket['comments_list'])}")
        for note in ticket["comments_list"]:
            ui.step(f"  {ui.bold(note['author'] or '익명')} {ui.oneline(note['body'], 160)}")
    if ticket["activity"]:
        ui.phase("활동")
        for row in ticket["activity"][:12]:
            field = _FIELD_LABEL.get(row["field"], row["field"])
            # 지운 것과 아무 일 없던 것이 같은 줄로 보이면 안 된다 — 빈 도착지는 '없음'이라 쓴다
            if row["field"] in {"created", "comment"}:
                change = ui.oneline(row["after"], 120)
            elif row["before"]:
                change = f"{ui.oneline(row['before'], 40)} → {ui.oneline(row['after'], 60) or '없음'}"
            else:
                change = f"→ {ui.oneline(row['after'], 60) or '없음'}"
            ui.step(ui.dim(f"  {row['actor'] or '—'} {field} {change}"))
    return 0


def run_move(ref: str, status: str, json_out: bool) -> int:
    ui.set_quiet(json_out)
    try:
        ticket = T.move_ticket(_root(), ref, status, actor="cli")
    except (T.TicketError, T.StoreError) as exc:
        ui.fail(str(exc))
        return 2
    if json_out:
        print(json.dumps(ticket, ensure_ascii=False, indent=2))
    else:
        ui.ok(f"{ticket['key']} → {T.STATUS_LABEL[ticket['status']]}")
    return 0


def run_set(
    ref: str,
    title: str,
    body: str,
    priority: int | None,
    assignee: str | None,
    labels: str | None,
    estimate: int | None,
    parent: str | None,
    cycle: str | None,
    json_out: bool,
) -> int:
    """준 칸만 바꾼다 — 안 준 칸은 남의 수정이라 그대로 둔다."""
    ui.set_quiet(json_out)
    changes: dict = {}
    if title:
        changes["title"] = title
    if body:
        changes["body"] = body
    if priority is not None:
        changes["priority"] = priority
    if assignee is not None:
        changes["assignee"] = assignee
    if labels is not None:
        changes["labels"] = [x.strip() for x in labels.split(",") if x.strip()]
    if estimate is not None:
        changes["estimate"] = estimate
    if parent is not None:
        changes["parent"] = parent
    if cycle is not None:
        changes["cycle"] = cycle
    if not changes:
        ui.fail("바꿀 칸을 하나는 주세요 (--title, --priority, --assignee, --label, …)")
        return 2
    try:
        ticket = T.update_ticket(_root(), ref, changes, actor="cli")
    except (T.TicketError, T.StoreError) as exc:
        ui.fail(str(exc))
        return 2
    if json_out:
        print(json.dumps(ticket, ensure_ascii=False, indent=2))
    else:
        ui.ok(f"{ticket['key']} 갱신 — {', '.join(sorted(changes))}")
    return 0


def _rejected(exc: Exception, ref: str) -> errors.AsgardError:
    """티켓 하나에 대한 거절을 경계의 어휘로 — 호출자가 고칠 수 있는 잘못이므로 2다.

    `StoreError`는 여기 안 온다: 호출부가 `TicketError`만 넘긴다. 저장소를 못 여는 것은 사용자가
    적은 값의 문제가 아니라 환경의 문제라 정본대로 `Unavailable` 1로 나가야 한다 — 그것을 2로
    바꾸면 스크립트가 "내가 틀렸다"와 "저장소가 깨졌다"를 구별하지 못한다."""
    return errors.InvalidInput(str(exc), remedy="asgard ticket list로 지금 있는 티켓을 보세요", detail={"ticket": ref})


def run_comment(ref: str, text: str, author: str, json_out: bool = False) -> int:
    errors.set_json_surface(json_out)
    ui.set_quiet(json_out)
    try:
        note = T.add_comment(_root(), ref, text, author=author or "cli")
    except T.TicketError as exc:
        raise _rejected(exc, ref) from exc
    return _emitted(note, f"{note['ticket']}에 댓글을 남겼어요", json_out)


def run_link(ref: str, other: str, kind: str, remove: bool, json_out: bool = False) -> int:
    errors.set_json_surface(json_out)
    ui.set_quiet(json_out)
    try:
        if remove:
            if not T.unlink_tickets(_root(), ref, kind, other):
                raise errors.NotFound(
                    "그런 관계가 없어요",
                    remedy=f"asgard ticket show {ref} 명령으로 지금 걸린 관계를 보세요",
                    detail={"ticket": ref, "other": other, "kind": kind},
                )
            return _emitted(
                {"ticket": ref, "other": other, "kind": kind, "linked": False},
                f"{ref} ⇸ {other} ({kind}) 해제",
                json_out,
            )
        ticket = T.link_tickets(_root(), ref, kind, other, actor="cli")
    except T.TicketError as exc:
        raise _rejected(exc, ref) from exc
    return _emitted(
        {"ticket": ticket["key"], "other": other, "kind": kind, "linked": True},
        f"{ticket['key']} → {other} ({kind})",
        json_out,
    )


def run_evidence(
    ref: str,
    stamp: str = "",
    scenario: str = "",
    note: str = "",
    list_only: bool = False,
    remove: str = "",
    json_out: bool = False,
) -> int:
    """부하 근거를 매달고·보고·뗀다. 표식을 안 주면 이 프로젝트의 가장 최근 기록이다.

    이 명령은 티켓을 막지 않는다. 부하와 무관한 티켓이 대부분이라, 여기에 게이트를 두면 그
    게이트는 우회되고 남는 것은 없다. 그래서 미판정 실행을 매달아도 종료 코드는 0이다 —
    다만 화면과 저장된 판정 칸이 그것을 통과와 다르게 말한다."""
    errors.set_json_surface(json_out)
    ui.set_quiet(json_out)
    root = _root()
    try:
        if remove:
            if not T.detach_evidence(root, ref, remove):
                raise errors.NotFound(
                    "그 근거가 이 티켓에 없어요",
                    remedy=f"asgard ticket evidence {ref} --list 명령으로 지금 매달린 것을 보세요",
                    detail={"ticket": ref, "stamp": remove},
                )
            return _emitted({"ticket": ref, "stamp": remove, "attached": False}, f"{remove} 근거를 뗐어요", json_out)
        if list_only:
            rows = T.list_evidence(root, ref)
            if json_out:
                print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
                return 0
            _show_evidence(rows)
            return 0
        row = T.attach_evidence(root, ref, stamp, scenario=scenario, note=note, actor="cli")
    except T.TicketError as exc:
        # 처방이 `_rejected`와 다르다: 여기서 틀릴 수 있는 값이 둘(티켓·실행 표식)이라,
        # 티켓 목록만 가리키면 표식을 잘못 친 사람은 볼 것이 없는 목록을 본다.
        raise errors.InvalidInput(
            str(exc),
            remedy="asgard k6 report로 기록된 실행을, asgard ticket list로 티켓을 확인하세요",
            detail={"ticket": ref, "stamp": stamp, "scenario": scenario},
        ) from exc
    if json_out:
        print(json.dumps(row, ensure_ascii=False, indent=2, default=str))
        return 0
    ui.ok(f"{ref} ⠶ {row['stamp']} · {_VERDICT_LABEL[row['verdict']]} · {_evidence_numbers(row)}")
    if row["verdict"] == "unjudged":
        ui.warn("이 실행은 임계값이 없어서 판정을 못 받았어요 — 통과가 아니라 미판정으로 적었어요.")
    return 0


_VERDICT_LABEL = {"pass": "통과", "fail": "실패", "unjudged": "미판정"}


def _evidence_numbers(row: dict) -> str:
    return f"p95 {row['p95_ms']:.1f}ms · 실패율 {row['failed_rate'] * 100:.2f}% · {row['rate_per_s']:.1f}건/s"


def _show_evidence(rows: list[dict]) -> None:
    """근거 목록 — 미판정을 통과와 같은 줄로 보이게 하면 이 계층이 막으려던 오독이 화면에 남는다."""
    if not rows:
        ui.step(ui.dim("매달린 부하 근거가 없어요 — `asgard ticket evidence <티켓>`으로 최근 실행을 매달아요."))
        return
    width = max(len(row["stamp"]) for row in rows)
    for row in rows:
        # 판정 이름은 `_pad`로 맞춘다 — '미판정'은 글자 3개지만 터미널에서 6칸을 먹는다
        verdict = _pad(_VERDICT_LABEL.get(row["verdict"], row["verdict"]), 6)
        tail = [row["runner"] or "—"]
        if not row["report_exists"]:
            tail.append("원본 없음 · 여기 적힌 수치가 남은 전부예요")
        if row["note"]:
            tail.append(row["note"])
        ui.step(f"  {_pad(row['stamp'], width)}  {verdict}  {_evidence_numbers(row)}" + ui.dim("  " + " · ".join(tail)))


def run_delete(ref: str, json_out: bool = False) -> int:
    errors.set_json_surface(json_out)
    ui.set_quiet(json_out)
    if not T.delete_ticket(_root(), ref):
        raise errors.NotFound(
            f"그런 티켓을 못 찾았어요: {ref}",
            remedy="asgard ticket list로 지금 있는 티켓을 보세요",
            detail={"ticket": ref},
        )
    return _emitted(
        {"ticket": ref, "deleted": True, "key_reused": False},
        f"{ref} 삭제 — 그 번호는 다시 발급되지 않아요",
        json_out,
    )


def run_cycle(name: str, close: str, json_out: bool, team: str = "") -> int:
    """주기는 팀 **하나**의 것이라 목록도 팀으로 갈린다 — 여기만 전체 보기가 기본이 아니다."""
    ui.set_quiet(json_out)
    root = _root()
    try:
        if close:
            cycle = T.close_cycle(root, close, team=team or None)
            return _emitted(cycle, f"주기 {cycle['number']} 닫음", json_out)
            return 0
        if name:
            cycle = T.create_cycle(root, name, team=team or None)
            return _emitted(cycle, f"주기 {cycle['number']} · {cycle['name']}", json_out)
            return 0
        rows = T.list_cycles(root, team=team or None)
    except (T.TicketError, T.StoreError) as exc:
        ui.fail(str(exc))
        return 2
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        ui.step(ui.dim('아직 주기가 없어요 — `asgard ticket cycle --new "7월 5주"`'))
        return 0
    for cycle in rows:
        state = "닫힘" if cycle["closed_at"] else "열림"
        ui.step(f"  {cycle['number']:>3}  {cycle['name']}  {cycle['done']}/{cycle['total']}  {ui.dim(state)}")
    return 0


# ── 팀 · 프로젝트 · 트리아지 — 워크스페이스 층 ─────────────────────────────────
#
# 티켓 위의 두 축이다. 팀은 번호의 주인이고(워크플로·사이클·트리아지가 팀마다 다르다),
# 프로젝트는 팀을 가로지르는 약속이다(끝이 있고, 리드가 있고, 목표일이 있다).

_ERRORS = (T.TicketError, TM.TeamError, P.ProjectError, T.StoreError)


def _fail(exc: Exception) -> int:
    ui.fail(str(exc))
    return 2


def _day(value: float | str | None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(float(value))) if value else "—"


def run_teams(new: str, key: str, triage: str, cycle_weeks: int, json_out: bool) -> int:
    """팀 목록 — 또는 `--new`로 하나 세우기."""
    ui.set_quiet(json_out)
    try:
        if new:
            fields = {}
            if triage:
                fields["triage"] = triage == "on"
            if cycle_weeks:
                fields["cycle_weeks"] = cycle_weeks
            team = TM.create_team(new, key, **fields)
            return _emitted(team, f"팀 {team['key']} · {team['name']} — 첫 티켓은 {team['key']}-1이 돼요", json_out)
            return 0
        rows = TM.list_teams()
    except _ERRORS as exc:
        return _fail(exc)
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        ui.step(ui.dim("아직 팀이 없어요 — 첫 티켓을 발급하면 이 폴더 이름으로 하나 생겨요."))
        return 0
    for row in rows:
        marks = []
        if row["triage"]:
            marks.append(f"트리아지 {row['triaging']}")
        if row["cycle_weeks"]:
            marks.append(f"{row['cycle_weeks']}주 주기")
        tail = ui.dim("  " + " · ".join(marks)) if marks else ""
        ui.step(f"  {row['key']:<6} {row['name']:<24} 티켓 {row['tickets']:>4}{tail}")
        for root in row["roots"]:
            ui.step(ui.dim(f"         ↳ {root}"))
    return 0


def run_projects(new: str, show: str, status: str, lead: str, target: str, teams: str, json_out: bool) -> int:
    """프로젝트 목록 · 상세 · 생성."""
    ui.set_quiet(json_out)
    try:
        if new:
            fields: dict = {"lead": lead} if lead else {}
            if teams:
                fields["teams"] = [x.strip() for x in teams.split(",") if x.strip()]
            if target:
                fields["target_at"] = time.mktime(time.strptime(target, "%Y-%m-%d"))
            project = P.create_project(new, **fields)
            return _emitted(
                project,
                f"프로젝트 · {project['name']} — 팀 {', '.join(t['key'] for t in project['teams']) or '없음'}",
                json_out,
            )
            return 0
        if show:
            return _show_project(P.get_project(show), json_out)
        rows = P.list_projects(status=status)
    except _ERRORS as exc:
        return _fail(exc)
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        ui.step(ui.dim('아직 프로젝트가 없어요 — `asgard ticket project --new "결제 개편"`'))
        return 0
    for row in rows:
        bar = f"{row['done']}/{row['total']}"
        health = f" · {row['health']}" if row["health"] else ""
        ui.step(f"  {row['name']:<28} {row['status']:<10} {bar:>7}  목표 {_day(row['target_at'])}{ui.dim(health)}")
    return 0


def _show_project(project: dict, json_out: bool) -> int:
    if json_out:
        print(json.dumps(project, ensure_ascii=False, indent=2))
        return 0
    ui.head(f"{project['name']} · {project['status']}")
    ui.step(f"  리드 {project['lead'] or '—'} · 팀 {', '.join(t['key'] for t in project['teams']) or '—'}")
    ui.step(f"  시작 {_day(project['starts_at'])} · 목표 {_day(project['target_at'])}")
    ui.step(f"  진척 {project['done']}/{project['total']} ({int(project['progress'] * 100)}%)")
    if project["health"]:
        ui.step(f"  건강도 {project['health']}")
    if project["milestones"]:
        ui.phase("마일스톤")
        for stone in project["milestones"]:
            done = "완료" if stone["completed_at"] else f"{stone['done']}/{stone['total']}"
            ui.step(f"  {stone['name']:<24} {done:>8}  목표 {_day(stone['target_at'])}")
    if project["updates"]:
        ui.phase("최근 보고")
        for note in project["updates"][:3]:
            ui.step(f"  {_day(note['created_at'])}  [{note['health'] or '—'}] {note['body'][:80]}")
    return 0


def run_milestone(project: str, name: str, target: str, done: str, json_out: bool) -> int:
    ui.set_quiet(json_out)
    try:
        if done:
            stone = P.complete_milestone(project, done)
            return _emitted(stone, f"마일스톤 완료 — {stone['name']}", json_out)
            return 0
        if name:
            when = time.mktime(time.strptime(target, "%Y-%m-%d")) if target else None
            stone = P.add_milestone(project, name, when)
            return _emitted(stone, f"마일스톤 · {stone['name']}", json_out)
            return 0
        rows = P.list_milestones(project)
    except _ERRORS as exc:
        return _fail(exc)
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for row in rows:
        ui.step(f"  {row['name']:<24} {row['done']}/{row['total']}  목표 {_day(row['target_at'])}")
    return 0


def run_update(project: str, body: str, health: str, json_out: bool) -> int:
    """프로젝트 진행 보고 한 줄 — 건강도를 같이 주면 계기판도 따라 움직인다."""
    ui.set_quiet(json_out)
    try:
        if body:
            note = P.add_update(project, body, health, author="cli")
            return _emitted(note, f"보고 남김 — [{note['health'] or '—'}] {note['body'][:60]}", json_out)
            return 0
        rows = P.list_updates(project)
    except _ERRORS as exc:
        return _fail(exc)
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for row in rows:
        ui.step(f"  {_day(row['created_at'])}  [{row['health'] or '—'}] {row['body'][:90]}")
    return 0


def run_triage(accept: str, decline: str, note: str, json_out: bool) -> int:
    """팀의 인박스 — 아직 받아들이지 않은 일감."""
    ui.set_quiet(json_out)
    root = _root()
    try:
        if accept:
            ticket = T.triage_accept(root, accept, actor="cli", note=note)
            return _emitted(ticket, f"{ticket['key']} 받음 — {ticket['status_label']}", json_out)
            return 0
        if decline:
            ticket = T.triage_decline(root, decline, actor="cli", note=note)
            return _emitted(ticket, f"{ticket['key']} 거절 — 취소로 닫았어요", json_out)
            return 0
        rows = T.triage_queue(root)
    except _ERRORS as exc:
        return _fail(exc)
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        ui.step(ui.dim("인박스가 비어 있어요."))
        return 0
    ui.head(f"트리아지 {len(rows)}건 — `--accept KEY`로 받고, `--decline KEY`로 거절해요")
    width = max(len(t["key"]) for t in rows)
    for ticket in rows:
        ui.step(_line(ticket, width))
    return 0


def run_import(json_out: bool) -> int:
    """폴더마다 보드가 하나이던 시절의 저장소를 워크스페이스로 들여온다 — 원본은 안 건드린다."""
    ui.set_quiet(json_out)
    root = _root()
    try:
        out = L.import_root(root)
    except _ERRORS as exc:
        return _fail(exc)
    if json_out:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if not out["imported"]:
        ui.step(ui.dim(f"들여올 게 없어요 — {out['reason']}"))
        return 0
    ui.ok(f"{out['tickets']}건을 들여왔어요 — 팀 {out['team']} (댓글 {out['comments']} · 라벨 {out['labels']})")
    if out.get("renamed"):
        ui.warn(f"접두어가 이미 쓰이고 있어서 바꿨어요 — {out['was']} → {out['team']}")
    ui.step(ui.dim(f"원본은 그대로 있어요 — {out['source']}"))
    return 0


def run_doc(
    new: str, show: str, edit: str, body_from: str, delete: str, project: str, team: str, json_out: bool
) -> int:
    """문서 — 목록·신설·읽기·본문 교체·삭제.

    본문은 셸 인자로 안 받는다(`--edit REF [--body 파일|-]`, 기본은 표준입력). 마크다운 한
    편을 인자에 담으면 따옴표와 줄바꿈이 셸마다 다르게 깨지고, 그 사고는 **저장된 뒤에**
    발견된다."""
    from ..studio import documents as DOC

    ui.set_quiet(json_out)
    try:
        if new:
            doc = DOC.create_document(new, author=_actor(), project=project or None, team=team or None)
            return _emitted(doc, f"{doc['title']} 문서를 열었어요 — `--edit`로 본문을 채워요", json_out)
        if delete:
            removed = DOC.delete_document(delete)
            return _emitted({"deleted": removed}, "지웠어요" if removed else "그런 문서가 없어요", json_out)
        if edit:
            doc = DOC.update_document(edit, {"body": _read_body(body_from or "-")}, actor=_actor())
            return _emitted(doc, f"{doc['title']} 본문을 다시 썼어요 ({doc['words']}단어)", json_out)
        if show:
            doc = DOC.get_document(show)
            if json_out:
                print(json.dumps(doc, ensure_ascii=False, indent=2))
                return 0
            ui.head(f"{doc['title']}{' · ' + doc['project']['name'] if doc['project'] else ''}")
            print(doc["body"] or "")
            return 0
        rows = DOC.list_documents(project=project or None, team=team or None)
    except _ERRORS as exc:
        return _fail(exc)
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        ui.step(ui.dim('문서가 없어요 — `asgard ticket doc --new "제목"`으로 시작해요.'))
        return 0
    ui.head(f"문서 {len(rows)}편")
    width = max(len(row["title"]) for row in rows)
    for row in rows:
        where = row["project"]["name"] if row["project"] else (row["team"]["key"] if row["team"] else "")
        ui.step(f"{_pad(row['title'], width)}  {ui.dim(where or '워크스페이스')}  {ui.dim(row['excerpt'])}")
    return 0


def _actor() -> str:
    """이 손이 누구인가 — 활성 에이전트 이름. 기본 프로파일이면 사람(오딘)이 적은 것으로 본다."""
    from ..profiles import active

    name = active()
    return "" if name in ("", "default") else name


def _read_body(source: str) -> str:
    """`-`면 표준입력, 아니면 파일. 편집기 파이프(`asgard … --edit -`)가 기본 사용법이다."""
    import sys

    if source == "-":
        return sys.stdin.read()
    with open(source, encoding="utf-8") as handle:
        return handle.read()


def run_doctor(recover: bool, json_out: bool) -> int:
    """저장소가 열리는지 보고, 사람이 시키면 못 여는 파일을 치운다.

    판정과 수리를 한 명령 안에 두되 **기본은 판정**이다. `--recover` 없이 부르면 아무것도
    안 옮긴다: 진단이 곧 수리이면, 무엇이 잘못됐는지 읽어 보려던 사람이 파일을 갈아 버린다."""
    from ..studio import db as D

    ui.set_quiet(json_out)
    found = D.probe()
    if recover:
        if found["ok"]:
            found = {**found, "recovered": False, "reason": "저장소가 정상이라 치우지 않았어요"}
        else:
            try:
                moved = D.quarantine()
            except _ERRORS as exc:
                return _fail(exc)
            found = {**D.probe(), "recovered": True, "moved_to": moved}
    # 종료 코드는 **판정**이 정한다 — 출력 형식이 아니라. `--json`을 붙였다고 못 여는 저장소가
    # 0으로 나가면, 이 명령을 문에 세운 스크립트는 고장을 통과로 읽는다.
    code = 0 if found["ok"] else 1
    if json_out:
        print(json.dumps(found, ensure_ascii=False, indent=2))
        return code
    if found.get("recovered"):
        ui.ok("새 워크스페이스를 세웠어요")
        ui.step(ui.dim(f"못 읽던 파일은 지우지 않고 옮겨 뒀어요 — {found['moved_to']}"))
        ui.step(ui.dim("옛 폴더 보드가 남아 있으면 `asgard ticket import`로 번호째 들여올 수 있어요."))
        return 0
    if found["ok"]:
        where = found["path"]
        ui.ok(
            "워크스페이스가 정상이에요"
            if found["exists"]
            else "아직 워크스페이스가 없어요 — 첫 티켓을 발급하면 그때 생겨요"
        )
        ui.step(ui.dim(where))
        if found.get("reason"):
            ui.step(ui.dim(found["reason"]))
        return 0
    ui.warn(f"워크스페이스를 못 열어요 — {found['message']}")
    ui.step(ui.dim(found["path"]))
    if found["recoverable"]:
        ui.step("치우고 새로 시작하려면 `asgard ticket doctor --recover` — 지우지 않고 옆에 둬요.")
    else:
        ui.step("이 파일은 데이터베이스로는 읽혀요. 치우지 말고 Asgard를 최신판으로 올린 뒤 여세요.")
    return 1
