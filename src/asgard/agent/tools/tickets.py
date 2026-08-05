"""도구 — 티켓. 에이전트가 스스로 일감을 발급하고 옮긴다."""

from __future__ import annotations

from ._core import ToolError


def _ticket_line(ticket: dict) -> str:
    from ...studio import tickets as T

    # 팀이 지은 상태 이름이 있으면 그것을 쓴다 — 기본 여섯 칸만 아는 표로 읽으면
    # 팀이 만든 '배포 대기'에서 KeyError로 죽는다.
    label = ticket.get("status_label") or T.STATUS_LABEL.get(ticket["status"], ticket["status"])
    bits = [f"{ticket['key']} [{label}]", ticket["title"]]
    if ticket.get("triage"):
        bits.append("트리아지 대기")
    if ticket["priority"]:
        bits.append(f"우선순위 {T.PRIORITY_LABEL[ticket['priority']]}")
    if ticket["assignee"]:
        bits.append(f"담당 {ticket['assignee']}")
    if ticket.get("project"):
        bits.append(f"프로젝트 {ticket['project']['name']}")
    if ticket["labels"]:
        bits.append("라벨 " + "/".join(label["name"] for label in ticket["labels"]))
    if ticket["blocked_by"]:
        bits.append("막힘 ← " + ", ".join(ticket["blocked_by"]))
    return " · ".join(bits)


def run_ticket(root: str, tool_input: dict) -> str:
    """일감 한 건을 읽거나 남긴다 — 사람이 스튜디오에서 보는 그 보드.

    툴이 하는 말은 **번호를 포함한 한 줄**이다. 모델이 다음 턴에 그 번호로 다시 부를 수 있어야
    이 계층이 쓸모가 있다 — "티켓을 만들었습니다"만 돌려주면 그 티켓은 만든 순간 잃어버린다."""
    from ...studio import tickets as T

    action = str(tool_input.get("action") or "").strip()
    ref = str(tool_input.get("ref") or "").strip()
    actor = "agent"
    try:
        if action == "list":
            rows = T.list_tickets(
                root,
                query=str(tool_input.get("query") or ""),
                open_only=bool(tool_input.get("open_only")),
                team=str(tool_input.get("team") or "") or None,
                project=str(tool_input.get("project") or "") or None,
                limit=60,
            )
            if not rows:
                return "no tickets match"
            rows.sort(key=T.sort_key)
            return "\n".join(_ticket_line(row) for row in rows)
        if action == "projects":
            from ...studio import projects as P

            rows = P.list_projects(status="open")
            if not rows:
                return "no open projects"
            return "\n".join(
                f"{row['name']} [{row['status']}] · 진척 {row['done']}/{row['total']}"
                + (f" · 팀 {', '.join(t['key'] for t in row['teams'])}" if row["teams"] else "")
                + (f" · 리드 {row['lead']}" if row["lead"] else "")
                for row in rows
            )
        if action == "get":
            ticket = T.get_ticket(root, ref)
            lines = [_ticket_line(ticket)]
            if ticket["body"]:
                lines += ["", ticket["body"]]
            for child in ticket["children_list"]:
                lines.append("  하위 " + _ticket_line(child))
            for note in ticket["comments_list"][-6:]:
                lines.append(f"  댓글 {note['author'] or '익명'}: {note['body'][:200]}")
            return "\n".join(lines)
        if action == "create":
            ticket = T.create_ticket(
                root,
                str(tool_input.get("title") or ""),
                body=str(tool_input.get("body") or ""),
                status=str(tool_input.get("status") or "todo"),
                priority=tool_input.get("priority") or 0,
                assignee=str(tool_input.get("assignee") or ""),
                estimate=tool_input.get("estimate"),
                labels=tool_input.get("labels") or (),
                parent=str(tool_input.get("parent") or "") or None,
                team=str(tool_input.get("team") or "") or None,
                project=str(tool_input.get("project") or "") or None,
                milestone=str(tool_input.get("milestone") or "") or None,
                source="agent",
                reporter=actor,
                actor=actor,
            )
            # 팀이 트리아지를 켜 뒀으면 이 티켓은 보드가 아니라 인박스에 선다. 그 사실을
            # 모델에게 돌려줘야 "만들었으니 됐다"로 끝내지 않고 사람에게 알린다.
            if ticket.get("triage"):
                return f"filed {_ticket_line(ticket)} — 팀 인박스(트리아지)에 세웠습니다. 사람이 받아야 보드로 갑니다."
            return f"filed {_ticket_line(ticket)}"
        # start·finish는 update의 지름길이다. 상태 슬러그를 외우게 하는 대신 **동작**을 준다:
        # 시작하면 진행 중으로 가고 담당이 붙고, 끝내면 검토 중으로 간다(완료가 아니다 —
        # 프로세스가 끝난 것과 사람이 받아들인 것은 다른 일이다).
        if action in ("start", "finish"):
            target = "in_progress" if action == "start" else "in_review"
            changes: dict = {"status": target}
            if action == "start" and not str(tool_input.get("assignee") or ""):
                changes["assignee"] = actor
            ticket = T.update_ticket(root, ref, changes, actor=actor)
            note = str(tool_input.get("text") or "")
            if note:
                T.add_comment(root, ref, note, author=actor)
            return f"{'started' if action == 'start' else 'ready for review'} {_ticket_line(ticket)}"
        if action == "update":
            changes = {
                key: tool_input[key]
                for key in (
                    "title",
                    "body",
                    "status",
                    "priority",
                    "assignee",
                    "estimate",
                    "labels",
                    "parent",
                    "team",
                    "project",
                    "milestone",
                )
                if key in tool_input
            }
            if not changes:
                raise ToolError("update needs at least one field to change")
            return f"updated {_ticket_line(T.update_ticket(root, ref, changes, actor=actor))}"
        if action == "comment":
            T.add_comment(root, ref, str(tool_input.get("text") or ""), author=actor)
            return f"commented on {ref}"
        if action == "link":
            kind = str(tool_input.get("kind") or "blocks")
            other = str(tool_input.get("other") or "")
            return f"linked {_ticket_line(T.link_tickets(root, ref, kind, other, actor=actor))}"
    except T.TicketError as exc:
        raise ToolError(str(exc)) from exc
    except T.StoreError as exc:
        raise ToolError(f"the studio ticket store is unavailable: {exc}") from exc
    raise ToolError(f"unknown ticket action: {action}")
