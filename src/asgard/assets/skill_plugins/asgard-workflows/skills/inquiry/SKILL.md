---
name: inquiry
description: Turn a decision the user cannot answer alone into a document for the one person who can.
disable-model-invocation: true
---

# Inquiry

`council` mines the user. An inquiry mines somebody else — the person who holds the knowledge the
user lacks — as a Markdown document they fill in async, or that the two of them work through in a
meeting.

**Interview the send, not the subject.** A normal grilling interrogates the topic, which is exactly
what the user cannot answer here; that is why they are sending it. So ask only about the send, which
they can always answer, and aim every question in the document at the gap between what the recipient
knows and what the user needs.

1. **Who is it going to?** In one exchange: the recipient's role, their expertise, and their
   relationship to the user. This fixes the document's tone and how much context it must carry.
   Done when you can say what this person knows that the user does not.
2. **What has to come back?** In one exchange: the specific decisions or facts the user cannot
   resolve alone. Done when you hold a concrete list of what the user must walk away able to decide.
3. **Write it.** Draft the questions against the gap from steps 1–2, in the structure below. Reuse
   the vocabulary already fixed in `CONTEXT.md` and the ADRs — a document that coins its own terms
   gets answered about the wrong thing. Write it where the repository already keeps such documents,
   otherwise `docs/inquiry/<slug>.md`, and report the path. Done when the file exists and every item
   from step 2 is covered by a question.

## Document structure

Order the questions most-important-first — async means one pass may be all you get — and group them
under `##` headings by theme once there are more than a handful. Every question is one idea, never
compound, with an answer stub directly beneath it, and a one-line reason only where the question
could be misread or could invite a throwaway answer.

<inquiry-template>

# <Title>

**Purpose:** why this exists and the decision riding on it.

**From:** <the user> — **To:** <the recipient> — **Where the answers go:** <what they feed>

## Context

One paragraph orienting a recipient who was not in the user's head. Enough to answer well, not a page.

## How to answer

The deadline and the rough effort. Partial answers and "I do not know" both carry information — flag
anything uncertain rather than skipping it.

## <Theme>

### What load is the system expected to carry at launch?

Why this matters: it decides whether we provision for burst traffic now or defer it.

>

## Anything else?

A closing catch-all: anything we did not ask that we should know?

</inquiry-template>
