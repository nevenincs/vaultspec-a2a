"""Focused tests for prod-like verifier evidence helpers."""

from __future__ import annotations

import json
import socketserver
import subprocess
import threading
import uuid

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib import parse

from .. import _verify


_TEST_TEMP_ROOT = Path.home() / ".codex" / "memories" / "vaultspec-verify-tests"
_TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)


class _ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def test_wait_for_health_records_probe_history_until_ok() -> None:
    """Health wait should preserve probe history across non-ready responses."""

    class HealthHandler(BaseHTTPRequestHandler):
        responses = [
            {"status": "starting"},
            {
                "status": "ok",
                "database_backend": "postgres",
                "checkpoint_backend": "postgres",
            },
        ]

        def do_GET(self) -> None:
            payload = self.responses.pop(0)
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, message_format: str, *args: object) -> None:
            return

    server = _ThreadedHTTPServer(("127.0.0.1", 0), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/health"
        health, probe_history = _verify._wait_for_health(
            url=url,
            max_attempts=3,
            sleep_seconds=0.0,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

    assert health["status"] == "ok"
    assert len(probe_history) == 2
    assert probe_history[0]["ok"] is False
    assert probe_history[0]["response"] == {"status": "starting"}
    assert probe_history[1]["ok"] is True
    assert probe_history[1]["response"]["database_backend"] == "postgres"


def test_write_provider_probe_artifacts_persists_stdout_and_stderr() -> None:
    """Provider probe artifacts should preserve bounded subprocess output."""
    result = subprocess.CompletedProcess(
        args=["docker", "compose"],
        returncode=7,
        stdout="probe stdout",
        stderr="probe stderr",
    )
    artifact_dir = _TEST_TEMP_ROOT / f"provider-{uuid.uuid4().hex}"
    artifact_dir.mkdir(parents=True, exist_ok=False)
    payload = _verify._write_provider_probe_artifacts(
        artifact_dir,
        provider="claude",
        result=result,
        error="probe failed",
    )

    assert payload["returncode"] == 7
    assert payload["error"] == "probe failed"
    assert (artifact_dir / "claude.probe.stdout.txt").read_text(
        encoding="utf-8"
    ) == "probe stdout"
    assert (artifact_dir / "claude.probe.stderr.txt").read_text(
        encoding="utf-8"
    ) == "probe stderr"
    manifest = json.loads(
        (artifact_dir / "claude.probe.json").read_text(encoding="utf-8")
    )
    assert manifest["stdout_artifact"] == "claude.probe.stdout.txt"
    assert manifest["stderr_artifact"] == "claude.probe.stderr.txt"


def test_provider_probe_exec_cmd_runs_worker_probe_from_isolated_workdir() -> None:
    """Docker provider probes should not inherit the repo workspace settings."""
    command = _verify._provider_probe_exec_cmd("gemini")

    assert command == [
        "docker",
        "compose",
        "-f",
        "docker-compose.prod.yml",
        "-f",
        "docker-compose.prod.postgres.yml",
        "-f",
        "docker-compose.prod.providers.yml",
        "exec",
        "-T",
        "-w",
        "/tmp",
        "worker",
        "/app/.venv/bin/python",
        "-m",
        "vaultspec_a2a.providers.probes.gemini",
    ]


def test_resolve_gemini_host_cli_home_uses_explicit_cli_home() -> None:
    """Verifier should honor GEMINI_CLI_HOME when locating host OAuth state."""
    cli_home = _TEST_TEMP_ROOT / f"gemini-home-{uuid.uuid4().hex}"
    creds_path = cli_home / ".gemini" / "oauth_creds.json"
    creds_path.parent.mkdir(parents=True)
    creds_path.write_text("{}", encoding="utf-8")

    resolved = _verify._resolve_gemini_host_cli_home(
        {"GEMINI_CLI_HOME": str(cli_home)}
    )

    assert resolved == cli_home


def test_resolve_gemini_host_cli_home_returns_none_without_creds() -> None:
    """Verifier should reject Gemini OAuth mode when the host creds file is absent."""
    missing = _TEST_TEMP_ROOT / f"missing-{uuid.uuid4().hex}"
    resolved = _verify._resolve_gemini_host_cli_home(
        {"GEMINI_CLI_HOME": str(missing)}
    )

    assert resolved is None


def test_extract_gemini_auth_settings_strips_user_mcp_config() -> None:
    """Verifier should preserve auth selection without inheriting noisy MCP config."""
    cli_home = _TEST_TEMP_ROOT / f"gemini-settings-{uuid.uuid4().hex}"
    gemini_dir = cli_home / ".gemini"
    gemini_dir.mkdir(parents=True)
    (gemini_dir / "settings.json").write_text(
        json.dumps(
            {
                "security": {"auth": {"selectedType": "oauth-personal"}},
                "mcpServers": {"context7": {"command": "npx"}},
                "experimental": {"enableAgents": True},
            }
        ),
        encoding="utf-8",
    )

    settings_payload = _verify._extract_gemini_auth_settings(cli_home)

    assert settings_payload == {
        "security": {"auth": {"selectedType": "oauth-personal"}}
    }


def test_prepare_isolated_gemini_host_cli_home_copies_only_auth_material() -> None:
    """Verifier should mount a minimal Gemini CLI home without extensions."""
    source_home = _TEST_TEMP_ROOT / f"gemini-isolated-{uuid.uuid4().hex}"
    source_gemini_dir = source_home / ".gemini"
    source_gemini_dir.mkdir(parents=True)
    (source_gemini_dir / "oauth_creds.json").write_text("{}", encoding="utf-8")
    (source_gemini_dir / "google_accounts.json").write_text("{}", encoding="utf-8")
    (source_gemini_dir / "settings.json").write_text(
        json.dumps(
            {
                "security": {"auth": {"selectedType": "oauth-personal"}},
                "mcpServers": {"nanobanana": {"command": "node"}},
            }
        ),
        encoding="utf-8",
    )
    (source_gemini_dir / "extensions").mkdir()

    _verify._ISOLATED_GEMINI_HOME_CACHE.clear()
    isolated_home = _verify._prepare_isolated_gemini_host_cli_home(source_home)

    isolated_gemini_dir = isolated_home / ".gemini"
    assert json.loads(
        (isolated_gemini_dir / "settings.json").read_text(encoding="utf-8")
    ) == {"security": {"auth": {"selectedType": "oauth-personal"}}}
    assert (isolated_gemini_dir / "oauth_creds.json").exists()
    assert (isolated_gemini_dir / "google_accounts.json").exists()
    assert not (isolated_gemini_dir / "extensions").exists()


def test_cleanup_isolated_gemini_homes_removes_temp_dirs() -> None:
    """Verifier cleanup should remove temp-backed Gemini auth homes."""
    isolated_home = _TEST_TEMP_ROOT / f"gemini-cleanup-{uuid.uuid4().hex}"
    isolated_home.mkdir(parents=True)
    (isolated_home / "marker.txt").write_text("cleanup", encoding="utf-8")
    _verify._ISOLATED_GEMINI_HOME_PATHS.add(isolated_home)

    _verify._cleanup_isolated_gemini_homes()

    assert not isolated_home.exists()


def test_wait_for_traces_uses_lookback_query_for_exercised_services() -> None:
    """Jaeger polling should use lookback semantics for the exercised services."""

    requests: list[dict[str, list[str]]] = []

    class JaegerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(parse.parse_qs(parse.urlsplit(self.path).query))
            body = json.dumps(
                {
                    "data": [{"traceID": "trace-a"}],
                    "errors": None,
                    "limit": 20,
                    "offset": 0,
                    "total": 1,
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, message_format: str, *args: object) -> None:
            return

    server = _ThreadedHTTPServer(("127.0.0.1", 0), JaegerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        query_url = f"http://127.0.0.1:{server.server_port}/api/traces"
        results = _verify._wait_for_traces(
            services=("vaultspec-a2a",),
            query_url=query_url,
            lookback="1m",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

    assert results["vaultspec-a2a"]["data"][0]["traceID"] == "trace-a"
    assert requests == [
        {
            "service": ["vaultspec-a2a"],
            "lookback": ["1m"],
            "limit": ["20"],
        }
    ]


def test_capture_jaeger_diagnostics_scopes_manifest_to_queried_services() -> None:
    """Trace manifests should only require and record the queried services."""
    trace_results = {
        "vaultspec-a2a": {
            "data": [{"traceID": "trace-a"}],
            "errors": None,
            "limit": 20,
            "offset": 0,
            "total": 1,
        }
    }
    artifact_dir = _TEST_TEMP_ROOT / f"jaeger-{uuid.uuid4().hex}"
    artifact_dir.mkdir(parents=True, exist_ok=False)

    manifest = _verify._capture_jaeger_diagnostics(
        artifact_dir,
        start_ms=1,
        services=("vaultspec-a2a",),
        trace_results=trace_results,
        lookback="1m",
    )

    assert manifest["services"] == ["vaultspec-a2a"]
    assert manifest["lookback"] == "1m"
    assert manifest["vaultspec-a2a"]["trace_ids"] == ["trace-a"]
    assert "vaultspec-worker" not in manifest
    written = json.loads(
        (artifact_dir / "trace-manifest.json").read_text(encoding="utf-8")
    )
    assert written["services"] == ["vaultspec-a2a"]
    assert written["vaultspec-a2a"]["trace_count"] == 1


def test_write_evidence_manifest_records_correlation_artifacts() -> None:
    """Evidence manifests should link bounded artifacts, traces, and services."""
    probe_history = [
        {
            "timestamp": "2026-03-11T12:00:00Z",
            "url": "http://localhost:8000/api/health",
            "ok": False,
            "response": {"status": "starting"},
        },
        {
            "timestamp": "2026-03-11T12:00:02Z",
            "url": "http://localhost:8000/api/health",
            "ok": True,
            "response": {"status": "ok", "database_backend": "postgres"},
        },
    ]
    trace_manifest = {
        "start_ms": 1,
        "end_ms": 2,
        "vaultspec-a2a": {
            "trace_count": 1,
            "trace_ids": ["trace-a"],
            "artifact": "jaeger-vaultspec-a2a.json",
        },
        "vaultspec-worker": {
            "trace_count": 1,
            "trace_ids": ["trace-b"],
            "artifact": "jaeger-vaultspec-worker.json",
        },
    }
    provider_probe = {
        "provider": "gemini",
        "returncode": 0,
        "stdout_artifact": "gemini.probe.stdout.txt",
        "stderr_artifact": "gemini.probe.stderr.txt",
    }
    artifact_dir = _TEST_TEMP_ROOT / f"manifest-{uuid.uuid4().hex}"
    artifact_dir.mkdir(parents=True, exist_ok=False)
    _verify._write_evidence_manifest(
        artifact_dir,
        compose_files=("docker-compose.prod.yml",),
        services=("gateway", "worker"),
        probe_history=probe_history,
        trace_manifest=trace_manifest,
        trace_services=("vaultspec-a2a", "vaultspec-worker"),
        run_context={
            "health": {
                "status": "ok",
                "database_backend": "postgres",
                "checkpoint_backend": "postgres",
            },
            "thread_id": "thread-123",
            "failure": "gateway not ready",
            "provider": "gemini",
            "provider_probe": provider_probe,
        },
    )

    manifest = json.loads(
        (artifact_dir / "evidence-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["thread_id"] == "thread-123"
    assert manifest["failure"] == "gateway not ready"
    assert manifest["readiness_probe_count"] == 2
    assert manifest["artifacts"]["compose_config"] == "compose.config.yaml"
    assert manifest["services"]["gateway"]["inspect"] == "gateway.inspect.json"
    assert manifest["trace_services"]["vaultspec-a2a"]["trace_ids"] == [
        "trace-a"
    ]
    assert (
        manifest["provider_probe"]["stdout_artifact"]
        == "gemini.probe.stdout.txt"
    )
