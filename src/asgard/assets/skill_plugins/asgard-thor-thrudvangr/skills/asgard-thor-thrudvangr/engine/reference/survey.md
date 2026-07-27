# survey — learn what governs here, before you write anything

Take this on the first backend task in a repository, or whenever you cannot state the conventions in
one line. It costs a few reads and saves the file that does not belong.

**This verb persists.** `asgard thor survey` writes what it learns to `.asgard/thor/stack.json`, so
the next session starts from your answers instead of re-deriving them. That matters beyond the saved
reads: a repository re-read from scratch every time gets read slightly differently every time, and
those differences harden into per-file conventions.

## The split — the machine detects, you judge

Step 1 is already done for you. `asgard thor survey` reads the manifests and reports the ecosystem,
the languages present, and the candidate verifier commands — all of it file-backed, none of it
guessed. Steps 2–5 are yours, because they need the code read.

Record each answer as you get it:

    asgard thor survey --note 'layering=<one line>'
    asgard thor survey --note 'errors=<one line>' --note 'transactions=<one line>'

Valid keys: `layering`, `errors`, `transactions`, `cleanup`. The command lists the blanks that remain
and refuses keys it does not know — a free-form record is one the next session cannot read.

**Never fill a blank with a guess.** An empty field costs one read next session; a wrong field costs
a file that does not belong, and it will be believed. Leaving it blank is the honest answer.

## Procedure

1. **Find the manifest** — `asgard thor survey` does this. Confirm what it reports matches what you
   see; do not assume a framework from directory names alone.
2. **Read two or three modules closest to where you will write** — not the ones with the best names,
   the ones nearest the write location. From them, answer four questions in one line each:
   - **Layering** — what depends on what, and which direction imports flow.
   - **Error propagation** — codes or exceptions? a catalog, or ad-hoc strings?
   - **Resource cleanup** — who closes what, and where the boundary is.
   - **Transaction boundary** — which layer owns it.
3. **Find the verifier the repo already ships.** A test command, a linter config, an architecture
   test, a CI workflow. Run it once now, on an untouched tree, so you know what green looks like
   before you change anything. A suite that was already red is not evidence about your change.
4. **Check what `asgard craft` and `asgard thor gate` can see here.** Run both against `HEAD` on the
   clean tree. Their `미판정`/`unmeasured` lines tell you which rules will be silent for this
   language — that silence is your burden for the rest of the task.
5. **Language canon.** If the language is one you have not established conventions for in this
   project, load `asgard-thor-thjalfi` and name the governing standard and the ecosystem's verifier.

## The hierarchy this establishes (it governs every later verb)

**The codebase outranks the canon.** Where existing structure conflicts with any Thor skill, follow
the existing structure and record the discrepancy in the report. Do not silently "fix" the repo's
style as a side effect of your assignment (Canon 7).

Where the repo has *not* decided something, that gap is a finding — report it rather than inventing
an answer the next file will contradict.

## Hand back

One line, and carry it into every later verb:

    Detected: <runtime+framework>, <storage/access>, <layering>, <error model>; verifier: <command>

If `asgard thor` says the record is **stale**, the manifests changed since it was written. Dependency
changes and convention changes travel together often enough that the judgement fields are suspect
too — re-read before trusting them.

## Next

`shape` for new work · `diagnose` if something is broken · `squad` if the change spans surfaces.
