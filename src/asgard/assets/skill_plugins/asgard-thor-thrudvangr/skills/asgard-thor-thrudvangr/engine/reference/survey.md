# survey — learn what governs here, before you write anything

Take this on the first backend task in a repository, or whenever you cannot state the conventions in
one line. It costs a few reads and saves the file that does not belong.

## Procedure

1. **Find the manifest.** `package.json`, `pom.xml`, `build.gradle(.kts)`, `pyproject.toml`,
   `go.mod`, `Cargo.toml`, `*.csproj`. Name the runtime, the framework, and the version. Do not
   assume a framework from directory names alone.
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

## Next

`shape` for new work · `diagnose` if something is broken · `squad` if the change spans surfaces.
