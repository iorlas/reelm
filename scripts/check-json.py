"""Validate all JSON files in the project."""

import json
import pathlib
import subprocess
import sys

result = subprocess.run(["git", "ls-files", "*.json", "**/*.json"], capture_output=True, text=True)  # noqa: S603, S607
files = [pathlib.Path(f) for f in result.stdout.strip().splitlines() if f]

errors = []
for p in files:
    try:
        json.loads(p.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"{p}: {e}")

if errors:
    for e in errors:
        print(e, file=sys.stderr)  # noqa: T201
    sys.exit(1)
