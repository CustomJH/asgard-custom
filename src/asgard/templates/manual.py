"""매뉴얼 시작 템플릿 두 벌 — 오딘이 규칙을 쓰는 자리 (공통 / 이 프로젝트).

자리가 두 층인 이유 (오딘 지시 26-07-29): "커밋은 이렇게 써라"는 프로젝트마다 다시 쓸 것이 아니고,
"이 저장소의 라우트는 /api/v1"은 남의 저장소에 새면 안 된다. 그래서 `~/.asgard/MANUAL.md`(공통)와
`<리포>/MANUAL.md`(이 프로젝트)를 따로 배송한다. 두 템플릿은 안내문만 다르고 계약은 같다.

프로젝트 층이 리포 루트인 이유: `.asgard/` 안에 있으면 사용자가 파일의 존재를 모른다.
`AGENTS.md` 옆에 나란히 놓여야 "저건 아스가르드 것, 이건 내 것"이 첫 화면에서 읽힌다.

전부 HTML 주석이다. 이유가 있다: `manual._meaningful()`이 주석을 걷어낸 뒤 빈 문자열이면 매뉴얼을
"없음"으로 판정하므로, 이 파일이 깔려 있어도 **프롬프트는 한 글자도 안 늘어난다**. 안내문을 배송해
발견성을 얻으면서 토큰 회귀는 0 — 사용자가 주석 밖에 한 줄이라도 쓰는 순간 켜진다.

주석 **두 덩이**로 갈라 둔 것도 의도다: 예시가 안내문과 같은 덩이에 있으면 "예시만 켜기"가 안내문까지
같이 꺼내 온다. 그리고 본문 어디에도 주석 종료 기호를 글자로 쓰지 않는다 — 주석 안의 그 세 글자는
거기서 주석을 끝내 버려서, 안내문 절반이 그대로 프롬프트에 실린다.

첫 줄의 `asgard:manual` 표식은 `manual.has_marker()`가 읽는다: 루트 `MANUAL.md`는 흔한 이름이라
이미 그 이름의 제품 문서를 가진 리포에도 존재할 수 있고, doctor는 그 둘을 구분해 물어봐야 한다.

setup/sync는 이 파일을 **있으면 덮지 않는다** (`_policy` = keep). 사용자 소유 내용이라 재스캐폴드가
규칙을 날리면 그건 Canon 3 급 사고다."""

MANUAL_STARTER_MD = """\
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
"""

COMMON_MANUAL_STARTER_MD = """\
<!-- asgard:manual — scaffolded by `asgard init`. This marker lives in a comment, so it is never
     part of what agents receive; `asgard doctor` uses it to tell this file apart from an unrelated
     MANUAL.md. Deleting it changes nothing but that check.

==============================================================================
 Your manual — every project on this machine.
==============================================================================

 Rules you write here reach every agent, in every mode, in EVERY repository you
 open with Asgard. This is where "how I want work done" lives — the habits you
 would otherwise repeat in each project's manual.

 Good candidates
   - How commits and PRs should read.
   - Which language you want reports and code comments written in.
   - Review habits: what must be run before something is called done.
   - Tools and idioms you always want reached for (or never).

 NOT here
   Anything true of one repository only — its routes, its schema, its build
   command. That belongs in `MANUAL.md` at that repository's root. Both are
   loaded (this file first, the project's after); where they collide, the
   project's rule wins because it is the more specific of the two.

 HOW TO USE IT
   Write below, outside the comment markers. Plain markdown. Be specific and
   checkable. Nothing here is active while it stays commented out.
   Split long manuals into `manual/*.md` next to this file (filename order).

 WHAT IT CANNOT DO
   The manual adds to the Canon; it never replaces it. Canon 2 (safety),
   3 (consent for destructive work), and 4 (secret protection) still win.

 KNOBS (`asgard-setting-global.json`, next to this file)
   {"manual": {"mode": "off"}}        turn the layer off on this machine
   {"manual": {"max_chars": 24000}}   raise the injection size limit (default 16000)

 CHECK IT
   `asgard manual`          what is loaded, from where, how big
   `asgard manual --show`   the exact text the agents receive
==============================================================================
-->

<!-- EXAMPLE — delete the comment marker on the line above this block and the one
     after it, then edit. Until you do, none of it is loaded.

## Reports

- Write reports in the language I wrote to you in.
- Lead with what changed and what was verified; skip the preamble.

## Done means verified

- Never call something done without showing the command you ran and its output.

-->
"""
