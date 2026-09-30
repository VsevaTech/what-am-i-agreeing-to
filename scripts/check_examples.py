"""Fail if the tracked demo PDFs in examples/ are stale.

Regenerates every demo document with examples/build_examples.py and asks Git whether any
tracked file under examples/ changed (or a new, untracked PDF appeared). There is no checksum
list to maintain: regeneration + `git status` is the check.

Usage:  python scripts/check_examples.py      (exit code 1 when assets are stale)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from examples import build_examples  # noqa: E402


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def main() -> int:
    build_examples.main()
    status = git("status", "--porcelain", "--untracked-files=all", "--", "examples/*.pdf")
    if not status.strip():
        print("OK: examples/*.pdf are reproducible from examples/build_examples.py.")
        return 0
    print("::error::Demo documents in examples/ are stale or untracked.", file=sys.stderr)
    print("Files that differ after regeneration:", file=sys.stderr)
    print(status, file=sys.stderr)
    print(git("diff", "--stat", "--", "examples/*.pdf"), file=sys.stderr)
    print(
        "Fix: run `python examples/build_examples.py` locally and commit the result "
        "(or let the 'Regenerate demo assets' workflow do it on main).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
