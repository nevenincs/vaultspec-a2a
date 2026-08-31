"""Shared real-process gateway boot for every tier that spawns the product.

This module is the single home of the primitives every real-process tier needs
to stand a production gateway up and take it down again: death-aware readiness,
bind-race retry, whole-tree reaping, the child gateway program, the seated
application home it boots over, and the sanitised environment an out-of-tree
subprocess is given.

Acquiring the ports it boots on is a separate concept with its own home,
:mod:`vaultspec_a2a.testing.ports`, and this consumes it. Nothing about holding
a scratch-band reservation is specific to a gateway - most callers of that
helper never boot one - so keeping it here made a general primitive reachable
only through a gateway module.

It lives at the package-root test tier rather than inside any one test package
on purpose. ``desktop_tests``, ``acceptance``, ``service_tests`` and every
per-package ``tests/`` directory are PEERS: making one of them the library the
others import inverts the tier relationship, which is exactly how the previous
arrangement drifted - ``acceptance`` grew a whole-module copy of the desktop
boot helper under a rename map, and the two copies then disagreed about the
readiness budget, the log-tail budget, and, dangerously, about whether a dead
child may be tree-killed. ``vaultspec_a2a.tests`` is owned by no feature
package, so importing from it is a downward import for every tier and a lateral
one for none. It is excluded from the runtime wheel by the existing
``**/tests`` denylist, so no test harness leaks into the product.

Two properties of the boot close the recurring admission-gate flake:

- **death-aware readiness**: the poll watches the child process; a gateway that
  exits before readiness fails IMMEDIATELY with its exit code and log tail
  (:class:`GatewayBootError`), never after a silent full-budget wait;
- **bind-race retry**: :func:`spawn_until_ready` re-allocates a fresh port and
  respawns on :class:`GatewayBootError`, bounded attempts. Only a DEAD child is
  retried - a live-but-unready gateway still fails loudly at the deadline, so a
  real boot regression cannot hide behind the retry. The attempts share one log
  file, so a retried run's log carries the dead attempt's bind error.

A boot that fails is also REAPED here rather than left running. The failure mode
this closes is cumulative, not local: a gateway that never became ready is still
a live process holding its port, its database handles, and its share of the
machine, and nothing downstream owns it - the caller's context manager never
received a handle to reap because the failure happened before the yield. Every
such failure used to leak one gateway tree, and a handful of them starve the box
until later boots time out too, turning one real failure into a cascade.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from typing import IO, TYPE_CHECKING, Literal

import httpx

from ..desktop._platform_acl import harden_credential_path
from ..desktop.credentials import (
    ATTACH_CREDENTIAL_NAME,
    OWNERSHIP_CAPABILITY_NAME,
)
from ..desktop.profile import derive_state_paths
from ..testing.ports import (
    allocate_free_ports,
    hold_for_process_lifetime,
    reserve_scratch_ports,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path


__all__ = [
    "READINESS_TIMEOUT",
    "GatewayBootError",
    "GatewayLogLevel",
    "armed_gateway_env",
    "await_gateway_ready",
    "clean_subprocess_environment",
    "gateway_script",
    "reap_gateway",
    "seat_valid_database",
    "seed_credentials",
    "spawn_gateway",
    "spawn_until_ready",
]

# The readiness budget for every tier. Deliberately the larger of the two values
# the forked copies disagreed about (40.0 and 60.0), because the poll is
# death-aware: a child that dies - the bind race, the real failure mode - fails
# immediately with its exit code, so this deadline only ever bounds the
# alive-but-slow case. There the cost of being too short is a FALSE failure on a
# loaded box, and the cost of being too long is latency on a genuine hang only.
# The tree already carried direct evidence that 40.0 was under the worst case:
# the ownership-prerequisite gate, which boots through the production ``serve``
# verb rather than a bare uvicorn script, had to override it upward to 60.0.
# Sizing the default for the slowest existing boot path costs a passing run
# nothing, since readiness returns the moment ``/health`` answers.
READINESS_TIMEOUT = 60.0

# The larger of the two forked values. This budget is diagnostic only - it caps
# how much of a dead child's log is quoted into the failure - so the wider tail
# buys context on the hardest boots at no runtime cost.
_LOG_TAIL_BYTES = 4096

_MIGRATE_MODULE = "vaultspec_a2a.cli.main"

GatewayLogLevel = Literal["info", "warning"]

# The child gateway is a real interpreter running the production ASGI app under
# uvicorn; nothing here is stubbed. The armed desktop profile is selected by the
# environment the parent passes, so this program carries no test-only wiring.
#
# The two forms are INTENTIONALLY distinct and must not be collapsed. The
# INFO form's ``logging.basicConfig(level=logging.INFO)`` is the only reason
# application log lines such as the worker auto-spawn announcement are
# observable at all, and gates assert on them. The quiet form installs no root
# handler and runs uvicorn at ``warning``, which is what lets the credential and
# readiness gates assert on a log that carries nothing but real warnings.
_GATEWAY_SCRIPT_INFO = """
import logging
import sys

