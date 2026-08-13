---
name: prototype
description: Answer a design question with throwaway runnable code. Use when reading and discussion cannot settle how logic should behave or what a UI should look like.
---

# Prototype

A prototype is throwaway code that answers one named question.

1. Name the question first; it decides the shape. Logic or state questions get a runnable demo that
   pushes the model through the hard cases. Look-and-feel questions get a few radically different
   variations behind one entry point.
2. Build the demo as **one self-contained HTML file** — plain HTML, CSS, and JS, no build step and
   no server — so the person who has to answer the question opens it by double-click and drives it
   themselves. Inside it: a labelled state panel showing the full model in their own domain language,
   free-play buttons available at all times, and a set of tabbed walkthroughs, each a named scenario
   with the ordered buttons to press underneath it. Keep the logic in a plain module the real code
   could lift; the shell around it is the throwaway part.
3. Keep it disposable: place it near the code it probes, name it so a casual reader sees it is a
   prototype, keep state in memory, and skip tests, error handling, and abstraction.
4. Fold the validated decision back into the plan, spec, or `CONTEXT.md`/ADR, recording the verdict
   together with the question it settled.

## Throwaway is not deleted

The prototype is the primary source for the decision it settled, and deleting it turns the record
into somebody's summary of it. Commit it as runnable evidence on a throwaway `prototype/<name>`
branch off main, and leave a pointer to that branch on the quest or issue that implements the
decision. Mainline keeps only the validated decision; the exploration stays findable by anyone who
later asks why.

Finish when the question has a verdict a plan can rely on, the verdict is recorded where the plan
will read it, and the prototype is parked on its own branch rather than sitting in mainline where
somebody could mistake it for production.
