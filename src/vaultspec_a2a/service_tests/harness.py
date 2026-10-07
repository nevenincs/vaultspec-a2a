"""Session-scoped service harness for the deterministic certification stack.

What is specific to the service tier lives here: the Compose-managed fixture
services, the fixed native gateway and worker profile they certify, and the
diagnostics a failed session leaves behind. Spawning, death-aware readiness,
tree reaping, log tails and the run-start verb are the shared primitives of
:mod:`vaultspec_a2a.testing`, composed rather than re-implemented.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast

import httpx
from sqlalchemy.engine import make_url

from ..control.config import settings
from ..graph.enums import Provider
from ..testing import (
    GatewayBootError,
    NoSelectableLaneError,
    RunVerbs,
    WatchedProcess,
    armed_lane_environment,
    await_ready,
    fetch_in_process_selection,
    free_port,
    gateway_process_env,
    log_tail,
    prune_stale_dirs,
    reap_process,
    spawn_logged,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class _PermissionResponseOptions(TypedDict, total=False):
    """Optional wire values accepted by :meth:`ServiceStack.respond_permission`."""

    kind: str | None
    idempotency_key: str | None
    expected_status: int


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "service" / "docker-compose.integration.yml"


# Service-test runtime lives in the machine-global A2A home, not inside
# .vault/ — vaultspec firmware rejects foreign directories inside the vault.
RUNTIME_ROOT = settings.a2a_home / "runtime" / "service-tests"
# The worker interprocess-communication token the harness gives its production
# worker. It is the single source: injected into the worker env and presented on
# the harness's own worker probes, which the gated worker surface now requires.
_INTERNAL_TOKEN = "vaultspec-integration-token"
# The engine-facing /v1 bearer this harness gives its gateway. The whole /v1
# router sits behind the attach gate, so without presenting this every call the
# harness makes - create, list, state, cancel - is a 401 and no service test can
# reach the surface it exists to certify.
#
# Deliberately NOT _INTERNAL_TOKEN: that is the worker IPC secret, and the two
# planes must never alias ("never shared with worker IPC or embedded in
# discovery"). Configuring it explicitly is also what makes it knowable here at
# all - left unset the gateway mints a per-process credential the harness has no
# way to learn.
_GATEWAY_SERVICE_TOKEN = "vaultspec-integration-gateway-token"


def _compose_env(ports: dict[str, int], project_name: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "COMPOSE_PROJECT_NAME": project_name,
            "COMPOSE_DISABLE_ENV_FILE": "1",
            "VAULTSPEC_A2A_PORT": str(ports["gateway"]),
            "VAULTSPEC_A2A_WORKER_PORT": str(ports["worker"]),
            "VIDAIMOCK_PORT": str(ports["vidaimock"]),
            "JAEGER_UI_PORT": str(ports["jaeger_ui"]),
            "JAEGER_OTLP_PORT": str(ports["jaeger_otlp"]),
        }
    )
    return env


def _compose_base_command(project_name: str) -> list[str]:
    docker = resolve_docker_executable()
    return [
        docker,
        "compose",
        "-p",
        project_name,
        "-f",
        str(COMPOSE_FILE),
    ]


def resolve_docker_executable() -> str:
    """Resolve Docker from PATH only."""
    for candidate in ("docker", "docker.exe"):
        resolved = shutil.which(candidate)
        if resolved is not None:
            return resolved

    raise FileNotFoundError("Docker CLI executable could not be resolved from PATH")


def _run_compose(
    project_name: str,
    *args: str,
    ports: dict[str, int],
    timeout: float = 900.0,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _compose_base_command(project_name) + list(args),
        cwd=REPO_ROOT,
        env=_compose_env(ports, project_name),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=check,
    )


# The tail of a native process's log a session's diagnostics preserve: wider
# than a readiness failure quotes, because this is read after the fact.
_DIAGNOSTIC_LOG_TAIL_BYTES = 20000


RETAINED_RUNTIME_DIRS = 5
"""How many earlier service-test runtime directories survive beside the current one.

