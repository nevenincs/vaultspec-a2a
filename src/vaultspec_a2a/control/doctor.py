"""Service health-check dashboard.

Invoked via::

    python -m vaultspec_a2a.control.doctor [target [service]]

Targets
-------
all (default)
    Run all checks: ports, config, services.

ports
    Try ``socket.bind()`` on every configured port and report which are free
    vs. already in use.

config
    Validate the active settings (database_backend, checkpoint_backend, API
    keys, etc.) and print a summary.

services [service]
    HTTP-probe the gateway ``/health`` and worker ``/health`` endpoints, plus
    optional sidecar services (Jaeger, Postgres, UI, VidaiMock) and report
    their status.  Pass an optional service name to probe only that service.
    Supported service names: gateway, worker, jaeger, postgres, ui, vidaimock.

Example output
--------------
::

  gateway ........ healthy (200, :8000)
  worker ......... healthy (200, :8001)
  jaeger ......... not running
  postgres ....... not configured (sqlite mode)
"""

from __future__ import annotations

__all__ = ["main"]

import argparse
import http.client
import socket
from typing import Literal

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

_Status = Literal["ok", "warn", "fail", "info"]


class _Row:
    """Single dashboard line."""

    __slots__ = ("detail", "label", "status")

    def __init__(self, label: str, status: _Status, detail: str = "") -> None:
        self.label = label
        self.status = status
        self.detail = detail

    def render(self, label_width: int = 18) -> str:
        dots = "." * max(1, label_width - len(self.label))
        icon = {
            "ok": "OK  ",
            "warn": "WARN",
            "fail": "FAIL",
            "info": "INFO",
        }[self.status]
        detail = f"  {self.detail}" if self.detail else ""
        return f"  {self.label} {dots} {icon}{detail}"


# ---------------------------------------------------------------------------
# Port checks
# ---------------------------------------------------------------------------

_DEFAULT_PORTS: list[tuple[str, int]] = [
    ("gateway", 8000),
    ("worker", 8001),
    ("mcp", 8100),
    ("vite-dev", 5173),
    ("vite-preview", 4173),
    ("jaeger-ui", 16686),
    ("jaeger-otlp", 4317),
    ("postgres", 5432),
]


def _check_ports() -> list[_Row]:
    rows: list[_Row] = []

    try:
        from ..core.config import settings

        configured: list[tuple[str, int]] = [
            ("gateway", settings.port),
            ("worker", settings.worker_port),
            ("mcp", settings.mcp_port),
        ]
        seen_ports = {p for _, p in configured}
        extra = [
            (label, port) for label, port in _DEFAULT_PORTS if port not in seen_ports
        ]
        all_ports = configured + extra
    except Exception:
        all_ports = _DEFAULT_PORTS

    for label, port in all_ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.close()
            rows.append(_Row(f"port:{port}", "ok", f"{label} — free"))
        except OSError:
            rows.append(_Row(f"port:{port}", "warn", f"{label} — in use"))

    return rows


# ---------------------------------------------------------------------------
# Config checks
# ---------------------------------------------------------------------------

_OPTIONAL_API_KEYS: list[tuple[str, str]] = [
    ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    ("GEMINI_API_KEY", "gemini_api_key"),
    ("OPENAI_API_KEY", "openai_api_key"),
    ("LANGSMITH_API_KEY", "langsmith_api_key"),
]


def _check_config() -> list[_Row]:
    rows: list[_Row] = []

    try:
        from ..core.config import settings
    except Exception as exc:
        rows.append(_Row("config", "fail", f"settings load failed: {exc}"))
        return rows

    # Database backend
    try:
        backend = settings.resolved_database_backend
        rows.append(_Row("db-backend", "ok", backend))
    except Exception as exc:
        rows.append(_Row("db-backend", "fail", str(exc)))

    # Checkpoint backend
    try:
        cp = settings.resolved_checkpoint_backend
        rows.append(_Row("ckpt-backend", "ok", cp))
    except Exception as exc:
        rows.append(_Row("ckpt-backend", "fail", str(exc)))

    # Database URL sanity
    db_url = settings.database_url
    if db_url.startswith("sqlite"):
        try:
            db_path = settings.database_path
            if str(db_path) == ":memory:":
                rows.append(_Row("db-file", "warn", ":memory: (ephemeral)"))
            elif db_path.exists():
                size_kb = db_path.stat().st_size / 1024
                rows.append(_Row("db-file", "ok", f"{db_path.name} ({size_kb:.0f} KB)"))
            else:
                rows.append(_Row("db-file", "warn", f"not found: {db_path}"))
        except Exception as exc:
            rows.append(_Row("db-file", "warn", str(exc)))
    else:
        rows.append(_Row("db-file", "info", "postgres — no local file"))

    # API keys (informational only)
    for env_name, attr in _OPTIONAL_API_KEYS:
        val = getattr(settings, attr, None)
        if val:
            masked = val[:4] + "***"
            rows.append(_Row(env_name[:18], "ok", masked))
        else:
            rows.append(_Row(env_name[:18], "info", "not set"))

    # Postgres requirement flag
    if settings.postgres_required:
        rows.append(_Row("postgres-req", "ok", "VAULTSPEC_POSTGRES_REQUIRED=true"))

    return rows


# ---------------------------------------------------------------------------
# Service health probes
# ---------------------------------------------------------------------------


