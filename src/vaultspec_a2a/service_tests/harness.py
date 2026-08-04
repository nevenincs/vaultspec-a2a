"""Session-scoped service harness for the deterministic certification stack."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx

from ..artifacts import ArtifactDeclaration, RetentionDisposition
from ..control.config import settings
from ..lifecycle.manager import tree_kill
from ..testing.ports import free_port
from ..tests.gateway_boot import GatewayBootError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# A process this harness owns, its label, and the log it writes: enough to fail
# a readiness wait with the exit code and the tail that explain the death.
_WatchedProcess = tuple[str, "subprocess.Popen[str]", Path]

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "service" / "docker-compose.integration.yml"

# The lanes that execute inside the gateway process. This stack holds no
# provider credential, so these are the only lanes its runs may select - named
# here rather than imported so a serving-policy change upstream cannot silently
# widen what a certification run is allowed to bill.
_IN_PROCESS_PROVIDER_IDS = frozenset({"deterministic", "mock"})


def _preset_in_process_provider(team_preset: str) -> str | None:
    """Return the in-process lane a bundled preset is pinned to, if any.

    Read from the preset rather than inferred from its name: the internal
    certification presets are the one category still permitted to pin a provider,
    and that pin is precisely the statement of which lane they need.
    """
    from ..team.team_config import load_team_config
    from ..thread.errors import ConfigError, TeamConfigNotFoundError

    try:
        config = load_team_config(team_preset)
    except (ConfigError, TeamConfigNotFoundError, ValueError):
        return None
    declared = [worker.model.provider for worker in config.workers]
    declared.append(config.defaults.provider)
    for provider in declared:
        if provider is not None and provider.value in _IN_PROCESS_PROVIDER_IDS:
            return provider.value
    return None


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
            "VAULTSPEC_PORT": str(ports["gateway"]),
            "VAULTSPEC_WORKER_PORT": str(ports["worker"]),
            "VIDAIMOCK_PORT": str(ports["vidaimock"]),
            "JAEGER_UI_PORT": str(ports["jaeger_ui"]),
            "JAEGER_OTLP_PORT": str(ports["jaeger_otlp"]),
        }
    )
    return env


def _compose_base_command(project_name: str) -> list[str]:
    docker = _resolve_docker_executable()
    return [
        docker,
        "compose",
        "-p",
        project_name,
        "-f",
        str(COMPOSE_FILE),
    ]


def _resolve_docker_executable() -> str:
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


def _spawn_process(
    *args: str,
    env: dict[str, str],
    log_path: Path,
) -> tuple[subprocess.Popen[str], Any]:
    log_file = log_path.open("w", encoding="utf-8", buffering=1)
    proc = subprocess.Popen(
        args,
        cwd=REPO_ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    return proc, log_file


_ERROR_LOG_TAIL_CHARS = 4000
_DIAGNOSTIC_LOG_TAIL_CHARS = 20000


def _log_tail(log_path: Path, *, limit: int = _ERROR_LOG_TAIL_CHARS) -> str:
    """Return the last *limit* characters of *log_path*, or ``""``."""
    try:
        return log_path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def _log_tail_suffix(watch: Sequence[_WatchedProcess]) -> str:
    """Render the watched processes' log tails for a failure message."""
    parts = [
        f"\n--- {name} log tail ---\n{tail}"
        for name, _proc, log_path in watch
        if (tail := _log_tail(log_path))
    ]
    return "".join(parts)


def _wait_for(
    label: str,
    probe: Callable[[], bool],
    *,
    timeout: float = 120.0,
    interval: float = 1.0,
    watch: Sequence[_WatchedProcess] = (),
) -> None:
    """Poll *probe* until it passes, failing fast on a dead watched process.

    Supplying *watch* makes the wait DEATH-AWARE: a child that exits before the
    probe passes fails immediately with its exit code and log tail rather than
    burning the whole deadline — the bind-race signature, and the reason the
    shared gateway-boot poll checks liveness every iteration. Waits with no
    owning process (the compose-managed services, whose lifecycle Docker owns)
    pass no *watch* and keep the plain deadline behaviour, because there is no
    exit status to consult.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        for name, proc, log_path in watch:
            if proc.poll() is not None:
                raise GatewayBootError(
                    f"{label}: {name} exited before readiness "
                    f"(exit {proc.returncode})"
                    f"{_log_tail_suffix([(name, proc, log_path)])}"
                )
        try:
            if probe():
                return
        except Exception as exc:  # pragma: no cover - diagnostic path
            last_error = exc
        time.sleep(interval)
    raise TimeoutError(
        f"Timed out waiting for {label}"
        + (f": {last_error}" if last_error is not None else "")
        + _log_tail_suffix(watch)
    )


RETAINED_RUNTIME_DIRS = 5
"""How many service-test runtime directories to keep before evicting the oldest.

