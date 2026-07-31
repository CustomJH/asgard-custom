"""`asgard ticket` — 창을 안 열고 일감을 만지는 손.

같은 워크스페이스를 스튜디오 창·에이전트 툴·이 명령이 함께 본다
(`<에이전트 홈>/studio/workspace.db`). 그래서 여기서 옮긴 칸은 창을 새로 고치면 그 자리에
있고, 에이전트가 스스로 끊은 번호는 `asgard ticket list` 에 그대로 뜬다.

**어디서 부르든 워크스페이스 전체를 본다.** 일감은 폴더의 것이 아니라 사람의 것이라, 같은
명령이 선 자리에 따라 다른 답을 내면 안 된다. 좁히고 싶으면 `--team <키>` 로 고르고,
`--team .` 은 이 폴더에 결속된 팀만 본다.

터미널이라 우선순위는 색이 아니라 **기호**로 말한다(`!!! !! ! ·`): 파이프로 넘기거나 로그에
붙여도 뜻이 남아야 한다.
"""

from __future__ import annotations

import json
import os
import time

from .. import ui
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
}
_STATUS_WIDTH = 8  # 표시 폭 — '진행 중'은 글자 3개지만 터미널에서 7칸을 먹는다


def _root() -> str:
    return _project_root(os.getcwd())


def _mark(ticket: dict) -> str:
    return _PRIORITY_MARK.get(int(ticket.get("priority") or 0), " ").rjust(3)


def _pad(text: str, cols: int) -> str:
    """터미널 칸 수로 맞춘다. `str.ljust` 는 **글자 수**로 세니 한글이 섞이면 줄이 어긋난다."""
    return text + " " * max(0, cols - ui.disp_width(text))


def _line(ticket: dict, width: int = 0) -> str:
    key = ticket["key"].ljust(width or len(ticket["key"]))
    # 팀이 지은 상태 이름이 있으면 그것을 든다 — 기본 여섯 칸의 이름표로만 읽으면
    # 팀이 만든 '배포 대기' 가 화면에서 KeyError 로 죽는다.
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


def _emit(rows: list[dict], json_out: bool) -> None:
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        ui.step(ui.dim("조건에 맞는 티켓이 없습니다."))
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
        ui.step(ui.dim('아직 티켓이 없습니다 — `asgard ticket new "할 일"` 로 첫 건을 남기세요.'))
        if not summary.get("team"):
            ui.step(ui.dim(f"  첫 티켓은 {summary['prefix']}-1 이 되고, 그때 팀이 하나 섭니다."))
        ui.step(ui.dim("  일감은 워크스페이스에 삽니다 — 팀이 번호의 주인이고, 프로젝트는 팀을 가로지릅니다."))
        ui.step(ui.dim("  보이는 것은 늘 전체입니다 — `--team <키>` 로 좁히고, `--team .` 은 이 폴더의 팀입니다."))
        if L.pending_roots([root]):
            ui.warn("이 폴더에 예전 방식의 보드가 남아 있습니다 — `asgard ticket import` 로 그대로 들여옵니다.")
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


def run_comment(ref: str, text: str, author: str) -> int:
    try:
        note = T.add_comment(_root(), ref, text, author=author or "cli")
    except (T.TicketError, T.StoreError) as exc:
        ui.fail(str(exc))
        return 2
    ui.ok(f"{note['ticket']}에 댓글을 남겼습니다")
    return 0


def run_link(ref: str, other: str, kind: str, remove: bool) -> int:
    try:
        if remove:
            if not T.unlink_tickets(_root(), ref, kind, other):
                ui.fail("그런 관계가 없습니다")
                return 2
            ui.ok(f"{ref} ⇸ {other} ({kind}) 해제")
            return 0
        ticket = T.link_tickets(_root(), ref, kind, other, actor="cli")
    except (T.TicketError, T.StoreError) as exc:
        ui.fail(str(exc))
        return 2
    ui.ok(f"{ticket['key']} → {other} ({kind})")
    return 0


