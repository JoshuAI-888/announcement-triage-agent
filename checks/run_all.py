"""Run every check written so far (AUTONOMY.md §2).

Checks are cheap and permanent, so later work cannot silently break earlier
work. Each checks/check_*.py runs in its own subprocess; any non-zero exit
fails the whole run.

Run:  python -m checks.run_all
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHECKS_DIR = Path(__file__).resolve().parent
ROOT = CHECKS_DIR.parent


def main() -> None:
    paths = sorted(CHECKS_DIR.glob("check_*.py"))
    if not paths:
        print("no checks found")
        sys.exit(1)

    failures: list[str] = []
    for path in paths:
        module = f"checks.{path.stem}"
        print(f"\n----- {module}")
        result = subprocess.run([sys.executable, "-m", module], cwd=ROOT)
        if result.returncode != 0:
            failures.append(module)

    print("\n===== summary")
    for path in paths:
        module = f"checks.{path.stem}"
        print(f"  {'FAIL' if module in failures else 'PASS'}  {module}")

    if failures:
        print(f"\n{len(failures)} of {len(paths)} check(s) FAILED")
        sys.exit(1)
    print(f"\nall {len(paths)} check(s) passed")


if __name__ == "__main__":
    main()
