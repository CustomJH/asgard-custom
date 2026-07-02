#!/usr/bin/env python3
# Asgard secret-guard — Canon Law 4 (시크릿 보호). Blocks Write/Edit that write a .env or introduce
# credentials (PreToolUse, {"tool_input": {...}}). Fail-open: any error -> exit 0 (allow). exit 2 = block.
import json
import re
import sys

SECRET = [
    (r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----", "private key"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS key"),
    (r"\bghp_[A-Za-z0-9]{36}\b", "GitHub token"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "Slack token"),
    (r"(?i)\b(secret|password|passwd|api[_-]?key|access[_-]?token|private[_-]?key)\s*[:=]\s*\S{8,}", "credential"),
]


def main() -> None:
    try:
        ti = json.load(sys.stdin).get("tool_input") or {}
    except Exception:
        sys.exit(0)
    path = str(ti.get("file_path") or "")
    text = " ".join(str(x) for x in (ti.get("content"), ti.get("new_string")) if x)
    if re.search(r"(^|/)\.env(\.[^/]*)?$", path) and not re.search(r"\.env\.(example|sample|template|dist)$", path):
        print("Asgard Canon Law 4 — .env write blocked: " + path + " (시크릿은 커밋하지 않습니다).", file=sys.stderr)
        sys.exit(2)
    for pat, label in SECRET:
        if re.search(pat, text):
            print("Asgard Canon Law 4 — possible secret (" + label + ") blocked: " + path, file=sys.stderr)
            sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
