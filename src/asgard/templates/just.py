"""asgard-just 스킬 — 실행 표면(`just`) 계약.

이 스킬을 낸 이유는 명령이 없어서가 아니라 **주소가 없어서**다. 같은 저장소에서 테스트를
돌리는 방법이 세션마다 달랐다 — 어떤 턴은 `python -m pytest`, 어떤 턴은 `uv run pytest`,
어떤 턴은 README 에서 베낀 낡은 줄이었다. 매니페스트를 읽어 매번 다시 정하는 대신, 읽은
결과를 파일 하나에 적어 두고 그 파일을 부르게 한다. 그러면 사람과 에이전트가 같은 한 줄을 친다.

본문이 레시피 문법을 통째로 지는 이유: 에이전트가 새 절차를 적을 자리가 바로 이 파일이다.
문법을 모르면 관리 구역을 손으로 고치거나(다음 sync 에 사라진다) Justfile 을 피해 raw 명령으로
돌아간다 — 둘 다 표면이 갈라지는 길이다. 특히 **한 줄 = 한 셸**은 모르면 반드시 밟는다.

리졸버가 맨 낱말 `just` 를 안 잡는 것이 핵심이다. 영어 산문에서 그 낱말은 부사로 쉴 새 없이
나오고("just run the tests", "just a typo"), 부분 일치로 잡으면 거의 모든 영어 과업에 이
본문이 붙는다. 트리거는 `justfile` 같은 모호하지 않은 어휘, 백틱 안의 `just`, `just --list`,
그리고 한글 문장 안의 라틴 `just <이름>` 넷이다. **인용부호 없는 영어 `just <이름>` 은 안
잡는다** — 그 꼴이 곧 영어 명령문이라 뒤에 오는 것이 레시피 이름인지 동사인지 문장만 봐서
못 가른다 (자세한 계약은 `_SUBSTR`·`_WORD_RE` 바로 위에)."""

import re

JUST_SKILL_MD = """\
---
name: asgard-just
description: The run surface — in a repository that has a Justfile, every command it can run lives there, written from the manifests and extended by hand. Load before running a project command in such a repository, before adding or changing a recipe, and when a task mentions a justfile, a task runner, or where the run commands live. Adoption is opt-in (`asgard just init`); a repository without a Justfile is not missing anything.
allowed-tools: Bash(just *), Bash(asgard just *)
---

# asgard-just — the run surface

A repository that has adopted this keeps every command it can run at one address: `just <recipe>`.
Not a README line, not a command you reassembled from `pyproject.toml`, not what worked in another
repository. One file, and `just --list` prints all of it.

## Adoption is the repository's choice

Nothing brings this in on its own. Installing Asgard does not, `asgard init` does not, and
`asgard sync` does not — the one door is `asgard just init`, which installs the runner and writes
the Justfile from the checked-in manifests.

So the first question is which kind of repository you are standing in. **A Justfile at the root
means it was adopted; no Justfile means it was not, and that is not a gap to close.** Run the
commands the ordinary way there, and leave adopting `just` to the person whose repository it is —
suggest it only if they raise the subject.

## In a repository that has one, before you run a project command

1. `just --list`. It is fast, it needs no arguments, and it is the only inventory that is current.
2. Found the recipe? Call it. Do not retype what it wraps — the recipe carries the flags, the
   working directory, and the environment that make the command correct here.
3. Not there? `asgard just sync` redraws the managed region from the manifests, then look again.
   Still missing means it is a procedure nobody has written down — write it (below).
4. `just` itself not on this machine? `asgard just install`. It comes from the same uv tool bin the
   `asgard` command itself lives in, so nothing new touches PATH.

## Two owners, one file

Between `# >>> asgard managed recipes >>>` and `# <<< asgard managed recipes <<<`, `asgard just
sync` rewrites everything from the manifests. **Never hand-edit inside those markers** — the next
sync erases it, and the erasure is silent.

Everything outside them is yours and is never rewritten. That is where deploys, migrations, local
service startup, and anything else no manifest can state belong. When a name collides, sync drops
its own recipe and keeps yours.

## Writing a recipe

```just
# Reset the dev database          <- this comment becomes the `just --list` description
db-reset env="dev": db-stop       <- `env` is a parameter with a default; `db-stop` runs first
    cd infra; ./reset.sh {{env}}  <- one line = one shell, so `cd` and the command ride together
```

- **One line is one shell.** A `cd` on its own line is gone by the next line. Join them with `;`,
  or open the recipe with a `#!/usr/bin/env bash` shebang line to make the whole body one script.
- `@` before a line hides the command itself and prints only its output; `@` before the recipe
  name does that for every line.
- Parameters: `name`, `name="default"`, `*ARGS` (zero or more), `+ARGS` (one or more). Reach them
  as `{{name}}`.
- Dependencies go after the colon and run first, left to right: `check: fmt-check lint test`.
- `[unix]` / `[windows]` above two recipes of the same name gives each platform its own body —
  that is the way to write a command that differs by OS, and it is not a duplicate definition.
- `[private]` keeps a helper out of `just --list`. A leading `_` does the same.
- Cross-platform values belong in variables at the top of the file, not inside each recipe:
  `gradlew := if os_family() == "windows" { ".\\\\gradlew.bat" } else { "./gradlew" }`.
- Keep the recipe a one-liner that calls a script when the body outgrows a few lines. A Justfile
  that holds the logic is a build system nobody chose.

## Keeping it honest

- `asgard just check` — says whether the managed region still matches the manifests, and names any
  recipe defined twice in a way `just` will reject. Writes nothing.
- `asgard doctor` carries the same answer in its **run surface** row. That row appears only in a
  repository that adopted the run surface; elsewhere there is nothing to diagnose.
- `asgard sync` redraws the managed region for every registered project that already has a
  Justfile, in the same pass that refreshes the code map. It never creates one. You rarely call
  `asgard just sync` by hand for this reason.
- When a quest criterion needs a verification command, name the recipe (`just check`), not the raw
  command underneath it. The recipe is what stays true after the manifests move.

## What does not belong here

Secrets, machine-specific paths, and one-off exploration. A recipe is a command the whole team runs
the same way; anything true only on your machine belongs in your shell history, and anything that
must not be read belongs in the secret store (Canon 4).
"""

