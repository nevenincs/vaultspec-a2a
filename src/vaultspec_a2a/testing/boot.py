"""Real-process boot for every tier that spawns the product.

This module is the single home of the primitives a real-process tier needs to
stand a production gateway up and take it down again: death-aware readiness,
bind-race retry, whole-tree reaping, the child gateway program, the seated
application home it boots over, and the environment a gateway child is given. It
also owns the other peers a tier spawns or serves beside a gateway - a stranger
process squatting on a worker port, a loopback listener for a worker bridge's
callbacks, and the spawner a test attaches to a worker it did not start.

Acquiring the ports it boots on is a separate concept with its own home,
:mod:`vaultspec_a2a.testing.ports`, and this consumes it. Nothing about holding
a scratch-band reservation is specific to a gateway - most callers of that
helper never boot one - so keeping it here would make a general primitive
reachable only through a gateway module.

``desktop_tests``, ``acceptance``, ``service_tests`` and every per-package
``tests/`` directory are PEERS: making one of them the library the others import
inverts the tier relationship, which is exactly how the arrangement this
replaced drifted - ``acceptance`` grew a whole-module copy of the desktop boot
helper under a rename map, and the two copies then disagreed about the
readiness budget, the log-tail budget, and, dangerously, about whether a dead
child may be tree-killed. ``testing`` is owned by no tier, so importing from it
is a downward import for every tier and a lateral one for none, and it is
excluded from the runtime wheel, so no harness leaks into the product.

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
until later boots time out too, turning one real failure into a cascade. Every
process this module starts runs in its own containment from its first
instruction and is reaped through it, so a root that already died does not put
its descendants out of reach.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import httpx
from fastapi import FastAPI

from ..desktop._platform_acl import harden_credential_path
from ..desktop.credentials import (
    ATTACH_CREDENTIAL_NAME,
    OWNERSHIP_CAPABILITY_NAME,
    create_worker_ipc_credential,
    credential_paths,
)
from ..desktop.profile import derive_state_paths
from ..utils import ProcessContainment, spawn_contained
from ..utils.runtime_exec import self_command
from .cli import run_cli
from .http import serve_on_loopback
from .lanes import armed_lane_environment
from .ports import (
    allocate_free_ports,
    hold_for_process_lifetime,
    reserve_scratch_ports,
)
from .reap import reap_contained

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        Callable,
        Generator,
        Mapping,
        Sequence,
    )
    from pathlib import Path

    from ..control.state_layout import StateLayout
    from ..control.worker_management import LazyWorkerSpawner
    from ..worker.ipc import WorkerBridge


__all__ = [
    "DEFAULT_ATTACH_CREDENTIAL",
    "DEFAULT_OWNERSHIP_CAPABILITY",
    "FIRST_DEMAND_TIMEOUT",
    "FOREIGN_WORKER_PROGRAM",
    "LOOPBACK_TIMEOUT",
    "READINESS_TIMEOUT",
    "BootedGateway",
    "GatewayBootError",
    "SignalledChild",
    "WatchedProcess",
    "adopted_spawner",
    "armed_gateway_env",
    "await_gateway_ready",
    "await_ready",
    "booted_gateway",
    "broker_gateway_env",
    "desktop_workspace",
    "foreign_worker",
    "gateway_process_env",
    "gateway_script",
    "log_tail",
    "loopback_callback_bridge",
    "read_worker_ipc_secret",
    "reap_process",
    "seat_app_home",
    "spawn_gateway",
    "spawn_logged",
    "spawn_signalled",
    "spawn_until_ready",
    "worker_lifecycle_gateway_script",
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

# The worker-readiness budget a HARNESS gateway is armed with, and the budget a
# caller must allow the verb that triggers first demand.
#
# The product's own default (30s) is sized for a desktop starting one worker for
# one user. A harness host is a different machine: several certification stacks,
# an xdist fan-out, and the suite itself start interpreters at the same moment,
# and a worker cold start there legitimately runs past a budget that is generous
# on an idle box. Past it the gateway does not merely answer slowly - it ABANDONS
# the spawn and reaps the tree, so the next prepare is refused not-ready and
# every admission proof downstream fails for a reason that is about host load
# rather than about admission. Both values are applied before a caller's own
# environment and keyword overrides, so a test ABOUT these budgets still sets
# its own.
_WORKER_READY_TIMEOUT = 180.0
FIRST_DEMAND_TIMEOUT = 300.0

# A loopback client budget for a verb that asserts on a RESPONSE rather than on
# latency. It exists only so a wedged gateway fails the call instead of hanging
# the session; the per-item pytest-timeout backstop remains the real guard. A
# test that genuinely measures response time states its own, smaller budget.
LOOPBACK_TIMEOUT = 60.0

# The larger of the two forked values. This budget is diagnostic only - it caps
# how much of a dead child's log is quoted into the failure - so the wider tail
# buys context on the hardest boots at no runtime cost.
_LOG_TAIL_BYTES = 4096

# The dashboard-created credential pair a seated home carries unless a test
# needs its own. Distinct, and long enough for the production length floor; a
# test that scans for a leaked secret can scan for these as well as any other.
DEFAULT_ATTACH_CREDENTIAL = "attach-credential-harness-1234567890abcdef"
DEFAULT_OWNERSHIP_CAPABILITY = "ownership-capability-harness-fedcba0987654321"

GatewayLogLevel = Literal["info", "warning"]

# Builds a gateway child's environment for ``(gateway_port, worker_port)``.
type GatewayEnv = Callable[[int, int], dict[str, str]]

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
from vaultspec_a2a.lifecycle.shutdown import bind_shutdown_owner

port = int(sys.argv[1])
app = create_app()
server = uvicorn.Server(
    uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
)
bind_shutdown_owner(app, server)
server.run()
"""

