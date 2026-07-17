"""Engine-serve wrapper core: seat the engine data store explicitly, then serve.

The engine binary itself is never modified (dev-process-registry ADR), so its
adoption is wrapper-based: this core registers a registry record for the band
port, launches the ``vaultspec serve --no-seat`` engine on that port, heartbeats
the record while the engine runs, and deregisters on owned shutdown. ``scripts/
engine_serve.py`` is the thin ``procs.toml`` entrypoint that delegates here; the
logic lives in the package so the data-safety boundary below is unit tested.

Data-safety boundary: the engine opens its data store RELATIVE TO ITS PROCESS
CWD. An unset or wrong workspace would seat that store in the wrapper's inherited
cwd - the a2a project root, the SAME store the resident engine (port 8767) holds
open - which is data corruption, not mere inconvenience. So the seat is an
explicit, validated directory (``resolve_data_seat``) and the engine is launched
with an explicit ``cwd`` there; an unset/missing seat is refused loudly rather
than defaulted. The engine invocation stays configuration via
``VAULTSPEC_ENGINE_SERVE_CMD`` (``{port}`` and ``{workspace}`` substituted), so a
template can also pass an explicit ``--data-dir {workspace}/...`` rather than lean
on cwd alone.
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
from pathlib import Path
from typing import TYPE_CHECKING

from .manager import render_command
from .procs_config import load_procs_config
from .registration import (
    deregister_serve,
    refresh_registration,
    register_serve,
)

if TYPE_CHECKING:
    from .registry import ProcRecord

__all__ = [
    "EngineSeatError",
    "engine_command",
    "main",
    "resolve_data_seat",
    "serve",
]

_ROLE = "engine-dev"
_SERVE_CMD_ENV = "VAULTSPEC_ENGINE_SERVE_CMD"
_DEFAULT_SERVE_CMD = "vaultspec serve --no-seat --port {port}"
_HEARTBEAT_SECONDS = 15.0


class EngineSeatError(ValueError):
    """The engine data seat is unset or not an existing directory (a refusal)."""


def resolve_data_seat(raw: str) -> str:
    """Return the explicit engine data-seat dir, or raise :class:`EngineSeatError`.

    The engine seats its data store relative to its process cwd, so the seat must
    be an operator-supplied existing directory. An empty seat or a path that is not
    a directory is refused - never defaulted to the wrapper's inherited cwd (the
    a2a project root shared with the resident engine).
    """
    candidate = raw.strip()
    if not candidate:
        raise EngineSeatError(
            "engine-serve: --workspace is required (the engine seats its data store "
            "relative to it); refusing to launch to avoid writing into the a2a "
            "project root shared with the resident engine"
        )
    path = Path(candidate)
    if not path.is_dir():
        raise EngineSeatError(
            f"engine-serve: --workspace {candidate!r} is not an existing directory; "
            "refusing to launch to avoid an implicit data seat"
        )
    return str(path)


def engine_command(port: int, workspace: str) -> list[str]:
    """The engine launch command with ``{port}``/``{workspace}`` substituted.

    Shell-splits the ``VAULTSPEC_ENGINE_SERVE_CMD`` template, then delegates token
    substitution to the lifecycle's :func:`render_command` (the single substitution
    implementation - no parallel copy). Threading ``{workspace}`` lets a template
    seat the data store explicitly (``--scope {workspace}`` /
    ``--data-dir {workspace}/engine-data``) instead of relying on cwd alone; the
    ``{python}`` token render_command also resolves is simply absent from engine
    templates.
    """
    template = os.environ.get(_SERVE_CMD_ENV) or _DEFAULT_SERVE_CMD
    return render_command(shlex.split(template), port=port, workspace=workspace)


def _heartbeat(record: ProcRecord | None, stop: threading.Event) -> None:
    """Advance the registry record every cadence until *stop* is set."""
    while not stop.wait(_HEARTBEAT_SECONDS):
        with contextlib.suppress(OSError):
            refresh_registration(record)


def serve(*, port: int, name: str | None, workspace: str) -> int:
    """Validate the data seat, register, launch the engine in the seat, and serve.

    Returns the engine's exit code, ``2`` when the data seat is ambiguous (refused
    before any registration or launch), or ``127`` when the engine binary cannot be
    launched. The engine is spawned with ``cwd`` set to the validated seat, so its
    cwd-relative data store can never land in the wrapper's inherited cwd.
    """
    try:
        seat = resolve_data_seat(workspace)
    except EngineSeatError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    config = load_procs_config()
    command = engine_command(port, seat)
    record = register_serve(
        _ROLE,
        port,
        name=name,
        workspace=seat,
        command=command,
        config=config,
    )

    stop = threading.Event()
    beat: threading.Thread | None = None
    if record is not None:
        beat = threading.Thread(target=_heartbeat, args=(record, stop), daemon=True)
        beat.start()

    try:
        process = subprocess.Popen(command, cwd=seat)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register and serve the engine.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--name", default=None, help="Registry record name.")
    parser.add_argument(
        "--workspace",
        default="",
        help="Explicit engine data-seat directory (the engine's data store is "
        "seated here). Required; an unset or missing directory is refused.",
    )
    args = parser.parse_args(argv)
    return serve(port=args.port, name=args.name, workspace=args.workspace)