def _http_probe(
    host: str,
    port: int,
    path: str,
    *,
    timeout: float = 2.0,
) -> tuple[int | None, str]:
    """Return (status_code, detail_string). Status is None on connection error."""
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            return resp.status, resp.read(256).decode("utf-8", errors="replace")
        finally:
            conn.close()
    except (OSError, TimeoutError, http.client.HTTPException):
        return None, ""


_ALL_SERVICES: tuple[str, ...] = (
    "gateway",
    "worker",
    "jaeger",
    "postgres",
    "ui",
    "vidaimock",
)


def _check_services(service_filter: str | None = None) -> list[_Row]:
    rows: list[_Row] = []

    try:
        from ..core.config import settings

        gateway_port = settings.port
        worker_port = settings.worker_port
        db_backend = settings.resolved_database_backend
    except Exception:
        gateway_port = 8000
        worker_port = 8001
        db_backend = "sqlite"

    def _want(name: str) -> bool:
        return service_filter is None or service_filter == name

    # Gateway
    if _want("gateway"):
        code, _ = _http_probe("127.0.0.1", gateway_port, "/api/health")
        if code is None:
            rows.append(_Row("gateway", "fail", f"not running (:{gateway_port})"))
        elif code == 200:
            rows.append(_Row("gateway", "ok", f"healthy (200, :{gateway_port})"))
        else:
            rows.append(_Row("gateway", "warn", f"status {code} (:{gateway_port})"))

    # Worker
    if _want("worker"):
        code, _ = _http_probe("127.0.0.1", worker_port, "/health")
        if code is None:
            rows.append(_Row("worker", "fail", f"not running (:{worker_port})"))
        elif code == 200:
            rows.append(_Row("worker", "ok", f"healthy (200, :{worker_port})"))
        else:
            rows.append(_Row("worker", "warn", f"status {code} (:{worker_port})"))

    # Jaeger (optional sidecar)
    if _want("jaeger"):
        code, _ = _http_probe("127.0.0.1", 14269, "/")
        if code is None:
            rows.append(_Row("jaeger", "info", "not running"))
        elif code in (200, 204):
            rows.append(_Row("jaeger", "ok", "healthy (:14269)"))
        else:
            rows.append(_Row("jaeger", "warn", f"status {code} (:14269)"))

    # Postgres (only meaningful when configured)
    if _want("postgres"):
        if db_backend == "postgres":
            try:
                import importlib.util

                if importlib.util.find_spec("psycopg") is not None:
                    import psycopg

                    from ..core.config import settings as s

                    conn_str = s.checkpoint_connection_string
                    with psycopg.connect(conn_str, connect_timeout=2):
                        rows.append(_Row("postgres", "ok", "connected"))
                else:
                    rows.append(_Row("postgres", "warn", "psycopg not installed"))
            except Exception as exc:
                rows.append(_Row("postgres", "fail", str(exc)[:60]))
        else:
            rows.append(_Row("postgres", "info", "not configured (sqlite mode)"))

    # UI dev server (Vite, optional)
    if _want("ui"):
        code, _ = _http_probe("127.0.0.1", 5173, "/")
        if code is None:
            rows.append(_Row("ui", "info", "not running (:5173)"))
        elif code == 200:
            rows.append(_Row("ui", "ok", "healthy (200, :5173)"))
        else:
            rows.append(_Row("ui", "warn", f"status {code} (:5173)"))

    # VidaiMock LLM provider (optional sidecar)
    if _want("vidaimock"):
        code, _ = _http_probe("127.0.0.1", 8100, "/v1/models")
        if code is None:
            rows.append(_Row("vidaimock", "info", "not running (:8100)"))
        elif code == 200:
            rows.append(_Row("vidaimock", "ok", "healthy (200, :8100)"))
        else:
            rows.append(_Row("vidaimock", "warn", f"status {code} (:8100)"))

    return rows


# ---------------------------------------------------------------------------
# Dashboard renderer
# ---------------------------------------------------------------------------


def _render_dashboard(rows: list[_Row]) -> None:
    label_width = max((len(r.label) for r in rows), default=10) + 2
    for row in rows:
        print(row.render(label_width))


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vaultspec_a2a.control.doctor",
        description="Service health-check dashboard.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="all",
        choices=["all", "ports", "config", "services"],
        help="Check to run (default: all).",
    )
    parser.add_argument(
        "service",
        nargs="?",
        default=None,
        choices=list(_ALL_SERVICES),
        metavar="service",
        help=(
            "When target=services, probe only this service. "
            f"Choices: {', '.join(_ALL_SERVICES)}."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    target: str = args.target
    service: str | None = args.service

    rows: list[_Row] = []

    if target in ("all", "ports"):
        if target == "all":
            print("ports")
        rows.extend(_check_ports())

    if target in ("all", "config"):
        if target == "all":
            print("\nconfig")
        rows_config = _check_config()
        rows.extend(rows_config)

    if target in ("all", "services"):
        if target == "all":
            print("\nservices")
        rows_services = _check_services(service_filter=service)
        rows.extend(rows_services)

    if target == "all":
        # Re-render with a combined label_width for the full dashboard.
        print()
        _render_dashboard(rows)
    else:
        _render_dashboard(rows)

    # Return non-zero if any hard failures were found.
    has_fail = any(r.status == "fail" for r in rows)
    return 1 if has_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
