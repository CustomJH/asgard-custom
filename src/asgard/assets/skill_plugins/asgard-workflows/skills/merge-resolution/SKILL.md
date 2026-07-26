---
name: merge-resolution
description: Resolve an in-progress merge or rebase conflict hunk by hunk, by intent rather than by text. Use when conflict markers are present or a merge/rebase is stopped mid-operation.
---

# Merge resolution

A conflict is two intents that met, not two blobs of text. Resolving by shape — keeping the longer
side, keeping "ours", accepting both — silently discards one of them.

## Never abort

`git merge --abort` / `git rebase --abort` throws away the resolution work **and** the information
you just gathered about why the two sides diverged. Finish the operation. If the merge turns out to
be genuinely wrong, that is a decision to report, not a command to run.

## Per hunk, in order

1. **Read both sides in full**, including the context above and below the markers. A hunk that looks
   like a rename is often a rename plus a behaviour change.
2. **Trace each side to its origin**: `git log --merge -p <file>` for the commits that touched it,
   and the branch's own commit message or ticket. The question is *what was each side trying to
   accomplish* — not which is newer.
3. **Resolve to the union of intents**, not the union of lines. If both sides added a guard, keep one
   guard that covers both conditions. If one side renamed what the other side calls, apply the rename
   to the other side's new code too — that call site is not in the conflict, and it is the classic
   silent breakage.
4. If the two intents genuinely contradict, that is a decision, not a merge: stop, name both intents
   and their sources, and escalate. Picking one because it is easier is fabrication.

## After the last hunk

- Search the whole file for leftover markers (`<<<<<<<`, `=======`, `>>>>>>>`) before staging — a
  marker inside a string or comment survives a compile.
- Re-run the project's checks. A merge that compiles is not a merge that works: the two sides'
  behaviours were never executed together before this moment.
- Grep for symbols either side renamed or removed, across the whole tree. Conflict markers only
  appear where both sides edited the *same* lines; the breakage lives where only one did.
- Then complete the operation (`git merge --continue` / `git rebase --continue`) and report which
  hunks were resolved to which intent.
