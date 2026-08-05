<!-- asgard:map-graph schema=1 -->
# Relation Graph

> Asgard managed relation catalog. Regenerate with `asgard map scan`; do not hand-edit.
> `?` marks candidate evidence — verify at the cited source before asserting.

- Evidence summary: commands 194 · db 2 · calls 6 · uses 2

## Coverage boundaries

> Named scanner gaps are evidence too. They weaken absence and blast-radius claims; details live in `map scan --json`.

- Coverage status: partial · 2 named limits
- test_sources_excluded [repository] — 180 test source files are outside the production relation graph · files 180
- unsupported_source_suffix [.rs] — no relation extractor is configured for Rust (.rs) · files 2

## Commands

> 이 저장소가 이미 답을 내는 표면이다 — 핸들러를 grep 하기 전에 여기서 고른다.

- `asgard auth login` — sign in to a subscription provider
- `asgard auth logout` — drop a subscription login Asgard was holding
- `asgard auth status` — is that subscription login still good
- `asgard automations add` — save one prompt with an hourly/daily/weekdays/weekly or 5-field cron schedule
- `asgard automations disable` — keep a saved automation without letting it become due
- `asgard automations due` — report what is due now; --run explicitly puts each prompt through asgard run
- `asgard automations enable` — let a saved automation become due again
- `asgard automations history` — show recent automation runs, newest first
- `asgard automations list` — show every saved automation and its last outcome
- `asgard automations remove` — remove a saved automation; its run history stays
- `asgard budget` — what this session has cost you so far — the total, what makes it up, and which lane spent it
- `asgard completions` — print or install shell completion (bash|zsh|fish|powershell)
- `asgard craft` — how THIS change is built up close — how big each unit is, how deep, how long it holds things
- `asgard doctor` — check the install — runtime, PATH, and project wiring
- `asgard einherjar bind` — place an agent in THIS project — as its default, per mode, or per Trinity role (swarm)
- `asgard einherjar config` — show or change one agent's model, provider, permissions, and other settings
- `asgard einherjar create` — raise a new agent — it gets its own home, its own identity, its own memory
- `asgard einherjar delete` — remove an agent — everything it remembered goes with it
- `asgard einherjar describe` — set what this agent is good at — the sentence the swarm routes on
- `asgard einherjar export` — export an agent to a local tar.gz backup
- `asgard einherjar identity` — show or replace an agent's AGENT.md instructions
- `asgard einherjar import` — import an agent from a tar.gz backup without overwriting an existing agent
- `asgard einherjar list` — every agent on this machine — plus the built-in ones not yet raised
- `asgard einherjar open` — open one agent's Studio window, reusing its live window unless --new is set
- `asgard einherjar rename` — rename an agent and keep its settings, identity, and memory together
- `asgard einherjar show` — one agent — who it is, how much it remembers, and what it can do
- `asgard einherjar unbind` — drop a placement from this project
- `asgard einherjar use` — make this the machine's active agent (built-in names are raised on demand)
- `asgard einherjar where` — who works here, and which declaration won
- `asgard einherjar windows` — show registered Studio windows, their agents, URLs, processes, and state
- `asgard evolve approve` — check a draft over and install it — the next dispatch can reach it, no restart
- `asgard evolve archive` — put a learned skill away without deleting it — you can bring it back
- `asgard evolve bench` — run it with a learned skill off, then on, and say whether the skill earns its place
- `asgard evolve curate` — which learned skills have gone quiet — stale at 30 days, put away at 90. shows only
- `asgard evolve list` — the skill drafts waiting on you — edit the files first if they need it
- `asgard evolve nudge` — for hooks: mention once that there is something new to dig out, then stay quiet
- `asgard evolve polish` — have a model rewrite a draft as principles rather than steps — it still waits on you
- `asgard evolve reject` — turn a draft down — that same lesson is never brought to you again
- `asgard evolve restore` — bring a put-away skill back, so it can be reached again
- `asgard evolve scan` — dig through the quest logs for lessons that cost something — every FAIL that became a PASS
- `asgard evolve show` — print one waiting draft, as its SKILL.md stands
- `asgard freyja-gate` — the visual surfaces THIS change touches — each Freyja engine judges its own, against a base
- `asgard health` — how much the codebase has worn down — size, duplication, coupling, hotspots, and which way it is going
- `asgard humanize` — read text back and say where it sounds like a machine wrote it (exit 1 = it does)
- `asgard init` — get a project ready for coding agents (Claude Code / Cursor / Codex)
- `asgard k6 baseline clear` — drop the target — the gate stops judging until you pin another
- `asgard k6 baseline set` — pin a run as the target to beat (the newest one, unless you name a stamp)
- `asgard k6 baseline show` — which run is the target right now, and how far a run may drift from it
- `asgard k6 doctor` — is everything here to run a test — the runner, the k6 build, the kit, the scenarios
- `asgard k6 gate` — did the last run get worse than the baseline (exit 1 = it did; it reads files, it does not run load)
- `asgard k6 report` — lay out a run you already did (the newest one, unless you name another)
- `asgard k6 run` — put the target under load and write down how it went (exit 1 = it missed the threshold)
- `asgard k6 scenarios` — the load scenarios that shipped, and the ones this project wrote
- `asgard k6 selftest` — does the harness tell the truth — measured against a target we told how to behave
- `asgard k6 sync` — lay the kit down in this project's .asgard/k6/ — the folders docker mounts
- `asgard manual` — your own project rules (MANUAL.md) — what is loaded, from where, how big
- `asgard map check` — how far the map has drifted, and which area maps are broken — writes nothing
- `asgard map context` — the slice of the map an agent would actually be handed
- `asgard map impact` — revision-bound two-way impact evidence, candidates, frontiers, and next exact source reads
- `asgard map list` — every node in the graph, with the id to trace from and where it came from
- `asgard map scan` — rebuild source-grounded relation evidence and retain every named scanner coverage limit
- `asgard map trace` — walk outward from one node — what sits next to it, not everything it could reach
- `asgard map update` — draw the project map, or redraw it after the repository has moved around
- `asgard mode pick` — change one setting by picking from a list instead of typing it out
- `asgard mode reset` — drop what this project pinned for one mode, or for one role inside it
- `asgard mode set` — pin the agent or model for a whole mode, or for one role inside it
- `asgard mode show` — what each role in one mode actually ends up with, after everything is layered
- `asgard office build` — build a document from a spec (docx | pptx | xlsx)
- `asgard office fill` — fill {{placeholders}} in a file somebody else designed
- `asgard office outline` — skeletons to start from — 23 shapes of document and deck
- `asgard office read` — read a document back out as Markdown or JSON
- `asgard office render` — turn it into a PDF and page images, or work an .xlsx out — needs LibreOffice
- `asgard office template` — the templates on file — list, show, new, adopt, check, render
- `asgard office verify` — check it before you send it — text running over, contrast, placeholders left in, formulas
- `asgard open studio` — Open Asgard Studio. 프로젝트 안이 아니어도 열린다 — 작업 공간은 창에서 고른다.
- `asgard orchestrate` — choose how much Asgard orchestrates, and see which engines are actually reachable
- `asgard plugins install` — install a local resource plugin directory
- `asgard plugins list` — the plugins that shipped, and the ones you installed here
- `asgard review cancel` — decline a pending Review request without running the model
- `asgard review decide` — accept, dismiss, resolve, or reopen one saved suggestion
- `asgard review list` — show pending, running, and completed Review records
- `asgard review show` — show one Review request or its saved suggestions
- `asgard role list` — which bridges are open, where the native roles sit, and what the hosts run
- `asgard role model` — see or change the model one role uses on native, Claude Code, Cursor, or Codex
- `asgard role run` — run one role's turn where it is placed, and write it into the quest log
- `asgard run` — put one task through the native Trinity loop with nobody watching — for benches and CI
- `asgard setup map` — draw the project's code map from what the code actually shows, or redraw it
- `asgard siege add` — add one task to the run's graph — with --dep it waits, without it is ready at once
- `asgard siege answer` — answer a waiting worker question yourself, and let it carry on
- `asgard siege ask` — a stuck worker asks the coordinator — whether it waits is yours to say
- `asgard siege blocked` — the worker questions nobody has answered yet
- `asgard siege check` — take the oldest unacked batch of mail — pass --ack to clear the one before it
- `asgard siege close` — close a run — no more tasks, gates, or attempts go into it
- `asgard siege decide` — close a waiting decision gate with your choice, and let the run carry on
- `asgard siege done` — report an attempt finished — the mail and the settlement land together
- `asgard siege escalate` — say the coordinator has to step in — for when there is no question to ask yet
- `asgard siege force` — write a task's status by hand — for recovery, not for the normal path
- `asgard siege gate` — stop the graph on a decision only a person should make — 'decide' closes it
- `asgard siege gates` — the decisions a coordinator stopped to ask about — still waiting on you
- `asgard siege heartbeat` — say a long attempt is still alive, so 'reclaim' leaves it alone
- `asgard siege inbox` — the messages one run sent and received — reading them leaves the mail unread
- `asgard siege mark` — mark an attempt stopped or outcome_unknown — neither one closes the task
- `asgard siege mirror` — for hooks: carry one ticket transition onto the ledger
- `asgard siege note` — for hooks: stand one dispatched agent up on the ledger
- `asgard siege open` — open an attempt on one task — a task carries one live attempt at a time
- `asgard siege ready` — the tasks you can dispatch right now — everything they waited on is done
- `asgard siege reclaim` — take back attempts whose worker vanished without settling them
- `asgard siege refresh` — work out every task's status from its dependencies again
- `asgard siege reset` — wipe the siege record — it is all rebuilt from elsewhere, and the quest log stays
- `asgard siege send` — put a message in the run's mailbox — a finished report goes through 'done' instead
- `asgard siege settle` — close an attempt from the coordinator's side, when the worker left no report
- `asgard siege show` — one run in full — its tasks, what each waited on, and every attempt
- `asgard siege start` — open a run — the namespace for its tasks and the coordinator's mailbox
- `asgard siege unnote` — for hooks: close that agent's live attempt on the ledger
- `asgard siege waves` — the graph laid out as batches — everything in one batch can run side by side
- `asgard skills assign` — give one role this skill, in this project
- `asgard skills disable` — keep this project from reaching for a skill
- `asgard skills enable` — let this project use a skill again
- `asgard skills list` — the skills that shipped, the ones you installed, and the ones Asgard learned
- `asgard skills resolve` — what one role would be told to do, given this task
- `asgard skills run` — run a helper a skill ships with
- `asgard skills show` — print one skill exactly as the agents read it
- `asgard skills unassign` — take this skill back off a role, in this project
- `asgard start` — open the Asgard terminal (Heimdall) — chat, connect a provider, run tasks
- `asgard surface` — what your public API looks like next to a base ref — what broke, and who has to change
- `asgard sync` — bring the hooks, agents and skills up to date in every project you have set up
- `asgard thor` — how backend work is done here — the playbook for each verb, what to do next, and the gate
- `asgard tools list` — every tool one role can use, native and Claude Code alike
- `asgard tutor` — hand THIS diff back to you — what changed, and the questions only you can answer
- `asgard uninstall` — remove asgard (the uv tool only — your ~/.asgard data is kept)
- `asgard update` — update asgard to the latest release, or pin a version: update vX.Y.Z
- `asgard yggdrasil add` — write a new page — text that looks like a planted instruction is turned away
- `asgard yggdrasil approve` — say yes to a waiting proposal — it goes into the wiki
- `asgard yggdrasil ask` — ask something about Odin — answered from personal, episodic and project memory
- `asgard yggdrasil autosave` — let memories be saved without coming back to ask you every time
- `asgard yggdrasil backup` — keep copies of the wiki — make one, list them, restore, check, or prune
- `asgard yggdrasil connect` — point this project at the memory store your team shares, and set it up
- `asgard yggdrasil contradiction-seen` — set a contradiction aside — it is not resolved, and neither page changes
- `asgard yggdrasil contradictions` — pages that disagree with each other — you decide, nothing is fixed for you
- `asgard yggdrasil discard` — throw a waiting proposal away — nothing is written
- `asgard yggdrasil episodes` — search the raw session transcripts — rebuilt from the logs, so treat it as a lead, not a source. an empty query gives yo
- `asgard yggdrasil export-okf` — write your personal memory out as a read-only OKF v0.1 bundle
- `asgard yggdrasil graph` — read the memory as a graph — what it grew around, why two pages are connected, what sits around one, and how many clumps
- `asgard yggdrasil ingest` — take something in — if a page already says nearly this, it grows instead
- `asgard yggdrasil lint` — how the wiki is holding up — broken links, pages going stale, duplicates, size, open contradictions
- `asgard yggdrasil mcp` — serve the project memory store over MCP — register it once, for your user
- `asgard yggdrasil merge` — fold one page into another — what to do when the wiki has outgrown its budget
- `asgard yggdrasil norn-restore` — bring back a page a norn pass filed away
- `asgard yggdrasil norn` — let the wiki grow up — a model suggests the edits, plain code makes them. shows only
- `asgard yggdrasil obsidian` — set the wiki up as an Obsidian vault and open it there
- `asgard yggdrasil path` — print or configure the personal memory directory
- `asgard yggdrasil pattern` — notice how Odin works, from past turns. shows only — '--apply' writes it down
- `asgard yggdrasil project-approve` — say yes to one waiting project-memory proposal, and write it
- `asgard yggdrasil project-evolve` — find project records that have gone stale, doubled up, or started disagreeing. shows only — '--apply' queues the fixes f
- `asgard yggdrasil project-ingest` — throw documents at it — pdf, docx, hwp, md — and they land in project memory
- `asgard yggdrasil project-learn` — set up what Hindsight watches, and the picture it keeps of the project
- `asgard yggdrasil project-reflect` — have a model think over everything the project remembers — take it as advice
- `asgard yggdrasil project-rehydrate` — replay the project records Git holds back into the store
- `asgard yggdrasil project-scan` — which code and docs are worth putting into project memory — a look first
- `asgard yggdrasil project-sync` — send the code and docs you approved into the project memory store
- `asgard yggdrasil proposals` — what the agent wants to remember, waiting on your say-so
- `asgard yggdrasil provider` — which model looks after your personal memory — see it, or change it
- `asgard yggdrasil query` — search the wiki — plain text search, no model, and every hit is counted
- `asgard yggdrasil recall` — the memory this question would pull in (nothing, if it is off or nothing matches)
- `asgard yggdrasil reindex` — rebuild index.md and state.db from pages/, which is the real record
- `asgard yggdrasil remove` — delete a page, and rebuild the index around the gap
- `asgard yggdrasil semantic` — search by meaning rather than words — where it stands, and how to turn it on
- `asgard yggdrasil show` — print one page, frontmatter and all
- `asgard yggdrasil snapshot` — the memory a new session starts with (nothing, if that is switched off)
- `asgard yggdrasil sync-turn` — for hooks: keep one finished turn, read as JSON from stdin
- `asgard yggdrasil sync` — keep the wiki in step with a shared folder or a git remote
- `asgard yggdrasil tick` — for hooks: the end-of-turn nudges, in one process

