"""주석 계약 — 주석과 독스트링 문체의 단일 소스. 판정기는 asgard/craft_note.py.

Bragi·seal과 같은 구조다: 프롬프트가 "이렇게 써라"를, 판정기가 "그렇게 썼는지"를 맡는다.
계약만 있으면 순응이 흔들리고, 판정기만 있으면 매 턴 재작성 비용이 든다.

세 계약의 경계:
  seal      커밋 메시지 — 저장소 이력에 남는 글
  bragi     보고문 — 사용자가 화면에서 읽는 글
  이 파일    주석·독스트링 — 다음에 이 코드를 여는 사람이 읽는 글

문법(조사 띄어쓰기·준말 금지·한 문장 한 언어)은 여기서 다시 적지 않는다. Bragi 계약이 이미
"보고문·문서·주석·커밋"에 걸쳐 계약하고 있고, 같은 규칙을 두 곳에 적으면 갈라진다.

품질 규칙의 출처 (26-08-01 자료조사):
  • Ousterhout, "A Philosophy of Software Design" (2018) 13장 — 지도 원칙 "comments should
    describe things that aren't obvious from the code", 상세도 계층(코드보다 낮으면 정밀도,
    높으면 의도, 같으면 코드의 반복), 적신호 "긴 주석이 필요한 이름은 추상이 잘못된 것".
  • Kernighan & Plauger, "The Elements of Programming Style" — "Don't comment bad code —
    rewrite it", "Make sure comments and code agree".
  • Martin, "Clean Code" 4장 — 나쁜 주석 분류(중복·오해·소음·이력·주석 처리한 코드·귀속).
  • PEP 257 / Google Python Style Guide — 독스트링은 계약(무엇을 하는가·인자·반환·예외)이지
    구현 설명이 아니다.
  • 국립국어원 「쉬운 공공언어 쓰기 길잡이」 — 공공언어의 요건은 소통성과 정확성. 읽는 사람이
    한 번에 알아듣는 쉬운 말로 쓰고, 어려운 한자어·번역투·지나친 압축을 피한다.
"""

COMMENT_CANON = """\
## Comment Contract — write for whoever opens this file next

A comment is read by someone who has the code in front of them and still does not understand it.
Everything below follows from that one reader.

### Why a comment exists

- **Say what the code cannot.** The constraint, the reason, the consequence, the measurement, the
  thing that breaks if you change it. A comment that restates the line it sits on is deletable.
- **Aim above or below the code, never level with it.** Below = precision the code omits (units,
  bounds, what `None` means, what stays true). Above = intent the code cannot show. Level with the
  code is repetition.
- **A name that needs a long comment is the defect.** Fix the name or the abstraction first, then
  write the shorter comment.
- **Comment and code must agree.** A stale comment is worse than no comment — it is believed. When
  you change behavior, change the comment in the same edit.
- **Do not comment out code.** Delete it; the history keeps it. No dated change logs, no author
  bylines, no `# ---- 여기까지 ----` markers.

### How it must read

This is where correct-but-unreadable comments come from, and it is the rule most often broken.

- **Explain, do not liken.** Code does not win, lose, stand, sit, live, eat, carry, wear, leak, or
  pay. Write the mechanism instead of the image: `# 임베더가 선다` means `# 임베더가 준비된다` — but
  only the writer knows that. An idiom a working developer actually says (`프로세스가 죽는다`,
  `메모리가 샌다`) is fine; an invented image is not.
- **Use the word that is in the dictionary.** Do not coin a term to save a syllable, and do not
  promote a metaphor into a term of art. If a reader has to learn your private vocabulary before
  reading the file, the comment has failed.
- **Name the code.** A comment should point at something the reader can search for — a path, a
  function, a constant, a flag, a config key. This is a habit, not a syntax check: a paragraph of
  design rationale in Korean legitimately contains no Latin identifier.
- **A comment is a note, not an essay.** No maxim to open, no moral to close, no suspense, no
  rhetorical question, no second person. State the finding first.
- **One sentence, one subject.** Korean lets you drop the subject; drop it only when exactly one
  candidate exists in the sentence. When two things could be doing the verb, name the one that is.
- **Cut what is true of the project rather than of this code.** If the sentence would survive
  unchanged in a different file, it belongs in a document, not here.

### When you rewrite a comment

Register is the only thing that changes. **Every fact survives verbatim** — measurements, dates,
issue ids, incident references, file paths, thresholds, the reason a value is what it is. A rewrite
that loses one of those is a defect, not a style choice: rewriting
`# 실측(26-07-29): 페이지 2장·vec 0행` into `# 실측 결과 인덱스가 비어 있었다` destroys the comment.

| Riddle (✗) | Record (✓) |
|---|---|
| `# 문지기는 commands.loopback 한 벌` | `# 루프백 접근 검사는 commands.loopback 한 곳에 있다` |
| `# 역할 정체성은 색이 아니라 글리프 모양이 진다` | `# 역할은 색이 아니라 글리프 모양으로 구분한다` |
| `# 임베더가 선다는 것으로 끝내면 안 된다` | `# 임베더가 준비된 것만으로는 부족하다` |
| `# 팀에는 뱅크가 아니라 저장소가 나른다` | `# 팀에는 뱅크가 아니라 저장소가 전달한다` |
| `# 사용자는 규칙이 먹은 줄 안다` | `# 사용자는 규칙이 적용된 것으로 오해한다` |
| `# 텍스트 한 벌` | `# 파일을 통째로 읽는다` |
| `# 명시 옵션이 있으면 그쪽이 이긴다` | `# 명시 옵션이 있으면 그쪽이 우선한다` |
| `# 두 레인은 서로 비의존` | `# 두 레인은 서로 의존하지 않는다` |
| `# 무매칭이면 원문을 그대로 둔다` | `# 일치가 없으면 원문을 그대로 둔다` |
| `# 불요한 재판정을 막는다` | `# 불필요한 재판정을 막는다` |
| `# 무임포트로 판정한다` | `# 임포트하지 않고 판정한다` |

### Docstrings

The first line is the contract, not the story: what the function does or returns, in one sentence.
Then, only if the caller needs it — arguments, return shape, raised errors, and what the caller
must guarantee. Design rationale (why this module exists, what was measured, what was rejected)
belongs in the module docstring, where a reader looking for it can find it, not spread across every
function. Say what a `None` return means; that is the single most-omitted fact in a codebase.

### Checking

`asgard craft` judges the comments this change added (`note-metaphor`, `note-jargon`) against a
closed dictionary and reports the plain wording for each hit. It is a ratchet — comments that were
already there are not your debt, and the check never fires on English comments.

`asgard craft --fix` repairs what it can prove and re-verifies; the rest is yours. The test is not
which rule fired but whether the standard wording is **already settled** — a rewrite this repository
has made the same way every time it made it. There the machine is reusing a decision, not taking
one, so it applies it. Where the dictionary offers candidates the decision is still open, and taking
it is a reading of what the sentence meant: `접지` is either `근거 대조` or `근거 확인`, and checking
one thing against another is not confirming that a thing is so. Both rules have settled entries and
open ones — `note-jargon` firing does not mean a repair is coming, and `note-metaphor` firing does
not mean one is not.

Position counts as much as the word. Some coined words sit where their standard form cannot: `비의존`
reads as a noun but `의존하지 않는다` is a clause, so `# 두 레인은 서로 비의존이다` is repaired and
`# 두 레인은 서로 비의존` is refused. The refusal says the sentence has to be rebuilt, because
rebuilding it is a rewrite, not a substitution.

So the refusal is the product. For every hit it will not repair, `--fix` names the standard
candidates or says what has to be rebuilt, and you choose in one step instead of rediscovering the
table. It refuses any repair that would drop a fact — the rule above is a guard in the engine, not
only advice — and it rewrites comment and docstring text only, never code bytes. Code shape (unit
length, nesting depth, resource lifetime, cost) is never repaired at all: where to cut a function is
a judgment, and a linter that reshapes functions on its own produces worse code than one that
reports.

Repair does not ratchet. Judging blocks only on what this change made worse, but `--fix` repairs
every qualifying comment in a file it judged, including lines this change never touched — so it will
report rewriting files you did not write in. A repaired file has already changed on disk, so re-read
it before you edit it — an edit written against your stale copy puts the repaired wording back. The
machine narrows, you choose, and `asgard craft` re-verifies.
"""


