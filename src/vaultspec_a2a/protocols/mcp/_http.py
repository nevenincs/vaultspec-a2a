"""Shared HTTP helpers for the MCP tool surface.

Centralises the httpx client lifecycle, gateway preset cache, and the
``_mcp_request`` coroutine so that individual tool modules contain zero
direct ``httpx`` imports.

All gateway communication errors are mapped to ``ToolError`` with
credential-stripped URLs.  ``_get_known_presets`` is deliberately kept
outside ``_mcp_request`` — it has catch-all error semantics that differ
from the strict exception mapping used by tool handlers.
"""

import contextlib
import logging
from urllib.parse import urlparse

import httpx
from httpx import HTTPStatusError as HTTPStatusError
from mcp.server.fastmcp.exceptions import ToolError

from ...control.config import settings
from ...control.gateway_auth import resolve_gateway_bearer

__all__: list[str] = []

logger = logging.getLogger(__name__)


def _auth_headers() -> dict[str, str]:
    """Return the ``Authorization`` header for a gateway request, or empty.

    The standalone adapter authenticates to a gated gateway with the same
    attach credential the operator command line uses, resolved by the shared
    gateway-auth authority. When no credential resolves the adapter sends no
    header, preserving the unauthenticated path a development gateway permits.
    """
    token = resolve_gateway_bearer(settings.gateway_url)
    if token is None:
        return {}
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Shared httpx client lifecycle
# ---------------------------------------------------------------------------

# Shared httpx.AsyncClient — lazily created on first use and reused
# across all tool calls to avoid per-request connection setup overhead.
# The client has no base_url so it works with the runtime env var value.
#
# When the underlying event loop changes (e.g. between test functions), the
# client's transport raises "Event loop is closed".  ``_get_client()`` detects
# this via ``is_closed`` and transparently creates a fresh instance.
_shared_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return the module-level shared httpx.AsyncClient, creating it if needed.

    The client is reused across all MCP tool invocations within the same event
    loop.  If the previous client was closed (e.g. event loop recycled between
    test runs), a new one is created automatically.
    """
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient()
    return _shared_client


def _reset_client() -> None:
    """Close and discard the shared client.  Used by test fixtures."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        # Use close() instead of __del__() for proper cleanup.
        with contextlib.suppress(Exception):
            transport = _shared_client._transport
            _close = getattr(transport, "close", None)
            if _close is not None:
                _close()
    _shared_client = None


# ---------------------------------------------------------------------------
# HTTP status constants
# ---------------------------------------------------------------------------

_HTTP_OK = 200
_HTTP_NOT_FOUND = 404
_HTTP_CONFLICT = 409


# ---------------------------------------------------------------------------
# Credential stripping
# ---------------------------------------------------------------------------


def _strip_credentials(url: str) -> str:
    """Return *url* with any userinfo (user:password@) stripped from the netloc.

    Used in error messages to prevent credential leakage in MCP tool output.
    Reuses the same approach as ``_ws_url_from_api_base``.
    """
    parsed = urlparse(url)
    netloc_no_creds = parsed.hostname or ""
    if parsed.port:
        netloc_no_creds = f"{netloc_no_creds}:{parsed.port}"
    return f"{parsed.scheme}://{netloc_no_creds}{parsed.path}"


# ---------------------------------------------------------------------------
# Preset cache
# ---------------------------------------------------------------------------

# Known presets — lazily fetched from the gateway via HTTP on first
# use.  This replaces the former import of discover_team_preset_ids() so the
# MCP server has zero coupling to the core team_config module.  The cache is
# populated once per process lifetime; restart the MCP server to pick up new
# presets.
_known_presets_cache: frozenset[str] | None = None


async def _get_known_presets() -> frozenset[str]:
    """Fetch known team preset IDs from the gateway, with caching.

    On first call, issues GET /api/teams to the gateway and caches
    the result.  Subsequent calls return the cached value immediately.
    If the gateway is unreachable, returns an empty frozenset (allowing
    the gateway itself to reject unknown presets at create time).
    """
    global _known_presets_cache
    if _known_presets_cache is not None:
        return _known_presets_cache

    api_base = settings.gateway_url
    try:
        client = _get_client()
        resp = await client.get(
            f"{api_base}/api/teams",
            headers=_auth_headers(),
            timeout=settings.mcp_query_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        presets = data.get("presets", [])
        _known_presets_cache = frozenset(
            p.get("id", "") for p in presets if p.get("id")
        )
    except Exception:
        logger.warning(
            "Could not fetch team presets from %s/api/teams", api_base, exc_info=True
        )
        _known_presets_cache = frozenset()
    return _known_presets_cache


def _reset_known_presets() -> None:
    """Clear the preset cache.  Used by test fixtures."""
    global _known_presets_cache
    _known_presets_cache = None


# ---------------------------------------------------------------------------
# Shared HTTP request helper
# ---------------------------------------------------------------------------


async def _mcp_request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    timeout: float,
    not_found_msg: str | None = None,
) -> dict:
    """Issue an HTTP request to the gateway and return the parsed JSON response.

    Maps the four httpx exception branches to ``ToolError`` with
    credential-stripped gateway URLs.  On ``HTTPStatusError``: if the
    status is 404 and *not_found_msg* is provided, raises
    ``ToolError(not_found_msg)``.  Otherwise re-raises the
    ``HTTPStatusError`` for handler-specific processing (e.g. 409).

    Returns the parsed JSON dict on success.
    """
    url = f"{settings.gateway_url}{path}"
    safe_url = _strip_credentials(settings.gateway_url)
    try:
        client = _get_client()
        resp = await client.request(
            method,
            url,
            json=json,
            params=params,
            headers=_auth_headers(),
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError as exc:
        raise ToolError(
            f"Network error: could not connect to {safe_url}. "
            f"Is the server running? Detail: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise ToolError(
            f"Timeout: the server at {safe_url} did not respond. Detail: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == _HTTP_NOT_FOUND and not_found_msg is not None:
            raise ToolError(not_found_msg) from exc
        raise
    except httpx.RequestError as exc:
        raise ToolError(
            f"Connection error (is the server running at {safe_url}?): {exc}"
        ) from exc
