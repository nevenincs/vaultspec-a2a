"""Shared CLI helpers."""

from __future__ import annotations

__all__ = [
    "_api_client",
    "_handle_response",
    "_mask",
    "_preflight_check",
    "_show_config_callback",
]

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

import click
import httpx

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

    Phase 7: Non-fatal check — prints a warning to stderr so the user
    knows supervised workflows (permissions) won't work, but doesn't
    block read-only commands like ``team status``.
    """
    try:
        resp = client.get("/health", timeout=5.0)
        if resp.status_code != 200:
            return  # gateway returned something unexpected; don't add noise
        data = resp.json()
        checks = data.get("checks", {})
        worker = checks.get("worker", {})
        cb = checks.get("circuit_breaker", {})

        if worker.get("status") == "error":
            click.echo(
                "⚠ Worker is not connected — agent dispatch"
                " and supervised workflows will fail.",
                err=True,
            )
        if cb.get("status") == "open":
            click.echo(
                "⚠ Circuit breaker OPEN — the worker has"
                " repeated failures. Dispatches are paused.",
                err=True,
            )
    except Exception:
        # Pre-flight is best-effort; never block the CLI.
        pass


@contextmanager
def _api_client() -> Generator[httpx.Client]:
    """Yield a sync httpx client pointed at the gateway API.

    Catches network-level errors (connect failures, timeouts) and prints
    a clean message instead of a raw traceback.  Runs a non-fatal pre-flight
    health check to warn about worker connectivity (Phase 7).
    """
    from ..core.config import settings

    base_url = f"http://127.0.0.1:{settings.port}/api"
    try:
        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            _preflight_check(client)
            yield client
    except (httpx.ConnectError, httpx.ConnectTimeout):
        click.echo(
            "Gateway not running. Start with: vaultspec service start gateway",
            err=True,
        )
        raise SystemExit(1) from None
    except httpx.ReadTimeout:
        click.echo("Request timed out. The backend may be overloaded.", err=True)
        raise SystemExit(1) from None
