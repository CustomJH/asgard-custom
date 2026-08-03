"""문서 — 티켓 옆에 사는 자유 마크다운.

**왜 티켓으로 대신할 수 없는가.** 티켓은 닫히는 것이다: 상태·담당·번호를 지고 다니고,
끝나면 완료 칸으로 가서 열린 건수에서 빠진다. 사양·회고·결정 기록·회의 메모는 닫히지
않는다 — 고쳐 쓰인다. 그걸 백로그에 섞으면 "열린 건 12"가 곧 거짓말이 되고, 사람은
목록을 안 믿게 된다. Linear가 이슈와 문서를 가르는 이유가 그거다.

**매다는 자리는 비어 있어도 된다.** 프로젝트·팀 둘 다 안 걸면 워크스페이스 문서다.
글은 대개 프로젝트보다 먼저 시작한다 — 무엇을 할지 적어 보고 나서 프로젝트가 생긴다.
자리를 반드시 고르게 하면, 그 글은 안 적히거나 엉뚱한 프로젝트에 걸린다.

**프로젝트를 지워도 문서는 남는다**(`ON DELETE SET NULL`). 프로젝트에서 푸는 것과 글을
잃는 것은 다른 일이다 — 티켓이 같은 계약을 지는 것과 같은 판정이다([[projects]]).

**목록은 본문을 안 준다.** 문서는 길다(2만 자까지). 목록마다 본문을 통째로 넣으면
스무 개짜리 서랍이 곧 화면 지연이 된다. 대신 첫 줄을 발췌로 든다 — 목록에서 필요한 것은
"이게 무슨 글인가"이지 글 자체가 아니다.
"""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Any
from uuid import uuid4

from .. import errors
from .db import StoreError, exists, reading, writing
from .projects import find_project
from .teams import find_team

__all__ = [
    "DocumentError",
    "DocumentNotFound",
    "StoreError",
    "archive_document",
    "create_document",
    "delete_document",
    "find_document",
    "get_document",
    "list_documents",
    "resolve_document",
    "update_document",
]

_MAX_TITLE = 200
_MAX_BODY = 200_000  # 티켓 설명(2만)보다 넉넉하다 — 사양 한 편이 여기 들어와야 한다
_MAX_NAME = 60
_EXCERPT = 180
_ID = re.compile(r"^[0-9a-f]{32}$")
# 고칠 수 있는 칸. 여기 없는 이름은 조용히 무시되지 않고 거절된다 — 오타 한 글자가
# "저장했는데 안 바뀐다"로 나타나는 것이 가장 나쁜 실패다.
_EDITABLE = ("title", "body", "icon", "project", "team")


class DocumentError(errors.InvalidInput, ValueError):
    """문서 어휘를 어겼다 — 호출자가 고칠 수 있는 잘못이다."""

    code = "invalid_document"


class DocumentNotFound(errors.NotFound, ValueError):
    """그런 문서가 없다.

    어휘 위반(400)과 가르는 이유는 **처방이 달라서**다. 빈 제목은 고쳐 다시 보내면 되고,
    없는 문서는 아무리 고쳐 보내도 없다 — 목록으로 돌아가는 것이 답이다. 한 코드로 접으면
    창은 둘 다 '입력이 잘못됐어요'로 그린다."""

    code = "document_not_found"


def _now() -> float:
    return time.time()


