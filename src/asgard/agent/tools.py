"""네이티브 루프 툴셋 — Anthropic-defined bash + text_editor 계약 구현.

Anthropic-defined 툴(스키마리스)을 쓰는 이유: 모델이 이 계약으로 훈련돼 있어 프롬프트 비용 없이
정확히 동작한다. 핸들러 계약(레퍼런스 문서 그대로):
  bash        {command} | {restart: true}
  text_editor view/create/str_replace/insert — str_replace는 정확히 1회 매치만 허용

보안 경계 (여기서만 지킨다 — 모델 출력은 전부 불신):
  * 모든 파일 경로는 프로젝트 루트 안으로 격리 (resolve 후 is_relative_to)
  * bash는 git-guard 훅을 배포 형태(subprocess stdin 계약)로 통과해야 실행 — 로직 중복 금지
  * 타임아웃·출력 상한 — 무한 명령/출력 폭주가 루프를 인질로 잡지 않게
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

BASH_TOOL = {"type": "bash_20250124", "name": "bash"}
EDITOR_TOOL = {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"}
READ_DOCUMENT_TOOL = {
    "name": "read_document",
    "description": "Extract paginated text from a project PDF, DOCX, HWPX, or HWP document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Project-relative document path."},
            "offset": {"type": "integer", "description": "1-based first extracted line; default 1."},
            "limit": {"type": "integer", "description": "Lines to return, 1-500; default 200."},
        },
        "required": ["path"],
    },
}
MEMORY_PROPOSE_TOOL = {
    "name": "memory_propose",
    "description": (
        "Record one durable fact in your own tier-1 memory — the memory that survives across "
        "sessions and belongs to this agent alone. Whether it lands at once or waits for the user's "
        "approval is the user's setting (memory.autosave); the response says which happened, so "
        "read it before you tell the user anything.\n\n"
        "RECORD WHEN (do it as it happens, don't wait to be asked):\n"
        "- The user corrects you, or says how they want work done ('don't do X', 'always Y')\n"
        "- The user states a preference, habit, or fact about themselves\n"
        "- You settle a decision with the user that will still bind you next session\n"
        "- You learn a durable fact about this environment, tool, or convention\n\n"
        "DO NOT RECORD: task progress, what you just finished, session outcomes, temporary state, "
        "anything easily rediscovered by reading a file, or anything about the repository's code "
        "(that is project memory, not yours). Secrets and credentials are rejected outright.\n\n"
        "Write one self-contained sentence that still makes sense a year from now: absolute dates, "
        "named tools, no 'yesterday' and no 'the above'. Fewer, sturdier facts beat many guesses."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The fact, as one self-contained sentence.",
            },
            "kind": {
                "type": "string",
                "enum": ["user", "feedback", "decision", "insight", "reference", "note"],
                "description": (
                    "'user' who the user is · 'feedback' how they want you to work · "
                    "'decision' a settled call · 'insight' something you worked out · "
                    "'reference' a durable lookup fact · 'note' anything else."
                ),
            },
        },
        "required": ["text", "kind"],
    },
}
INGEST_DOCUMENT_TOOL = {
    "name": "ingest_document",
    "description": (
        "Put a document into this project's shared memory so the whole team inherits it. "
        "Use it when the user hands over a requirements doc, spec, protocol sheet, plan, or "
        "decision record and asks to analyse it, set it up, or remember it for the project. "
        "Parses pdf/docx/hwp/hwpx/md/txt, picks the retain strategy from the document's own "
        "shape, lifts requirement IDs into entities, and either stages the write for human approval "
        "or commits it at once when the user turned on project_memory.autosave. Reports what it "
        "decided and which of the two happened."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Document paths. Absolute or project-relative; the file may live outside the repo.",
            },
            "strategy": {
                "type": "string",
                "enum": ["document", "record"],
                "description": (
                    "Override the automatic choice. 'document' stores verbatim chunks with no LLM "
                    "extraction (static specs, requirements). 'record' extracts facts and consolidates "
                    "observations (decisions, incidents). Omit to let the shape decide."
                ),
            },
        },
        "required": ["paths"],
    },
}
WEB_FETCH_TOOL = {
    "name": "web_fetch",
    "description": "Fetch a public HTTP(S) URL and return bounded text or HTML. Private/internal addresses are blocked.",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Public http:// or https:// URL."},
            "format": {"type": "string", "enum": ["text", "html"], "description": "Default: text."},
            "max_chars": {"type": "integer", "description": "Output limit, 1-30000; default 30000."},
        },
        "required": ["url"],
    },
}
PROCESS_TOOL = {
    "name": "process",
    "description": "Start, poll, list, or stop a session-scoped background command. Jobs are terminated when the agent session ends.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "poll", "list", "stop"]},
            "command": {"type": "string", "description": "Required for start."},
            "process_id": {"type": "string", "description": "Required for poll/stop."},
            "wait_seconds": {"type": "number", "description": "Poll wait, 0-10 seconds; default 0."},
        },
        "required": ["action"],
    },
}
TICKET_TOOL = {
    "name": "ticket",
    "description": (
        "Read and write the work tracker — the same board the human sees in Asgard Studio. "
        "Shaped like Linear: a workspace holds TEAMS (each owns its numbering, workflow states, "
        "cycles and triage inbox) and PROJECTS (dated bodies of work that cut across teams, with "
        "milestones). Tickets are numbered once and forever (PRJ-12), so you can refer to one by "
        "number in later turns and in the next session. The board is NOT tied to the folder you "
        "are standing in: reading always covers the whole workspace, so a ticket filed in one repo "
        "is visible from any other. Narrow with team='<KEY>' when you mean one team, or team='.' "
        "for the team bound to this folder.\n\n"
        "TRACK THE WORK YOU ARE DOING. When the human asks for something that is more than a "
        "one-liner, open a ticket first (action=create), move it with action=start when you begin, "
        "and action=finish when the change is ready for review. That is what makes the board a "
        "record of what actually happened rather than a wishlist.\n\n"
        "ALSO FILE A TICKET when you find work you are NOT doing right now:\n"
        "- A defect you noticed while working on something else\n"
        "- Follow-up the user deferred ('later', 'not now', 'in a separate pass')\n"
        "- A step you had to skip, or a limitation you hit and worked around\n"
        "- A piece you split off a large request so the remainder stays reviewable\n"
        "Filing is how you stop losing that work. A sentence in your final message is forgotten "
        "by the next session; a ticket is not.\n\n"
        "DO NOT FILE: vague ideas with no owner or trigger, or a second ticket for work an open "
        "ticket already covers. One ticket per piece of work — a ticket that says 'improve things' "
        "cannot be finished.\n\n"
        "Write the title as the outcome ('결제 재시도에 지수 백오프 적용'), not as a topic ('결제 재시도'). "
        "Put reproduction, constraints, and acceptance criteria in the body.\n\n"
        "Actions: list · get · create · start · finish · update · comment · link · projects. Use "
        "`list` before `create` when the work might already be tracked — duplicates cost the human "
        "more than they cost you. Never invent a project name: call `projects` and use one that exists."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "get", "create", "start", "finish", "update", "comment", "link", "projects"],
            },
            "ref": {
                "type": "string",
                "description": "Ticket number (PRJ-12) or id. Required for get/start/finish/update/comment/link.",
            },
            "title": {"type": "string", "description": "Outcome-shaped title. Required for create."},
            "body": {"type": "string", "description": "Context, reproduction, acceptance criteria."},
            "status": {
                "type": "string",
                "description": (
                    "Workflow state slug. The defaults are backlog · todo · in_progress · in_review · "
                    "done · canceled, but a team may define its own — call action=get or list to see "
                    "what this team uses. Default for a new ticket is 'todo'."
                ),
            },
            "priority": {
                "type": "integer",
                "description": "1 urgent · 2 high · 3 medium · 4 low · 0 none (default).",
            },
            "assignee": {"type": "string", "description": "Who owns it. Leave empty when unknown."},
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Free-form labels; created on first use.",
            },
            "parent": {"type": "string", "description": "Parent ticket for a sub-ticket. One level only."},
            "estimate": {"type": "integer", "description": "Effort points, 0-999."},
            "team": {
                "type": "string",
                "description": (
                    "Team key (e.g. ENG). On action=list, omitting it reads the WHOLE workspace; "
                    "pass '.' to narrow to the team bound to this folder. On writes, omitting it "
                    "files into this folder's bound team, or the workspace default team if none."
                ),
            },
            "project": {"type": "string", "description": "Project name or id — a dated body of work that spans teams."},
            "milestone": {"type": "string", "description": "Milestone inside that project. Needs `project` as well."},
            "kind": {
                "type": "string",
                "enum": ["blocks", "relates", "duplicates"],
                "description": "Relation for action=link. 'blocks' means ref blocks other.",
            },
            "other": {"type": "string", "description": "The other ticket, for action=link."},
            "text": {"type": "string", "description": "Comment body, for action=comment; the note for start/finish."},
            "query": {"type": "string", "description": "Substring filter over title/body/number, for action=list."},
            "open_only": {"type": "boolean", "description": "action=list: only tickets that are not done or canceled."},
        },
        "required": ["action"],
    },
}
APPLY_PATCH_TOOL = {
    "name": "apply_patch",
    "description": "Validate every change, then transactionally apply a Codex-style multi-file patch inside the project.",
    "input_schema": {
        "type": "object",
        "properties": {"patch_text": {"type": "string", "description": "Full *** Begin Patch block."}},
        "required": ["patch_text"],
    },
}

_TIMEOUT = 120
_MAX_OUT = 30_000  # chars — 초과분은 절단 표기 (조용한 절단 금지)
_MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MAX_FETCH_BYTES = 5 * 1024 * 1024


class ToolError(Exception):
    """핸들러 실패 — 메시지가 그대로 is_error tool_result로 나간다 (모델이 복구하게)."""


def _confine(root: str, path: str) -> str:
    """모델이 준 경로를 루트 안으로 격리. 탈출(.., 절대경로 밖, 심링크)은 거부."""
    p = os.path.realpath(os.path.join(root, path) if not os.path.isabs(path) else path)
    if p != os.path.realpath(root) and not p.startswith(os.path.realpath(root) + os.sep):
        raise ToolError(f"경로가 프로젝트 루트를 벗어납니다: {path} (Canon — 범위 존중)")
    return p


def _hook_guard(root: str, module: str, tool_input: dict) -> str | None:
    """가드 훅을 배포 형태(subprocess stdin 계약)로 통과. 차단이면 사유 문자열, 통과면 None.
    fail-open (훅 오류 = 통과) — 로직 중복 금지, 훅이 단일 출처."""
    try:
        p = subprocess.run(
            [sys.executable, "-m", module],
            input=json.dumps({"tool_input": tool_input}),
            capture_output=True,
            text=True,
            timeout=10,
            cwd=root,
            encoding="utf-8",
            errors="replace",
        )
        if p.returncode != 0:
            return (p.stderr or p.stdout or module + " 차단").strip()[:500]
    except Exception:
        pass
    return None


def _git_guard(root: str, command: str) -> str | None:
    return _hook_guard(root, "asgard.hooks.git_guard", {"command": command})


def _release_guard(root: str, command: str) -> str | None:
    return _hook_guard(root, "asgard.hooks.release_guard", {"command": command})


# 셸 파괴 명령 가드 (Canon 3) — git 계열은 git-guard 훅이 단일 출처, 여기는 비-git만.
# 루트 안 rm -rf는 허용 (스크래치 정리는 정당 + git이 복구 지점) — 루트 밖·조상 경로만 차단.
_DEV_DESTRUCTIVE = re.compile(r"\bmkfs(\.\w+)?\b|\bdd\b[^|;&]*\bof=/dev/")
_CONTROL_PATHS = (".asgard", ".claude")


def _destructive_guard(root: str, cmd: str) -> str | None:
    """rm -rf 급 삭제가 프로젝트 루트 밖을 노리면 차단. 파싱 불가 세그먼트는 fail-open
    (lagom: 셸 문법 전체 해석은 안 한다 — 게이트·git이 최종 방어선)."""
    if _DEV_DESTRUCTIVE.search(cmd):
        return f"파괴 명령 차단: {cmd[:80]} (Canon 3 — 디바이스 파괴는 Odin 동의로도 네이티브 루프 밖)"
    rr = os.path.realpath(root)
    for seg in re.split(r"[;&|]+", cmd):
        try:
            toks = shlex.split(seg)
        except ValueError:
            continue
        if not toks or os.path.basename(toks[0]) != "rm":
            continue
        flags = "".join(t.lstrip("-") for t in toks[1:] if t.startswith("-")).lower()
        if not ("r" in flags and "f" in flags):
            continue
        for t in toks[1:]:
            if t.startswith("-"):
                continue
            p = os.path.realpath(os.path.expanduser(t) if t.startswith(("~", "/")) else os.path.join(root, t))
            if p != rr and not p.startswith(rr + os.sep):
                return f"rm -rf가 프로젝트 루트 밖을 대상: {t} (Canon 3 — Odin 명시 동의 필요)"
    return None


def _has_dynamic_expansion(command: str) -> bool:
    """동적 경로를 만들 수 있는 셸 확장 감지. 작은따옴표 안의 정규식 `$` 등은 리터럴이다."""
    single = False
    escaped = False
    for char in command:
        if escaped:
            escaped = False
        elif char == "\\" and not single:
            escaped = True
        elif char == "'":
            single = not single
        elif not single and char in ("$", "`"):
            return True
    return False


def _scope_guard(root: str, command: str) -> str | None:
    """명시 경로·따옴표 결합·셸 확장으로 프로젝트/제어 경계를 넘는 명령을 거부."""
    if _has_dynamic_expansion(command):
        return (
            "동적 셸 확장($/backtick)은 프로젝트 경로 경계를 검증할 수 없어 차단 — 리터럴 경로로"
            " 다시 써라. 임시 파일·캐시는 프로젝트 내부 .gitignore 경로(예: .cache/)를 쓴다"
        )
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = [token for token in lexer if not all(char in "|&;<>()" for char in token)]
    except ValueError:
        return "셸 명령을 안전하게 해석할 수 없어 차단"

    rr = os.path.realpath(root)
    for token in tokens:
        values = [token]
        if "=" in token:
            values.append(token.split("=", 1)[1])
        for value in values:
            normalized = value.replace("\\", "/")
            if normalized.startswith(("http://", "https://")):
                continue
            candidate = os.path.realpath(
                os.path.expanduser(value) if value.startswith(("~", "/")) else os.path.join(root, value)
            )
            if any(
                candidate == os.path.realpath(os.path.join(root, marker))
                or candidate.startswith(os.path.realpath(os.path.join(root, marker)) + os.sep)
                for marker in _CONTROL_PATHS
            ):
                return "Asgard 제어 경로는 모델 Bash에서 접근할 수 없음 — 하니스/전용 명령만 사용"
            if (
                (normalized.startswith(("~", "/", "../")) or normalized == ".." or "/../" in normalized)
                and candidate != rr
                and not candidate.startswith(rr + os.sep)
            ):
                return (
                    f"Bash 경로가 프로젝트 루트를 벗어남: {value} — 임시 파일·캐시가 필요하면"
                    " 프로젝트 내부 .gitignore 경로(예: .cache/)를 쓰라"
                )
    # ponytail: 셸은 OS 샌드박스가 아니다. 더 강한 격리가 필요하면 플랫폼 sandbox 프로세스로 교체.
    return None


def _cap(s: str) -> str:
    return s if len(s) <= _MAX_OUT else s[:_MAX_OUT] + f"\n[... {len(s) - _MAX_OUT} chars 절단]"


def _dedup_log(s: str) -> str:
    """성공한 셸 로그의 연속 중복만 접는다. 오류 출력과 서로 떨어진 중복은 원문 보존."""
    if len(s) < 500:
        return s
    out: list[str] = []
    previous: str | None = None
    repeated = 0
    for line in s.splitlines():
        if line == previous:
            repeated += 1
            continue
        if repeated:
            out.append(f"[... {repeated} duplicate lines]")
        out.append(line)
        previous, repeated = line, 0
    if repeated:
        out.append(f"[... {repeated} duplicate lines]")
    compact = "\n".join(out)
    return compact if len(compact) < len(s) else s


class _HTMLText(HTMLParser):
    _BLOCKS = frozenset({"article", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "pre", "section", "tr"})
    _SKIP = frozenset({"embed", "iframe", "noscript", "object", "script", "style", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if self.skip or tag in self._SKIP:
            self.skip += 1
        elif tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.skip:
            self.skip -= 1
        elif tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = (re.sub(r"[ \t]+", " ", line).strip() for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def _public_url(raw: str) -> str:
    try:
        parsed = urlsplit(raw.strip())
        port = parsed.port
    except ValueError as exc:
        raise ToolError(f"잘못된 URL: {exc}") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ToolError("web_fetch는 공개 http:// 또는 https:// URL만 지원합니다")
    if parsed.username or parsed.password:
        raise ToolError("URL 사용자정보는 허용하지 않습니다")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ToolError("내부 호스트 URL은 차단됩니다")
    try:
        ipaddress.ip_address(host)
        addresses = {host}
    except ValueError:
        try:
            addresses = {
                item[4][0] for item in socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80))
            }
        except OSError as exc:
            raise ToolError(f"URL 호스트를 확인할 수 없습니다: {exc}") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ToolError("사설·루프백·링크로컬·예약 주소는 차단됩니다")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))


def run_web_fetch(_root: str, tool_input: dict) -> str:
    import httpx

    url = str(tool_input.get("url") or "")
    output_format = str(tool_input.get("format") or "text")
    max_chars = int(tool_input.get("max_chars") or _MAX_OUT)
    if output_format not in {"text", "html"} or not 1 <= max_chars <= _MAX_OUT:
        raise ToolError("format은 text|html, max_chars는 1..30000이어야 합니다")
    headers = {
        "Accept": "text/html, text/plain, application/json, application/xml;q=0.9, */*;q=0.1",
        "User-Agent": "Asgard/1 web_fetch",
    }
    try:
        with httpx.Client(follow_redirects=False, timeout=30, headers=headers) as client:
            for _ in range(6):
                url = _public_url(url)
                with client.stream("GET", url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ToolError("리다이렉트 대상이 없습니다")
                        url = urljoin(url, location)
                        continue
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > _MAX_FETCH_BYTES:
                            raise ToolError("응답이 5 MiB 안전 상한을 초과합니다")
                        chunks.append(chunk)
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if content_type and not (
                        content_type.startswith("text/")
                        or content_type
                        in {"application/json", "application/ld+json", "application/xml", "application/xhtml+xml"}
                    ):
                        raise ToolError(f"텍스트가 아닌 응답입니다: {content_type}")
                    body = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                    if output_format == "text" and ("html" in content_type or "<html" in body[:500].lower()):
                        parser = _HTMLText()
                        parser.feed(body)
                        body = parser.text()
                    shown = urlunsplit((*urlsplit(url)[:3], "", ""))
                    suffix = "" if len(body) <= max_chars else f"\n[... {len(body) - max_chars} chars 절단]"
                    return f"[{response.status_code} {content_type or 'unknown'} · {shown}]\n{body[:max_chars]}{suffix}"
            raise ToolError("리다이렉트가 5회를 초과했습니다")
    except ToolError:
        raise
    except httpx.HTTPError as exc:
        raise ToolError(f"URL 요청 실패: {exc}") from exc


def _safe_archive(path: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 4096 or sum(item.file_size for item in entries) > _MAX_ARCHIVE_BYTES:
                raise ToolError("문서 압축 해제 크기가 안전 상한을 초과합니다")
    except zipfile.BadZipFile as exc:
        raise ToolError(f"올바른 문서 ZIP이 아닙니다: {exc}") from exc


def _extract_docx(path: str) -> str:
    _safe_archive(path)
    try:
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
    except (KeyError, ET.ParseError) as exc:
        raise ToolError(f"DOCX 본문을 읽을 수 없습니다: {exc}") from exc
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines: list[str] = []
    for paragraph in root.iter(f"{ns}p"):
        text: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{ns}t":
                text.append(node.text or "")
            elif node.tag == f"{ns}tab":
                text.append("\t")
            elif node.tag in {f"{ns}br", f"{ns}cr"}:
                text.append("\n")
        lines.extend("".join(text).splitlines() or [""])
    return "\n".join(lines)


def _extract_pdf(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    return "\n".join(f"# Page {index}\n{page.extract_text() or ''}" for index, page in enumerate(reader.pages, 1))


def _extract_hwpx(path: str) -> str:
    from hwpx import TextExtractor

    _safe_archive(path)
    with TextExtractor(path) as extractor:
        return extractor.extract_text(include_nested=True, object_behavior="nested", skip_empty=True)


def _extract_hwp(path: str) -> str:
    script = (
        Path(__file__).resolve().parents[1]
        / "assets"
        / "skill_plugins"
        / "hwpx-skill"
        / "skills"
        / "hwpx"
        / "scripts"
        / "convert_hwp.py"
    )
    with tempfile.TemporaryDirectory(prefix="asgard-hwp-read-") as temp:
        converted = os.path.join(temp, "document.hwpx")
        try:
            result = subprocess.run(
                [sys.executable, str(script), path, "-o", converted],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise ToolError("HWP 읽기에는 Node.js 18+가 필요합니다") from exc
        if result.returncode:
            raise ToolError((result.stderr or result.stdout or "HWP 변환 실패").strip()[:2000])
        return _extract_hwpx(converted)


def run_memory_propose(root: str, tool_input: dict) -> str:
    """개인 기억 쓰기 — 기본은 대기열(사람이 승인해야 정본), 자동저장이 켜져 있으면 즉시 저장.

    어느 쪽인지는 이 함수가 정하지 않는다: `propose.submit`이 설정 하나를 읽고 정하고,
    표면은 그 결과를 옮긴다 (MCP와 같은 문장 — `propose.outcome_text`).
    거절 사유는 문장으로 돌려준다 — 에이전트가 읽고 고쳐 다시 낼 수 있어야 한다."""
    del root  # 개인 기억은 프로젝트가 아니라 에이전트에 붙는다 (memory_dir이 프로파일별)
    from ..memory import propose

    text = str(tool_input.get("text") or "").strip()
    kind = str(tool_input.get("kind") or "note").strip()
    try:
        outcome = propose.submit(text, kind=kind)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return propose.outcome_text(outcome)


def _ticket_line(ticket: dict) -> str:
    from ..studio import tickets as T

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
    from ..studio import tickets as T

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
            from ..studio import projects as P

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


def run_ingest_document(root: str, tool_input: dict) -> str:
    """문서를 프로젝트 메모리 승인 대기로 올린다 — 사람은 파일만 던지면 된다.

    쓰기가 아니라 **제안**이다. 팀 공유 스코프라 승인 없이 들어가지 않는다 (프로젝트 메모리
    계약 그대로). 그래서 이 도구는 inspect 권한으로 충분하고, 실제 등록은 사람이 승인한다."""
    from ..memory_bridge import find_config, is_backend_trusted
    from ..project_memory import ingest

    raw = tool_input.get("paths")
    paths = [str(p) for p in raw if str(p).strip()] if isinstance(raw, list) else []
    if not paths:
        raise ToolError("paths가 비었습니다")
    if len(paths) > 20:
        raise ToolError("한 번에 20개까지 처리합니다")
    resolved = [p if os.path.isabs(p) else os.path.join(root, p) for p in paths]
    found = find_config(root)
    if not found:
        raise ToolError("프로젝트 메모리가 연결돼 있지 않습니다 — asgard memory connect <endpoint>")
    project_root, cfg = found
    if not is_backend_trusted(cfg):
        raise ToolError("이 기계에서 신뢰되지 않은 backend 입니다 — asgard memory connect로 재승인")
    strategy = str(tool_input.get("strategy") or "").strip() or None
    ready, failed = ingest.plan(resolved, strategy=strategy)
    if not ready:
        detail = "; ".join(f"{os.path.basename(r['path'])}: {r['error']}" for r in failed) or "읽을 문서가 없습니다"
        raise ToolError(detail)
    if any(d.lane == ingest.LANE_GRAPH for d in ready):
        ingest.ensure_strategies(cfg)
    staged = ingest.stage_documents(project_root, cfg, ready)
    from ..memory_bridge import autosave_enabled

    auto = autosave_enabled(cfg)
    lines = [
        f"{len(staged)}건을 처리했습니다."
        + (
            " 자동저장(project_memory.autosave)이라 승인 없이 등록합니다."
            if auto
            else " 승인 전에는 공유 메모리에 들어가지 않습니다."
        )
    ]
    for row in staged:
        head = (
            f"- {row['name']} · {row['kind']} · 전략 {row['strategy']} · {row['chars']:,}자 · "
            f"엔티티 {row['entities']} · 레인 {row['lane']}"
        )
        if row["lane"] == ingest.LANE_LOCAL:
            # 그래프에 넣으면 뱅크가 죽는 크기 — 저장소 정본 + 로컬 인덱스로 보냈다.
            lines.append(
                f"{head}\n  저장소 정본: {row['canonical_path']} "
                f"(예측 unit {row['graph_units']} > 상한 {ingest.GRAPH_UNIT_CEILING} — 커밋하면 팀과 공유)"
            )
        elif auto:
            # 실패해도 approval_id는 살아 있다 — 문서 한 건이 막혀도 나머지는 계속 들어가고,
            # 막힌 건은 사람이 그 id로 이어받는다 (부분 성공을 전체 실패로 만들지 않는다).
            try:
                from ..project_memory import commit_approved_record

                commit_approved_record(project_root, cfg, row["approval_id"])
            except Exception as exc:
                lines.append(f"{head}\n  자동저장 실패 — asgard memory project-approve {row['approval_id']} ({exc})")
            else:
                lines.append(f"{head}\n  저장 완료 (자동저장)")
        else:
            lines.append(f"{head}\n  승인 대기 — asgard memory project-approve {row['approval_id']}")
    for row in failed:
        lines.append(f"- (읽지 못함) {os.path.basename(row['path'])} — {row['error']}")
    return "\n".join(lines)


def run_document(root: str, tool_input: dict) -> str:
    path = _confine(root, str(tool_input.get("path") or ""))
    if not os.path.isfile(path):
        raise ToolError(f"문서 파일 없음: {os.path.relpath(path, root)}")
    if os.path.getsize(path) > _MAX_DOCUMENT_BYTES:
        raise ToolError("문서가 64 MiB 안전 상한을 초과합니다")
    extractors = {".pdf": _extract_pdf, ".docx": _extract_docx, ".hwpx": _extract_hwpx, ".hwp": _extract_hwp}
    suffix = Path(path).suffix.lower()
    if suffix not in extractors:
        raise ToolError("지원 형식: .pdf, .docx, .hwpx, .hwp")
    try:
        text = extractors[suffix](path)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(f"문서 추출 실패: {exc}") from exc
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        hint = " 스캔 PDF라면 OCR 도구가 필요합니다." if suffix == ".pdf" else ""
        raise ToolError("추출 가능한 텍스트가 없습니다." + hint)
    offset = int(tool_input.get("offset") or 1)
    limit = int(tool_input.get("limit") or 200)
    if offset < 1 or not 1 <= limit <= 500:
        raise ToolError("offset은 1 이상, limit은 1..500이어야 합니다")
    page = lines[offset - 1 : offset - 1 + limit]
    end = min(offset + len(page) - 1, len(lines))
    header = f"[{suffix[1:].upper()} · lines {offset}-{end}/{len(lines)}]"
    if end < len(lines):
        header += f"\n다음: offset={end + 1}"
    return _cap(header + "\n" + "\n".join(page))


class _TailBuffer:
    """실행 중 상한이 걸리는 꼬리 버퍼 — 출력 폭주가 RAM을 인질로 잡지 않게 읽는 즉시 버린다.
    bash는 오류·실패 사유가 끝에 몰리므로 꼬리 보존 (view는 머리 유지 _cap)."""

    def __init__(self, limit: int = _MAX_OUT) -> None:
        self.limit = limit
        self.parts: deque[str] = deque()
        self.size = 0
        self.dropped = 0
        self._lock = threading.Lock()

    def add(self, chunk: str) -> None:
        with self._lock:
            self.parts.append(chunk)
            self.size += len(chunk)
            while self.size > self.limit and len(self.parts) > 1:
                old = self.parts.popleft()
                self.size -= len(old)
                self.dropped += len(old)
            if self.size > self.limit:  # 단일 청크가 상한 초과 — 청크 안에서 꼬리만 남긴다
                only = self.parts[0]
                cut = self.size - self.limit
                self.parts[0] = only[cut:]
                self.size -= cut
                self.dropped += cut

    def text(self) -> str:
        with self._lock:
            body = "".join(self.parts)
            if self.dropped:
                return f"[... 앞 {self.dropped} chars 절단]\n" + body
            return body


def _kill_group(p: subprocess.Popen) -> None:
    """프로세스 그룹 전체 종료(손자 포함) — SIGTERM 유예 2s 후 그룹에 무조건 SIGKILL.
    셸 부모가 먼저 죽고 손자만 SIGTERM을 무시하는 경우를 놓치지 않는다. Windows는 트리 킬."""
    if os.name != "posix":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        except OSError:
            pass
        return
    try:
        pgid = os.getpgid(p.pid)
    except ProcessLookupError, PermissionError, OSError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
    except ProcessLookupError, PermissionError, OSError:
        pass
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError, PermissionError, OSError:
        pass


def validate_bash_command(root: str, command: str) -> str | None:
    """Return a deterministic block reason without executing the command."""
    return (
        _scope_guard(root, command)
        or _git_guard(root, command)
        or _release_guard(root, command)
        or _destructive_guard(root, command)
    )


def run_bash(root: str, tool_input: dict, cancel: threading.Event | None = None) -> tuple[str, int | None]:
    """(output, exit_code). exit_code는 퀘스트 로그 commands 증거용.
    cancel 이벤트가 켜지면 프로세스 그룹째 종료 — 취소는 즉시성이 생명이라 0.2s 폴링."""
    if tool_input.get("restart"):
        return "shell restarted (stateless — cwd는 프로젝트 루트 고정)", 0
    cmd = str(tool_input.get("command") or "")
    if not cmd.strip():
        raise ToolError("빈 명령")
    blocked = validate_bash_command(root, cmd)
    if blocked:
        raise ToolError(blocked)
    group: dict = {"start_new_session": True} if os.name == "posix" else {}
    p = subprocess.Popen(
        cmd,
        shell=True,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **group,
    )
    out_buf, err_buf = _TailBuffer(), _TailBuffer(4000)
    readers = [
        threading.Thread(target=_pump, args=(p.stdout, out_buf), daemon=True),
        threading.Thread(target=_pump, args=(p.stderr, err_buf), daemon=True),
    ]
    for r in readers:
        r.start()
    deadline = time.monotonic() + _TIMEOUT
    try:
        while True:
            try:
                p.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    _kill_group(p)
                    raise ToolError(f"사용자 취소 — 명령 중단 (프로세스 그룹 종료){_tail_note(out_buf, err_buf)}")
                if time.monotonic() > deadline:
                    _kill_group(p)
                    raise ToolError(
                        f"타임아웃 ({_TIMEOUT}s) — 장기 실행은 분할하거나 백그라운드로{_tail_note(out_buf, err_buf)}"
                    )
    except BaseException:  # KeyboardInterrupt 포함 — 분리된 프로세스 그룹을 절대 고아로 남기지 않는다
        if p.poll() is None:
            _kill_group(p)
        raise
    finally:
        for r in readers:
            r.join(timeout=5)
    stdout = out_buf.text()
    if p.returncode == 0:
        stdout = _dedup_log(stdout)
    out = stdout + (("\n" + err_buf.text()) if err_buf.size or err_buf.dropped else "")
    return out.strip() or f"(no output, exit {p.returncode})", p.returncode


class BackgroundProcessManager:
    """Small session-owned process table; never leaves child processes behind."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def run(self, root: str, tool_input: dict, cancel: threading.Event | None = None) -> str:
        action = str(tool_input.get("action") or "")
        if action == "list":
            with self._lock:
                jobs = list(self._jobs.items())
            if not jobs:
                return "background processes: none"
            return "\n".join(self._summary(process_id, job) for process_id, job in jobs)

        process_id = str(tool_input.get("process_id") or "")
        if action in {"poll", "stop"}:
            with self._lock:
                job = self._jobs.get(process_id)
            if job is None:
                raise ToolError(f"알 수 없는 process_id: {process_id}")
            if action == "stop":
                if job["process"].poll() is None:
                    _kill_group(job["process"])
                return self._render(process_id, job)
            wait_seconds = float(tool_input.get("wait_seconds") or 0)
            if not 0 <= wait_seconds <= 10:
                raise ToolError("wait_seconds는 0..10이어야 합니다")
            deadline = time.monotonic() + wait_seconds
            while job["process"].poll() is None and time.monotonic() < deadline:
                if cancel is not None and cancel.is_set():
                    raise ToolError("사용자 취소 — poll 중단")
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            return self._render(process_id, job)

        if action != "start":
            raise ToolError("action은 start|poll|list|stop 중 하나여야 합니다")
        command = str(tool_input.get("command") or "")
        if not command.strip():
            raise ToolError("start에는 command가 필요합니다")
        blocked = validate_bash_command(root, command)
        if blocked:
            raise ToolError(blocked)
        with self._lock:
            if sum(job["process"].poll() is None for job in self._jobs.values()) >= 8:
                raise ToolError("동시 백그라운드 프로세스 상한(8)에 도달했습니다")
            process_id = f"p{self._next_id}"
            self._next_id += 1
        group: dict = {"start_new_session": True} if os.name == "posix" else {}
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **group,
        )
        job = {"process": process, "command": command, "out": _TailBuffer(), "err": _TailBuffer(4000)}
        job["readers"] = [
            threading.Thread(target=_pump, args=(process.stdout, job["out"]), daemon=True),
            threading.Thread(target=_pump, args=(process.stderr, job["err"]), daemon=True),
        ]
        for reader in job["readers"]:
            reader.start()
        with self._lock:
            self._jobs[process_id] = job
        time.sleep(0.05)
        return self._render(process_id, job)

    def close(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job["process"].poll() is None:
                _kill_group(job["process"])
            for reader in job.get("readers", ()):
                reader.join(timeout=1)

    @staticmethod
    def _summary(process_id: str, job: dict) -> str:
        code = job["process"].poll()
        state = "running" if code is None else f"exited({code})"
        return f"{process_id} · {state} · {job['command'][:160]}"

    def _render(self, process_id: str, job: dict) -> str:
        output = job["out"].text()
        if job["process"].poll() in {None, 0}:
            output = _dedup_log(output)
        errors = job["err"].text()
        body = output + (("\n" + errors) if errors else "")
        return _cap(self._summary(process_id, job) + (f"\n{body.strip()}" if body.strip() else "\n(no output)"))


def _pump(pipe, buf: _TailBuffer) -> None:
    """파이프 → 꼬리 버퍼 상시 배수 — 자식이 파이프 블로킹으로 멈추는 것도 함께 방지."""
    try:
        for chunk in iter(lambda: pipe.read(8192), ""):
            buf.add(chunk)
    except OSError, ValueError:
        pass


def _tail_note(out_buf: _TailBuffer, err_buf: _TailBuffer) -> str:
    partial = (out_buf.text() + "\n" + err_buf.text()).strip()
    return f"\n[중단 시점 출력 꼬리]\n{partial[-2000:]}" if partial else ""


def _parse_patch(patch_text: str) -> list[dict]:
    if len(patch_text) > 200_000:
        raise ToolError("패치가 200,000자 안전 상한을 초과합니다")
    lines = patch_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    end_index = next((index for index, line in enumerate(lines) if line.strip() == "*** End Patch"), None)
    if not lines or lines[0].strip() != "*** Begin Patch" or end_index is None:
        raise ToolError("*** Begin Patch / *** End Patch 형식이 필요합니다")
    operations: list[dict] = []
    current: dict | None = None
    hunk: list[tuple[str, str]] | None = None
    for line in lines[1:end_index]:
        header = re.match(r"\*\*\* (Add|Update|Delete) File: (.+)$", line)
        if header:
            current = {"action": header.group(1).lower(), "path": header.group(2).strip(), "hunks": []}
            operations.append(current)
            hunk = None
            continue
        if line.startswith("*** Move to: "):
            if current is None or current["action"] != "update":
                raise ToolError("Move to는 Update File 바로 뒤에서만 사용할 수 있습니다")
            current["move_to"] = line.removeprefix("*** Move to: ").strip()
            continue
        if line.startswith("@@"):
            if current is None or current["action"] != "update":
                raise ToolError("업데이트 hunk 앞에 Update File이 필요합니다")
            hunk = []
            current["hunks"].append(hunk)
            continue
        if current is None:
            if line.strip():
                raise ToolError(f"파일 작업 밖의 패치 내용: {line[:80]}")
            continue
        if current["action"] == "add":
            if not line.startswith("+"):
                raise ToolError(f"Add File 본문 줄은 +로 시작해야 합니다: {current['path']}")
            current.setdefault("content", []).append(line[1:])
        elif current["action"] == "update":
            if hunk is None:
                raise ToolError(f"Update File에 @@ hunk가 필요합니다: {current['path']}")
            if not line or line[0] not in " +-":
                raise ToolError(f"hunk 줄은 공백, +, - 중 하나로 시작해야 합니다: {current['path']}")
            hunk.append((line[0], line[1:]))
        elif line.strip():
            raise ToolError(f"Delete File 뒤에는 본문을 둘 수 없습니다: {current['path']}")
    if not operations or len(operations) > 50:
        raise ToolError("패치에는 1..50개 파일 작업이 필요합니다")
    return operations


def _patch_path(root: str, path: str) -> tuple[str, str]:
    absolute = _confine(root, path)
    relative = os.path.relpath(absolute, os.path.realpath(root))
    if relative in _CONTROL_PATHS or relative.startswith(tuple(marker + os.sep for marker in _CONTROL_PATHS)):
        raise ToolError("Asgard 제어 경로는 모델이 변경할 수 없음")
    return absolute, relative


def _apply_hunks(path: str, content: str, hunks: list[list[tuple[str, str]]]) -> str:
    source = content.splitlines()
    trailing_newline = content.endswith("\n")
    cursor = 0
    for hunk in hunks:
        old = [text for prefix, text in hunk if prefix != "+"]
        new = [text for prefix, text in hunk if prefix != "-"]
        if not old:
            raise ToolError(f"문맥 없는 추가 hunk는 거부됩니다: {path}")
        matches = [
            index for index in range(cursor, len(source) - len(old) + 1) if source[index : index + len(old)] == old
        ]
        if not matches:
            raise ToolError(f"패치 문맥이 현재 파일과 일치하지 않습니다: {path}")
        at = matches[0]
        source[at : at + len(old)] = new
        cursor = at + len(new)
    result = "\n".join(source)
    return result + ("\n" if trailing_newline and source else "")


def run_apply_patch(root: str, tool_input: dict, writes: list[str]) -> str:
    operations = _parse_patch(str(tool_input.get("patch_text") or ""))
    state: dict[str, str | None] = {}
    paths: dict[str, tuple[str, str]] = {}

    def load(path: str) -> tuple[str, str, str | None]:
        absolute, relative = _patch_path(root, path)
        paths[absolute] = (absolute, relative)
        if absolute not in state:
            try:
                state[absolute] = Path(absolute).read_text(encoding="utf-8")
            except FileNotFoundError:
                state[absolute] = None
            except UnicodeDecodeError as exc:
                raise ToolError(f"UTF-8 텍스트 파일만 패치할 수 있습니다: {relative}") from exc
        return absolute, relative, state[absolute]

    for operation in operations:
        absolute, relative, current = load(operation["path"])
        action = operation["action"]
        if action == "add":
            if current is not None:
                raise ToolError(f"Add File 대상이 이미 존재합니다: {relative}")
            state[absolute] = "\n".join(operation.get("content", [])) + "\n"
        elif action == "delete":
            if current is None:
                raise ToolError(f"Delete File 대상이 없습니다: {relative}")
            state[absolute] = None
        else:
            if current is None:
                raise ToolError(f"Update File 대상이 없습니다: {relative}")
            updated = _apply_hunks(relative, current, operation["hunks"])
            move_to = operation.get("move_to")
            if move_to:
                destination, destination_rel, destination_content = load(move_to)
                if destination_content is not None:
                    raise ToolError(f"Move 대상이 이미 존재합니다: {destination_rel}")
                state[absolute] = None
                state[destination] = updated
            else:
                state[absolute] = updated

    originals = {path: (Path(path).read_bytes() if os.path.exists(path) else None) for path in state}
    for path, content in state.items():
        if content is None:
            continue
        relative = paths[path][1]
        blocked = _hook_guard(root, "asgard.hooks.secret_guard", {"file_path": relative, "content": content})
        if blocked:
            raise ToolError(blocked)
    try:
        for path, content in state.items():
            if content is None:
                continue
            os.makedirs(os.path.dirname(path) or root, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".asgard-patch-", dir=os.path.dirname(path) or root)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
                    output.write(content)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        for path, content in state.items():
            if content is None and os.path.exists(path):
                os.unlink(path)
    except Exception:
        for path, content in originals.items():
            if content is None:
                if os.path.exists(path):
                    os.unlink(path)
            else:
                os.makedirs(os.path.dirname(path) or root, exist_ok=True)
                Path(path).write_bytes(content)
        raise
    changed = [paths[path][1] for path in state]
    writes.extend(changed)
    return "applied patch:\n" + "\n".join(f"- {path}" for path in changed)


def run_editor(root: str, tool_input: dict, writes: list[str]) -> str:
    """text_editor 계약. write 계열은 writes에 상대경로 기록 — 게이트의 write-sentinel 대응."""
    cmd = tool_input.get("command")
    path = _confine(root, str(tool_input.get("path") or ""))
    rel = os.path.relpath(path, os.path.realpath(root))  # path는 realpath — 기준도 풀어야 함 (macOS /var 심링크)

    if cmd in ("create", "str_replace", "insert"):
        if rel == ".asgard" or rel.startswith(".asgard/") or rel == ".claude" or rel.startswith(".claude/"):
            raise ToolError("Asgard 제어 경로는 모델이 변경할 수 없음")
        # secret-guard 훅 (Canon Law 4) — mode B와 동일 차단 지점(파일 쓰기). shell 우회는
        # 훅 헤더에 문서화된 알려진 구멍 (양 모드 공통).
        body = str(tool_input.get("file_text") or tool_input.get("new_str") or tool_input.get("insert_text") or "")
        blocked = _hook_guard(root, "asgard.hooks.secret_guard", {"file_path": rel, "content": body})
        if blocked:
            raise ToolError(blocked)

    if cmd == "view":
        if os.path.isdir(path):
            return _cap("\n".join(sorted(os.listdir(path))[:500]))
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                lines = handle.read().splitlines()
        except FileNotFoundError:
            raise ToolError(f"파일 없음: {rel}")
        rng = tool_input.get("view_range")
        if rng and len(rng) == 2:
            lo = max(1, int(rng[0]))
            hi = len(lines) if int(rng[1]) == -1 else int(rng[1])
            lines = lines[lo - 1 : hi]
            start = lo
        else:
            start = 1
        return _cap("\n".join(f"{i + start:6}\t{ln}" for i, ln in enumerate(lines)))

    if cmd == "create":
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        if os.path.exists(path):  # 계약: 기존 파일은 백업 후 덮어쓴다
            os.replace(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(tool_input.get("file_text") or "")
        writes.append(rel)
        return f"created {rel}"

    if cmd == "str_replace":
        old = tool_input.get("old_str") or ""
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except FileNotFoundError:
            raise ToolError(f"파일 없음: {rel}")
        n = text.count(old)
        if n != 1:
            raise ToolError(f"old_str 매치 {n}회 — 정확히 1회여야 합니다 (더 좁혀서 재시도)")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text.replace(old, tool_input.get("new_str") or "", 1))
        writes.append(rel)
        return f"edited {rel}"

    if cmd == "insert":
        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines(keepends=True)
        except FileNotFoundError:
            raise ToolError(f"파일 없음: {rel}")
        at = int(tool_input.get("insert_line") or 0)
        if not 0 <= at <= len(lines):
            raise ToolError(f"insert_line {at} 범위 밖 (0..{len(lines)})")
        ins = tool_input.get("insert_text") or ""
        if not ins.endswith("\n"):
            ins += "\n"
        lines.insert(at, ins)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("".join(lines))
        writes.append(rel)
        return f"inserted into {rel}"

    raise ToolError(f"지원하지 않는 command: {cmd}")