JUST_SKILLS: list[tuple[str, str]] = [("asgard-just", JUST_SKILL_MD)]

# 맨 낱말 `just` 는 없다 — 영어 부사와 부딪힌다. 실제로 걸러야 했던 오발: "just run the tests",
# "just a typo", "just checking", "그냥"의 번역투. 한국어 쪽도 낱말 경계가 없어서 넓은 조각을
# 피한다: `명령`만 두면 "명령형", "명령어 이름"까지 걸린다.
#
# 맨 `recipe`·`레시피` 도 없다 — 요리 앱을 만드는 과업("add a recipe card to the cooking
# app")이 그대로 걸렸다. 두 낱말을 실행 표면 어휘와 근접 조건으로 묶어 살리려다 "just a
# recipe card" 가 다시 걸려서, 규칙을 하나 더 얹는 대신 지웠다. 잃는 것은 다른 표식이 하나도
# 없는 "add a deploy recipe" 뿐이고, 그 자리는 Claude Code 의 설명 기반 자동 선택과
# AGENTS.md 의 실행 표면 절이 이미 덮는다 — 이 리졸버는 보조 갈래지 유일한 문이 아니다.
_SUBSTR: tuple[str, ...] = (
    "justfile",
    "just --list",
    "asgard just",
    "task runner",
    "run command",
    "run surface",
    "실행 명령",
    "실행 표면",
    "런 명령",
    "빌드 명령",
    "명령 러너",
    "makefile",
    "npm script",
    "package script",
)
# `just <레시피>` 를 레시피 이름 목록으로 잡으려던 첫 판이 틀렸다. 그 꼴은 영어 명령문 그
# 자체다 — "just check the logs", "just test it quickly", "just build it", "just list the
# files" 가 전부 걸렸고, 뒤에 오는 낱말이 이름인지 동사인지는 문장만 봐서 못 가른다.
# 그래서 부사로 읽힐 수 없는 자리만 남긴다.
_WORD_RE: tuple[str, ...] = (
    r"`\s*just\s",  # 백틱 안 — 산문의 부사는 명령 인용부호 안에 안 들어간다
    r"\bjust\s+--?l\b",  # just --list · just -l
)
# 한국어 문장에는 부사 "just" 가 없다. 그래서 한글이 섞인 과업에서 라틴 `just <이름>` 은
# 인용된 명령으로 읽는다 — "just test 가 왜 실패하지" 가 이 갈래다.
# lagom: "just fix the typo 해줘" 같은 혼용문은 이름 목록에 없는 낱말이라 안 걸리지만,
# "just check 해줘" 는 걸린다. 그 모호함은 문장만으로는 못 푼다.
_HANGUL_RE = re.compile(r"[가-힣]")
_HANGUL_INVOCATION_RE = re.compile(
    r"\bjust\s+(test|build|lint|check|fmt|format|typecheck|dev|serve|deploy|migrate|list)\b"
)


def resolve_just_skills(task: str) -> list[tuple[str, str]]:
    """실행 표면 어휘가 있는 과업 → 계약 (이름, frontmatter 제거 본문) — 0-LLM 휴리스틱.

    일치가 없으면 빈 목록이다 (fail-open). 명령을 어디에 적는지와 무관한 과업에 이 본문이
    붙으면 값 없이 컨텍스트만 먹으므로, 넓게 잡는 쪽보다 안 잡는 쪽으로 기운다."""
    text = task.lower()
    if any(key in text for key in _SUBSTR):
        return _body()
    if any(re.search(pattern, text) for pattern in _WORD_RE):
        return _body()
    if _HANGUL_RE.search(task) and _HANGUL_INVOCATION_RE.search(text):
        return _body()
    return []


def _body() -> list[tuple[str, str]]:
    return [(name, body.split("---", 2)[2].lstrip()) for name, body in JUST_SKILLS]
