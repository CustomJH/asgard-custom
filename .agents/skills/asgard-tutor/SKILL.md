---
name: asgard-tutor
description: Conduct Odin's one-on-one tutor session and write his own sentence back into the record — one question per turn, no lecture, and never his answer supplied by you. Load when he asks to be tutored, quizzed, or walked through what just changed (튜터, 나한테 물어봐 줘, 시험해줘, 가르쳐줘, tutor me, quiz me), and when `asgard tutor` leaves an open question after a change.
disable-model-invocation: true
allowed-tools: Bash(asgard tutor *), Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show asgard-tutor` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
