"""Real-filesystem and loopback proofs of the engine discovery trust boundary."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING

import pytest

from ...control.config import settings
from ...desktop._platform_acl import harden_credential_path
from ...testing import (
    JsonReplyHandler,
    armed_environment,
    health_listener,
    plant_link_to_file,
    serve_handler,
    settings_override,
)
from .._engine_trust import (
    CHALLENGE_HEADER,
    PID_HEADER,
    PROOF_HEADER,
    STARTED_MS_HEADER,
)
from ..discovery import resolve_engine
from ._engine_peer import (
    TEST_BEARER,
    engine_health_listener,
    health_proof,
    write_engine_record,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@contextmanager
def attacker_listener(
    *, proof: str = "", port: int = 0
) -> Generator[tuple[int, list[dict[str, str]]]]:
    """Capture real incoming headers from a listener without the engine's secret."""
    requests: list[dict[str, str]] = []

    class _Attacker(JsonReplyHandler, BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            requests.append(dict(self.headers.items()))
            self.send_response(200)
            self.send_header(PROOF_HEADER, proof)
            self.send_header(PID_HEADER, "1")
            self.send_header(STARTED_MS_HEADER, "1")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:
            self.do_GET()

    with serve_handler(_Attacker, port=port) as bound:
        yield bound, requests


def test_workspace_legacy_record_cannot_select_an_authoring_endpoint(
    tmp_path: Path,
) -> None:
    """A live attacker health listener must not turn repository JSON into authority."""
    with attacker_listener() as (port, requests):
        record = tmp_path / ".vault" / "data" / "engine-data" / "service.json"
        record.parent.mkdir(parents=True)
        record.write_text(
            json.dumps(
                {
                    "port": port,
                    "service_token": "attacker-bearer",
                    "last_heartbeat": int(time.time() * 1000),
                }
            ),
            encoding="utf-8",
        )
        with settings_override(project_root=tmp_path, engine_service_json=record):
            assert resolve_engine(liveness_timeout=0.5) is None
        assert requests == []


def test_default_discovery_is_outside_the_project(tmp_path: Path) -> None:
    with settings_override(project_root=tmp_path, engine_service_json=None):
        first = settings.engine_discovery_path
        assert not first.is_relative_to(tmp_path)
    with settings_override(project_root=tmp_path / "other", engine_service_json=None):
        assert first != settings.engine_discovery_path


@pytest.mark.parametrize("proof", ["", "0" * 64, "untrusted-proof"])
def test_stale_port_listener_gets_only_a_challenge(
    secure_engine_dir: Path, proof: str
) -> None:
    """A protected record alone cannot authenticate whoever now occupies its port."""
    with attacker_listener(proof=proof) as (port, requests):
        path = secure_engine_dir / "service.json"
        write_engine_record(path, port)
        with settings_override(engine_service_json=path):
            assert resolve_engine(liveness_timeout=0.5) is None
        assert len(requests) == 1
        assert CHALLENGE_HEADER in requests[0]
        assert "Authorization" not in requests[0]
        assert "x-authoring-actor-token" not in requests[0]
        assert TEST_BEARER not in str(requests)


def test_old_valid_proof_cannot_be_replayed(secure_engine_dir: Path) -> None:
    with attacker_listener() as (port, _requests):
        old_proof = health_proof(port, TEST_BEARER, "0" * 64)
    with attacker_listener(proof=old_proof) as (port, requests):
        path = secure_engine_dir / "service.json"
        write_engine_record(path, port)
        with settings_override(engine_service_json=path):
            assert resolve_engine(liveness_timeout=0.5) is None
        assert requests[0][CHALLENGE_HEADER] != "0" * 64


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("version", 2),
        ("version", True),
        ("version", 1.0),
        ("producer", "desktop"),
        ("port", True),
        ("port", 0),
        ("port", 65_536),
        ("pid", 0),
        ("started_ms", None),
        ("last_heartbeat", None),
        ("last_heartbeat", 10**400),
        ("service_token", "short"),
        ("service_token", "non-ascii-" + "\u00e9" * 40),
    ],
)
def test_invalid_identity_never_probes(
    secure_engine_dir: Path, name: str, value: object
) -> None:
    with attacker_listener() as (port, requests):
        path = secure_engine_dir / "service.json"
        write_engine_record(path, port)
        info = json.loads(path.read_text(encoding="utf-8"))
        info[name] = value
        path.write_text(json.dumps(info), encoding="utf-8")
        with settings_override(engine_service_json=path):
            assert resolve_engine(liveness_timeout=0.5) is None
        assert requests == []


def test_a_record_in_another_repository_is_untrusted(secure_engine_dir: Path) -> None:
    (secure_engine_dir / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    with engine_health_listener() as port:
        path = secure_engine_dir / "service.json"
        write_engine_record(path, port)
        with settings_override(engine_service_json=path):
            assert resolve_engine(liveness_timeout=0.5) is None


def test_linked_private_record_is_untrusted(secure_engine_dir: Path) -> None:
    with engine_health_listener() as port:
        target = secure_engine_dir / "real.json"
        write_engine_record(target, port)
        link = secure_engine_dir / "service.json"
        kind = plant_link_to_file(link, target)
        with settings_override(engine_service_json=link):
            assert resolve_engine(liveness_timeout=0.5) is None, kind


def test_unrestricted_record_is_untrusted(secure_engine_dir: Path) -> None:
    with health_listener() as port:
        path = secure_engine_dir / "service.json"
        write_engine_record(path, port)
        contents = path.read_text(encoding="utf-8")
        path.unlink()
        path.write_text(contents, encoding="utf-8")
        if os.name == "posix":
            path.chmod(0o644)
        # Windows inherits its parent's DACL; inherited permissions are refused.
        with settings_override(engine_service_json=path):
            assert resolve_engine(liveness_timeout=0.5) is None


def test_oversized_private_record_is_untrusted(secure_engine_dir: Path) -> None:
    path = secure_engine_dir / "service.json"
    path.write_bytes(b" " * 65_537)
    harden_credential_path(path)
    with settings_override(engine_service_json=path):
        assert resolve_engine(liveness_timeout=0.5) is None


def test_proxy_environment_cannot_intercept_discovery(secure_engine_dir: Path) -> None:
    with (
        engine_health_listener() as port,
        attacker_listener() as (proxy_port, requests),
    ):
        path = secure_engine_dir / "service.json"
        write_engine_record(path, port)
        proxy_url = f"http://127.0.0.1:{proxy_port}"
        with (
            armed_environment(HTTP_PROXY=proxy_url, ALL_PROXY=proxy_url, NO_PROXY=""),
            settings_override(engine_service_json=path),
        ):
            endpoint = resolve_engine(liveness_timeout=0.5)
        assert endpoint is not None
        assert endpoint.base_url == f"http://127.0.0.1:{port}"
        assert requests == []
