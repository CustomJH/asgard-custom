#!/usr/bin/env python3
"""Pass Asgard skill arguments to the pinned official 21st.dev CLI."""

import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    return subprocess.run(
        ["npx", "-y", "@21st-dev/cli@1.7.2", *(sys.argv[1:] if argv is None else argv)],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
