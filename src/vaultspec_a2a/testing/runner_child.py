"""Contained pytest entrypoint that binds completion to its own process."""

from __future__ import annotations

import os
import sys

import pytest

from .runner import COMPLETION_OWNER_PID_ENV


def main() -> int:
    previous_environment = os.environ.get("VAULTSPEC_ENVIRONMENT")
    previous_owner = os.environ.pop(COMPLETION_OWNER_PID_ENV, None)
    os.environ.setdefault("VAULTSPEC_ENVIRONMENT", "development")
    try:
        exit_status = pytest.main(sys.argv[1:])
        # pytest_sessionfinish runs before pytest_unconfigure and before
        # pytest.main() returns.  Publish only after that teardown completes so
        # the outer owner can distinguish a root that is still shutting down
        # from one that has exited while a descendant remains.
        os.environ[COMPLETION_OWNER_PID_ENV] = str(os.getpid())
        from .plugin import _send_completion_receipt

        try:
            _send_completion_receipt(exit_status)
        except (OSError, ValueError) as exc:
            print(
                f"resource-aware completion receipt failed: {exc}",
                file=sys.stderr,
                flush=True,
            )
        return int(exit_status)
    finally:
        if previous_environment is None:
            os.environ.pop("VAULTSPEC_ENVIRONMENT", None)
        else:
            os.environ["VAULTSPEC_ENVIRONMENT"] = previous_environment
        if previous_owner is None:
            os.environ.pop(COMPLETION_OWNER_PID_ENV, None)
        else:
            os.environ[COMPLETION_OWNER_PID_ENV] = previous_owner


if __name__ == "__main__":
    raise SystemExit(main())
