"""Canon hook scripts (Python). Fail-open by contract: any parse/IO error -> exit 0 (allow), so a
guard can never brick a session. exit 2 = block with a reason on stderr. Shared verbatim by Claude
Code and Codex (same PreToolUse stdin schema: {"tool_input": {"command": ...}}). Kept stdlib-only
(json/sys/re) so the per-tool-call cold start stays minimal.

Emitters are normal triple-quoted strings with doubled backslashes (\\b -> \\b in output); the emitted
scripts use raw strings (r"...") for their regexes."""

_GIT_GUARD = """\
#!/usr/bin/env python3
# Asgard git-guard — Canon Law 3/6 (증거 보존). Blocks irreversible git ops in PreToolUse(Bash);
# they require Odin's explicit per-action consent. Fail-open: any error -> exit 0 (allow).
import sys, json, re
try:
    cmd = str((json.load(sys.stdin).get("tool_input") or {}).get("command") or "")
except Exception:
    sys.exit(0)
BLOCK = [
    (r"\\bgit\\s+push\\b[^|;&]*\\s-(-force\\b|f\\b)", "force-push"),
    (r"\\bgit\\s+push\\b[^|;&]*--force-with-lease\\b", "force-push"),
    (r"\\bgit\\s+reset\\s+--hard\\b", "reset --hard"),
    (r"\\bgit\\s+clean\\s+-[a-zA-Z]*f", "clean -f"),
    (r"\\bgit\\s+branch\\s+-D\\b", "branch -D"),
    (r"\\bgit\\s+(rebase|filter-branch|filter-repo)\\b", "history rewrite"),
    (r"\\bgit\\s+update-ref\\s+-d\\b", "update-ref -d"),
    (r"\\bgit\\s+(stash\\s+(drop|clear)|reflog\\s+(delete|expire))\\b", "drop history"),
]
for pat, label in BLOCK:
    if re.search(pat, cmd):
        print("Asgard Canon Law 3/6 — irreversible git op (" + label + "). Odin의 명시적 동의를 먼저 받으세요 (매 건, 대상 단위).", file=sys.stderr)
        sys.exit(2)
sys.exit(0)
"""

_SECRET_GUARD = """\
#!/usr/bin/env python3
# Asgard secret-guard — Canon Law 4 (시크릿 보호). Blocks Write/Edit that write a .env or introduce
# credentials. Fail-open: any error -> exit 0 (allow).
import sys, json, re
try:
    ti = json.load(sys.stdin).get("tool_input") or {}
except Exception:
    sys.exit(0)
path = str(ti.get("file_path") or "")
text = " ".join(str(x) for x in (ti.get("content"), ti.get("new_string")) if x)
if re.search(r"(^|/)\\.env(\\.[^/]*)?$", path) and not re.search(r"\\.env\\.(example|sample|template|dist)$", path):
    print("Asgard Canon Law 4 — .env write blocked: " + path + " (시크릿은 커밋하지 않습니다).", file=sys.stderr)
    sys.exit(2)
SECRET = [
    (r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----", "private key"),
    (r"\\bAKIA[0-9A-Z]{16}\\b", "AWS key"),
    (r"\\bghp_[A-Za-z0-9]{36}\\b", "GitHub token"),
    (r"\\bxox[baprs]-[A-Za-z0-9-]{10,}\\b", "Slack token"),
    (r"(?i)\\b(secret|password|passwd|api[_-]?key|access[_-]?token|private[_-]?key)\\s*[:=]\\s*\\S{8,}", "credential"),
]
for pat, label in SECRET:
    if re.search(pat, text):
        print("Asgard Canon Law 4 — possible secret (" + label + ") blocked: " + path, file=sys.stderr)
        sys.exit(2)
sys.exit(0)
"""


def git_guard() -> str:
    return _GIT_GUARD


def secret_guard() -> str:
    return _SECRET_GUARD