_GATEWAY_SCRIPT_QUIET = """
import sys
import uvicorn
from vaultspec_a2a.api.app import create_app
from vaultspec_a2a.lifecycle.shutdown import bind_shutdown_owner

port = int(sys.argv[1])
app = create_app()
server = uvicorn.Server(
    uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
)
bind_shutdown_owner(app, server)
server.run()
"""

# A real stranger process answering ``/health`` with a fixed body on a worker
# port, recording every request it receives. It is the modeled adversary - a
# process the gateway did not start holding the port - and never a stand-in for
# code under test: it imports nothing of the product, so nothing it answers can
# be mistaken for the product's own behaviour. Every ``POST`` is refused, so a
# shutdown aimed at it is recorded and survived.
FOREIGN_WORKER_PROGRAM = """
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(sys.argv[1])
body = json.loads(sys.argv[2])
log_path = sys.argv[3]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with open(log_path, "a", encoding="utf-8") as log:
            log.write("GET " + self.path + "\\n")
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        with open(log_path, "a", encoding="utf-8") as log:
            log.write("POST " + self.path + "\\n")
        self.send_response(503)
        self.end_headers()

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""


class GatewayBootError(AssertionError):
    """A process exited before its readiness probe passed.

    One class for every tier. Two of these used to exist under the same name in
    two packages with no shared base, so an ``except GatewayBootError`` written
    against one silently failed to catch the other.
    """


@dataclass(frozen=True, slots=True)
class WatchedProcess:
    """A process the kit started in its own containment, and the log of its death.

    The containment has held the whole tree since the root's first instruction,
    so :func:`reap_process` reaps everything the process started, whether or not
    the root is still alive.
    """

    name: str
    process: subprocess.Popen[bytes]
    containment: ProcessContainment
    log_path: Path | None = None


@dataclass(frozen=True, slots=True)
class BootedGateway:
    """One running gateway this process booted and will reap."""

    process: subprocess.Popen[bytes]
    base_url: str
    gateway_port: int
    worker_port: int
    log_path: Path


def gateway_script(*, log_level: GatewayLogLevel) -> str:
    """Return the child gateway program at *log_level*.

    ``"info"`` installs a root logging handler at INFO and runs uvicorn at
    ``info``; ``"warning"`` installs no root handler and runs uvicorn at
    ``warning``. The two are parameterised rather than unified because the
    difference is load-bearing in both directions - see the module comment above
    the script constants.
    """
    return _GATEWAY_SCRIPT_INFO if log_level == "info" else _GATEWAY_SCRIPT_QUIET


def worker_lifecycle_gateway_script() -> str:
    """Exercise real worker ownership below the run-admission boundary.

    The driver composes the production lifespan and spawner directly. It never
    admits a desktop run; its subject is worker pairing and lifespan cleanup.
    """
    return """