## Relations by file

- `src/asgard/studio/projects.py` — db: conn.execute?×59
- `src/asgard/studio/teams.py` — db: conn.execute?×49
- `src/asgard/cli/memory.py` — commands: yggdrasil add, yggdrasil approve, yggdrasil ask, yggdrasil autosave, yggdrasil backup, yggdrasil connect, yggdrasil contradiction-seen, yggdrasil contradictions, yggdrasil discard, yggdrasil episodes, yggdrasil export-okf, yggdrasil graph, yggdrasil ingest, yggdrasil lint, yggdrasil mcp, yggdrasil merge, yggdrasil norn, yggdrasil norn-restore, yggdrasil obsidian, yggdrasil path, yggdrasil pattern, yggdrasil project-approve, yggdrasil project-evolve, yggdrasil project-ingest, yggdrasil project-learn, yggdrasil project-reflect, yggdrasil project-rehydrate, yggdrasil project-scan, yggdrasil project-sync, yggdrasil proposals, yggdrasil provider, yggdrasil query, yggdrasil recall, yggdrasil reindex, yggdrasil remove, yggdrasil semantic, yggdrasil show, yggdrasil snapshot, yggdrasil sync, yggdrasil sync-turn, yggdrasil tick
- `src/asgard/orchestration/board.py` — db: conn.execute?×30
- `src/asgard/cli/siege.py` — commands: siege add, siege answer, siege ask, siege blocked, siege check, siege close, siege decide, siege done, siege escalate, siege force, siege gate, siege gates, siege heartbeat, siege inbox, siege mark, siege mirror, siege note, siege open, siege ready, siege reclaim, siege refresh, siege reset, siege send, siege settle, siege show, siege start, siege unnote, siege waves
- `src/asgard/memory/index.py` — db: conn.execute?×24, conn.executemany?×2
- `src/asgard/orchestration/dispatch.py` — db: conn.execute?×26
- `src/asgard/studio/tickets/crud.py` — db: conn.execute?×25
- `src/asgard/studio/tickets/views.py` — db: conn.execute?×24
- `src/asgard/cli/ticket.py` — commands: open map, open memory, open studio, ticket board, ticket comment, ticket cycle, ticket delete, ticket doc, ticket doctor, ticket evidence, ticket import, ticket link, ticket list, ticket milestone, ticket move, ticket new, ticket project, ticket set, ticket show, ticket team, ticket triage, ticket update
- `src/asgard/cli/agent.py` — commands: auth login, auth logout, auth status, einherjar bind, einherjar config, einherjar create, einherjar delete, einherjar describe, einherjar export, einherjar identity, einherjar import, einherjar list, einherjar open, einherjar rename, einherjar show, einherjar unbind, einherjar use, einherjar where, einherjar windows
- `src/asgard/orchestration/mail.py` — db: conn.execute?×18, conn.executemany?
- `src/asgard/cli/root.py` — commands: budget?, completions?, craft?, doctor?, freyja-gate?, health?, humanize?, init?, manual?, orchestrate?, run?, start?, surface?, sync?, thor?, tutor?, uninstall?, update?
- `src/asgard/cli/k6.py` — commands: automations add, automations disable, automations due, automations enable, automations history, automations list, automations remove, k6 baseline clear, k6 baseline set, k6 baseline show, k6 doctor, k6 gate, k6 report, k6 run, k6 scenarios, k6 selftest, k6 sync
- `src/asgard/orchestration/store.py` — db: conn.execute?×14
- `src/asgard/studio/db.py` — db: conn.execute?×12
- `src/asgard/studio/documents.py` — db: conn.execute?×12
- `src/asgard/studio/legacy.py` — db: conn.execute?×12
- `src/asgard/agent/episodes.py` — db: conn.execute?×11
- `src/asgard/cli/evolve.py` — commands: evolve approve, evolve archive, evolve bench, evolve curate, evolve list, evolve nudge, evolve polish, evolve reject, evolve restore, evolve scan, evolve show
- `src/asgard/cli/skills.py` — commands: plugins install, plugins list, skills assign, skills disable, skills enable, skills list, skills resolve, skills run, skills show, skills unassign, tools list
- `src/asgard/project_memory/documents.py` — db: conn.execute?×10
- `src/asgard/cli/map.py` — commands: map check, map context, map impact, map list, map scan, map trace, map update, map why, setup map
- `src/asgard/agent/evicted.py` — db: conn.execute?×8
- `src/asgard/studio/tickets/labels.py` — db: conn.execute?×8
- `src/asgard/cli/office.py` — commands: office build, office fill, office outline, office read, office render, office template, office verify
- `src/asgard/cli/role.py` — commands: mode pick, mode reset, mode set, mode show, role list, role model, role run
- `src/asgard/studio/tickets/triage.py` — db: conn.execute?×7
- `src/asgard/studio/tickets/_core.py` — db: conn.execute?×6
- `src/asgard/studio/tickets/evidence.py` — db: conn.execute?×4 · calls: failed_rate?, rate_per_s?
- `src/asgard/cli/review.py` — commands: review cancel, review decide, review list, review show
- `src/asgard/commands/studio/load.py` — calls: count?, failed?, rate_per_s?
- `src/asgard/io_sqlite.py` — db: conn.execute?×3
- `src/asgard/openai_codex.py` — calls: httpx.get?, httpx.post? · uses: openai
- `src/asgard/agent/session.py` — uses: anthropic, openai
- `benchmarks/shortcut-recall/harness.py` — db: conn.execute?

