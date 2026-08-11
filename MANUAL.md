<!-- asgard:manual — scaffolded by `asgard init`. This marker lives in a comment, so it is never
     part of what agents receive; `asgard doctor` uses it to tell this file apart from an unrelated
     MANUAL.md that happened to already be in the repo. Deleting it changes nothing but that check.

==============================================================================
 Project Manual — this file is yours.
==============================================================================

 AGENTS.md next to this file is Asgard's own identity, and it is replaced
 wholesale on every `asgard sync`. This file is the opposite: Asgard never
 rewrites it. Whatever you put here is injected into every agent role, in every
 mode — Claude Code, Cursor, Codex, and the native `asgard start` loop.

 THIS FILE IS FOR **THIS** REPOSITORY
   Rules you want in every project go in `~/.asgard/MANUAL.md` instead. Both are
   loaded: the machine-wide one first, this one after. Where the two collide,
   this file wins, because it is the more specific of the two.

 HOW TO USE IT
   Write your project's rules below, outside the comment markers. Plain markdown.
   Be specific and checkable — a rule an agent cannot verify is a rule the gate
   cannot enforce. Nothing here is active while it stays commented out.

 SPLITTING IT UP
   Long manuals can be split into `.asgard/manual/*.md`; those are appended in
   filename order after this file. A common layout:

       MANUAL.md                  overview + the rules that always apply
       .asgard/manual/10-api.md
       .asgard/manual/20-database.md
       .asgard/manual/30-naming.md

   `.asgard/MANUAL.md` also works if you would rather keep it out of the repo
   root; it is appended after this file. The names CUSTOM_MANUAL.md, CUSTOM.md,
   and RULES.md are accepted in either location, in that order of precedence —
   only one per directory is ever loaded, and `asgard manual` says which won.

 WHAT IT CANNOT DO
   The manual adds to the Canon; it never replaces it. Canon 2 (safety),
   3 (consent for destructive work), and 4 (secret protection) still win. On any
   other conflict the agent follows your manual and says which rule it applied.

 KNOBS (`.asgard/asgard-setting-project.json`)
   {"manual": {"mode": "off"}}        turn the layer off entirely
   {"manual": {"max_chars": 24000}}   raise the injection size limit (default 16000)

 CHECK IT
   `asgard manual`          what is loaded, from where, how big
   `asgard manual --show`   the exact text the agents receive
==============================================================================
-->

## 오딘에게 보고하는 말투

본체 계약(AGENTS.md 의 Bragi 절, `Explain, do not compress`)이 정본이고 여기서 되풀이하지
않는다. 이 저장소에만 더 얹는 것 둘:

- 신화 어휘(Asgard·Odin·Heimdall·Bifröst)는 첫 줄이나 마지막 줄에 한 번, 없어도 문장이
  성립할 때만. 매 문단에 넣지 않는다.
- 표와 목록은 항목이 셋 이상일 때만. 두 개짜리 표는 문장 두 개로 쓴다.

기준: 이 저장소를 모르는 동료가 한 번 읽고 "무슨 일이 있었고 지금 뭘 하면 되는지" 말할 수
있으면 통과다.

<!-- EXAMPLE — delete the comment marker on the line above this block and the one
     after it, then edit. Until you do, none of it is loaded.

## API

- Every route lives under `/api/v1`; a new top-level prefix needs Odin's call.
- Errors return `{"error": {"code", "message"}}` — never a bare string.

## Database

- Every migration ships with a working `down`. Verify with `make db.rollback`.
- No raw SQL in handlers; queries live in `repository/`.

## Naming

- Files `snake_case`, React components `PascalCase`, env vars `SCREAMING_SNAKE`.

-->