logging.basicConfig(level=logging.INFO)
import uvicorn
from vaultspec_a2a.api.app import create_app

port = int(sys.argv[1])
uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")
"""

_GATEWAY_SCRIPT_QUIET = """
import sys
import uvicorn
from vaultspec_a2a.api.app import create_app

port = int(sys.argv[1])
uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")
"""

# Interpreter and package-manager state that would leak the running virtual
# environment into a child asked to exercise a freshly installed one.
_LEAKING_ENVIRONMENT_NAMES = (
    "PYTHONHOME",
    "PYTHONPATH",
    "UV_PROJECT_ENVIRONMENT",
    "VIRTUAL_ENV",
)


class GatewayBootError(AssertionError):
    """The gateway process exited before its readiness endpoint answered.

    One class for every tier. Two of these used to exist under the same name in
    two packages with no shared base, so an ``except GatewayBootError`` written
    against one silently failed to catch the other.
    """


def gateway_script(*, log_level: GatewayLogLevel) -> str:
    """Return the child gateway program at *log_level*.

    ``"info"`` installs a root logging handler at INFO and runs uvicorn at
    ``info``; ``"warning"`` installs no root handler and runs uvicorn at
    ``warning``. The two are parameterised rather than unified because the
    difference is load-bearing in both directions - see the module comment above
    the script constants.
    """
    return _GATEWAY_SCRIPT_INFO if log_level == "info" else _GATEWAY_SCRIPT_QUIET


def _log_tail(log_path: Path | None) -> str:
    if log_path is None:
        return ""
    try:
        data = log_path.read_bytes()
    except OSError:
        return ""
    tail = data[-_LOG_TAIL_BYTES:].decode("utf-8", errors="replace")
    return f"; log tail:\n{tail}" if tail else ""


def await_gateway_ready(
    base: str,
    proc: subprocess.Popen[bytes],
    *,
    log_path: Path | None = None,
    timeout: float = READINESS_TIMEOUT,
) -> None:
    """Wait until ``GET /health`` answers 200, failing FAST on a dead child.

    Raises :class:`GatewayBootError` the moment the spawned process exits before
    readiness (the bind-race signature), carrying the exit code and the log
    tail. A process that stays alive but never becomes ready raises a plain
    :class:`AssertionError` at the deadline - that is a genuine readiness
    failure and is never retried.
    """
    deadline = time.monotonic() + timeout
    last: str | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise GatewayBootError(
                f"gateway process exited before readiness "
                f"(exit {proc.returncode}){_log_tail(log_path)}"
            )
        try:
            with httpx.Client(base_url=base, timeout=2.0) as client:
                if client.get("/health").status_code == 200:
                    return
        except httpx.HTTPError as exc:  # not up yet
            last = repr(exc)
        time.sleep(0.1)
    raise AssertionError(
        f"gateway readiness never came up ({last}){_log_tail(log_path)}"
    )


def reap_gateway(proc: subprocess.Popen[bytes]) -> None:
    """Terminate a spawned gateway TREE, tolerating an already-dead child.

    The tree, not the handle: on Windows the virtual-environment interpreter is
    a launcher stub, so the real gateway - and any worker it auto-spawned - are
    descendants that outlive a kill aimed at the handle alone.

    The dead-child guard is not a micro-optimisation. Several callers reach here
    on a path where the child is already known dead, and Windows recycles pids:
    a tree kill aimed at a reaped pid is aimed at whatever process now holds
    that number.
    """
    if proc.poll() is not None:
        return
    import asyncio

    from ..utils import kill_pid_tree_async

    with contextlib.suppress(Exception):
        asyncio.run(kill_pid_tree_async(proc.pid, term_timeout=10.0, kill_timeout=5.0))
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=15)


def spawn_until_ready(
    spawn: Callable[[int, int], subprocess.Popen[bytes]],
    *,
    log_path: Path | None = None,
    attempts: int = 3,
    timeout: float = READINESS_TIMEOUT,
) -> tuple[subprocess.Popen[bytes], int, int, str]:
    """Boot a gateway on a fresh port pair, retrying only the bind-race death.

    *spawn* receives ``(gateway_port, worker_port)`` and returns the spawned
    process; this drives up to *attempts* boots, each on freshly allocated
    ports, and returns ``(proc, gateway_port, worker_port, base)`` once the
    gateway answers its health endpoint. A child that dies before readiness is
    retried on new ports; the final attempt's failure propagates.

    Ownership of a FAILED boot ends here. Only a successful boot hands its
    process to the caller, so a child still running after a failed attempt has
    no other owner and is reaped before this returns or raises - including on an
    interrupt, which is when a leaked gateway is least likely to be noticed.
    """
    from ..lifecycle import release_reservation

    last_boot_error: GatewayBootError | None = None
    for _ in range(attempts):
        # Reserve the pair through the registry first (default-safe: a
        # concurrent session cannot be handed either number while the markers
        # hold), falling back to one atomic candidate call so the pair cannot
        # collide with itself: a gateway handed its own port for its worker
        # would die on the second bind and burn a retry.
        reservations = reserve_scratch_ports(2)
        if reservations is not None:
            gateway_port, worker_port = (r.port for r in reservations)
        else:
            gateway_port, worker_port = allocate_free_ports(2)
        proc = spawn(gateway_port, worker_port)
        base = f"http://127.0.0.1:{gateway_port}"
        try:
            await_gateway_ready(base, proc, log_path=log_path, timeout=timeout)
        except GatewayBootError as exc:
            # Called for symmetry and for the narrow window where the child died
            # between the poll and here; by this error's definition it is already
            # dead, so the dead-child guard normally makes this a no-op. It does
            # NOT recover descendants a dead child had already spawned - once the
            # root pid is gone there is no tree left to walk - which is why the
            # harness relies on the gateway's own containment for that case.
            reap_gateway(proc)
            if reservations is not None:
                for reservation in reservations:
                    release_reservation(reservation)
            last_boot_error = exc
            continue
        except BaseException:
            # Unready-at-deadline, interrupt, or anything else: this attempt
            # never becomes the caller's, so it must not outlive the failure.
            reap_gateway(proc)
            if reservations is not None:
                for reservation in reservations:
                    release_reservation(reservation)
            raise
        if reservations is not None:
            # The gateway provably bound its port (readiness answered), so the
            # bind itself now excludes claimants and the marker goes back to
            # the band. The worker port may still be UNBOUND - the gateway
            # spawns its worker lazily - so that marker is held for the
            # process lifetime; pid-death reclaim retires it if we die.
            gateway_reservation, worker_reservation = reservations
            release_reservation(gateway_reservation)
            hold_for_process_lifetime(worker_reservation)
        return proc, gateway_port, worker_port, base
    raise AssertionError(
        f"gateway did not boot within {attempts} attempts; last: {last_boot_error}"
    )


def armed_gateway_env(
    app_home: Path,
    *,
    gateway_port: int,
    worker_port: int,
    auto_spawn_worker: bool = True,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the armed desktop environment a real gateway child is spawned with.

    The worker derives its declared gateway URL from the same gateway port,
    which is what lets a gateway-spawned worker and an independently started one
    be compared on identical addressing facts. *extra* is applied last, so a
    caller can add or override any variable.

    *extra* is an explicit mapping rather than ``**kwargs``: a keyword-splat
    would collide with ``auto_spawn_worker`` for any caller forwarding its own
    ``**extra_env``, which is exactly what several callers do.
    """
    env = os.environ.copy()
    env["VAULTSPEC_DESKTOP_APP_HOME"] = str(app_home)
    env["VAULTSPEC_ENVIRONMENT"] = "production"
    env["VAULTSPEC_PORT"] = str(gateway_port)
    env["VAULTSPEC_WORKER_PORT"] = str(worker_port)
    env["VAULTSPEC_AUTO_SPAWN_WORKER"] = "true" if auto_spawn_worker else "false"
    if extra:
        env.update(extra)
    return env


