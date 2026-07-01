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


_FAILURE_TRACKER = """\
#!/usr/bin/env python3
# Asgard failure-tracker — Canon Law 9 (무한 루프 방지). PostToolUse: counts failures per
# tool + normalized error signature in a per-session file; at 3+ of the same kind, injects a SOFT
# warning (additionalContext) to reframe — never blocks. Signature normalization defeats "reword the
# same retry" gaming. Fail-open: any error -> exit 0 with no output. Stdlib-only (json/sys/re/os).
import sys, json, re, os

def _sig(text):
    s = text.lower()
    s = re.sub(r"0x[0-9a-f]+|\\b[0-9a-f]{6,}\\b", "", s)   # hex / hashes
    s = re.sub(r"[\\\\/]\\S+", "", s)                        # bare paths (drop the variable part)
    s = re.sub(r"\\d+", "#", s)                             # numbers -> #
    return re.sub(r"\\s+", " ", s).strip()[:80]

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
try:
    tool = str(data.get("tool_name") or "").strip() or "unknown"
    resp = data.get("tool_response")
    err = ""
    if isinstance(resp, dict):
        if resp.get("is_error") or resp.get("error"):
            err = str(resp.get("error") or resp.get("stderr") or "error")
    if not err and data.get("error"):
        err = str(data.get("error"))
    if not err or tool == "unknown":
        sys.exit(0)                                        # not a recognized failure -> no-op

    proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("session_id") or "default"))[:64]
    d = os.path.join(proj, ".claude", ".asgard")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "failures-" + sid + ".json")
    counts = {}
    if os.path.exists(path):
        try:
            counts = json.load(open(path))
        except Exception:
            counts = {}
    key = tool + "|" + _sig(err)
    counts[key] = int(counts.get(key, 0)) + 1
    n = counts[key]
    try:
        json.dump(counts, open(path, "w"))
    except Exception:
        pass
    if n >= 3:
        warn = (
            "<asgard-failure-warning>\\n"
            "\\u26a0\\ufe0f Repeated failure: `" + tool + "` failed " + str(n) +
            "\\u00d7 with the same error kind this session.\\n"
            "Canon Law 9 (\\ubb34\\ud55c \\ub8e8\\ud504 \\ubc29\\uc9c0): \\uac19\\uc740 \\uc811\\uadfc\\uc73c\\ub85c 3\\ud68c+ \\uc2e4\\ud328 \\uc2dc STOP \\u2014 "
            "\\uac00\\uc124\\uc744 \\uc7ac\\uc124\\uacc4\\ud558\\uac70\\ub098 \\ub2e4\\ub978 \\uc804\\ub7b5/\\ub3c4\\uad6c\\ub85c \\ubc14\\uafb8\\uace0, \\ub9c9\\ud788\\uba74 Odin\\uc5d0\\uac8c \\ubb3c\\uc5b4\\ubcf4\\uc138\\uc694.\\n"
            "</asgard-failure-warning>"
        )
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": warn}}))
except Exception:
    sys.exit(0)
sys.exit(0)
"""


def git_guard() -> str:
    return _GIT_GUARD


def secret_guard() -> str:
    return _SECRET_GUARD


def failure_tracker() -> str:
    return _FAILURE_TRACKER