## Trace seeds

> Exact node ids — copy into `asgard map trace --from <id>` or `asgard map impact <id>`.

- commands: `command:auth_login` · `command:auth_logout` · `command:auth_status` · `command:automations_add` · `command:automations_disable` · `command:automations_due` · `command:automations_enable` · `command:automations_history` · `command:automations_list` · `command:automations_remove` · `command:budget` · `command:completions` · `command:craft` · `command:doctor` · `command:einherjar_bind` · `command:einherjar_config` · `command:einherjar_create` · `command:einherjar_delete` · `command:einherjar_describe` · `command:einherjar_export` · `command:einherjar_identity` · `command:einherjar_import` · `command:einherjar_list` · `command:einherjar_open` · `command:einherjar_rename` · `command:einherjar_show` · `command:einherjar_unbind` · `command:einherjar_use` · `command:einherjar_where` · `command:einherjar_windows` · `command:evolve_approve` · `command:evolve_archive` · `command:evolve_bench` · `command:evolve_curate` · `command:evolve_list` · `command:evolve_nudge` · `command:evolve_polish` · `command:evolve_reject` · `command:evolve_restore` · `command:evolve_scan` (+154 more — `asgard map list --kind command`)

## Navigation contract

- Trace edges with `asgard map trace --from <node-id>` (`--kinds touches,calls` filters edge kinds).
- Enumerate node ids with `asgard map list [--kind route]`; both directions at once with `asgard map impact <node-id>`.
- Do not read this catalog whole on large repos — `asgard map context --query "<task>"` returns the bounded, task-ranked slice.
- A missing edge is not evidence of absence — this graph is static-lane adjacency, not an exhaustive dependency inventory.
