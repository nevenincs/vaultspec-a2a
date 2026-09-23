"""Contained pytest entrypoint that binds completion to its own process."""

from __future__ import annotations

import os
import sys

import pytest

from .runner import COMPLETION_ENDPOINT_ENV, COMPLETION_OWNER_PID_ENV


def main() -> int:
    previous_environment = os.environ.get("VAULTSPEC_A2A_ENVIRONMENT")
    completion_endpoint = os.environ.pop(COMPLETION_ENDPOINT_ENV, None)
    previous_owner = os.environ.pop(COMPLETION_OWNER_PID_ENV, None)
    os.environ.setdefault("VAULTSPEC_A2A_ENVIRONMENT", "development")
    try:
        if completion_endpoint:
            from .plugin import _send_completion_message

            _send_completion_message(completion_endpoint, "hello")
        exit_status = pytest.main(sys.argv[1:])
        # pytest_sessionfinish runs before pytest_unconfigure and before
        # pytest.main() returns.  Publish only after that teardown completes so
        # the outer owner can distinguish a root that is still shutting down
        # from one that has exited while a descendant remains.
        from .plugin import _send_completion_receipt

        try:
            if completion_endpoint:
                _send_completion_receipt(exit_status, endpoint=completion_endpoint)
        except (OSError, ValueError) as exc:
            print(
                f"resource-aware completion receipt failed: {exc}",
                file=sys.stderr,
                flush=True,
            )
        return int(exit_status)
    finally:
        if previous_environment is None:
            os.environ.pop("VAULTSPEC_A2A_ENVIRONMENT", None)
        else:
            os.environ["VAULTSPEC_A2A_ENVIRONMENT"] = previous_environment
        if completion_endpoint is not None:
            os.environ[COMPLETION_ENDPOINT_ENV] = completion_endpoint
        if previous_owner is None:
            os.environ.pop(COMPLETION_OWNER_PID_ENV, None)
        else:
            os.environ[COMPLETION_OWNER_PID_ENV] = previous_owner


if __name__ == "__main__":
    raise SystemExit(main())