Deleting a run's directory outright would destroy the compose logs and session
summary the harness writes precisely so a failed run can be diagnosed after the
fact. Bounding the count keeps recent post-mortems available while stopping the
unbounded accumulation in the operator's machine-global home.
"""

# The bound here is on the COUNT of directories, not on any one directory's size,
# and it is applied by the harness itself at the moment it first writes. That
# ordering is the enforcement: a stack constructed but never started leaves
# nothing behind, because the sweep and the mkdir share one call site.
RUNTIME_DIR_DECLARATION = ArtifactDeclaration(
    name="service-test-runtime-dir",
    root="<a2a_home>/runtime/service-tests/<compose_project_name>/",
    owner="service_tests.harness",
    disposition=RetentionDisposition.BOUNDED_BY_SIZE,
    mechanism=(
        f"sweep_stale_runtime_dirs keeps the {RETAINED_RUNTIME_DIRS} most recently "
        "modified directories and removes the rest, run from _ensure_runtime_dir "
        "at the point something first writes; no bound applies to any single "
        "directory's contents, so one run's compose logs can be arbitrarily large"
    ),
)

ARTIFACT_DECLARATIONS: tuple[ArtifactDeclaration, ...] = (RUNTIME_DIR_DECLARATION,)


def sweep_stale_runtime_dirs(
    *, keep: Path | None = None, root: Path | None = None
) -> list[Path]:
    """Evict all but the most recent service-test runtime directories.

    Args:
        keep: A directory to retain regardless of age - the caller's own run.
        root: Directory to sweep; defaults to the machine-global runtime root.
            Taking it as a parameter keeps the sweep testable against a real
            temporary tree without reassigning module state.

    Returns:
        The directories removed.
    """
    search_root = root if root is not None else RUNTIME_ROOT
    try:
        candidates = [entry for entry in search_root.iterdir() if entry.is_dir()]
    except OSError:
        return []
    # Name breaks ties so several directories sharing one filesystem timestamp
    # tick evict deterministically rather than in arbitrary order.
    ordered = sorted(
        candidates, key=lambda entry: (entry.stat().st_mtime, entry.name), reverse=True
    )
    removed: list[Path] = []
    for stale in ordered[RETAINED_RUNTIME_DIRS:]:
        if keep is not None and stale == keep:
            continue
        shutil.rmtree(stale, ignore_errors=True)
        if not stale.exists():
            removed.append(stale)
    return removed


@dataclass(slots=True)
class ServiceStack:
    """Owns the docker-compose integration stack for a single test session."""

    project_name: str
    ports: dict[str, int]
    started_at: float = field(default_factory=time.time)
    runtime_dir: Path = field(init=False)
    artifacts: dict[str, Any] = field(default_factory=dict)
    _gateway_proc: subprocess.Popen[str] | None = field(
        default=None, init=False, repr=False
    )
    _worker_proc: subprocess.Popen[str] | None = field(
        default=None, init=False, repr=False
    )
    _gateway_log: Any | None = field(default=None, init=False, repr=False)
    _worker_log: Any | None = field(default=None, init=False, repr=False)
    _stopped: bool = field(default=False, init=False, repr=False)
    # One served selection per (workspace, preset). The first catalog read on a
    # gateway builds it cold across every registered lane, so it is paid once per
    # session rather than once per run.
    _selection_cache: dict[str, dict[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )

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
        sweep_stale_runtime_dirs(keep=self.runtime_dir)

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

    def _watched(self, *names: str) -> list[_WatchedProcess]:
        """Return the named harness-owned processes that are currently spawned.

        Only processes this harness holds a ``Popen`` for are watchable; the
        compose-managed services are deliberately absent, since Docker owns
        their lifecycle and there is no local exit status to read.
        """
        owned: dict[str, subprocess.Popen[str] | None] = {
            "gateway": self._gateway_proc,
            "worker": self._worker_proc,
        }
        return [
            (name, proc, self.runtime_dir / f"{name}.log")
            for name in names
            if (proc := owned[name]) is not None
        ]

    def start(self) -> None:
        """Bring the deterministic compose stack online and wait for readiness."""
        self._ensure_runtime_dir()
        try:
            self._start_infra()
            self._start_gateway()
            _wait_for(
                "gateway HTTP readiness",
                self._gateway_http_ready,
                timeout=120.0,
                interval=1.0,
                watch=self._watched("gateway"),
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
        env = os.environ.copy()
        env.update(
            {
                "VAULTSPEC_ENVIRONMENT": "production",
                "VAULTSPEC_DATABASE_URL": (
                    "sqlite+aiosqlite:///"
                    f"{(self.runtime_dir / 'service.db').as_posix()}"
                ),
                "VAULTSPEC_DATABASE_BACKEND": "sqlite",
                "VAULTSPEC_CHECKPOINT_BACKEND": "sqlite",
                "VAULTSPEC_GATEWAY_URL": self.gateway_url,
                "VAULTSPEC_WORKER_URL": self.worker_url,
                "VAULTSPEC_WORKER_HOST": "127.0.0.1",
                "VAULTSPEC_WORKER_PORT": str(self.ports["worker"]),
                "VAULTSPEC_PORT": str(self.ports["gateway"]),
                "VAULTSPEC_INTERNAL_TOKEN": _INTERNAL_TOKEN,
                "VAULTSPEC_A2A_GATEWAY_TOKEN": _GATEWAY_SERVICE_TOKEN,
                "VAULTSPEC_AUTO_SPAWN_WORKER": "false",
                "VAULTSPEC_PROJECT_ROOT": str(REPO_ROOT),
                "MOCK_API_BASE": self.vidaimock_url,
                # Arm the in-process lanes. This stack has no provider
                # credentials, and a run now has to present a selection naming a
                # lane the gateway reports selectable - so without this the
                # catalog offers nothing selectable at all and every run here is
                # unstartable. The mock lane additionally needs a tape server,
                # which MOCK_API_BASE above supplies, so both in-process lanes
                # are served and the mock presets can select their own.
                "VAULTSPEC_SERVE_IN_PROCESS_LANES": "true",
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
        return env

    def _start_worker(self) -> None:
        if self._worker_proc is not None:
            return
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        proc, log_file = _spawn_process(
            sys.executable,
            "-m",
            "uvicorn",
            "vaultspec_a2a.worker.app:create_worker_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.ports["worker"]),
            env=self._local_env(),
            log_path=self.runtime_dir / "worker.log",
        )
        self._worker_proc = proc
        self._worker_log = log_file

    def _start_gateway(self) -> None:
        if self._gateway_proc is not None:
            return
        proc, log_file = _spawn_process(
            sys.executable,
            "-m",
            "uvicorn",
            "vaultspec_a2a.api.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.ports["gateway"]),
            env=self._local_env(),
            log_path=self.runtime_dir / "gateway.log",
        )
        self._gateway_proc = proc
        self._gateway_log = log_file

    def _stop_process(self, proc: subprocess.Popen[str] | None) -> None:
        if proc is None or proc.poll() is not None:
            return
        # Reuse the lifecycle tree-kill: a bare terminate/kill orphans grandchildren
        # on Windows (no taskkill /T), stranding e.g. an engine the process spawned.
        tree_kill(proc.pid, timeout=30.0)
        with contextlib.suppress(Exception):
            proc.wait(timeout=30.0)

    def _wait_for_process_health(
        self,
        probe: Callable[[], dict[str, Any]],
        *,
        label: str,
        timeout: float,
        watch: Sequence[_WatchedProcess] = (),
    ) -> None:
        _wait_for(
            label,
            lambda: probe().get("status") == "ok",
            timeout=timeout,
            interval=1.0,
            watch=watch,
        )

    def stop(self) -> None:
        """Capture diagnostics and tear the compose stack down."""
        if self._stopped:
            self.record("teardown", {"status": "already_stopped"})
            return
        self._stopped = True
        self._stop_process(self._gateway_proc)
        self._stop_process(self._worker_proc)
        if self._gateway_log is not None:
            self._gateway_log.close()
            self._gateway_log = None
        if self._worker_log is not None:
            self._worker_log.close()
        self._worker_log = None
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
            ("gateway", self.runtime_dir / "gateway.log"),
            ("worker", self.runtime_dir / "worker.log"),
        ):
            if proc_path.exists():
                (self.runtime_dir / f"{name}-tail.txt").write_text(
                    _log_tail(proc_path, limit=_DIAGNOSTIC_LOG_TAIL_CHARS),
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
        _wait_for(
            "gateway readiness",
            _probe,
            timeout=180.0,
            interval=2.0,
            watch=self._watched("gateway", "worker"),
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

        The lane is chosen to match what the preset is FOR. These presets run the
        in-process lanes - the mock lane replays a tape, the deterministic lane
        answers from fixed role-keyed content - and picking anything else would
        change what the test exercises. So an external lane is never selected
        here even when one is available: on a developer machine with a real
        provider session this would otherwise quietly send certification traffic
        to a billable lane, which is a worse failure than not running.
        """
        cache_key = f"{workspace_root}|{team_preset}"
        cached = self._selection_cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        # A first read builds the catalog cold, probing every registered lane.
        with self._client(timeout=240.0) as client:
            resp = client.get(
                "/v1/provider-catalog", params={"workspace_root": workspace_root}
            )
            resp.raise_for_status()
            providers = cast("list[dict[str, Any]]", resp.json()["providers"])

        served = [
            record
            for record in providers
            if record["health"]["selectable"] and record["catalog"]["models"]
        ]
        in_process = [
            record
            for record in served
            if record["provider_id"] in _IN_PROCESS_PROVIDER_IDS
        ]
        if not in_process:
            raise GatewayBootError(
                "this stack's gateway serves no selectable in-process lane, so a "
                f"{team_preset!r} run cannot present a valid selection. The "
                "gateway environment must set VAULTSPEC_SERVE_IN_PROCESS_LANES "
                "(and MOCK_API_BASE for the mock lane). Selectable lanes served: "
                f"{[record['provider_id'] for record in served]}"
            )
        # Prefer the lane the preset itself is pinned to, so a mock preset keeps
        # replaying its tape rather than being answered by the deterministic lane.
        preferred = _preset_in_process_provider(team_preset)
        record = next(
            (item for item in in_process if item["provider_id"] == preferred),
            in_process[0],
        )
        catalog = record["catalog"]
        selection = {
            "schema_version": 1,
            "provider_id": record["provider_id"],
            "execution_mode": record["execution_mode"],
            "catalog_revision": catalog["state"]["revision"],
            "entry_id": catalog["models"][0]["entry_id"],
            "controls": {},
        }
        self._selection_cache[cache_key] = selection
        # Copied per call so a caller mutating its body cannot reach the cache
        # and silently change what every later run in the session selects.
        return dict(selection)

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
        meta: dict[str, Any] = dict(metadata) if metadata else {}
        workspace_root = str(meta.get("workspace_root") or self.runtime_dir)
        Path(workspace_root).mkdir(parents=True, exist_ok=True)
        meta["workspace_root"] = workspace_root

        body: dict[str, Any] = {
            "message": initial_message,
            "team_preset": team_preset,
            "run_id": run_id,
            "selection": self.catalog_selection(workspace_root, team_preset),
            "metadata": meta,
        }
        if title is not None:
            body["title"] = title
        if autonomous is not None:
            body["autonomous"] = autonomous
        with self._client(timeout=30.0) as client:
            resp = client.post("/v1/runs", json=body)
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

    def send_message(
        self,
        thread_id: str,
        *,
        content: str,
        agent_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"content": content}
        if agent_id is not None:
            body["agent_id"] = agent_id
        headers: dict[str, str] = {}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        with self._client(timeout=30.0) as client:
            resp = client.post(
                f"/v1/runs/{thread_id}/messages",
                json=body,
                headers=headers or None,
            )
            resp.raise_for_status()
            payload = resp.json()
            self.record(f"send-message:{thread_id}", payload)
            return payload

    def respond_permission(
        self,
        request_id: str,
        *,
        thread_id: str,
        option_id: str,
        kind: str | None = None,
        idempotency_key: str | None = None,
        expected_status: int = 200,
    ) -> dict[str, Any]:
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


def build_service_stack() -> ServiceStack:
    ports = {
        "gateway": free_port(),
        "worker": free_port(),
        "vidaimock": free_port(),
        "jaeger_ui": free_port(),
        "jaeger_otlp": free_port(),
    }
    project_name = f"vaultspec-service-tests-{uuid.uuid4().hex[:8]}"
    return ServiceStack(project_name=project_name, ports=ports)
