"""Shared HTTP helpers for the MCP tool surface.

Centralises the httpx client lifecycle and the ``_mcp_request`` coroutine so
that individual tool modules contain zero direct ``httpx`` imports.

All gateway communication errors are mapped to ``ToolError`` with
credential-stripped URLs.
"""

import contextlib
import logging
from urllib.parse import urlparse

import httpx
from httpx import HTTPStatusError as HTTPStatusError
from mcp.server.mcpserver.exceptions import ToolError

from ...control.config import settings
from ...gateway_auth import gateway_auth_headers

__all__: list[str] = []

logger = logging.getLogger(__name__)


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
_HTTP_SERVICE_UNAVAILABLE = 503


def _response_detail(response: httpx.Response) -> str:
    """Return the human-readable ``detail`` an error response carries, if any.

    The gateway answers a policy refusal with a string ``detail`` and a request
    validation failure with a list of per-field errors. Both are safe to surface
    to the tool caller: neither carries credentials, and the refusal reason is
    the only thing that tells an operator agent what to change. Anything else
    (or an unparseable body) yields the empty string, so callers can fall back
    to their own wording without a second failure mode.
    """
    try:
        payload = response.json()
    except Exception:
        return ""
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = [
            f"{'.'.join(str(p) for p in item.get('loc', []))}: {item.get('msg', '')}"
            for item in detail
            if isinstance(item, dict)
        ]
        return "; ".join(part for part in parts if part.strip(": "))
    return ""


# ---------------------------------------------------------------------------
# Credential stripping
# ---------------------------------------------------------------------------


def _strip_credentials(url: str) -> str:
    """Return *url* with any userinfo (user:password@) stripped from the netloc.

    Used in error messages to prevent credential leakage in MCP tool output.
    """
    parsed = urlparse(url)
    netloc_no_creds = parsed.hostname or ""
    if parsed.port:
        netloc_no_creds = f"{netloc_no_creds}:{parsed.port}"
    return f"{parsed.scheme}://{netloc_no_creds}{parsed.path}"


# The versioned presets-list verb, read by ``discovery.list_team_presets``.
_PRESETS_PATH = "/v1/presets"


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

    Returns the parsed JSON dict on success, or an empty dict when the
    successful response carried no body.  A body-less success is a success:
    callers that must tell one apart from a success carrying a body test for
    that body's own fields rather than for the absence of a parse error.
    """
    url = f"{settings.gateway_url}{path}"
    safe_url = _strip_credentials(settings.gateway_url)
    try:
        client = _get_client()
        resp = await client.request(
            method,
            url,
            headers=gateway_auth_headers(url),
            json=json,
            params=params,
            timeout=timeout,
        )
        resp.raise_for_status()
        if not resp.content:
            # A no-content success carries its whole meaning in the status
            # line.  Parsing it as JSON raises a decode error that none of the
            # branches below map, so it would escape this helper uncaught and
            # crash the calling tool on an outcome the gateway considers a
            # success.
            return {}
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
