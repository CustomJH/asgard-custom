"""도구 선언 — 모델에게 보내는 스키마. 실행 코드는 여기 없다.

선언과 구현을 갈라 둔 이유는 고치는 이유가 다르기 때문이다: 여기는 모델이 읽는 글이라
문구 하나를 바꾸면 도구 선택이 달라지고, 구현은 그 선택 뒤에 도는 코드다."""

from __future__ import annotations

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
