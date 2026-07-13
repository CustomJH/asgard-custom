"""Claude Code templates: a minimal-but-real settings.json (permission floor + PreToolUse guards)
and the foundational .claude/ folder set (each seeded with a README so git tracks it)."""

import json

CC_FOLDERS = [
    (
        "commands",
        "Custom slash commands — one `.md` each, invoked as `/name`. (Skills are the newer alternative.)\nDocs: https://code.claude.com/docs/en/slash-commands",
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
    return (
        json.dumps(
            {
                # Lagom 모드 가시성 (CUS-215) — 상태파일/config 를 읽는 셸 전용 스크립트
                "statusLine": {
                    "type": "command",
                    "command": 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/lagom-statusline.sh"',
                },
                "permissions": {
                    "allow": ["Bash(git status)", "Bash(git diff *)", "Bash(git log *)"],
                    "deny": [
                        "Bash(rm -rf *)",
                        "Bash(git push --force*)",
                        "Bash(git push -f*)",
                        "Bash(git reset --hard*)",
                    ],
                },
                "hooks": {
                    # Lagom (CUS-208) — 세션 시작·재개·클리어·컴팩트 시 모드 초기화 + 캐논 주입.
                    "SessionStart": [
                        {
                            "matcher": "startup|resume|clear|compact",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/lagom-activate.py"',
                                }
                            ],
                        },
                    ],
                    # Canon 8 (무인이면 진행) — 자동화 permission_mode 감지 시 무인 계약 주입 (CUS-169).
                    # Lagom tracker (CUS-213) — /lagom 전환·영속·비활성 문구.
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/unattended-context.py"',
                                },
                                {
                                    "type": "command",
                                    "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/lagom-tracker.py"',
                                },
                            ]
                        },
                    ],
                    # Lagom (CUS-214) — SessionStart 컨텍스트 미전파 보상. verifier 는 스크립트가 자체 제외.
                    "SubagentStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/lagom-subagent.py"',
                                }
                            ]
                        },
                    ],
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/git-guard.py"',
                                }
                            ],
                        },
                        {
                            "matcher": "Write|Edit",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/secret-guard.py"',
                                }
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
                                    "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/failure-tracker.py"',
                                }
                            ],
                        },
                        {
                            "matcher": "Write|Edit|NotebookEdit",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/write-sentinel.py"',
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
                                    "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/subagent-gate.py"',
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
                                    "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/verifier-gate.py"',
                                }
                            ]
                        },
                    ],
                },
            },
            indent=2,
        )
        + "\n"
    )