def run_delete(ref: str) -> int:
    if not T.delete_ticket(_root(), ref):
        ui.fail(f"티켓을 찾을 수 없습니다: {ref}")
        return 2
    ui.ok(f"{ref} 삭제 — 번호는 다시 발급되지 않습니다")
    return 0


def run_cycle(name: str, close: str, json_out: bool, team: str = "") -> int:
    """주기는 팀 **하나**의 것이라 목록도 팀으로 갈린다 — 여기만 전체 보기가 기본이 아니다."""
    ui.set_quiet(json_out)
    root = _root()
    try:
        if close:
            cycle = T.close_cycle(root, close, team=team or None)
            ui.ok(f"주기 {cycle['number']} 닫음")
            return 0
        if name:
            cycle = T.create_cycle(root, name, team=team or None)
            ui.ok(f"주기 {cycle['number']} · {cycle['name']}")
            return 0
        rows = T.list_cycles(root, team=team or None)
    except (T.TicketError, T.StoreError) as exc:
        ui.fail(str(exc))
        return 2
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        ui.step(ui.dim('주기가 없습니다 — `asgard ticket cycle --new "7월 5주"`'))
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
    """팀 목록 — 또는 `--new` 로 하나 세우기."""
    ui.set_quiet(json_out)
    try:
        if new:
            fields = {}
            if triage:
                fields["triage"] = triage == "on"
            if cycle_weeks:
                fields["cycle_weeks"] = cycle_weeks
            team = TM.create_team(new, key, **fields)
            ui.ok(f"팀 {team['key']} · {team['name']} — 첫 티켓은 {team['key']}-1 이 됩니다")
            return 0
        rows = TM.list_teams()
    except _ERRORS as exc:
        return _fail(exc)
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        ui.step(ui.dim("팀이 없습니다 — 첫 티켓을 끊으면 이 폴더 이름으로 하나 섭니다."))
        return 0
    for row in rows:
        marks = []
        if row["triage"]:
            marks.append(f"트리아지 {row['triaging']}")
        if row["cycle_weeks"]:
            marks.append(f"{row['cycle_weeks']}주 사이클")
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
            ui.ok(f"프로젝트 · {project['name']} — 팀 {', '.join(t['key'] for t in project['teams']) or '없음'}")
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
        ui.step(ui.dim('프로젝트가 없습니다 — `asgard ticket project --new "결제 개편"`'))
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
            ui.ok(f"마일스톤 완료 — {stone['name']}")
            return 0
        if name:
            when = time.mktime(time.strptime(target, "%Y-%m-%d")) if target else None
            stone = P.add_milestone(project, name, when)
            ui.ok(f"마일스톤 · {stone['name']}")
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
            ui.ok(f"보고 남김 — [{note['health'] or '—'}] {note['body'][:60]}")
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
            ui.ok(f"{ticket['key']} 받음 — {ticket['status_label']}")
            return 0
        if decline:
            ticket = T.triage_decline(root, decline, actor="cli", note=note)
            ui.ok(f"{ticket['key']} 거절 — 취소로 닫았습니다")
            return 0
        rows = T.triage_queue(root)
    except _ERRORS as exc:
        return _fail(exc)
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        ui.step(ui.dim("인박스가 비었습니다."))
        return 0
    ui.head(f"트리아지 {len(rows)}건 — 받거나(`--accept KEY`) 거절합니다(`--decline KEY`)")
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
        ui.step(ui.dim(f"들여올 것이 없습니다 — {out['reason']}"))
        return 0
    ui.ok(f"팀 {out['team']} 으로 {out['tickets']}건 반입 (댓글 {out['comments']} · 라벨 {out['labels']})")
    if out.get("renamed"):
        ui.warn(f"접두어 {out['was']} 가 이미 쓰이고 있어 {out['team']} 로 비켰습니다")
    ui.step(ui.dim(f"원본은 그대로 있습니다 — {out['source']}"))
    return 0
