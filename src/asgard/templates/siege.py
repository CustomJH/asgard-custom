"""asgard-siege 스킬 — 배차 장부(`asgard siege`)를 모는 계약.

이 스킬을 낸 이유는 표면이 아니라 문이 없었기 때문이다. 동사 25종과 도메인은 이미 있었는데
그것을 부르는 법이 적힌 자리는 `templates/agents.py` 의 한 문단뿐이었고, 거기엔 플래그가 한
줄도 없었다. 그래서 호스트 도구의 에이전트는 25종을 `--help` 로 더듬거나, 이름만 보고 인자를
지어내야 했다 — 실제로 `done` 에 task id 를 넘기는 오류가 그 자리에서 난다.

본문이 시그니처를 통째로 지는 이유가 여기 있다. 스킬이 이름만 대면 드리프트가 조용히 자라고,
`tests/test_siege_skill.py` 가 본문의 동사·플래그를 CLI 와 한자리에서 대조해 그것을 막는다.

배정은 Worker 와 Thor 편대장 둘이다. 배차를 실제로 여는 쪽이 그 둘이고, Verifier·loki 는
resolve 단계에서 이미 빠진다 (advisory 를 판정 표면에 안 넣는 규율)."""

import re

SIEGE_SKILL_MD = """\
---
name: asgard-siege
description: Drive and read the dispatch ledger — open a run, lay out a task graph, track every attempt, ask a blocking question, hold a decision gate, and reclaim abandoned work. Load when a quest runs more than one worker, when a parallel unit is stuck waiting on an answer, or when you need what was attempted rather than what was verified.
allowed-tools: Bash(asgard siege *)
---

# asgard-siege — the dispatch ledger

A **siege** is one quest seen from the dispatch axis: who attempted what, how many times, what
they asked, and what is still waiting on an answer. It lives in `.asgard/orchestration.db`, every
verb is `asgard siege …`, and every verb takes `--json` — the reader here is usually an agent.

**A siege is not the quest log.** The quest log records what was *verified* and is canonical; the
siege records what was *attempted* and is derived. When the two disagree the quest log wins, and a
ledger entry is never completion evidence and never a verification criterion.

## Three layers

| layer | what it is | id |
| --- | --- | --- |
| **Run** | the namespace and the coordinator's mailbox. It schedules nothing and places nobody. | `run_…` |
| **Task** | one piece of work. `--dep` on another task in the same run builds the DAG. | `task_…` |
| **Dispatch** | one **attempt** at a Task by one worker. Lifecycle authority lives here. | `disp_…` |

Task and Dispatch are separate so a retry keeps its own history: three attempts at one Task are
three Dispatches, with three workers and three outcomes. A completion report therefore belongs to a
**Dispatch, not a Task** — `siege done` takes a `<dispatch_id>`, and handing it a task id is the
most common mistake at this surface. Dispatch ids come from `siege open`, or from
`siege show <run>` under each task's `attempts_detail`.

- Task status: `pending` `ready` `dispatched` `completed` `failed` `blocked`. Only dependencies
  separate `pending` from `ready`; one failed or blocked dependency makes it `blocked`.
- Dispatch state: `ready` `settled` `failed` `stopped` `outcome_unknown`. **`outcome_unknown` is
  not a failure** — the worker left no report and its process and files may still be alive. Folding
  it into failure counts a live worker as dead and puts a second worker on the same files.
- One live Dispatch per Task. A resolved Task never reopens. Three failed outcomes break the
  circuit and fail the Task (`ticket_runtime.max_attempts` overrides the count).

## Who writes the spine — settle this before your first write

The spine is `start → add → open → done|settle`. **One writer per run.** Two writers open two
Dispatches on one Task; the domain refuses the loser, and which one loses changes between runs.

| where you are | who writes the spine |
| --- | --- |
| Native loop (`asgard start`, `asgard run`) | the loop writes it. Leave the spine alone. |
| Claude Code / Cursor / Codex, on work carrying quest units | `quest-log.py ticket-claim` and `ticket-finish` write it for you: claiming a unit opens the Task and the Dispatch, finishing settles them. Leave the spine alone. |
| Claude Code / Cursor / Codex, dispatching any other agent | the dispatch hook writes it: spawning the agent opens the Task and the Dispatch under the agent's name, and its stop settles them. Leave the spine alone — a hand-written `open` for the same call puts the work on the ledger twice. |
| coordination with no quest unit behind it | the spine is yours — `start`, `add`, `open`, `done`. |

Everything below the spine — asking, answering, gating, escalating, staying alive, mail — is
**yours in every mode**. That half is why you are here.

Look before you write:

    asgard siege --json                  # every run
    asgard siege show <run_id> --json    # one run: its tasks, their deps, every attempt

## Reading

    asgard siege [--json]                                 every run
    asgard siege show <run_id> [--json]                   tasks, deps, gates, and attempts_detail
    asgard siege inbox <run_id> [--limit <n>] [--json]    mail sent and received; leaves it unread
    asgard siege blocked [--json]                         worker questions nobody has answered
    asgard siege gates [<run_id>] [--all] [--json]        decisions still waiting on a person
    asgard siege ready <run_id> [--json]                  tasks you can dispatch right now
    asgard siege waves <run_id> [--json]                  the DAG as batches; one batch runs at once

## Coordination — the half you always drive

    asgard siege ask <run_id> "<question>" [--option <a>]… [--sender <who>] [--task <task_id>]
        [--dispatch <dispatch_id>] [--wait-ms <n>] [--json]

A stuck worker asks the coordinator. With `--wait-ms` it blocks for the answer; the default `0`
records the question and returns at once. Canon 8 still applies — ask only when no default is
defensible, and prefer a recorded assumption over a stopped session.

    asgard siege answer <message_id> "<answer>" [--json]

Answers a waiting question so the asker carries on. `siege blocked` lists the message ids.

    asgard siege gate <run_id> "<question>" [--option <a>]… [--task <task_id>] [--json]
    asgard siege decide <gate_id> <resolution> [--json]

A gate holds the graph on a choice that is the user's alone. `decide` closes it, and the answer
reads back in `siege show` under `gates[].resolution`.

    asgard siege escalate <run_id> "<reason>" [--task <task_id>] [--dispatch <dispatch_id>]
        [--sender <who>] [--json]

For when the coordinator has to step in and there is no question to ask yet.

    asgard siege heartbeat <run_id> <task_id> <dispatch_id> [--phase "<what it is doing>"] [--json]

Says a long attempt is still alive. It touches the attempt itself, so `reclaim --older-than` leaves
a heartbeating worker where it is. Send it on any stretch long enough that silence looks like death.

    asgard siege send <run_id> <type> [--subject <text>] [--body <text>] [--sender <who>]
        [--recipient <who>] [--task <task_id>] [--dispatch <dispatch_id>]
        [--priority low|normal|high] [--json]

Free-form mail. Types: `status` `dispatch` `worker_done` `merge_ready` `escalation` `handoff`
`question` `decision_gate` `heartbeat`. A finished report goes through `done`, never through `send`.

    asgard siege check <run_id> [--ack <delivery_id>] [--type <type>]… [--peek] [--wait-ms <n>]
        [--json]

Takes the oldest unacknowledged batch of mail and replays that same batch until you `--ack` it.
Process every message in the batch before acknowledging. `--type` decides what wakes a wait, not
what the batch contains — pass `--type worker_done --type escalation --type question` so a
heartbeat does not wake you for nothing. `--peek` looks without taking. A batch caps at 50.

**An empty batch or an expired `--wait-ms` is a checkpoint, not a dead worker.** Keep waiting in
rolling calls. Do not stop, replace, or relaunch a worker because it has been quiet; a heartbeat
means alive, not done.

## The spine — only when it is yours

    asgard siege start "<objective>" [--quest <quest_id>] [--coordinator <who>]
        [--shape direct|single|graph|squad] [--why "<one line>"] [--json]

`--quest` binds the run to a quest and reuses the run that quest already has, so re-running is
idempotent. `--why` is read back in `show`.

    asgard siege add <run_id> "<spec>" [--dep <task_id>]… [--unit <unit_id>] [--parent <task_id>]
        [--json]

`--dep` names a task in the same run that must finish first; with no `--dep` the task is ready at
once. `--unit` carries the assignment-unit id so the ledger and the quest log name the same work.
A dependency cycle is refused.

    asgard siege open <task_id> [--worker <who>] [--role <trinity_role>] [--agent <agent>]
        [--model <model>] [--retry-of <dispatch_id>] [--json]

Opens the attempt and returns the `disp_…` id you will report with.

    asgard siege done <dispatch_id> succeeded|failed [--run <run_id>] [--task <task_id>]
        [--subject <text>] [--body <text>] [--file <path>]… [--sender <who>] [--json]

The worker's own report: the `worker_done` mail and the settlement land in one transaction.
`--run` and `--task` are guards that refuse a dispatch which does not belong where you think it does.

    asgard siege settle <dispatch_id> succeeded|failed [--summary <text>] [--file <path>]… [--json]

The coordinator closing an attempt whose worker left no report.

    asgard siege mark <dispatch_id> stopped|outcome_unknown [--json]

Neither state closes the Task — the work still needs an owner.

## Recovery

    asgard siege reclaim <run_id> [--older-than <seconds>] [--json]
    asgard siege refresh <run_id> [--json]
    asgard siege force <task_id> pending|ready|dispatched|completed|failed|blocked
        [--result <json>] [--json]
    asgard siege close <run_id> [--json]
    asgard siege reset [--tasks] [--messages] [--all] [--json]

`reclaim` takes back attempts whose worker vanished without settling, so the Task can be dispatched
again; without it a dead process leaves a live Dispatch and that Task is never handed out again.
`--older-than <seconds>` spares anything touched more recently, which is what makes heartbeats
worth sending — omit it only when every worker is known dead. `refresh` recomputes each task's
status from its dependencies. `force` writes a status by hand for repair, never on the normal path
— a status nobody attempted is a status nobody can explain. `reset` wipes the ledger; the quest log
survives, because the ledger is derived.

## Coordinator loop

1. `siege show <run>` — see where the graph stands.
2. `siege ready <run>` (or `waves`) — take a whole batch and launch all of it in one message.
3. `siege check <run> --type worker_done --type escalation --type question --wait-ms <n> --json`.
4. Handle every message in the delivery: `question` → `siege answer`, `escalation` → decide or put
   it to the user, `worker_done` → move on.
5. `siege check <run> --ack <delivery_id> --wait-ms <n>` — acknowledge and keep waiting in one call.
6. When the batch settles, `siege ready` again for the next wave. `siege close <run>` at the end.

## Worker turn

1. You were handed a task id, and a dispatch id if the spine is yours to open.
2. Blocked on something only the coordinator can answer:
   `siege ask <run> "<q>" --sender <you> --task <task> --wait-ms <n>`.
3. Working a long stretch: `siege heartbeat <run> <task> <dispatch> --phase "<what you are doing>"`.
4. Finished: `siege done <dispatch> succeeded|failed --subject "<headline>" --file <each path>`.

## Invariants

- Exit codes are 0 and 2 only. `2` means the domain refused; never read it as success.
- The ledger is derived — never completion evidence, never a verification criterion.
- One live Dispatch per Task; a resolved Task does not reopen.
- Do not hand-write what the lifecycle already writes for you.
"""

