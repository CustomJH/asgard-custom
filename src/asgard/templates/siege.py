"""asgard-siege 스킬 — 배차 장부(`asgard siege`)를 모는 계약.

이 스킬을 낸 이유는 표면이 아니라 문이 없었기 때문이다. 동사 25종과 도메인은 이미 있었는데
그것을 부르는 법이 적힌 자리는 `templates/agents.py` 의 한 문단뿐이었고, 거기엔 플래그가 한
줄도 없었다. 그래서 호스트 도구의 에이전트는 25종을 `--help` 로 더듬거나, 이름만 보고 인자를
지어내야 했다 — 실제로 `done` 에 task id 를 넘기는 오류가 그 자리에서 난다.

본문이 시그니처를 통째로 지는 이유가 여기 있다. 스킬이 이름만 대면 드리프트가 조용히 자라고,
`tests/test_siege_skill.py` 가 본문의 동사·플래그를 CLI 와 한자리에서 대조해 그것을 막는다.

표면이 다 있어도 그래프는 저절로 안 돈다. 26-08-12 이전의 본문은 동사 25종을 정확히 적었지만
**무엇을 먼저 하라는 말이 없어서**, 부르는 쪽이 매번 다시 정했다 — 그래서 같은 장부 위에서
어떤 세션은 wave 를 띄우고 어떤 세션은 일감을 하나씩 줄 세웠다. 지금 본문 앞에 선 다섯 단계가
그 자리다: 그래프를 먼저 적고, 에이전트를 계획 시점에 묶고, 한 물결을 한 메시지에서 띄우고,
받은 에이전트가 자기 전문가를 다시 부르고, 검증은 단위마다 따로 돈다.

`plan` 과 검증 짝(`--verify`)이 그 계약을 실제로 쥔다. `add` 를 여러 번 쳐도 결과는 같지만,
그쪽은 id 를 받아 다음 호출로 옮기는 품이 들어서 의존이 자주 생략됐다 — 남는 것은 그래프가
아니라 평평한 목록이었다. 검증 짝은 자기 단위 하나에만 걸린다: 그래야 A 의 검증이 B 의 작업과
같은 물결에 뜬다.

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

## Drive the graph — the sequence, not a suggestion

Coordination fails the same way every time. The coordinator keeps the decomposition in its head,
launches one agent, waits for it, launches the next, and calls the result a graph. It is a queue
with extra bookkeeping: nothing ran beside anything else, and no wave ever existed. These five
steps are what separate the two, and they are the reason this skill is loaded.

1. **Write the graph down before you launch anything.** `siege plan` takes the whole decomposition
   in one call — every unit, who it is for, what it waits on, whether it gets its own verifier. A
   unit that was never written down cannot be handed out, retried, reclaimed, or verified, and no
   later step recovers it. Decompose to the point where two units touch different files; stop
   before units get so small that the handoff costs more than the work.
2. **Bind the agent when you plan, not when you launch.** `agent` on a unit is the dispatch
   decision, made once and recorded. `siege ready` then answers *who to launch*, not merely *what
   is unblocked*, so the choice is not re-argued every round and a resumed run picks up the same
   assignment the plan made.
3. **Launch a whole wave in one assistant message.** Every task `siege ready` hands back becomes
   its own Agent call, and all of them go in the same message. Splitting them across messages
   serialises the graph you just built — the tool that runs them concurrently is the host, and it
   only does so for calls that arrive together. Six ready tasks mean six calls in one message.
4. **A launched agent dispatches its own specialists.** The agent you launch is not a leaf. It
   opens its own dispatches down the delegation ladder for the surfaces it does not own, and those
   sub-calls follow the same one-message rule. Two invariants decide every pair — a role never
   calls its own rung or above, and a read-only caller reaches only read-only agents — and the
   `subagent-gate` hook is the one place that enforces them. Do not restate the ladder here or
   pre-filter it yourself; name the agent you want and let the gate answer.
5. **Verification runs per unit, beside the work.** A unit planned with `verify` gets a verify task
   that waits on **that unit alone**. So the moment unit A settles, its verifier is dispatchable —
   while unit B is still being written. Verification stops being a stage at the end of the run and
   becomes another lane of the same graph. One verifier at the end is the single most common way a
   parallel run loses its parallelism.

The verify task is a dispatch-axis record — that a verifier was put on that unit, and what it
reported. **It is not the verdict.** The PASS that closes the quest is the Trinity Verifier's
event in the quest log, and nothing here substitutes for it.

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
    asgard siege watch <run_id> [--interval <s>] [--for <s>]
        the `show` view redrawn while the run is going, so a fan-out is visible before it ends. It
        stops on its own when no attempt is live and no task is unfinished, or at `--for` (1800s).
        Hand this line to the person waiting: their terminal can watch what yours cannot show.

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
        [--as <who>] [--json]

Takes the oldest unacknowledged batch of mail and replays that same batch until you `--ack` it.
Process every message in the batch before acknowledging. `--type` decides what wakes a wait, not
what the batch contains — pass `--type worker_done --type escalation --type question` so a
heartbeat does not wake you for nothing. `--peek` looks without taking. A batch caps at 50.

**An empty batch or an expired `--wait-ms` is a checkpoint, not a dead worker.** Keep waiting in
rolling calls. Do not stop, replace, or relaunch a worker because it has been quiet; a heartbeat
means alive, not done.

## Addressed mail — talking to one participant, and to a model

One run has one mailbox, and `--recipient` divides it. Mail sent with a recipient is claimed only
by a `check --as <that name>`; mail sent without one still belongs to the coordinator, which is the
`check` that names nobody. So a caller that gives `--as` never takes work another participant is
waiting on, and never takes the coordinator's mail either.

    asgard siege serve <run_id> --as <who> [--provider <p>] [--model <m>] [--once]
        [--idle-timeout <seconds>] [--json]

Stands at the mailbox under that name and hands whatever arrives for it to a model, then puts the
answer back: a `question` is answered on that message, anything else comes back as fresh mail to
its sender. The model is whatever `providers` resolves — anthropic, an OpenAI-compatible endpoint,
a local ollama — so the pair below is one round trip with a model of your choosing, from any host:

    asgard siege serve <run_id> --as codex-1 --provider openai &
    asgard siege ask <run_id> "does this migration need a backfill?" --recipient codex-1 --wait-ms 60000

The asking call blocks and returns the answer, so a host that has no cross-session messaging of its
own still gets one. Two limits are worth knowing before you lean on it. A model that cannot be
called leaves an `escalation` in the mailbox instead of an invented answer — the asker times out
with no answer, and the reason is in `siege inbox`. And a `serve` process holds no conversation:
each message is answered on its own, with the run objective as the only shared context.

## The spine — only when it is yours

    asgard siege start "<objective>" [--quest <quest_id>] [--coordinator <who>]
        [--shape direct|single|graph|squad] [--why "<one line>"] [--json]

`--quest` binds the run to a quest and reuses the run that quest already has, so re-running is
idempotent. `--why` is read back in `show`.

    asgard siege plan <run_id> '<units_json>' [--json]

Lays the whole graph in one call — **start here** on any run with more than one unit. The argument
is a JSON array, and `deps` are indices into that same array, so no unit waits on an id you have
not been handed yet:

    [{"spec": "the API surface",  "agent": "asgard-thor",   "verify": true},
     {"spec": "the CLI surface",  "agent": "asgard-thor",   "verify": true},
     {"spec": "docs over both",   "agent": "asgard-worker", "deps": [0, 1], "verify": true}]

`agent` binds who takes the unit, `verify` pairs it with a verifier that waits on that unit alone,
and `unit` carries the assignment-unit id. A dep pointing at itself or at a later index is refused
before anything is written, so a bad graph never leaves half its tasks behind. The reply carries
the tasks and the wave layout — the first wave is what you launch, in one message.

    asgard siege add <run_id> "<spec>" [--dep <task_id>]… [--unit <unit_id>] [--parent <task_id>]
        [--agent <agent>] [--verify] [--json]

One task, for grafting onto a graph that already exists — a unit the plan did not foresee, or a
retry surface found mid-run. `--dep` names a task in the same run that must finish first; with no
`--dep` the task is ready at once. `--unit` carries the assignment-unit id so the ledger and the
quest log name the same work. `--agent` binds who takes it, `--verify` pairs it with a verifier
that waits on this task alone. A dependency cycle is refused.

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

0. `siege plan <run> '<units>'` — lay the graph. Everything below reads what this wrote.
1. `siege ready <run> --json` — the tasks that are dispatchable now. Each row carries `agent`,
   `kind`, and `spec`: that is a launch order, not a reading.
2. **Launch every row in one message.** One Agent call per row, `agent` deciding which agent, `spec`
   the assignment, and the task id passed through so the worker can report against it. Work rows
   (`kind: work`) and verify rows (`kind: verify`) go out together — a verifier for a finished unit
   belongs in the same wave as work on an unfinished one.
3. `siege check <run> --type worker_done --type escalation --type question --wait-ms <n> --json`.
4. Handle every message in the delivery: `question` → `siege answer`, `escalation` → decide or put
   it to the user, `worker_done` → move on.
5. `siege check <run> --ack <delivery_id> --wait-ms <n>` — acknowledge and keep waiting in one call.
6. Back to step 1 as soon as **anything** settles. Do not wait for the wave to drain: one finished
   unit unblocks its own verifier and any unit that was waiting only on it, and those launch now.
   `siege close <run>` at the end.

`siege waves <run>` shows the same graph as batches, for reading the shape. `ready` is what you
dispatch from — it accounts for what has actually settled, and `waves` does not.

## Worker turn

1. You were handed a task id, and a dispatch id if the spine is yours to open.
2. Your unit is yours to decompose further. Surfaces you do not own go to the specialist that does,
   dispatched down the ladder, and several of them go out in one message like any other wave.
3. Blocked on something only the coordinator can answer:
   `siege ask <run> "<q>" --sender <you> --task <task> --wait-ms <n>`. On a host (Claude Code,
   Cursor, Codex) drop `--wait-ms`: the coordinator is inside its own turn until you return, so
   waiting there buys a timeout. Leave the question, state the assumption, carry on (Canon 8).
4. Working a long stretch: `siege heartbeat <run> <task> <dispatch> --phase "<what you are doing>"`.
5. Finished: `siege done <dispatch> succeeded|failed --subject "<headline>" --file <each path>`.
   Given no dispatch id — every host-mode dispatch — name yourself instead:
   `siege done --quest <quest> --agent <you> --outcome failed --body "<what stopped you>"`. Report
   only a failure; an attempt that returns without a word is settled as succeeded, which is right
   for a success and invisible for anything else.

## Invariants

- Exit codes are 0 and 2 only. `2` means the domain refused; never read it as success.
- The ledger is derived — never completion evidence, never a verification criterion.
- One live Dispatch per Task; a resolved Task does not reopen.
- Do not hand-write what the lifecycle already writes for you.
- A wave launches in one message. Ready tasks sent one per message did not run in parallel.
- A verify task waits on its own unit and nothing else. Widening it to the whole graph puts
  verification back at the end of the run.
- Verification independence holds here too: a verify task goes to `asgard-verifier`, never to an
  agent that can edit the diff it is judging.
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