def _text(value: Any, field: str, limit: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise DocumentError(f"{field} must be text")
    value = value.strip() if field != "body" else value.rstrip()
    if required and not value:
        raise DocumentError(f"{field} is required")
    if len(value) > limit:
        raise DocumentError(f"{field} must be at most {limit} characters")
    return value


def excerpt(body: str) -> str:
    """목록 한 줄에 넣을 발췌 — 마크다운 장식은 지우고 첫 문단만.

    `#`·`>`·목록 기호를 그대로 두면 목록이 기호로 시작하는 줄들의 벽이 된다. 여기서
    거는 것은 표시용 손질이지 저장 내용이 아니다 — 원문은 `body`에 그대로 있다."""
    for line in body.splitlines():
        stripped = re.sub(r"^\s*(#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)", "", line).strip()
        stripped = re.sub(r"[*_`~]", "", stripped)
        if stripped:
            return stripped[:_EXCERPT]
    return ""


def _row(conn: sqlite3.Connection, row: sqlite3.Row, *, deep: bool = False) -> dict[str, Any]:
    """한 문서의 모양. `deep`이면 본문까지 — 목록은 발췌만 든다."""
    project = None
    if row["project_id"]:
        found = conn.execute("SELECT id, name, icon FROM projects WHERE id = ?", (row["project_id"],)).fetchone()
        if found:
            project = {"id": str(found["id"]), "name": str(found["name"]), "icon": str(found["icon"] or "")}
    team = None
    if row["team_id"]:
        found = conn.execute("SELECT id, key, name FROM teams WHERE id = ?", (row["team_id"],)).fetchone()
        if found:
            team = {"id": str(found["id"]), "key": str(found["key"]), "name": str(found["name"])}
    body = str(row["body"] or "")
    out: dict[str, Any] = {
        "id": str(row["id"]),
        "title": str(row["title"]),
        "icon": str(row["icon"] or ""),
        "excerpt": excerpt(body),
        "words": len(body.split()),
        "author": str(row["author"] or ""),
        "project": project,
        "team": team,
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "archived": row["archived_at"] is not None,
    }
    if deep:
        out["body"] = body
    return out


def _scope(conn: sqlite3.Connection, fields: dict[str, Any]) -> tuple[str | None, str | None]:
    """어디에 매달 것인가 — 프로젝트·팀 각각 없으면 None(워크스페이스 문서)."""
    project_id = None
    if fields.get("project"):
        found = find_project(conn, fields["project"])
        if found is None:
            raise DocumentError(f"project not found: {fields['project']}")
        project_id = str(found["id"])
    team_id = None
    if fields.get("team"):
        found = find_team(conn, fields["team"])
        if found is None:
            raise DocumentError(f"team not found: {fields['team']}")
        team_id = str(found["id"])
    return project_id, team_id


def create_document(title: str, body: str = "", author: str = "", **fields: Any) -> dict[str, Any]:
    """문서 하나를 연다. 제목만 있으면 된다 — 빈 문서로 시작하는 것이 정상이다."""
    title = _text(title, "document title", _MAX_TITLE, required=True)
    body = _text(body, "body", _MAX_BODY)
    now = _now()
    doc_id = uuid4().hex
    with writing() as conn:
        project_id, team_id = _scope(conn, fields)
        conn.execute(
            "INSERT INTO documents(id, title, body, icon, team_id, project_id, author, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                doc_id,
                title,
                body,
                _text(fields.get("icon"), "icon", 8),
                team_id,
                project_id,
                _text(author, "author", _MAX_NAME),
                now,
                now,
            ),
        )
        return _row(conn, conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone(), deep=True)


def find_document(conn: sqlite3.Connection, ref: Any) -> sqlite3.Row | None:
    if not isinstance(ref, str):
        return None
    ref = ref.strip()
    if not ref:
        return None
    if _ID.fullmatch(ref):
        found = conn.execute("SELECT * FROM documents WHERE id = ?", (ref,)).fetchone()
        if found:
            return found
    # 제목으로도 찾는다 — 사람이 대화에서 부르는 이름이 그것이라서. 같은 제목이 둘이면
    # 최근에 고친 것을 준다(오래된 사본을 덮어쓰는 쪽이 더 나쁜 실패다).
    return conn.execute(
        "SELECT * FROM documents WHERE title = ? COLLATE NOCASE ORDER BY updated_at DESC LIMIT 1", (ref,)
    ).fetchone()


