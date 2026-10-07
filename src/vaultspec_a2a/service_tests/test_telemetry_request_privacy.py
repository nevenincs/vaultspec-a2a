"""Request URL privacy through the real middleware, OTLP exporter, and Jaeger."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from ..testing import free_port
from .harness import COMPOSE_FILE, REPO_ROOT, resolve_docker_executable

if TYPE_CHECKING:
    from collections.abc import Generator

    from ..conftest import ExternalPrerequisiteRule

_REQUEST_PROBE = """
import asyncio
import json
import sys

from httpx import ASGITransport, AsyncClient
from opentelemetry import trace
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from vaultspec_a2a.telemetry import TelemetryMiddleware, configure_telemetry

async def endpoint(request):
    return JSONResponse({'query': request.scope['query_string'].decode('ascii')})

async def main():
    configure_telemetry(service_name='request-privacy-proof')
    app = Starlette(routes=[Route('/probe', endpoint)])
    app.add_middleware(TelemetryMiddleware)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url='http://telemetry.example:8181'
    ) as client:
        response = await client.get('/probe' + sys.argv[1], headers={
            'Host': sys.argv[2],
            'traceparent': '00-' + sys.argv[3] + '-0123456789abcdef-01',
            'Authorization': 'Bearer private-header-canary',
        })
        response.raise_for_status()
        print(json.dumps(response.json()))
    provider = trace.get_tracer_provider()
    assert provider.force_flush(timeout_millis=10000)
    provider.shutdown()

asyncio.run(main())
"""


@pytest.fixture(scope="module")
def jaeger_request_privacy(
    external_prerequisite: ExternalPrerequisiteRule,
) -> Generator[tuple[str, str]]:
    """Start only the real collector in a uniquely owned Compose project."""
    external_prerequisite("docker")
    docker = resolve_docker_executable()
    project = "vaultspec-request-privacy-" + uuid.uuid4().hex[:10]
    ui_port, otlp_port = free_port(), free_port()
    env = {
        **os.environ,
        "JAEGER_UI_PORT": str(ui_port),
        "JAEGER_OTLP_PORT": str(otlp_port),
    }
    command = [
        docker,
        "compose",
        "--env-file",
        os.devnull,
        "-p",
        project,
        "-f",
        str(COMPOSE_FILE),
    ]
    try:
        subprocess.run(
            [*command, "up", "-d", "--no-deps", "--wait", "jaeger"],
            env=env,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        yield f"http://127.0.0.1:{otlp_port}", f"http://127.0.0.1:{ui_port}"
    finally:
        subprocess.run(
            [*command, "down", "--remove-orphans"],
            env=env,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=90,
        )


@pytest.mark.parametrize(
    ("query", "host", "expected_url", "expected_address"),
    [
        (
            "",
            "telemetry.example:8181",
            "http://telemetry.example:8181/probe",
            "telemetry.example",
        ),
        (
            "?TOKEN=private-url-canary&api%5Fkey=private-url-canary&opaque=private-url-canary&opaque=second&workspace_root=%2Fprivate-project",
            "telemetry.example:8181",
            "http://telemetry.example:8181/probe",
            "telemetry.example",
        ),
        ("?limit=10&cursor=start", "[::1]:8181", "http://[::1]:8181/probe", "::1"),
        (
            "?opaque=private-url-canary",
            "[::1]:08181",
            "http://[::1]:08181/probe",
            "::1",
        ),
    ],
)
def test_request_url_privacy_survives_export(
    jaeger_request_privacy: tuple[str, str],
    query: str,
    host: str,
    expected_url: str,
    expected_address: str,
) -> None:
    """Export omits query content while handlers and W3C ancestry remain intact."""
    endpoint, query_url = jaeger_request_privacy
    trace_id = uuid.uuid4().hex
    env = {
        **os.environ,
        "VAULTSPEC_A2A_OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        "VAULTSPEC_A2A_OTEL_EXPORTER_OTLP_INSECURE": "true",
        "VAULTSPEC_A2A_OTEL_TRACES_EXPORTER": "otlp",
        "VAULTSPEC_A2A_OTEL_METRICS_EXPORTER": "none",
        "VAULTSPEC_A2A_OTEL_SDK_DISABLED": "false",
        "VAULTSPEC_A2A_OTEL_EXPORTER_CONSOLE": "false",
    }
    result = subprocess.run(
        [sys.executable, "-c", _REQUEST_PROBE, query, host, trace_id],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=45,
    )
    assert json.loads(result.stdout)["query"] == query.removeprefix("?")
    deadline = time.monotonic() + 30
    payload: dict[str, Any] = {}
    with httpx.Client(base_url=query_url, timeout=5) as client:
        while time.monotonic() < deadline:
            response = client.get(f"/api/traces/{trace_id}")
            response.raise_for_status()
            payload = cast("dict[str, Any]", response.json())
            if payload.get("data"):
                break
            time.sleep(0.25)
    assert payload.get("data"), "middleware span was not exported to Jaeger"
    spans = payload["data"][0]["spans"]
    assert len(spans) == 1
    span = spans[0]
    tags = {tag["key"]: tag["value"] for tag in span["tags"]}
    assert span["operationName"] == "GET /probe"
    assert span["references"][0]["traceID"] == trace_id
    assert span["references"][0]["spanID"] == "0123456789abcdef"
    assert tags["url.full"] == expected_url
    assert tags["http.route"] == "/probe"
    assert tags["http.request.method"] == "GET"
    assert tags["http.response.status_code"] == 200
    assert tags["server.address"] == expected_address
    assert tags["server.port"] == 8181
    exported = json.dumps(payload)
    assert "private-url-canary" not in exported
    assert "private-header-canary" not in exported
    assert "private-project" not in exported
