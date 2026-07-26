---
name: codebase-design
description: Design deep modules — a lot of behaviour behind a small interface, placed at a clean seam. Use when adding a module, widening an interface, refactoring structure, or when a change keeps rippling across files.
---

# Codebase design

Agents accelerate entropy: code arrives faster than the design that should hold it. The defence is
not more layers but **depth** — the ratio of behaviour hidden to interface exposed.

## Depth before placement

1. Measure the module you are about to touch: how much does a caller have to know to use it
   correctly? Every parameter, ordering rule, error case, and "call this first" is interface cost.
   A module whose interface cost approaches its behaviour is a pass-through — remove it or absorb it.
2. Prefer one module that answers the whole question over three that each answer a third of it.
   Two thin wrappers around one call are worse than the call.
3. A special case belongs *inside* the module that owns the general case. Pushing it out to every
   caller is how one decision becomes twelve call sites.
4. Name the module for what it guarantees, not for the layer it sits in. `retry_http` guarantees
   nothing; `idempotent_send` does.

## Design it twice

Before committing to a structure, sketch a second one that differs in **where the boundary falls**
— not in naming or file layout. Compare them on: what a caller must know, what breaks when the
requirement shifts one step, and how much of the change is reversible. Write down the loser and why
it lost; that sentence is what stops the next session from re-litigating it.

## Seams

- The right seam is where the change stops. If a one-line requirement change forces edits in three
  files, the seam is in the wrong place — say so before adding the fourth.
- Test through the interface you are claiming is small. A test that has to reach past the interface
  is evidence the interface is not the real boundary.
- Dependency direction is part of the design: a lower layer that reaches upward, a new cycle, or a
  reach into another module's internals is a defect even when it compiles.

## When this fires mid-task

Scope discipline still wins (Canon 7). If the design flaw is outside the assigned change, **record
it in the report with `file:line` evidence** and implement the smallest correct change inside scope.
Fixing the ball of mud you noticed is a separate quest, not a bonus.
