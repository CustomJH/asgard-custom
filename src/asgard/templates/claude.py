"""Claude Code templates: a minimal-but-real settings.json (permission floor + PreToolUse guards)
and the foundational .claude/ folder set (each seeded with a README so git tracks it)."""

import json

from ..platform import UV_HOOK_PYTHON, hook_python, hook_python_token, preflight_command

CC_FOLDERS = [
    (
        "commands",
        "Legacy scope — Claude Code merged custom commands into skills; put new content in `skills/<name>/SKILL.md`. Existing `.md` files here still work as `/name`.\nDocs: https://code.claude.com/docs/en/skills",
    ),
    (
        "agents",
        "Subagents — one `.md` each; frontmatter: name, description, tools, model.\nDocs: https://code.claude.com/docs/en/sub-agents",
    ),
    (
        "skills",
        "Agent skills — each in `<name>/SKILL.md` with a `description` frontmatter.\nDocs: https://code.claude.com/docs/en/skills",
    ),
    (
        "hooks",
        "Hook scripts, wired from `settings.json` `hooks{}` by matcher + command.\nDocs: https://code.claude.com/docs/en/hooks",
    ),
    (
        "rules",
        "Path-scoped instructions — frontmatter `paths:` globs load them when matching files are read.\nDocs: https://code.claude.com/docs/en/memory",
    ),
    ("output-styles", "Custom system-prompt styles — one `.md` each.\nDocs: https://code.claude.com/docs/en/settings"),
]


