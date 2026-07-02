"""Claude Code templates: a minimal-but-real settings.json (permission floor + PreToolUse guards)
and the foundational .claude/ folder set (each seeded with a README so git tracks it)."""

import json

CC_FOLDERS = [
    ("commands", "Custom slash commands — one `.md` each, invoked as `/name`. (Skills are the newer alternative.)\nDocs: https://code.claude.com/docs/en/slash-commands"),
    ("agents", "Subagents — one `.md` each; frontmatter: name, description, tools, model.\nDocs: https://code.claude.com/docs/en/sub-agents"),
    ("skills", "Agent skills — each in `<name>/SKILL.md` with a `description` frontmatter.\nDocs: https://code.claude.com/docs/en/skills"),
    ("hooks", "Hook scripts, wired from `settings.json` `hooks{}` by matcher + command.\nDocs: https://code.claude.com/docs/en/hooks"),
    ("rules", "Path-scoped instructions — frontmatter `paths:` globs load them when matching files are read.\nDocs: https://code.claude.com/docs/en/memory"),
    ("output-styles", "Custom system-prompt styles — one `.md` each.\nDocs: https://code.claude.com/docs/en/settings"),
]


def cc_settings() -> str:
    # Permission floor (belt) + deterministic PreToolUse guards (braces): "prose asks, hooks forbid."
    return json.dumps(
        {
            "permissions": {
                "allow": ["Bash(git status)", "Bash(git diff *)", "Bash(git log *)"],
                "deny": ["Bash(rm -rf *)", "Bash(git push --force*)", "Bash(git push -f*)", "Bash(git reset --hard*)"],
            },
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/git-guard.py"'}]},
                    {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/secret-guard.py"'}]},
                ],
                # Canon Law 9 — soft 3-strike loop warning (never blocks). All tools.
                # write-sentinel — records session write paths so the Stop gate can catch
                # quest-less writes (Trinity enforcement; write tools only, so no read-call overhead).
                "PostToolUse": [
                    {"matcher": "*", "hooks": [{"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/failure-tracker.py"'}]},
                    {"matcher": "Write|Edit|NotebookEdit", "hooks": [{"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/write-sentinel.py"'}]},
                ],
                # Canon Law 10 (Trinity) — Stop-time verifier gate: diff-hash physical comparison.
                "Stop": [
                    {"hooks": [{"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/verifier-gate.py"'}]},
                ],
            },
        },
        indent=2,
    ) + "\n"
