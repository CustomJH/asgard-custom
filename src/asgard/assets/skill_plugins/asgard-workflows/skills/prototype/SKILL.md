---
name: prototype
description: Answer a design question with throwaway runnable code. Use when reading and discussion cannot settle how logic should behave or what a UI should look like.
---

# Prototype

A prototype is throwaway code that answers one named question.

1. Name the question first; it decides the shape. Logic or state questions get a minimal runnable script that pushes the model through hard cases. Look-and-feel questions get a few radically different variations behind one entry point.
2. Keep it disposable: place it near the code it probes, name it so a casual reader sees it is a prototype, keep state in memory, and skip tests, error handling, and abstraction.
3. One command must run it. Surface the full relevant state after every action or variant switch so the user can react to something concrete.
4. Fold the validated decision back into the plan, spec, or `CONTEXT.md`/ADR, recording the verdict together with the question it settled. The prototype itself never merges into mainline work.

Finish when the question has a verdict a plan can rely on and the prototype is marked or removed so nobody mistakes it for production.
