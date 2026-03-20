"""Shared CLI helpers."""

from __future__ import annotations

__all__ = [
    "_api_client",
    "_handle_response",
    "_mask",
    "_preflight_check",
    "_show_config_callback",
]

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

import click
import httpx

logger = logging.getLogger(__name__)

_SENSITIVE_SUBSTRINGS = ("key", "token", "secret", "password")
_MASK_MIN_LEN = 4


def _mask(name: str, value: object) -> str:
    text = str(value)
    if (
        any(s in name.lower() for s in _SENSITIVE_SUBSTRINGS)
        and len(text) > _MASK_MIN_LEN
    ):
        return f"****{text[-4:]}"
    return text


def _show_config_callback(
    ctx: click.Context,
    _param: click.Parameter,
    value: bool,
) -> None:
    if not value or ctx.resilient_parsing:
        return
    from ..core.config import settings

    for name in settings.model_fields:
        click.echo(f"{name}={_mask(name, getattr(settings, name))}")
    ctx.exit()


def _handle_response(resp: httpx.Response) -> httpx.Response:
    """Raise SystemExit with a clean error message on HTTP errors."""
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        click.echo(f"Error {resp.status_code}: {detail}", err=True)
        raise SystemExit(1) from None
    return resp


def _preflight_check(client: httpx.Client) -> None:
    """Probe ``/health`` and warn if the worker is disconnected.

    Non-fatal check -- prints a warning to stderr so the user knows
    supervised workflows (permissions) won't work, but doesn't block
    read-only commands like ``team status``.
    """
    try:
        resp = client.get("/health", timeout=5.0)
        if resp.status_code != 200:
            return
        data = resp.json()
        checks = data.get("checks", {})
        worker = checks.get("worker", {})
        cb = checks.get("circuit_breaker", {})

        if worker.get("status") == "error":
            click.echo(
                "WARNING: Worker is not connected -- agent dispatch"
                " and supervised workflows will fail.\n"
                "  Ensure the worker is running: just dev service start worker",
                err=True,
            )
        if cb.get("status") == "open":
            click.echo(
                "WARNING: Circuit breaker is OPEN -- the worker has"
                " repeated failures. Dispatches are paused.\n"
                "  Check worker health: just dev service health worker\n"
                "  Restart the worker:  just dev service restart worker",
                err=True,
            )
    except Exception:
        # Pre-flight is best-effort; never block the CLI.
        pass


@contextmanager
def _api_client() -> Generator[httpx.Client]:
    """Yield a sync httpx client pointed at the gateway API.

    Catches network-level errors (connect failures, timeouts, protocol
    errors) and prints a clean, actionable message instead of a raw
    traceback. Runs a non-fatal pre-flight health check to warn about
    worker connectivity.
    """
    from ..core.config import settings

    port = settings.port
    base_url = f"http://127.0.0.1:{port}/api"
    try:
        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            _preflight_check(client)
            yield client

    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        logger.debug("Gateway connection failed: %s", exc, exc_info=True)
        click.echo(
            f"Error: Could not connect to the Team Gateway service on port {port}.\n"
            f"\n"
            f"The gateway is either not running or not reachable at {base_url}.\n"
            f"\n"
            f"To fix this:\n"
            f"  1. Start the gateway:   just dev service start gateway\n"
            f"  2. Start all services:  just dev service start\n"
            f"  3. Check health:        just dev service health\n"
            f"\n"
            f"If the gateway is already running on a different port, set:\n"
            f"  VAULTSPEC_PORT=<port>",
            err=True,
        )
        raise SystemExit(1) from None

    except httpx.RemoteProtocolError as exc:
        logger.debug("Gateway protocol error on port %s: %s", port, exc, exc_info=True)
        click.echo(
            f"Error: Port {port} is in use but did not respond as a Team Gateway.\n"
            f"\n"
            f"Something is listening on port {port} but it is not the vaultspec\n"
            f"gateway service. This is usually caused by a stale process from a\n"
            f"previous session or another application using the same port.\n"
            f"\n"
            f"To fix this:\n"
            f"  1. Check what is on port {port}:  just dev service health gateway\n"
            f"  2. Stop stale services:           just dev service kill gateway\n"
            f"  3. Restart the gateway:           just dev service restart gateway\n"
            f"\n"
            f"If another application owns port {port}, use a different port:\n"
            f"  VAULTSPEC_PORT=9000 just dev service start gateway",
            err=True,
        )
        raise SystemExit(1) from None

    except httpx.ReadTimeout as exc:
        logger.debug("Gateway read timeout: %s", exc, exc_info=True)
        click.echo(
            f"Error: The Team Gateway on port {port} did not respond in time.\n"
            f"\n"
            f"The gateway is running but took too long to respond. This can\n"
            f"happen when the service is overloaded or starting up.\n"
            f"\n"
            f"To fix this:\n"
            f"  1. Check gateway health:  just dev service health gateway\n"
            f"  2. Wait and retry -- the gateway may still be starting up\n"
            f"  3. Restart if stuck:      just dev service restart gateway",
            err=True,
        )
        raise SystemExit(1) from None