import asyncio
import logging
import sys
import uvicorn
from vaultspec_a2a.api.app import create_app, gateway_lifespan
from vaultspec_a2a.lifecycle.shutdown import bind_shutdown_owner

logging.basicConfig(level=logging.INFO)
app = create_app()
server = uvicorn.Server(uvicorn.Config(
    app, host="127.0.0.1", port=int(sys.argv[1]), log_level="info", lifespan="off"
))
bind_shutdown_owner(app, server)

async def main():
    async with gateway_lifespan(app):
        await app.state.worker_spawner.ensure_worker()
        print(
            f"lifecycle worker spawned: {app.state.worker_spawner.spawned}", flush=True
        )
        await server.serve()

asyncio.run(main())
"""


def log_tail(log_path: Path | None, *, limit: int = _LOG_TAIL_BYTES) -> str:
    """Return the last *limit* bytes of *log_path* as text, or ``""``."""
    if log_path is None:
        return ""
    try:
        data = log_path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", errors="replace")


def _tails(watch: Sequence[WatchedProcess]) -> str:
    return "".join(
        f"\n--- {watched.name} log tail ---\n{tail}"
        for watched in watch
        if (tail := log_tail(watched.log_path))
    )


def await_ready(
    probe: Callable[[], bool],
    *,
    what: str,
    watch: Sequence[WatchedProcess] = (),
    timeout: float = READINESS_TIMEOUT,
    interval: float = 0.1,
) -> None:
    """Poll *probe* until it passes, failing FAST on a dead watched process.

    Raises :class:`GatewayBootError` the moment a watched process exits before
    the probe passes (the bind-race signature), carrying its exit code and log
    tail. A probe that never passes while every watched process stays alive
    raises a plain :class:`AssertionError` at the deadline - that is a genuine
    readiness failure and is never retried. A probe that raises an HTTP or
    decoding error counts as not-yet-ready.

    A wait with no *watch* - a service whose lifecycle another owner holds, such
    as a Compose-managed container - keeps the plain deadline, because there is
    no exit status to consult.
    """
    deadline = time.monotonic() + timeout
    last: str | None = None
    while time.monotonic() < deadline:
        for watched in watch:
            if watched.process.poll() is not None:
                raise GatewayBootError(
                    f"{what}: {watched.name} exited before readiness "
                    f"(exit {watched.process.returncode}){_tails([watched])}"
                )
        try:
            if probe():
                return
        except (httpx.HTTPError, ValueError) as exc:  # not up yet
            last = repr(exc)
        time.sleep(interval)
    raise AssertionError(f"{what} readiness never came up ({last}){_tails(watch)}")


def _answers_health(base: str, *, timeout: float) -> bool:
    with httpx.Client(base_url=base, timeout=timeout) as client:
        return client.get("/health").status_code == 200


def await_gateway_ready(
    base: str,
    gateway: WatchedProcess,
    *,
    timeout: float = READINESS_TIMEOUT,
) -> None:
    """Wait until the gateway at *base* answers ``GET /health`` 200.

    :func:`await_ready` over the gateway's unauthenticated liveness, watching
    *gateway*: a gateway that dies first fails at once with its exit code and
    log.
    """
    await_ready(
        lambda: _answers_health(base, timeout=2.0),
        what="gateway",
        watch=[gateway],
        timeout=timeout,
    )


def reap_process(watched: WatchedProcess) -> None:
    """Reap a spawned process TREE through its containment, from any context.

    The tree, not the handle: on Windows the virtual-environment interpreter is
    a launcher stub, so the real gateway - and any worker it auto-spawned - are
    descendants that outlive a kill aimed at the handle alone. The containment
    has held all of them since the root's first instruction, so a root that has
    already exited is no obstacle and no kill is aimed at a recycled pid. A
    repeat call is a no-op.
    """
    reap_contained(watched.process, watched.containment)


def spawn_logged(
    command: Sequence[str],
    *,
    name: str,
    env: Mapping[str, str],
    log_path: Path,
    cwd: Path | None = None,
    detached: bool = False,
) -> WatchedProcess:
    """Spawn *command* contained, with its merged output appended to *log_path*.

    The log is opened for this spawn only and closed again before returning: the
    child writes through its own inherited handle, so the parent keeps nothing a
    failed boot could leak, or that would block deleting the log on Windows.
    Appending keeps every attempt of a bind-race retry, and every lifetime of a
    deliberate restart over one home, in one file. *name* labels the process in
    a readiness failure.

    The child starts inside a fresh containment before its first instruction,
    and :func:`reap_process` reaps it through that containment. A POSIX child
    therefore always leads its own session; *detached* also gives a Windows
    child its own console process group, so a stray interrupt aimed at the
    runner's console does not reach it.
    """
    with log_path.open("ab") as log_handle:
        containment = ProcessContainment.create()
        process = spawn_contained(
            command,
            containment,
            env=env,
            cwd=cwd,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            new_process_group=detached,
        )
    return WatchedProcess(name, process, containment, log_path)


def spawn_gateway(
    *,
    script: str | None,
    gateway_port: int,
    env: Mapping[str, str],
    log_path: Path,
    detached: bool = False,
) -> WatchedProcess:
    """Spawn the child gateway interpreter, appending its output to *log_path*.

    *script* is a program from :func:`gateway_script` or
    :func:`worker_lifecycle_gateway_script`, handed the gateway port. ``None``
    boots through the production ``serve`` verb instead, which reads its port
    from *env* and is the only path that takes the runtime singleton before the
    listener binds. *detached* is as :func:`spawn_logged` describes.
    """
    command = (
        self_command("serve")
        if script is None
        else [sys.executable, "-c", script, str(gateway_port)]
    )
    return spawn_logged(
        command, name="gateway", env=env, log_path=log_path, detached=detached
    )


def spawn_until_ready(
    spawn: Callable[[int, int], WatchedProcess],
    *,
    attempts: int = 3,
    timeout: float = READINESS_TIMEOUT,
    ports: tuple[int, int] | None = None,
) -> tuple[WatchedProcess, int, int, str]:
    """Boot a gateway on a fresh port pair, retrying only the bind-race death.

    *spawn* receives ``(gateway_port, worker_port)`` and returns the spawned
    process; this drives up to *attempts* boots, each on freshly allocated
    ports, and returns ``(gateway, gateway_port, worker_port, base)`` once the
    gateway answers its health endpoint. A child that dies before readiness is
    retried on new ports; the final attempt's failure propagates.

    *ports* is a ``(gateway_port, worker_port)`` pair the caller claimed itself,
    because it must know both before the boot - to seat a peer on the worker
    port that reports the gateway's address, say. The pair is used as given, on
    one attempt: a pinned port cannot be re-rolled, so a bind race on it fails
    the boot instead of being retried.

    Ownership of a FAILED boot ends here. Only a successful boot hands its
    process to the caller, so a child still running after a failed attempt has
    no other owner and is reaped before this returns or raises - including on an
    interrupt, which is when a leaked gateway is least likely to be noticed.
    """
    from ..lifecycle import release_reservation

    tries = attempts if ports is None else 1
    last_boot_error: GatewayBootError | None = None
    for _ in range(tries):
        # Reserve the pair through the registry first (default-safe: a
        # concurrent session cannot be handed either number while the markers
        # hold), falling back to one atomic candidate call so the pair cannot
        # collide with itself: a gateway handed its own port for its worker
        # would die on the second bind and burn a retry.
        reservations = None if ports is not None else reserve_scratch_ports(2)
        if ports is not None:
            gateway_port, worker_port = ports
        elif reservations is not None:
            gateway_port, worker_port = (r.port for r in reservations)
        else:
            gateway_port, worker_port = allocate_free_ports(2)
        gateway = spawn(gateway_port, worker_port)
        base = f"http://127.0.0.1:{gateway_port}"
        try:
            await_gateway_ready(base, gateway, timeout=timeout)
        except GatewayBootError as exc:
            # The root is dead by this error's definition, but whatever it had
            # already spawned is still inside its containment, so the reap
            # recovers those descendants too.
            reap_process(gateway)
            if reservations is not None:
                for reservation in reservations:
                    release_reservation(reservation)
            last_boot_error = exc
            continue
        except BaseException:
            # Unready-at-deadline, interrupt, or anything else: this attempt
            # never becomes the caller's, so it must not outlive the failure.
            reap_process(gateway)
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
        return gateway, gateway_port, worker_port, base
    raise AssertionError(
        f"gateway did not boot within {tries} attempt(s); last: {last_boot_error}"
    )


@contextlib.contextmanager
def booted_gateway(
    env: GatewayEnv,
    *,
    log_path: Path,
    script: str | None,
    detached: bool = False,
    timeout: float = READINESS_TIMEOUT,
    ports: tuple[int, int] | None = None,
) -> Generator[BootedGateway]:
    """Boot one gateway on fresh ports, yield it once ready, and reap its tree.

    *env* builds the child's environment for the ports each attempt is given -
    :func:`armed_gateway_env` or :func:`broker_gateway_env`, or a caller's own
    builder. *script* and *detached* are as :func:`spawn_gateway` describes, and
    *ports* as :func:`spawn_until_ready` does. The tree is reaped when the body
    ends, whatever its outcome, so no gateway or worker it spawned outlives the
    test.
    """

    def _spawn(gateway_port: int, worker_port: int) -> WatchedProcess:
        return spawn_gateway(
            script=script,
            gateway_port=gateway_port,
            env=env(gateway_port, worker_port),
            log_path=log_path,
            detached=detached,
        )

    gateway, gateway_port, worker_port, base = spawn_until_ready(
        _spawn, timeout=timeout, ports=ports
    )
    try:
        yield BootedGateway(
            process=gateway.process,
            base_url=base,
            gateway_port=gateway_port,
            worker_port=worker_port,
            log_path=log_path,
        )
    finally:
        reap_process(gateway)


def gateway_process_env(
    *,
    gateway_port: int,
    worker_port: int,
    auto_spawn_worker: bool,
    serve_in_process_lanes: bool = False,
) -> dict[str, str]:
    """The production process environment every harness gateway starts from.

    The current environment, in the production profile, addressed on the given
    port pair, and armed with the harness's worker-readiness budget. Profiles
    layer their own stores and credentials on top.

    *serve_in_process_lanes* serves the in-process lanes, the source checkout's
    fixture lanes among them, through :func:`.lanes.armed_lane_environment`. A
    gateway hands its worker the environment it was given, so one declaration
    arms both processes.
    """
    env = os.environ.copy()
    env["VAULTSPEC_A2A_ENVIRONMENT"] = "production"
    env["VAULTSPEC_A2A_PORT"] = str(gateway_port)
    env["VAULTSPEC_A2A_WORKER_PORT"] = str(worker_port)
    env["VAULTSPEC_A2A_AUTO_SPAWN_WORKER"] = "true" if auto_spawn_worker else "false"
    env["VAULTSPEC_A2A_WORKER_READY_TIMEOUT_SECONDS"] = f"{_WORKER_READY_TIMEOUT:g}"
    if serve_in_process_lanes:
        env.update(armed_lane_environment())
    return env


_DESKTOP_WORKSPACES: dict[int, Path] = {}


def armed_gateway_env(
    app_home: Path,
    *,
    auto_spawn_worker: bool = True,
    extra: Mapping[str, str] | None = None,
) -> GatewayEnv:
    """The armed desktop environment a real gateway child over *app_home* gets.

    The worker derives its declared gateway URL from the same gateway port,
    which is what lets a gateway-spawned worker and an independently started one
    be compared on identical addressing facts. *extra* is applied last, so a
    caller can add or override any variable.

    *extra* is an explicit mapping rather than ``**kwargs``: a keyword-splat
    would collide with ``auto_spawn_worker`` for any caller forwarding its own
    ``**extra_env``, which is exactly what several callers do.
    """

    def _env(gateway_port: int, worker_port: int) -> dict[str, str]:
        env = gateway_process_env(
            gateway_port=gateway_port,
            worker_port=worker_port,
            auto_spawn_worker=auto_spawn_worker,
        )
        env["VAULTSPEC_A2A_DESKTOP_APP_HOME"] = str(app_home)
        if extra:
            env.update(extra)
        _DESKTOP_WORKSPACES[gateway_port] = (
            derive_state_paths(app_home).workspaces_root / "project"
        )
        return env

    return _env


def broker_gateway_env(
    app_home: Path,
    *,
    gateway_token: str,
    auto_spawn_worker: bool = True,
    extra: Mapping[str, str] | None = None,
) -> GatewayEnv:
    """Boot authenticated broker tests outside the desktop execution profile.

    Desktop admission refuses execution until native isolation is qualified.
    Independent broker tests use explicit stores under *app_home*, real gateway
    and worker auth, and the in-process lanes served, the source checkout's
    fixture lanes among them. *extra* is applied last.
    """
    armed = armed_gateway_env(app_home, auto_spawn_worker=auto_spawn_worker)

    def _env(gateway_port: int, worker_port: int) -> dict[str, str]:
        env = armed(gateway_port, worker_port)
        env.pop("VAULTSPEC_A2A_DESKTOP_APP_HOME", None)
        state = derive_state_paths(app_home)
        env.update(
            {
                "VAULTSPEC_A2A_HOME": str(state.home),
                "VAULTSPEC_A2A_WORKSPACE_ROOT": str(state.workspaces_root),
                "VAULTSPEC_A2A_DATABASE_BACKEND": "sqlite",
                "VAULTSPEC_A2A_DATABASE_URL": (
                    f"sqlite+aiosqlite:///{state.database_path.as_posix()}"
                ),
                "VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL": (
                    f"sqlite+aiosqlite:///{state.checkpoint_path.as_posix()}"
                ),
                "VAULTSPEC_A2A_CHECKPOINT_BACKEND": "sqlite",
                "VAULTSPEC_A2A_GATEWAY_TOKEN": gateway_token,
                "VAULTSPEC_A2A_INTERNAL_TOKEN": create_worker_ipc_credential(
                    state.credentials_dir
                ),
                **armed_lane_environment(),
            }
        )
        if extra:
            env.update(extra)
        return env

    return _env


def desktop_workspace(base: str) -> str:
    """Create the project registered by this test-owned desktop gateway boot."""
    port = httpx.URL(base).port
    if port is None or port not in _DESKTOP_WORKSPACES:
        raise ValueError("No desktop workspace was registered for this gateway")
    workspace = _DESKTOP_WORKSPACES[port]
    workspace.mkdir(parents=True, exist_ok=True)
    return str(workspace)


def seat_app_home(
    app_home: Path,
    *,
    attach: str = DEFAULT_ATTACH_CREDENTIAL,
    ownership: str = DEFAULT_OWNERSHIP_CAPABILITY,
) -> StateLayout:
    """Seat a valid application home a gateway can boot over, and return its layout.

    Writes the dashboard-created attach and ownership credential files,
    owner-restricted, then seats the database through the real ``migrate``
    entrypoint. The returned layout carries the credentials directory - where the
    gateway later mints its worker-IPC secret - and the seated database.

    The migration is awaited on its own progress rather than on a wall clock: it
    is a real interpreter start plus real schema work, and how long that takes is
    a property of the host, not of the migration. A child that stops working is
    still caught, and reaped, by the progress wait.
    """
    app_home.mkdir(parents=True, exist_ok=True)
    state = derive_state_paths(app_home)
    state.credentials_dir.mkdir(parents=True, exist_ok=True)
    for name, secret in (
        (ATTACH_CREDENTIAL_NAME, attach),
        (OWNERSHIP_CAPABILITY_NAME, ownership),
    ):
        path = state.credentials_dir / name
        path.write_text(secret, encoding="utf-8")
        harden_credential_path(path)
    result = run_cli("migrate", "--app-home", str(app_home))
    if result.returncode != 0:
        raise GatewayBootError(
            f"migrate failed (exit {result.returncode}): "
            f"{result.stdout}\n{result.stderr}"
        )
    payload = json.loads(result.stdout.strip())
    if payload.get("status") != "succeeded":
        raise GatewayBootError(f"migrate did not succeed: {payload}")
    if not state.database_path.is_file():
        raise GatewayBootError("migrate reported success but no database file exists")
    return state


def read_worker_ipc_secret(app_home: Path) -> str:
    """The worker IPC secret the gateway over *app_home* minted at boot.

    Read from the real owner-restricted file at the production path, so a test
    that presents it to a worker or scans for its leak holds the very secret the
    gateway holds.
    """
    credentials_dir = derive_state_paths(app_home).credentials_dir
    return (
        credential_paths(credentials_dir)
        .worker_ipc_path.read_text(encoding="utf-8")
        .strip()
    )


@contextlib.contextmanager
def foreign_worker(
    port: int, body: Mapping[str, object], *, request_log: Path
) -> Generator[subprocess.Popen[bytes]]:
    """Run :data:`FOREIGN_WORKER_PROGRAM` on *port*, answering ``/health`` with *body*.

    Every request it receives is appended to *request_log* as ``METHOD path``,
    so a test can prove what the gateway asked of it - a health read, or an
    eviction attempt. Yields the process once it answers, and reaps its tree
    through its containment after.
    """
    request_log.write_text("", encoding="utf-8")
    containment = ProcessContainment.create()
    process = spawn_contained(
        [
            sys.executable,
            "-c",
            FOREIGN_WORKER_PROGRAM,
            str(port),
            json.dumps(body),
            str(request_log),
        ],
        containment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    squatter = WatchedProcess("foreign worker", process, containment)
    try:
        await_ready(
            lambda: _answers_health(f"http://127.0.0.1:{port}", timeout=1.0),
            what="foreign worker",
            watch=[squatter],
            timeout=10.0,
            interval=0.05,
        )
        yield process
    finally:
        reap_process(squatter)


@dataclass(frozen=True, slots=True)
class SignalledChild:
    """A child program that reports readiness, and is told to stop, through files.

    For a probe that runs production code in an interpreter of its own rather
    than a gateway: the program writes a payload to *ready* once it holds what
    the test inspects, and exits once *stop* exists. It runs in its own
    *containment*, through which its tree is reaped.
    """

    process: subprocess.Popen[bytes]
    containment: ProcessContainment
    ready: Path
    stop: Path

    def payload(self, *, timeout: float = 25.0) -> str:
        """Wait for the child's ready payload and return it.

        Death-aware: a child that exits before it reports fails at once with
        its exit code, rather than after the whole budget.
        """
        await_ready(
            lambda: (
                self.ready.is_file() and bool(self.ready.read_text(encoding="utf-8"))
            ),
            what="signalled child",
            watch=[WatchedProcess(self.ready.stem, self.process, self.containment)],
            timeout=timeout,
            interval=0.05,
        )
        return self.ready.read_text(encoding="utf-8")

    def request_stop(self, *, timeout: float = 25.0) -> int:
        """Ask the child to stop and return its exit status.

        A child that ignores the request past *timeout* is reaped as a tree, and
        so is anything a child that honoured it left running in its containment.
        """
        self.stop.touch()
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.process.wait(timeout=timeout)
        reap_contained(self.process, self.containment)
        return self.process.wait(timeout=timeout)


def spawn_signalled(
    program: str, *args: str, signal_dir: Path, tag: str
) -> SignalledChild:
    """Run *program* in a contained child interpreter as a :class:`SignalledChild`.

    The child is handed *args* followed by its ready and stop file paths, both
    under *signal_dir* and named by *tag*.
    """
    ready = signal_dir / f"{tag}.ready"
    stop = signal_dir / f"{tag}.stop"
    containment = ProcessContainment.create()
    process = spawn_contained(
        [sys.executable, "-c", program, *args, str(ready), str(stop)], containment
    )
    return SignalledChild(
        process=process, containment=containment, ready=ready, stop=stop
    )


async def _accept_callback() -> dict[str, str]:
    """Accept one of the bridge's real callbacks - an event batch or a heartbeat."""
    return {"status": "ok"}


