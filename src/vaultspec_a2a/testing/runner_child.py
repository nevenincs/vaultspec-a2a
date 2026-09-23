"""Contained pytest entrypoint that binds completion to its own process."""

from __future__ import annotations

import os
import sys

import pytest

from .harness_names import COMPLETION_ENDPOINT_ENV, COMPLETION_OWNER_PID_ENV


def _seated_arguments(arguments: list[str]) -> list[str]:
    """Pin this session's basetemp inside its seat unless the caller named one.

    A run launched with ``--confcutdir`` below the repository never loads the
    root conftest or the harness plugin that would otherwise seat it, and pytest
    would fall back to the system temporary directory.
    """
    if any(arg == "--basetemp" or arg.startswith("--basetemp=") for arg in arguments):
        return arguments
    from ..control.settings_base import resolve_project_root
    from .session_root import seat_test_session

    seat = seat_test_session(resolve_project_root())
    return [*arguments, f"--basetemp={seat.basetemp}"]


def main() -> int:
    previous_environment = os.environ.get("VAULTSPEC_A2A_ENVIRONMENT")
    completion_endpoint = os.environ.pop(COMPLETION_ENDPOINT_ENV, None)
    previous_owner = os.environ.pop(COMPLETION_OWNER_PID_ENV, None)
    os.environ.setdefault("VAULTSPEC_A2A_ENVIRONMENT", "development")
    try:
        if completion_endpoint:
            from .plugin import send_completion_message

            send_completion_message(completion_endpoint, "hello")
        exit_status = pytest.main(_seated_arguments(sys.argv[1:]))
        # pytest_sessionfinish runs before pytest_unconfigure and before
        # pytest.main() returns.  Publish only after that teardown completes so
        # the outer owner can distinguish a root that is still shutting down
        # from one that has exited while a descendant remains.
        from .plugin import send_completion_receipt

        try:
            if completion_endpoint:
                send_completion_receipt(exit_status, endpoint=completion_endpoint)
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
