"""Minimal assertion harness for the executable checks (AUTONOMY.md §2).

Every check prints what it asserted and exits non-zero on the first failure.
No test framework — stdlib only.
"""

from __future__ import annotations

import sys
import traceback
from typing import Callable


class CheckFailure(AssertionError):
    pass


class Check:
    """Collects assertions for one sub-step and reports them."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.passed = 0

    def require(self, condition: bool, description: str) -> None:
        """Assert `condition`, printing the description either way."""
        if condition:
            self.passed += 1
            print(f"  ok   {description}")
        else:
            print(f"  FAIL {description}")
            raise CheckFailure(f"{self.name}: {description}")

    def equal(self, actual: object, expected: object, description: str) -> None:
        if actual == expected:
            self.passed += 1
            print(f"  ok   {description}")
        else:
            print(f"  FAIL {description}\n         expected: {expected!r}\n         actual:   {actual!r}")
            raise CheckFailure(f"{self.name}: {description}")

    def raises(self, exc_type: type[BaseException], fn: Callable[[], object], description: str) -> None:
        """Assert that calling `fn` raises `exc_type` — used to prove the code fails loudly."""
        try:
            fn()
        except exc_type:
            self.passed += 1
            print(f"  ok   {description}")
            return
        except Exception as exc:  # wrong exception type is still a failure
            print(f"  FAIL {description} (raised {type(exc).__name__}: {exc})")
            raise CheckFailure(f"{self.name}: {description}") from exc
        print(f"  FAIL {description} (nothing raised)")
        raise CheckFailure(f"{self.name}: {description}")

    def note(self, message: str) -> None:
        print(f"  ..   {message}")


def run(name: str, body: Callable[[Check], None]) -> None:
    """Run a check body, print a banner and summary, exit non-zero on failure."""
    print(f"== {name}")
    check = Check(name)
    try:
        body(check)
    except CheckFailure:
        print(f"== {name}: FAILED after {check.passed} passing assertion(s)")
        sys.exit(1)
    except Exception:
        traceback.print_exc()
        print(f"== {name}: ERRORED after {check.passed} passing assertion(s)")
        sys.exit(1)
    print(f"== {name}: PASS ({check.passed} assertions)")
