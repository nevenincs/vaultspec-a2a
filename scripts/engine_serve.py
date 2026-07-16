"""Engine-serve wrapper: register the engine in the dev-process registry, then serve.

The engine binary itself is never modified (dev-process-registry ADR), so its
adoption is wrapper-based: this script - the ``engine-dev`` serve command declared
in ``procs.toml`` - registers a registry record for the band port, launches the
workspace-local ``vaultspec serve --no-seat`` engine on that port, heartbeats the
record while the engine runs, and deregisters on owned shutdown. A ``procs``
operator can then enumerate, attach, rerun, and reap the engine like any other
managed dev process.

The engine launch command defaults to ``vaultspec serve --no-seat --port <port>``
and is overridable with ``VAULTSPEC_ENGINE_SERVE_CMD`` (a shell-split template in
which ``{port}`` is substituted) so the exact engine invocation stays configuration,
not a code constant.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shlex
import signal
import subprocess
import sys
import threading
from typing import TYPE_CHECKING

from vaultspec_a2a.lifecycle.procs_config import load_procs_config
from vaultspec_a2a.lifecycle.registration import (
    deregister_serve,
    refresh_registration,
    register_serve,
)

if TYPE_CHECKING:
    from vaultspec_a2a.lifecycle.registry import ProcRecord

_ROLE = "engine-dev"
_SERVE_CMD_ENV = "VAULTSPEC_ENGINE_SERVE_CMD"
_DEFAULT_SERVE_CMD = "vaultspec serve --no-seat --port {port}"
_HEARTBEAT_SECONDS = 15.0


def _engine_command(port: int) -> list[str]:
    template = os.environ.get(_SERVE_CMD_ENV) or _DEFAULT_SERVE_CMD
    return [part.replace("{port}", str(port)) for part in shlex.split(template)]


def _heartbeat(record: ProcRecord | None, stop: threading.Event) -> None:
    """Advance the registry record every cadence until *stop* is set."""
    while not stop.wait(_HEARTBEAT_SECONDS):
        with contextlib.suppress(OSError):
            refresh_registration(record)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register and serve the engine.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--name", default=None, help="Registry record name.")
    parser.add_argument("--workspace", default="", help="Workspace path to record.")
    args = parser.parse_args(argv)

    config = load_procs_config()
    record = register_serve(
        _ROLE,
        args.port,
        name=args.name,
        workspace=args.workspace,
        command=_engine_command(args.port),
        config=config,
    )

    stop = threading.Event()
    beat: threading.Thread | None = None
    if record is not None:
        beat = threading.Thread(target=_heartbeat, args=(record, stop), daemon=True)
        beat.start()

    command = _engine_command(args.port)
    try:
        process = subprocess.Popen(command)
    except OSError as exc:
        stop.set()
        if beat is not None:
            beat.join(timeout=2.0)
        deregister_serve(record)
        print(
            f"engine-serve: cannot launch {command[0]!r}: {exc}. "
            "Set VAULTSPEC_ENGINE_SERVE_CMD or ensure the engine binary is on PATH.",
            file=sys.stderr,
        )
        return 127
    try:
        return process.wait()
    except KeyboardInterrupt:
        with contextlib.suppress(Exception):
            if sys.platform == "win32":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.terminate()
        with contextlib.suppress(Exception):
            process.wait(timeout=10)
        return process.returncode or 0
    finally:
        stop.set()
        if beat is not None:
            beat.join(timeout=2.0)
        deregister_serve(record)


if __name__ == "__main__":
    raise SystemExit(main())