@contextlib.asynccontextmanager
async def loopback_callback_bridge(
    gateway: FastAPI | None = None,
) -> AsyncGenerator[WorkerBridge]:
    """Serve worker callbacks on an ephemeral loopback listener.

    ``WorkerBridge`` remains normally constructed with its production HTTP
    client; only the callback destination is local to the test. With no
    *gateway* the callbacks are accepted and dropped; given the gateway app
    under test, they reach its real internal routes, so the worker's own frames
    drive the relay a deployed gateway runs. The bridge presents the internal
    token that gateway seated, since that is the secret its relay routes verify.
    """
    from ..worker.ipc import WorkerBridge

    internal_token: str | None = None
    if gateway is None:
        app = FastAPI()
        for path in ("/internal/events/batch", "/internal/heartbeat"):
            app.add_api_route(path, _accept_callback, methods=["POST"])
    else:
        app = gateway
        internal_token = gateway.state.internal_token

    async with serve_on_loopback(app, lifespan="off") as base:
        bridge = WorkerBridge(
            api_url=base,
            worker_id="loopback-callback-worker",
            internal_token=internal_token,
        )
        try:
            yield bridge
        finally:
            await bridge.close()


def adopted_spawner(
    worker_url: str = "http://worker", worker_port: int = 8001
) -> LazyWorkerSpawner:
    """A spawner attached to an already serving worker that it never starts.

    Adoption marks the dispatch target usable without a health probe, so a test
    that reaches the worker through its own client - an in-process ASGI app, or an
    unreachable address chosen to provoke a transport failure - is not also sent
    through the spawner's attach path. Auto-spawn is off, so nothing built here can
    launch a worker. A test of the attach or spawn path itself constructs
    ``LazyWorkerSpawner`` directly instead: adoption would settle the very state it
    asserts on.
    """
    from ..control.worker_management import LazyWorkerSpawner

    spawner = LazyWorkerSpawner(
        worker_url=worker_url, worker_port=worker_port, auto_spawn=False
    )
    spawner.adopt_worker()
    return spawner
