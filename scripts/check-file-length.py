"""Enforce file length limits and ban non-empty __init__.py files."""

import pathlib
import subprocess
import sys

MAX_LINES = 500
EXCLUDE = {"scripts/dokctl.py"}  # vendored tool, not project code
result = subprocess.run(["git", "ls-files", "*.py", "**/*.py"], capture_output=True, text=True)  # noqa: S603, S607
files = [pathlib.Path(f) for f in result.stdout.strip().splitlines() if f and str(f) not in EXCLUDE]

errors = []
for p in files:
    if p.name == "__init__.py":
        content = p.read_text().strip()
        if content and content != "__all__ = []":
            errors.append(f"{p}: __init__.py must be empty or contain only __all__ = [] (no re-exports, no logic)")
        continue
    count = len(p.read_text().splitlines())
    if count > MAX_LINES:
        errors.append(f"{p}: {count} lines (max {MAX_LINES})")

if errors:
    for e in errors:
        print(e, file=sys.stderr)  # noqa: T201
    sys.exit(1)
