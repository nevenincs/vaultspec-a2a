"""Development containers expose local trace and deterministic provider fixtures."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from .harness import COMPOSE_FILE, REPO_ROOT, resolve_docker_executable


@pytest.mark.parametrize("ui_port", ["", "26686"])
@pytest.mark.parametrize("otlp_port", ["", "24317"])
def test_resolved_integration_jaeger_boundary(ui_port: str, otlp_port: str) -> None:
    """Host certification retains loopback ingestion and querying at custom ports."""
    result = subprocess.run(
        [
            resolve_docker_executable(),
            "compose",
            "--env-file",
            os.devnull,
            "-f",
            str(COMPOSE_FILE),
            "config",
            "--format",
            "json",
        ],
        env={**os.environ, "JAEGER_UI_PORT": ui_port, "JAEGER_OTLP_PORT": otlp_port},
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    services = json.loads(result.stdout)["services"]
    ports = services["jaeger"]["ports"]
    assert len(ports) == 2
    published = {port["target"]: port["published"] for port in ports}
    assert published == {4317: otlp_port or "4317", 16686: ui_port or "16686"}
    assert all(port["host_ip"] == "127.0.0.1" for port in ports)
    assert all(port["protocol"] == "tcp" for port in ports)
    assert "http://localhost:13133/status" in services["jaeger"]["healthcheck"]["test"]
    assert set(services) == {"jaeger", "vidaimock"}
    assert services["vidaimock"]["ports"][0]["host_ip"] == "127.0.0.1"


@pytest.mark.parametrize(
    "variable", ["JAEGER_UI_PORT", "JAEGER_OTLP_PORT", "VIDAIMOCK_PORT"]
)
@pytest.mark.parametrize("value", ["0.0.0.0:26686", "[::]:26686"])
def test_fixture_rejects_host_address_override(variable: str, value: str) -> None:
    """A port override cannot restore wildcard publication through short syntax."""
    result = subprocess.run(
        [
            resolve_docker_executable(),
            "compose",
            "--env-file",
            os.devnull,
            "-f",
            str(COMPOSE_FILE),
            "config",
            "--format",
            "json",
        ],
        env={
            **os.environ,
            "JAEGER_UI_PORT": "",
            "JAEGER_OTLP_PORT": "",
            variable: value,
        },
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0, result.stdout
    assert "invalid" in result.stderr.lower(), result.stderr
