"""Print the current reachability finding count for dead-code burndown."""

from __future__ import annotations

import sys

from dev.audit.unreachable_code import (
    UnreachableCodeOutcome,
    run_unreachable_code_scan,
)
from dev.exit_codes import ADVISORY_BROKEN, OK


def main() -> int:
    """Print one integer, failing when the scan cannot produce a valid signal."""
    result = run_unreachable_code_scan()
    if result.outcome is UnreachableCodeOutcome.ERROR:
        print(result.reason, file=sys.stderr)
        return ADVISORY_BROKEN
    print(result.finding_count)
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
