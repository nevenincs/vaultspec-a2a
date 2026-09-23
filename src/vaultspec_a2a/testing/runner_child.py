"""Contained pytest entrypoint that binds completion to its own process."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

import pytest

from .runner import COMPLETION_OWNER_PID_ENV

_A2A_HOME_ENV = "VAULTSPEC_A2A_HOME"


def main() -> int:
    previous_environment = os.environ.get("VAULTSPEC_A2A_ENVIRONMENT")
    completion_endpoint = os.environ.pop("VAULTSPEC_PYTEST_COMPLETION_ENDPOINT", None)
    previous_owner = os.environ.pop(COMPLETION_OWNER_PID_ENV, None)
    os.environ.setdefault("VAULTSPEC_A2A_ENVIRONMENT", "development")
    # Left unset, the app home defaults to the user's real ~/.vaultspec-a2a, and
    # any code path that falls back to the default database would then open the
    # user's live store. A session-private home makes that fallback harmless.
    isolated_home: str | None = None
    if _A2A_HOME_ENV not in os.environ:
        isolated_home = tempfile.mkdtemp(prefix="vaultspec-a2a-test-home-")
        os.environ[_A2A_HOME_ENV] = isolated_home
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
        if isolated_home is not None:
            os.environ.pop(_A2A_HOME_ENV, None)
            shutil.rmtree(isolated_home, ignore_errors=True)
            if os.path.exists(isolated_home):
                # On Windows a store still held open by a surviving process
                # cannot be removed; name it rather than leak it silently.
                print(
                    f"test app home was not removed: {isolated_home}",
                    file=sys.stderr,
                    flush=True,
                )
        if previous_environment is None:
            os.environ.pop("VAULTSPEC_A2A_ENVIRONMENT", None)
        else:
            os.environ["VAULTSPEC_A2A_ENVIRONMENT"] = previous_environment
        if completion_endpoint is not None:
            os.environ["VAULTSPEC_PYTEST_COMPLETION_ENDPOINT"] = completion_endpoint
        if previous_owner is None:
            os.environ.pop(COMPLETION_OWNER_PID_ENV, None)
        else:
            os.environ[COMPLETION_OWNER_PID_ENV] = previous_owner


if __name__ == "__main__":
    raise SystemExit(main())
