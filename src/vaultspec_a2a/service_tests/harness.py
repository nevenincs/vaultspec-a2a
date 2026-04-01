"""Session-scoped service harness for the deterministic certification stack."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "service" / "docker-compose.integration.yml"
RUNTIME_ROOT = REPO_ROOT / ".vault" / "runtime" / "service-tests"


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


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


def _wait_for(
    label: str,
    probe: Callable[[], bool],
    *,
    timeout: float = 120.0,
    interval: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if probe():
                return
        except Exception as exc:  # pragma: no cover - diagnostic path
            last_error = exc
        time.sleep(interval)
    raise TimeoutError(
        f"Timed out waiting for {label}"
        + (f": {last_error}" if last_error is not None else "")
    )


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

    def __post_init__(self) -> None:
        self.runtime_dir = RUNTIME_ROOT / self.project_name
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

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
        return httpx.Client(base_url=self.gateway_url, timeout=timeout)

    def gateway_client(self, *, timeout: float | None = 10.0) -> httpx.Client:
        """Return a gateway-scoped HTTP client for public API calls."""
        return self._client(timeout=timeout)

    def _worker_client(self) -> httpx.Client:
        return httpx.Client(base_url=self.worker_url, timeout=10.0)

    def _jaeger_client(self) -> httpx.Client:
        return httpx.Client(base_url=self.jaeger_url, timeout=10.0)

    def _vidaimock_client(self) -> httpx.Client:
        return httpx.Client(base_url=self.vidaimock_url, timeout=10.0)

    def _gateway_http_ready(self) -> bool:
        with self._client(timeout=5.0) as client:
            resp = client.get("/api/health")
            return resp.status_code == 200

    def start(self) -> None:
        """Bring the deterministic compose stack online and wait for readiness."""
        try:
            self._start_infra()
            self._start_gateway()
            _wait_for(
                "gateway HTTP readiness",
                self._gateway_http_ready,
                timeout=120.0,
                interval=1.0,
            )
            self._start_worker()
            self._wait_for_process_health(
                self.worker_health, label="worker health", timeout=120.0
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
                "VAULTSPEC_INTERNAL_TOKEN": "vaultspec-integration-token",
                "VAULTSPEC_AUTO_SPAWN_WORKER": "false",
                "VAULTSPEC_PROJECT_ROOT": str(REPO_ROOT),
                "VAULTSPEC_UI_BUILD_DIR": str(REPO_ROOT / "src" / "ui" / "dist"),
                "MOCK_API_BASE": self.vidaimock_url,
                "OTEL_EXPORTER_OTLP_ENDPOINT": (
                    f"http://127.0.0.1:{self.ports['jaeger_otlp']}"
                ),
                "OTEL_EXPORTER_OTLP_INSECURE": "true",
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
        if proc is None:
            return
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=30.0)
            except Exception:
                proc.kill()
                proc.wait(timeout=30.0)

    def _wait_for_process_health(
        self,
        probe: Callable[[], dict[str, Any]],
        *,
        label: str,
        timeout: float,
    ) -> None:
        _wait_for(
            label,
            lambda: probe().get("status") == "ok",
            timeout=timeout,
            interval=1.0,
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
                    proc_path.read_text(encoding="utf-8", errors="replace")[-20000:],
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

        _wait_for("gateway readiness", _probe, timeout=180.0, interval=2.0)
        return self.health()

    def health(self) -> dict[str, Any]:
        with self._client(timeout=15.0) as client:
            resp = client.get("/api/health")
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
            resp = client.post(
                "/mock-coder-human/v1/chat/completions",
                json={
                    "model": "mock-coder-human",
                    "messages": [{"role": "user", "content": "health probe"}],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
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

    def create_thread(
        self,
        *,
        initial_message: str,
        team_preset: str,
        title: str | None = None,
        autonomous: bool | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "initial_message": initial_message,
            "team_preset": team_preset,
        }
        if title is not None:
            body["title"] = title
        if autonomous is not None:
            body["autonomous"] = autonomous
        with self._client(timeout=30.0) as client:
            resp = client.post("/api/threads", json=body)
            resp.raise_for_status()
            payload = resp.json()
            self.record("last-create-thread", payload)
            return payload

    def list_threads(self, *, status: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        with self._client(timeout=15.0) as client:
            resp = client.get("/api/threads", params=params)
            resp.raise_for_status()
            payload = resp.json()
            self.record("last-thread-list", payload)
            return payload

    def get_thread_state(self, thread_id: str) -> dict[str, Any]:
        with self._client(timeout=15.0) as client:
            resp = client.get(f"/api/threads/{thread_id}/state")
            resp.raise_for_status()
            payload = resp.json()
            self.record(f"thread-state:{thread_id}", payload)
            return payload

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
                f"/api/threads/{thread_id}/messages",
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
                f"/api/permissions/{request_id}/respond",
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
            resp = client.post(f"/api/threads/{thread_id}/cancel")
            resp.raise_for_status()
            payload = resp.json()
            self.record(f"cancel-thread:{thread_id}", payload)
            return payload


def build_service_stack() -> ServiceStack:
    ports = {
        "gateway": _pick_free_port(),
        "worker": _pick_free_port(),
        "vidaimock": _pick_free_port(),
        "jaeger_ui": _pick_free_port(),
        "jaeger_otlp": _pick_free_port(),
    }
    project_name = f"vaultspec-service-tests-{uuid.uuid4().hex[:8]}"
    return ServiceStack(project_name=project_name, ports=ports)
