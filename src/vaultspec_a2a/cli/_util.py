"""Shared CLI helpers."""

from __future__ import annotations


__all__ = ["_api_client", "_handle_response", "_mask", "_show_config_callback"]

from collections.abc import Generator
from contextlib import contextmanager

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
    from ..core.config import settings  # noqa: PLC0415

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


@contextmanager
def _api_client() -> Generator[httpx.Client]:
    """Yield a sync httpx client pointed at the backend API.

    Catches network-level errors (connect failures, timeouts) and prints
    a clean message instead of a raw traceback.
    """
    from ..core.config import settings  # noqa: PLC0415

    base_url = f"http://127.0.0.1:{settings.port}/api"
    try:
        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            yield client
    except (httpx.ConnectError, httpx.ConnectTimeout):
        click.echo("Backend not running. Start with: vaultspec service start", err=True)
        raise SystemExit(1) from None
    except httpx.ReadTimeout:
        click.echo("Request timed out. The backend may be overloaded.", err=True)
        raise SystemExit(1) from None