def resolve_document(conn: sqlite3.Connection, ref: Any) -> sqlite3.Row:
    row = find_document(conn, ref)
    if row is None:
        raise DocumentNotFound(f"document not found: {ref}")
    return row


def get_document(ref: Any) -> dict[str, Any]:
    with reading() as conn:
        return _row(conn, resolve_document(conn, ref), deep=True)


def list_documents(
    project: Any = None,
    team: Any = None,
    query: str = "",
    include_archived: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """최근에 고친 순. 읽기는 자리를 만들지 않는다 — 아직 워크스페이스가 없으면 빈 목록."""
    if not exists():
        return []
    with reading() as conn:
        clauses, values = [], []
        if not include_archived:
            clauses.append("archived_at IS NULL")
        if project:
            found = find_project(conn, project)
            if found is None:
                return []
            clauses.append("project_id = ?")
            values.append(str(found["id"]))
        if team:
            found = find_team(conn, team)
            if found is None:
                return []
            clauses.append("team_id = ?")
            values.append(str(found["id"]))
        text = _text(query, "query", _MAX_TITLE)
        if text:
            clauses.append("(title LIKE ? OR body LIKE ?)")
            values += [f"%{text}%"] * 2
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM documents {where} ORDER BY updated_at DESC LIMIT ?",
            (*values, max(1, min(int(limit), 1000))),
        )
        return [_row(conn, row) for row in rows]


def update_document(ref: Any, changes: dict[str, Any], actor: str = "") -> dict[str, Any]:
    """이름 있는 칸만 고친다. 모르는 칸은 **거절한다** — 조용히 무시하면 오타가 유실이 된다."""
    if not isinstance(changes, dict):
        raise DocumentError("changes must be an object")
    unknown = [key for key in changes if key not in _EDITABLE]
    if unknown:
        raise DocumentError(f"unknown field: {', '.join(sorted(unknown))}")
    with writing() as conn:
        row = resolve_document(conn, ref)
        sets: list[str] = []
        values: list[Any] = []
        if "title" in changes:
            sets.append("title = ?")
            values.append(_text(changes["title"], "document title", _MAX_TITLE, required=True))
        if "body" in changes:
            sets.append("body = ?")
            values.append(_text(changes["body"], "body", _MAX_BODY))
        if "icon" in changes:
            sets.append("icon = ?")
            values.append(_text(changes["icon"], "icon", 8))
        if "project" in changes:
            sets.append("project_id = ?")
            values.append(_scope(conn, {"project": changes["project"]})[0])
        if "team" in changes:
            sets.append("team_id = ?")
            values.append(_scope(conn, {"team": changes["team"]})[1])
        if sets:
            # 고쳐 쓴 시각은 목록의 정렬 축이다 — 안 올리면 방금 고친 글이 맨 아래 남는다.
            sets.append("updated_at = ?")
            values.append(_now())
            if actor:
                sets.append("author = ?")
                values.append(_text(actor, "author", _MAX_NAME))
            conn.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id = ?", (*values, row["id"]))
        return _row(conn, conn.execute("SELECT * FROM documents WHERE id = ?", (row["id"],)).fetchone(), deep=True)


def archive_document(ref: Any, archived: bool = True) -> dict[str, Any]:
    """치워 두기 — 목록에서 빠지되 남는다. 지우기와 다른 자리다."""
    with writing() as conn:
        row = resolve_document(conn, ref)
        conn.execute(
            "UPDATE documents SET archived_at = ?, updated_at = ? WHERE id = ?",
            (_now() if archived else None, _now(), row["id"]),
        )
        return _row(conn, conn.execute("SELECT * FROM documents WHERE id = ?", (row["id"],)).fetchone(), deep=True)


def delete_document(ref: Any) -> bool:
    with writing() as conn:
        row = find_document(conn, ref)
        if row is None:
            return False
        conn.execute("DELETE FROM documents WHERE id = ?", (row["id"],))
        return True