SIEGE_SKILLS: list[tuple[str, str]] = [("asgard-siege", SIEGE_SKILL_MD)]

# 조율을 실제로 부르는 말만 넣는다. 배차·게이트·질문은 이 장부 말고 갈 곳이 없으므로 잡아도
# 손해가 없지만, 흔한 코드 어휘를 잡으면 단독 작업에도 계약이 붙어 값이 죽는다.
_SUBSTR: tuple[str, ...] = (
    "병렬",
    "동시에 실행",
    "배차",
    "공성전",
    "코디네이터",
    "오케스트레이션",
    "작업 그래프",
    "의존 그래프",
    "결정 게이트",
    "siege",
    "coordinator",
    "orchestrat",
    "task graph",
    "task dag",
    "fan out",
    "fan-out",
    "worker_done",
    "decision gate",
    "in parallel",
)
# 짧은 ASCII 용어는 단어 경계 필수 — `dispatch` 를 부분 일치로 잡으면 이벤트 dispatcher 를
# 고치는 단독 작업에도 조율 계약이 붙는다. `\\bdispatch\\b` 는 dispatcher 를 안 잡는다.
_WORD_RE: tuple[str, ...] = (
    r"\bparallel\b",
    r"\bdags?\b",
    r"\bsquads?\b",
    r"\bdispatch(es|ed|ing)?\b",
    r"\bcoordinate[sd]?\b",
    r"\bescalat(e|es|ed|ion)\b",
)


def resolve_siege_skills(task: str) -> list[tuple[str, str]]:
    """조율 어휘가 있는 과업 → 배차 계약 (이름, frontmatter 제거 본문) — 0-LLM 휴리스틱.

    일치가 없으면 빈 목록이다 (fail-open). 장부를 안 쓰는 작업에 이 계약이 붙으면 25종짜리
    본문이 값 없이 컨텍스트를 먹으므로, 넓게 잡는 쪽보다 안 잡는 쪽으로 기운다.
    """
    text = task.lower()
    if not (any(k in text for k in _SUBSTR) or any(re.search(p, text) for p in _WORD_RE)):
        return []
    return [(name, body.split("---", 2)[2].lstrip()) for name, body in SIEGE_SKILLS]