COMMENT_AGENTS_SECTION = """\
<!-- >>> asgard:comments >>> -->
## Asgard — Comments and Docstrings

A comment is read by someone who has the code in front of them and still does not understand it.
Write what the code cannot say: the constraint, the reason, the consequence, the measurement, the
thing that breaks if it changes. A comment level with the code repeats it — aim below it (units,
bounds, what `None` means) or above it (intent). If a name needs a long comment, fix the name.
Comment and code must agree; update both in the same edit. Never comment out code, and never leave
change logs or author bylines — the history holds those.

**Explain, do not liken.** Code does not win, stand, live, eat, carry, or pay. Write the mechanism,
not the image (`# 임베더가 선다` → `# 임베더가 준비된다`); a real developer idiom (`프로세스가 죽는다`)
is fine, an invented one is not. Use words that are in the dictionary — do not coin a term to save
a syllable, and do not promote a metaphor into a term of art. Point at something searchable (a path,
function, constant, or config key) where the sentence allows it. No maxim to open, no moral to
close, no rhetorical question, no second person. In Korean, drop the subject only when exactly one
candidate exists. Grammar follows the Bragi contract.

**When you rewrite a comment, only the register changes** — every measurement, date, issue id, path,
and threshold survives verbatim, and a rewrite that loses one is a defect, not a style choice.
Docstrings start with the contract (what it does or returns, one sentence), then only what a caller
needs; design rationale goes in the module docstring.

`asgard craft` checks the comments a change added and names the plain wording for each hit.
`asgard craft --fix` repairs only what is already settled — a rewrite this repository has made the
same way every time — and refuses every hit whose standard wording is still a choice, naming the
candidates so you decide in one step. Position counts: `비의존이다` is repaired, bare `비의존` is
refused, because `의존하지 않는다` is a clause and that sentence has to be rebuilt. Code shape is never
repaired. Repair does not ratchet — it also rewrites comments this change did not add — and it
rewrites files on disk, so re-read a repaired file before editing it or your stale copy puts the old
wording back.
<!-- <<< asgard:comments <<< -->
"""
