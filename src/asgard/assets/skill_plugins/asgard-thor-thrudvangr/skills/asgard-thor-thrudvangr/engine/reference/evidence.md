# evidence — what qualifies a report

The last verb, and the one that decides whether any of the others counted. Load
`asgard-thor-tanngrisnir`.

## Running is not evaluating (Canon 10)

That a command ran and that a criterion was met are different facts. State which evidence maps to
which criterion, and leave the uncovered criteria listed as **unevaluated**. Never smear them
together into "done".

You do not render the verdict on your own work. Your output is the record; the verdict belongs
upstream.

## Assert on artifacts, not on narration

Not the response text, not one hopeful log line — the actual effect. The row that was written. The
file that exists with the content you expected. The endpoint's real response body. If you claim a
behavior, the evidence shows that behavior, not that a command exited zero.

Preserve failure through pipes:

    set -o pipefail && <test command> 2>&1 | tail -n 100

Without `pipefail`, the filter's success hides the test's failure, and you will report green on red.

## Numbers are measurements or they are not claims

Any performance or memory claim carries before and after numbers from a repeated run — "faster",
"no longer leaks", "much lighter" without figures are not claims, they are impressions (Canon 8).
Name what you measured, how many runs, and the spread.

## The report

    Changed files: <list>
    Decision summary: <what shape, and why — including any 3-for-2 trade you took>
    Evidence:
      <criterion> → <command + observed result>
      <criterion> → unevaluated (<why>)
    Gates: craft <result>; thor gate <result>; unmeasured <languages/rules>
    Out-of-scope findings: <list|none>
    Residual risk: <what could still be wrong, and where it would show>

## Kind check, before you send it

- Is the artifact the **kind** that was requested — working code, not a document about code?
- Did the verification prove the requested **behavior**, or only that a file exists?
- Was a bug fixed without a regression case? Then it is scheduled to recur. Add the case.
- Did you claim anything you did not run? Remove it or run it.

## Approval boundary

Irreversible data mutation, changes to a live environment, and externally visible side effects
(publish, push, deploy) are delivered as a **plan** — target, impact, rollback. You do not execute
them, and a task assignment is not approval. That approval belongs to Odin.
