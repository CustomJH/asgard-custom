"""Claude Code templates: a minimal-but-real settings.json (permission floor + PreToolUse guards)
and the foundational .claude/ folder set (each seeded with a README so git tracks it)."""

import json

from ..platform import hook_python

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


def cc_settings() -> str:
    # Permission floor (belt) + deterministic PreToolUse guards (braces): "prose asks, hooks forbid."
    # 훅 인터프리터는 생성 시점의 타깃 머신 기준 — Windows 엔 python3 실행 파일이 없다.
    py = hook_python()
    return (
        json.dumps(
            {
                # Lagom 모드 가시성 — 상태파일/config를 읽는 셸 전용 스크립트
                "statusLine": {
                    "type": "command",
                    "command": 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/lagom-statusline.sh"',
                },
                "permissions": {
                    # 스킬 시스템의 유일한 로드 경로(asgard skills 읽기 3종)와 quest-log 루프는
                    # 사전 승인 — 헤드리스(-p)에서 자동 거부되면 정본 폴백·게이트 불능이 된다.
                    # 쓰기 계열(assign/disable 등)은 제외.
                    "allow": [
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
                        f"Bash({py} .claude/hooks/quest-log.py *)",
                    ],
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
                    "SessionStart": [
                        {
                            "matcher": "startup|resume|clear|compact",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/lagom-activate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/memory-activate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/charter-activate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/manual-activate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/agent-activate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/map-activate.py"',
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
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/unattended-context.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/lagom-tracker.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/memory-activate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/charter-activate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/manual-activate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/agent-activate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/map-activate.py"',
                                },
                                # 되짚기의 앞쪽 절반 — 같은 자리를 다시 건드리기 **전에** 남은 물음을
                                # 사용자에게만 꺼낸다. 모델 컨텍스트에 넣으면 모델이 대신 답해 버린다.
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/tutor-note.py" claude brief',
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
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/lagom-subagent.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/charter-activate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/manual-activate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/agent-activate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/map-activate.py"',
                                },
                            ]
                        },
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
                                }
                            ],
                        },
                    ],
                    # Trinity mode B — role subagents must record their quest-log event before
                    # finishing (deterministic role-discipline; final backstop is still the Stop gate).
                    "SubagentStop": [
                        {
                            "matcher": "^asgard-(thinker|worker|verifier)$",
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
                    ],
                    # Canon Law 10 (Trinity) — Stop-time verifier gate: diff-hash physical comparison.
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/verifier-gate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/memory-activate.py"',
                                },
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/map-activate.py"',
                                },
                                # 되짚기 — 이 턴이 쓴 코드를 사용자 앞에 물음으로 되돌린다. 절대
                                # 안 막는다(health 등급): 되짚기가 관문이 되면 사람이 먼저 끈다.
                                {
                                    "type": "command",
                                    "command": f'{py} "$CLAUDE_PROJECT_DIR/.claude/hooks/tutor-note.py"',
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
