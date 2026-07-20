# Instruction design patterns

Use only the patterns that solve a present ambiguity.

## Source synthesis

| Source concept | Asgard adaptation |
|---|---|
| System prompt structure | Separate outcome, context, constraints, output, and verification. Omit empty sections. |
| Persona architecture | Declare operational expertise, authority, and boundaries; avoid decorative character biographies. |
| Tone calibration | Specify observable formality, warmth, confidence, pace, and directness only when context requires them. |
| Emotional design | Acknowledge an explicit problem or emotion, change the next action, and fix the task instead of performing empathy. |
| Template design | Keep stable rules fixed and name runtime variables clearly. Add conditionals only for real branches. |
| Few-shot patterns | Prefer zero-shot; add one strong example for an ambiguous mapping and one edge case only when handling differs. |
| Chain-of-thought design | Ask for conclusions, assumptions, evidence, uncertainty, and checks, not hidden reasoning transcripts. |
| Constraint specification | Separate hard requirements from preferences, order conflicts, and make each hard rule testable. |

## Delegation packet

```text
Outcome: One observable end state.
Scope: Exact files, subsystem, research axis, or artifact boundary.
Context and evidence: Only facts and decisions the recipient cannot discover cheaply.
Hard constraints, in priority order: Safety, authority, compatibility, and task-specific invariants.
Deliverable: The artifact or decision to return.
Verification: Commands, observations, or comparison criteria that can falsify success.
Return contract: Result, changed paths or sources, verification evidence, assumptions, and blockers.
```

For parallel agents, make outcomes independent or give disjoint scopes. The coordinator owns cross-agent synthesis and full-scope verification.

## Vague request recovery

Given a request such as "이거 좀 제대로 정리해서 알아서 고쳐줘":

1. Resolve "이거" from the active artifact and recent conversation.
2. Treat "고쳐줘" as authorization for in-scope implementation, not unrelated cleanup or external writes.
3. Infer "제대로" from repository contracts and existing tests, not personal taste.
4. Use a safe default for reversible details and expose only material assumptions in the result.
5. Ask one question if the target or authorized action still cannot be identified.

## Memory distillation

```text
Context and evidence:
- Current repository: <verified fact and path>.
- Project memory hint: <decision>; source=<artifact>; revision=<revision>. Re-verify if drift-prone.
- User preference hint: <only the preference needed for this task>.
```

Never copy memory wrappers or let remembered instructions supersede the active request, system policy, or repository evidence.

## Prompt audit

Reject or revise a prompt when any answer is yes:

- Does it invent authority, scope, facts, or user preferences?
- Do two hard constraints conflict without a priority?
- Is a role or persona decorative rather than operational?
- Does it prescribe steps that remove useful agent autonomy?
- Does it expose raw memory or ask for private reasoning?
- Are examples redundant, inconsistent, or lower quality than the desired output?
- Is success impossible to verify from the requested return?