Deleting a run's directory outright would destroy the compose logs and session
summary the harness writes precisely so a failed run can be diagnosed after the
fact. Bounding the count keeps recent post-mortems available while stopping the
unbounded accumulation in the operator's machine-global home.
"""


@dataclass(slots=True)
class ServiceStack:
    """Owns native services and their Docker development fixtures for a session."""

    project_name: str
    ports: dict[str, int]
    postgres_url: str | None = field(default=None, repr=False)
    started_at: float = field(default_factory=time.time)
    runtime_dir: Path = field(init=False)
    artifacts: dict[str, Any] = field(default_factory=dict)
    _gateway_proc: subprocess.Popen[bytes] | None = field(
        default=None, init=False, repr=False
    )
    _worker_proc: subprocess.Popen[bytes] | None = field(
        default=None, init=False, repr=False
    )
    _gateway_log_name: str = field(default="gateway.log", init=False, repr=False)
    _stopped: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        # Resolve only. Creating the directory here meant constructing a stack -
        # which several unit-shaped tests do purely to inspect env and header
        # wiring, never starting anything - left a permanent directory in the
        # operator's real machine-global home. A side effect that survives the
        # process belongs behind an explicit action, not a constructor.
        self.runtime_dir = RUNTIME_ROOT / self.project_name

    def _ensure_runtime_dir(self) -> None:
        """Create the runtime directory at the point something will write to it."""
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        prune_stale_dirs(
            RUNTIME_ROOT, kept_newest=RETAINED_RUNTIME_DIRS, keep=self.runtime_dir
        )

    @property
    def gateway_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['gateway']}"

    @property
    def worker_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['worker']}"

    @property
    def vidaimock_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['vidaimock']}"

    @property
    def jaeger_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['jaeger_ui']}"

    @property
    def hold_gate(self) -> Path:
        """The gate this stack's hold-then-complete turns wait on.

        Hand it to :func:`vaultspec_a2a.testing.lanes.held_turns` to hold a run
        mid-turn on the real worker for the length of a block.
        """
        return self.runtime_dir / "hold-then-complete.gate"

    def record(self, name: str, payload: Any) -> None:
        self.artifacts[name] = payload

    def _client(self, *, timeout: float | None = 10.0) -> httpx.Client:
        # Every /v1 route is behind the attach gate, so the bearer belongs on the
        # shared client rather than on individual calls - one call built without
        # it is a 401 that reads like a broken route.
        return httpx.Client(
            base_url=self.gateway_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {_GATEWAY_SERVICE_TOKEN}"},
        )

    def gateway_client(self, *, timeout: float | None = 10.0) -> httpx.Client:
        """Return a gateway-scoped HTTP client for public API calls."""
        return self._client(timeout=timeout)

    def _worker_client(self) -> httpx.Client:
        # The worker surface (dispatch, health, admin) requires the worker IPC
        # bearer; the harness probes it as the paired gateway would, presenting the
        # same token it injected into the worker env.
        return httpx.Client(
            base_url=self.worker_url,
            timeout=10.0,
            headers={"Authorization": f"Bearer {_INTERNAL_TOKEN}"},
        )

    def _jaeger_client(self) -> httpx.Client:
        return httpx.Client(base_url=self.jaeger_url, timeout=10.0)

    def _vidaimock_client(self) -> httpx.Client:
        return httpx.Client(base_url=self.vidaimock_url, timeout=10.0)

    def _gateway_http_ready(self) -> bool:
        with self._client(timeout=5.0) as client:
            resp = client.get("/health")
            return resp.status_code == 200

    def _watched(self, *names: str) -> list[WatchedProcess]:
        """Return the named harness-owned processes that are currently spawned.

        Only processes this harness holds a ``Popen`` for are watchable; the
        compose-managed services are deliberately absent, since Docker owns
        their lifecycle and there is no local exit status to read.
        """
        owned: dict[str, subprocess.Popen[bytes] | None] = {
            "gateway": self._gateway_proc,
            "worker": self._worker_proc,
        }
        return [
            WatchedProcess(
                name,
                proc,
                self.runtime_dir
                / (self._gateway_log_name if name == "gateway" else f"{name}.log"),
            )
            for name in names
            if (proc := owned[name]) is not None
        ]

    def start(self) -> None:
        """Bring the deterministic compose stack online and wait for readiness."""
        self._ensure_runtime_dir()
        try:
            self._start_infra()
            self._start_gateway()
            await_ready(
                self._gateway_http_ready,
                what="gateway HTTP",
                watch=self._watched("gateway"),
                timeout=120.0,
                interval=1.0,
            )
            self._start_worker()
            self._wait_for_process_health(
                self.worker_health,
                label="worker health",
                timeout=120.0,
                watch=self._watched("worker"),
            )
            self.wait_for_ready()
        except Exception:
            try:
                self.stop()
            except Exception:
                self.write_diagnostics()
            raise

    def _start_infra(self) -> None:
        _run_compose(
            self.project_name,
            "up",
            "-d",
            "--build",
            "vidaimock",
            "jaeger",
            ports=self.ports,
        )

    def _local_env(self) -> dict[str, str]:
        # Arm the in-process lanes. This stack has no provider credentials, and
        # a run has to present a selection naming a lane the gateway reports
        # selectable - so without this the catalog offers nothing selectable at
        # all and every run here is unstartable. The mock lane additionally
        # needs a tape server, which VAULTSPEC_A2A_MOCK_API_BASE below supplies,
        # so both in-process lanes are served and the mock presets can select
        # their own.
        env = gateway_process_env(
            gateway_port=self.ports["gateway"],
            worker_port=self.ports["worker"],
            auto_spawn_worker=False,
            serve_in_process_lanes=True,
        )
        if self.postgres_url is None:
            database_url = (
                f"sqlite+aiosqlite:///{(self.runtime_dir / 'service.db').as_posix()}"
            )
            backend = "sqlite"
        else:
            database_url = (
                make_url(self.postgres_url)
                .set(drivername="postgresql+asyncpg", query={})
                .render_as_string(hide_password=False)
            )
            backend = "postgres"
        env.update(
            {
                "VAULTSPEC_A2A_DATABASE_URL": database_url,
                "VAULTSPEC_A2A_DATABASE_BACKEND": backend,
                "VAULTSPEC_A2A_CHECKPOINT_BACKEND": backend,
                "VAULTSPEC_A2A_GATEWAY_URL": self.gateway_url,
                "VAULTSPEC_A2A_WORKER_URL": self.worker_url,
                "VAULTSPEC_A2A_WORKER_HOST": "127.0.0.1",
                "VAULTSPEC_A2A_INTERNAL_TOKEN": _INTERNAL_TOKEN,
                "VAULTSPEC_A2A_GATEWAY_TOKEN": _GATEWAY_SERVICE_TOKEN,
                "VAULTSPEC_A2A_INSTALL_ROOT": str(REPO_ROOT),
                "VAULTSPEC_A2A_MOCK_API_BASE": self.vidaimock_url,
                "OTEL_EXPORTER_OTLP_ENDPOINT": (
                    f"http://127.0.0.1:{self.ports['jaeger_otlp']}"
                ),
                "OTEL_EXPORTER_OTLP_INSECURE": "true",
                # This tier boots a real Jaeger and wants spans in it, so it
                # opts back IN: the root conftest switches trace export off for
                # ordinary suites, and this environment starts from a copy of
                # the pytest process's own.
                "OTEL_TRACES_EXPORTER": "otlp",
                "OTEL_METRICS_EXPORTER": "none",
                "OTEL_SDK_DISABLED": "false",
            }
        )
        # Arm the in-process lanes. This stack has no provider credentials, and a
        # run has to present a selection naming a lane the gateway reports
        # selectable - so without this the catalog offers nothing selectable and
        # every run here is unstartable. The worker is spawned with the same
        # arming, and with it the hold gate its held turns wait on.
        env.update(armed_lane_environment(hold_gate=self.hold_gate))
        if self.postgres_url is not None:
            env["VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL"] = self.postgres_url
            env["VAULTSPEC_A2A_POSTGRES_REQUIRED"] = "true"
        return env

    def spawn_native(
        self,
        factory: str,
        *,
        port: int,
        env: dict[str, str],
        log_name: str,
    ) -> subprocess.Popen[bytes]:
        """Spawn the production ASGI *factory* under uvicorn on *port*.

        Detached, so a stray interrupt aimed at the harness's own foreground
        group never reaches it; its output lands in *log_name* under this run's
        directory, where readiness failures and diagnostics read it back.
        """
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        return spawn_logged(
            [
                sys.executable,
                "-m",
                "uvicorn",
                factory,
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            log_path=self.runtime_dir / log_name,
            cwd=REPO_ROOT,
            detached=True,
        )

    def _start_worker(self) -> None:
        if self._worker_proc is not None:
            return
        self._worker_proc = self.spawn_native(
            "vaultspec_a2a.worker.app:create_worker_app",
            port=self.ports["worker"],
            env=self._local_env(),
            log_name="worker.log",
        )

    def _start_gateway(self) -> None:
        if self._gateway_proc is not None:
            return
        self._gateway_proc = self.spawn_native(
            "vaultspec_a2a.api.app:create_app",
            port=self.ports["gateway"],
            env=self._local_env(),
            log_name=self._gateway_log_name,
        )

    def crash_gateway(self) -> None:
        """Kill this stack's gateway while leaving its worker and stores running."""
        if self._gateway_proc is None:
            raise RuntimeError("gateway is not running")
        reap_process(self._gateway_proc)
        self._gateway_proc = None
        self._gateway_log_name = "gateway-restarted.log"

    def restart_gateway(self) -> None:
        """Start the same gateway profile over this stack's durable stores."""
        if self._gateway_proc is not None:
            raise RuntimeError("gateway is already running")
        self._start_gateway()
        self.wait_for_ready()

    def _wait_for_process_health(
        self,
        probe: Callable[[], dict[str, Any]],
        *,
        label: str,
        timeout: float,
        watch: Sequence[WatchedProcess] = (),
    ) -> None:
        await_ready(
            lambda: probe().get("status") == "ok",
            what=label,
            watch=watch,
            timeout=timeout,
            interval=1.0,
        )

    def stop(self) -> None:
        """Capture diagnostics and tear the compose stack down."""
        if self._stopped:
            self.record("teardown", {"status": "already_stopped"})
            return
        self._stopped = True
        for process in (self._gateway_proc, self._worker_proc):
            if process is not None:
                reap_process(process)
        self._gateway_proc = None
        self._worker_proc = None
        diagnostics_error: Exception | None = None
        try:
            self.write_diagnostics()
        except Exception as exc:
            diagnostics_error = exc
            self.record("teardown-diagnostics-error", {"error": repr(exc)})
        finally:
            try:
                teardown_result = _run_compose(
                    self.project_name,
                    "down",
                    "-v",
                    "--remove-orphans",
                    ports=self.ports,
                    timeout=300.0,
                    check=False,
                )
            except Exception as exc:
                self.record(
                    "teardown",
                    {
                        "status": "compose_down_error",
                        "error": repr(exc),
                    },
                )
            else:
                self.record(
                    "teardown",
                    {
                        "status": (
                            "ok"
                            if teardown_result.returncode == 0
                            else "compose_down_failed"
                        ),
                        "returncode": teardown_result.returncode,
                        "stdout": teardown_result.stdout,
                        "stderr": teardown_result.stderr,
                    },
                )
            self._write_session_summary()
        if diagnostics_error is not None:
            raise diagnostics_error

    def write_diagnostics(self) -> None:
        """Persist a lightweight session summary for debugging failed runs."""
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        try:
            compose_logs = _run_compose(
                self.project_name,
                "logs",
                "--no-color",
                "--timestamps",
                ports=self.ports,
                timeout=180.0,
                check=False,
            )
        except Exception as exc:
            self.record("diagnostics-compose-logs-error", {"error": repr(exc)})
            (self.runtime_dir / "compose-logs.txt").write_text(
                repr(exc),
                encoding="utf-8",
            )
        else:
            (self.runtime_dir / "compose-logs.txt").write_text(
                compose_logs.stdout + "\n" + compose_logs.stderr,
                encoding="utf-8",
            )
        self._write_session_summary()
        for name, proc_path in (
            ("gateway", self.runtime_dir / self._gateway_log_name),
            ("worker", self.runtime_dir / "worker.log"),
        ):
            if proc_path.exists():
                (self.runtime_dir / f"{name}-tail.txt").write_text(
                    log_tail(proc_path, limit=_DIAGNOSTIC_LOG_TAIL_BYTES),
                    encoding="utf-8",
                )

    def _write_session_summary(self) -> None:
        """Persist the current session summary using the latest artifacts."""
        summary = {
            "project_name": self.project_name,
            "ports": self.ports,
            "gateway_url": self.gateway_url,
            "worker_url": self.worker_url,
            "vidaimock_url": self.vidaimock_url,
            "jaeger_url": self.jaeger_url,
            "started_at": self.started_at,
            "artifacts": self.artifacts,
        }
        (self.runtime_dir / "session-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    def wait_for_ready(self) -> dict[str, Any]:
        """Poll the public readiness surface until the stack is certifying."""

        def _probe() -> bool:
            health = self.health()
            self.record("health", health)
            self.worker_health()
            self.jaeger_services()
            self.vidaimock_health()
            checks = health.get("checks", {})
            return (
                health.get("status") == "ok"
                and health.get("worker_connected") is True
                and checks.get("database", {}).get("status") == "ok"
                and checks.get("checkpoint", {}).get("status") == "ok"
                and checks.get("worker", {}).get("status") == "ok"
                and checks.get("circuit_breaker", {}).get("status") == "closed"
            )

        # The aggregate probe spans both owned processes, so either dying is a
        # fast failure rather than a 180s burn ending in a bare timeout.
        await_ready(
            _probe,
            what="service stack",
            watch=self._watched("gateway", "worker"),
            timeout=180.0,
            interval=2.0,
        )
        return self.health()

    def health(self) -> dict[str, Any]:
        with self._client(timeout=15.0) as client:
            resp = client.get("/health")
            resp.raise_for_status()
            payload = resp.json()
            self.record("health", payload)
            return payload

    def worker_health(self) -> dict[str, Any]:
        with self._worker_client() as client:
            resp = client.get("/health")
            resp.raise_for_status()
            payload = resp.json()
            self.record("worker-health", payload)
            return payload

    def jaeger_services(self) -> dict[str, Any]:
        with self._jaeger_client() as client:
            resp = client.get("/api/services")
            resp.raise_for_status()
            payload = resp.json()
            self.record("jaeger-services", payload)
            return payload

    def vidaimock_health(self) -> dict[str, Any]:
        """Exercise the deterministic provider route before certifying ready."""
        with self._vidaimock_client() as client:
            probes = {
                "mock_coder_human": {
                    "path": "/mock-coder-human/v1/chat/completions",
                    "body": {
                        "model": "mock-coder-human",
                        "messages": [{"role": "user", "content": "health probe"}],
                        "stream": False,
                    },
                },
                "vaultspec_supervisor": {
                    "path": "/vaultspec-supervisor/v1/chat/completions",
                    "body": {
                        "model": "vaultspec-supervisor",
                        "messages": [{"role": "user", "content": "health probe"}],
                        "stream": False,
                    },
                },
            }
            payload: dict[str, Any] = {}
            for name, probe in probes.items():
                path = str(probe["path"])
                body = cast("dict[str, Any]", probe["body"])
                resp = client.post(path, json=body)
                resp.raise_for_status()
                payload[name] = resp.json()
            self.record("vidaimock-health", payload)
            return payload

    def jaeger_traces(
        self,
        *,
        service: str,
        start_us: int,
        end_us: int,
        limit: int = 20,
    ) -> dict[str, Any]:
        with self._jaeger_client() as client:
            resp = client.get(
                "/api/traces",
                params={
                    "service": service,
                    "lookback": "custom",
                    "start": start_us,
                    "end": end_us,
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            self.record("jaeger-traces", payload)
            return payload

    def catalog_selection(
        self, workspace_root: str, team_preset: str
    ) -> dict[str, Any]:
        """Return a served selection for *team_preset*, from this stack's gateway.

        A selection cannot be hand-written: run start revalidates it against the
        catalog served FOR THIS WORKSPACE, so it has to name a lane this gateway
        actually reports selectable, at that lane's current revision.

        The lane is chosen to match what the preset is FOR. Every preset this
        stack runs is a deterministic scenario, keyed by its agents on the
        deterministic lane, and picking anything else would change what the test
        exercises. So an external lane is never selected here even when one is
        available: on a developer machine with a real provider session this
        would otherwise quietly send certification traffic to a billable lane,
        which is a worse failure than not running.
        """
        # Refusing a non-in-process lane is the mechanism's own guarantee: it
        # will not hand back a billable lane even if one is the only selectable
        # thing this stack serves. The choice is cached because the first catalog
        # read on a gateway builds it cold across every registered lane.
        try:
            with self._client() as client:
                return fetch_in_process_selection(
                    client,
                    workspace_root,
                    prefer_provider_id=Provider.DETERMINISTIC.value,
                    cache=True,
                )
        except NoSelectableLaneError as exc:
            raise GatewayBootError(
                f"a {team_preset!r} run cannot present a valid selection: {exc}"
            ) from exc

    def create_thread(
        self,
        *,
        initial_message: str,
        team_preset: str,
        title: str | None = None,
        autonomous: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Start a run, supplying the fields run-start now requires.

        Three of them are not optional and none was being sent: a path-safe
        ``run_id``, an explicit served ``selection``, and a metadata envelope
        naming an existing ``workspace_root``. They are defaulted here rather
        than pushed onto eleven call sites, because none of the three is what any
        of those tests is about - they assert cancellation, lifecycle,
        permissions, and streaming - while a caller that DOES care (two of them
        supply their own workspace) still overrides by passing metadata.
        """
        # Path-safe by construction: run ids reach the filesystem, and the
        # schema pattern refuses anything else.
        run_id = f"svc-{uuid.uuid4().hex}"
        workspace_root = str((metadata or {}).get("workspace_root") or self.runtime_dir)
        Path(workspace_root).mkdir(parents=True, exist_ok=True)
        verbs = RunVerbs(
            base_url=self.gateway_url,
            authorization=f"Bearer {_GATEWAY_SERVICE_TOKEN}",
            team_preset=team_preset,
            workspace_root=workspace_root,
            selection=lambda workspace: self.catalog_selection(workspace, team_preset),
        )
        resp = verbs.start(
            run_id,
            message=initial_message,
            metadata=metadata,
            title=title,
            autonomous=autonomous,
        )
        resp.raise_for_status()
        payload = resp.json()
        self.record("last-create-thread", payload)
        return payload

    def list_threads(self, *, status: str | None = None) -> dict[str, Any]:
        """List every run, including terminal ones, via the history reading.

        The list verb's default reading is capped active-run discovery, which
        omits terminal runs; a harness that asserts on a completed run has to
        ask for the history reading explicitly.
        """
        params: dict[str, Any] = {"state": "all"}
        if status is not None:
            params["status"] = status
        with self._client(timeout=15.0) as client:
            resp = client.get("/v1/runs", params=params)
            resp.raise_for_status()
            payload = resp.json()
            self.record("last-thread-list", payload)
            return payload

    def get_thread_state(self, thread_id: str) -> dict[str, Any]:
        """Return the run's state snapshot from the versioned history verb.

        The history response embeds the snapshot under ``state`` alongside the
        run's metadata. This returns the snapshot itself, which is what the
        method has always promised and what every caller asserts against; the
        full envelope is what gets recorded for post-mortem.
        """
        with self._client(timeout=15.0) as client:
            resp = client.get(f"/v1/runs/{thread_id}/history")
            resp.raise_for_status()
            payload = resp.json()
            self.record(f"thread-state:{thread_id}", payload)
            return payload["state"]

    def respond_permission(
        self,
        request_id: str,
        *,
        thread_id: str,
        option_id: str,
        **options: Unpack[_PermissionResponseOptions],
    ) -> dict[str, Any]:
        kind = options.get("kind")
        idempotency_key = options.get("idempotency_key")
        expected_status = options.get("expected_status", 200)
        body: dict[str, Any] = {"option_id": option_id}
        if kind is not None:
            body["kind"] = kind
        headers: dict[str, str] = {}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        with self._client(timeout=30.0) as client:
            resp = client.post(
                f"/v1/runs/{thread_id}/permissions/{request_id}/respond",
                json=body,
                headers=headers or None,
            )
            if resp.status_code != expected_status:
                raise AssertionError(
                    "unexpected permission response status: "
                    f"expected {expected_status}, got {resp.status_code}, "
                    f"body={resp.text!r}"
                )
            payload = resp.json()
            self.record(f"permission-response:{request_id}", payload)
            return payload

    def cancel_thread(self, thread_id: str) -> dict[str, Any]:
        with self._client(timeout=15.0) as client:
            resp = client.post(f"/v1/runs/{thread_id}/cancel")
            resp.raise_for_status()
            payload = resp.json()
            self.record(f"cancel-thread:{thread_id}", payload)
            return payload


def build_service_stack(*, postgres_url: str | None = None) -> ServiceStack:
    ports = {
        "gateway": free_port(),
        "worker": free_port(),
        "vidaimock": free_port(),
        "jaeger_ui": free_port(),
        "jaeger_otlp": free_port(),
    }
    project_name = f"vaultspec-service-tests-{uuid.uuid4().hex[:8]}"
    return ServiceStack(
        project_name=project_name, ports=ports, postgres_url=postgres_url
    )
