---
name: domain-modeling
description: Build shared domain language and durable decisions. Use when terms are overloaded, boundaries are unclear, or a costly architectural decision should survive the current session.
---

# Domain modeling

1. Read the nearest `CONTEXT.md` and relevant `docs/adr/` entries before introducing vocabulary.
2. Challenge overloaded terms with boundary and counterexample scenarios. Prefer one exact term per concept.
3. When a term resolves, update `CONTEXT.md` immediately. Create it lazily; keep it a glossary, not a spec or implementation map.
4. Add a short numbered ADR under `docs/adr/` only when the decision is costly to reverse and a future agent could reasonably reopen it. Record context, decision, and consequence.
5. Use the resolved terms consistently in plans, tests, tickets, and code-facing names.

Finish when every newly relied-on domain term has one definition and every durable decision has one source of truth.