def spawn_gateway(
    *,
    script: str,
    gateway_port: int,
    env: Mapping[str, str],
    log_handle: IO[bytes],
    new_session: bool = False,
) -> subprocess.Popen[bytes]:
    """Spawn the child gateway interpreter, logging its merged output.

    *new_session* is honoured on POSIX only (``start_new_session`` has no
    Windows equivalent here); pass it where the caller wants the child detached
    from the test runner's process group.
    """
    return subprocess.Popen(
        [sys.executable, "-c", script, str(gateway_port)],
        env=dict(env),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=new_session and os.name != "nt",
    )


def seed_credentials(app_home: Path, *, attach: str, ownership: str) -> Path:
    """Write the dashboard-created attach and ownership credential files.

    Returns the credentials directory, which gates that also read the
    gateway-minted worker-IPC secret out of it need.
    """
    state = derive_state_paths(app_home)
    state.credentials_dir.mkdir(parents=True, exist_ok=True)
    for name, secret in (
        (ATTACH_CREDENTIAL_NAME, attach),
        (OWNERSHIP_CAPABILITY_NAME, ownership),
    ):
        path = state.credentials_dir / name
        path.write_text(secret, encoding="utf-8")
        harden_credential_path(path)
    return state.credentials_dir


def seat_valid_database(app_home: Path) -> None:
    """Seat a valid desktop database via the real ``migrate`` entrypoint."""
    result = subprocess.run(
        [sys.executable, "-m", _MIGRATE_MODULE, "migrate", "--app-home", str(app_home)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        raise GatewayBootError(
            f"migrate failed (exit {result.returncode}): "
            f"{result.stdout}\n{result.stderr}"
        )
    payload = json.loads(result.stdout.strip())
    if payload.get("status") != "succeeded":
        raise GatewayBootError(f"migrate did not succeed: {payload}")
    if not derive_state_paths(app_home).database_path.is_file():
        raise GatewayBootError("migrate reported success but no database file exists")


def clean_subprocess_environment() -> dict[str, str]:
    """The current environment with this virtual environment's leakage removed.

    A child asked to exercise a freshly installed capsule must not inherit the
    running interpreter's ``PYTHONHOME``/``PYTHONPATH`` or the project's uv
    environment pointers, or it resolves the development tree instead of what
    was installed. Colour and progress output are also suppressed so captured
    output is comparable.
    """
    environment = dict(os.environ)
    for name in _LEAKING_ENVIRONMENT_NAMES:
        environment.pop(name, None)
    environment["NO_COLOR"] = "1"
    environment["UV_NO_PROGRESS"] = "1"
    return environment