def _dispatch(py: str, *specs: str) -> str:
    """주입 훅 여럿을 프로세스 하나로 — `hook-dispatch.py [-- <경로> [인자...]]...`.

    각 `spec` 은 배선이 예전에 적던 그대로다: 훅 이름, 그리고 그 훅이 받던 인자
    (`"tutor-note claude brief"`). 이름이 아니라 경로를 통째로 적는 이유는 진단 때문이다 —
    `doctor` 의 `_HOOK_IN_COMMAND` 가 명령줄에서 `hooks/<이름>.py` 를 찾아 이벤트별 배선
    누락을 잰다. 이름만 적으면 합쳐진 훅들이 그 눈에서 통째로 사라지고, 그 상태가 초록으로
    읽힌다.

    합치는 것은 주입 훅뿐이다. 가드와 증거 훅은 각자 뜬다 (hook_dispatch.py 머리말).
    """
    parts = [f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/hook-dispatch.py"']
    for spec in specs:
        name, _, args = spec.partition(" ")
        parts.append(f'-- "$CLAUDE_PROJECT_DIR/.claude/hooks/{name}.py"' + (f" {args}" if args else ""))
    return " ".join(parts)


def cc_settings() -> str:
    # Permission floor (belt) + deterministic PreToolUse guards (braces): "prose asks, hooks forbid."
    # 두 표기가 서로 다른 일을 한다. 배선(`py`)은 훅 폴더에 같이 깔리는 런처를 부른다 — 배선
    # 파일은 팀에 커밋돼 다른 기계에서도 읽히므로 여기 이 기계의 uv 경로를 적을 수 없고, PATH 가
    # 넉 줄뿐인 독·launchd 프로세스도 서야 해서 맨 `uv` 도 적을 수 없다 (platform.hook_python).
    # 허용목록(`token`)은 안내문이 시키는 맨 토큰이라 모델이 친 명령과 한 글자도 안 어긋난다.
    py = hook_python("$CLAUDE_PROJECT_DIR/.claude/hooks")
    token = hook_python_token()
    return (
        json.dumps(
            {
                # statusLine 은 여기 없다. Claude Code 는 프로젝트 설정이 사용자 설정보다 우선하므로
                # 이 키를 적으면 사용자가 ~/.claude/settings.json에 지정한 상태줄이 asgard
                # 프로젝트마다 무시된다. 호스트의 상태줄은 호스트 설정이 정하고, 아스가르드 고유
                # 상태줄은 네이티브 터미널에만 있다 (agent/repl.py statusline). lagom-statusline.sh
                # 는 그대로 설치되니, 쓰려면 사용자 settings.json의 statusLine 에 그 경로를 지정한다.
                "permissions": {
                    # 스킬 시스템의 유일한 로드 경로(asgard skills 읽기 3종)와 quest-log 루프는
                    # 사전 승인 — 헤드리스(-p)에서 자동 거부되면 정본 폴백·게이트 불능이 된다.
                    # 쓰기 계열(assign/disable 등)은 제외.
                    # dict.fromkeys — uv 기계에서는 hook_python_token()과 정본 토큰이 같은
                    # 문자열이라 같은 항목이 두 번 들어간다. 순서는 보존한 채 접는다.
                    "allow": list(
                        dict.fromkeys(
                            [
                                "Bash(git status)",
                                "Bash(git diff *)",
                                "Bash(git log *)",
                                "Bash(asgard skills list*)",
                                "Bash(asgard skills show *)",
                                "Bash(asgard skills resolve *)",
                                # 개인 메모리 계약 읽기(AGENTS.md) — 회상이 승인 프롬프트에 막히면
                                # 헤드리스에서 조용히 죽는다. 쓰기(ingest)는 의도적으로 제외 —
                                # 저장 동의는 클라이언트 권한 프롬프트가 오딘의 승인 표면이다.
                                "Bash(asgard memory query *)",
                                f"Bash({token} .claude/hooks/quest-log.py *)",
                                # 안내문(AGENTS.md·역할 계약)은 정적이라 언제나 uv 정본 형태를 적는다.
                                # 이 기계의 hook_python_token()이 폴백을 골랐을 때 허용목록만 다른
                                # 토큰을 담으면, 헤드리스(-p)에서 모델이 적힌 대로 친 명령이 자동
                                # 거부되고 게이트가 조용히 죽는다.
                                f"Bash({UV_HOOK_PYTHON} .claude/hooks/quest-log.py *)",
                            ]
                        )
                    ),
                    "deny": [
                        "Bash(rm -rf *)",
                        "Bash(git push --force*)",
                        "Bash(git push -f*)",
                        "Bash(git reset --hard*)",
                        # 헬리오스 교훈 — 실제 자산을 날린 건 아래 두 계열이었다: bare stash는
                        # 전체 트리를 걷어가고(병렬 세션 미커밋분 포함), checkout -- 는 경로를
                        # 조용히 소실시킨다. 정밀 판정은 git-guard 훅(단일 출처)이 맡고, 여기는
                        # 훅이 죽었을 때(fail-open)를 위한 최소 안전망만 중복한다.
                        "Bash(git stash)",
                        "Bash(git stash push*)",
                        "Bash(git stash save*)",
                        "Bash(git stash drop*)",
                        "Bash(git stash clear*)",
                        "Bash(git stash -*)",
                        "Bash(git checkout -- *)",
                        "Bash(git checkout HEAD -- *)",
                        "Bash(git clean -f*)",
                    ],
                },
                "hooks": {
                    # Lagom — 세션 시작·재개·클리어·컴팩트 시 모드 초기화 + 캐논 주입.
                    # Memory v3 — 개인 위키 스냅샷 주입 (asgard memory snapshot 소비, fail-open).
                    # 여섯이 한 프로세스로 뜬다 — 전부 주입 훅이라 합쳐도 잃는 판정이 없다.
                    "SessionStart": [
                        {
                            "matcher": "startup|resume|clear|compact",
                            "hooks": [
                                # 환경 프리플라이트 — 바로 아래 줄이 부르는 인터프리터가 이 기계에
                                # 있는지부터 본다. 파이썬 없이 도는 sh 라서, 없을 때 말할 수 있는
                                # 유일한 자리다 (templates/env.py).
                                {
                                    "type": "command",
                                    "command": preflight_command("$CLAUDE_PROJECT_DIR/.claude/hooks", "claude-code"),
                                },
                                {
                                    "type": "command",
                                    "command": _dispatch(
                                        py,
                                        "lagom-activate",
                                        "memory-activate",
                                        "charter-activate",
                                        "manual-activate",
                                        "agent-activate",
                                        "map-activate",
                                    ),
                                },
                            ],
                        },
                    ],
                    # Canon 8 (무인이면 진행) — 자동화 permission_mode 감지 시 무인 계약 주입.
                    # Lagom tracker — /lagom 전환·영속·비활성 문구.
                    # budget-guard — 턴 시작 전 세션 누적 판정. 최대 지출 세션은 서브에이전트를
                    # 한 번도 안 쓴다(381세션 실측)이라 메인 레인에도 지점이 필요하다.
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/budget-guard.py" claude-code prompt',
                                },
                                # 나머지 열은 주입 훅이라 프로세스 하나로 뜬다. 순서는 그대로 —
                                # 디스패처가 배선 순서대로 컨텍스트를 잇는다. 각 훅이 무엇을 하는지:
                                #   scope-activate  이 요청의 작업 형상과 넘길 전문가. 계획 규율은
                                #     결정론으로 정해져 있었지만 세 호스트 모드에 오는 길이 없었다.
                                #   siege-inbox     다른 세션·`siege serve` 가 이 세션 앞으로 보낸 메일.
                                #     받을 것이 없으면 sqlite 조회 하나로 끝난다.
                                #   tutor-note      되짚기의 앞쪽 절반. 같은 자리를 다시 건드리기
                                #     **전에** 남은 물음을 사용자에게만 꺼낸다 (모델 컨텍스트에 넣으면
                                #     모델이 대신 답해 버린다) — 그래서 이 훅만 systemMessage 로 나가고,
                                #     디스패처가 컨텍스트와 다른 칸에 담는다.
                                {
                                    "type": "command",
                                    "command": _dispatch(
                                        py,
                                        "unattended-context",
                                        "lagom-tracker",
                                        "memory-activate",
                                        "charter-activate",
                                        "manual-activate",
                                        "agent-activate",
                                        "map-activate",
                                        "scope-activate",
                                        "siege-inbox",
                                        "tutor-note claude brief",
                                    ),
                                },
                            ]
                        },
                    ],
                    # Lagom — SessionStart 컨텍스트 미전파 보상. verifier는 스크립트가 자체 제외.
                    # Memory v3 — Thinker 한정 주입 (감사 매트릭스: Worker/딜리버리 무주입,
                    # Verifier/Loki 영구 무주입 — 보상 주입 패턴을 메모리에 쓰지 않는다).
                    "SubagentStart": [
                        {
                            "hooks": [
                                # 일곱 주입 훅이 프로세스 하나로. 뒤의 둘이 하는 일:
                                #   scope-activate    배차받은 역할의 형상 규율. 판정 표면
                                #     (verifier·loki)은 훅이 스스로 제외한다 — advisory 지식은
                                #     판정자에게 가지 않는다.
                                #   dispatch-context  What a dispatched agent needs to reach the
                                #     ledger it is already on: its own address, where to leave a
                                #     question it cannot settle, and how to report a failure. Without
                                #     the last one the ledger records every attempt as succeeded. No
                                #     matcher — the hook excludes the Verifier itself, whose seat here
                                #     belongs to verifier-context.
                                {
                                    "type": "command",
                                    "command": _dispatch(
                                        py,
                                        "lagom-subagent",
                                        "charter-activate",
                                        "manual-activate",
                                        "agent-activate",
                                        "map-activate",
                                        "scope-activate",
                                        "dispatch-context",
                                    ),
                                },
                            ]
                        },
                        # The verdict's own input — the harness-observed record of what ran since the
                        # last verdict. Without it a subagent Verifier knows only what the coordinator
                        # typed, so the party being judged writes the judge's brief. Memory stays
                        # blocked (see the thinker-only matcher below): this widens observation, not
                        # interpretation.
                        {
                            "matcher": "^asgard-verifier$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/verifier-context.py"',
                                }
                            ],
                        },
                        # 주입 훅인데 위 디스패처에 안 들어간다. 들어가려면 이 matcher 를 지워야
                        # 하고, 그러면 "Thinker 한정" 선언이 훅 안의 검사 하나만 남는다 — 격리
                        # 매트릭스(Verifier·Loki 영구 무주입)의 바깥 겹이 배선에서 사라진다.
                        # 아끼는 것은 Thinker 배차 한 번당 프로세스 하나뿐이라 저울이 안 맞는다.
                        {
                            "matcher": "^asgard-thinker$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/memory-activate.py"',
                                }
                            ],
                        },
                        # Trinity mode B — 역할 시작 기록 (agent_id↔세션 결속; Stop 게이트 대조 원료)
                        {
                            "matcher": "^asgard-(thinker|worker|verifier)$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/subagent-gate.py"',
                                }
                            ],
                        },
                    ],
                    "PreToolUse": [
                        # Trinity mode B — Worker/Verifier 디스패치 게이트 (unit 마커·ticket 물리 대조)
                        # budget-guard — 스폰 **전** 판정. SubagentStop은 돈이 이미 나간 뒤라 무의미하다
                        # (헬리오스 선행 연구의 실패 지점 — budget_guard.py 모듈 주석 참조).
                        {
                            "matcher": "Agent",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/budget-guard.py" claude-code task',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/subagent-gate.py"',
                                },
                            ],
                        },
                        {
                            "matcher": "Bash",
                            "hooks": [
                                # Canon 4 읽기 절반 — shell로 우회한 credential 덤프(cat .env·env·
                                # keychain)를 막는다. 읽힌 값은 매 턴 프로바이더로 재전송된다.
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/secret-guard.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/git-guard.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/release-guard.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/readonly-guard.py"',
                                },
                            ],
                        },
                        {
                            "matcher": "Write|Edit|NotebookEdit",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/readonly-guard.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/secret-guard.py"',
                                },
                            ],
                        },
                        # Canon 4 읽기 절반 — 자격 저장소는 이름만으로 판정한다 (내용을 보려면
                        # 이미 읽은 뒤라 늦다). .env.example 같은 템플릿은 면제.
                        {
                            "matcher": "Read|Grep|Glob|NotebookRead",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/secret-guard.py"',
                                },
                            ],
                        },
                    ],
                    # Canon Law 9 — soft 3-strike loop warning (never blocks). All tools.
                    # write-sentinel — records session write paths so the Stop gate can catch
                    # quest-less writes (Trinity enforcement; write tools only, so no read-call overhead).
                    "PostToolUse": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/failure-tracker.py"',
                                }
                            ],
                        },
                        {
                            "matcher": "Write|Edit|NotebookEdit",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/write-sentinel.py"',
                                },
                                # tutor tip — the mid-work reach point. The turn boundaries
                                # (UserPromptSubmit / Stop) cannot see the stretch where review
                                # actually thins out, so this speaks once inside it. It counts
                                # writes itself and only shells out every Nth one, so the
                                # per-call cost here is a file read.
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/tutor-note.py" claude tip',
                                },
                            ],
                        },
                    ],
                    # Trinity mode B — role subagents must record their quest-log event before
                    # finishing (deterministic role-discipline; final backstop is still the Stop gate).
                    # Unmatched: the same hook also closes the siege ledger row this dispatch opened,
                    # and delivery specialists open one too. A matcher here would leave every
                    # non-role agent standing as "still running" in `asgard siege` forever.
                    "SubagentStop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/subagent-gate.py"',
                                }
                            ],
                        },
                        # Micro-shape ratchet — judges only what this subagent's writes made worse than
                        # HEAD. Unmatched (no matcher) because the discipline follows the writing, not
                        # the role: any delivery agent that touched Python is judged the same way.
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/craft-gate.py"',
                                }
                            ],
                        },
                        # 저장소가 정한 코드 스타일 — 규칙은 checkstyle.xml·eslint.config.js 쪽에 있고
                        # 이 훅은 그것을 이 세션이 쓴 파일에만 물린다. `code_style` 을 선언하지 않은
                        # 저장소에서는 설정 파일 한 번 읽고 끝난다 (자식 프로세스 없음).
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/style-gate.py"',
                                }
                            ],
                        },
                    ],
                    # Canon Law 10 (Trinity) — Stop-time verifier gate: diff-hash physical comparison.
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/verifier-gate.py"',
                                },
                                # 코드 스타일 — 조율자가 직접 쓴 코드는 SubagentStop 을 안 지나므로
                                # 그 자리 하나로는 메인 루프의 쓰기가 통째로 판정 밖에 남는다.
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/style-gate.py"',
                                },
                                # Canon Law 9 — the same tracker, second observation site. This host
                                # does not call PostToolUse when a tool call fails (measured; see the
                                # hook's header), so the tool-failure lane exists only here: at the turn
                                # boundary the tracker reads the transcript tail instead of a payload.
                                # Once per turn, not once per tool call. 게이트와 함께 제자리에 남는다 —
                                # 증거 훅이 디스패처 안에서 조용히 죽으면 게이트가 초록인 채 판정의
                                # 증거만 사라진다.
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/failure-tracker.py"',
                                },
                                # 나머지 셋은 한 프로세스로. tutor-note 는 되짚기 — 이 턴이 쓴 코드를
                                # 사용자 앞에 물음으로 되돌린다. 절대 안 막는다(health 등급):
                                # 되짚기가 관문이 되면 사람이 먼저 끈다.
                                {
                                    "type": "command",
                                    "command": _dispatch(py, "memory-activate", "map-activate", "tutor-note"),
                                },
                            ]
                        },
                    ],
                },
            },
            indent=2,
        )
        + "\n"
    )
