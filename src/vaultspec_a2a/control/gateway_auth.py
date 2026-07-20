"""Client-side resolution of the gateway attach bearer.

A single authority shared by every local gateway client - the operator command
line and the standalone Model Context Protocol adapter - so the rule for which
credential authenticates a gateway request lives in one place.

Resolution order for a request to ``url``:

1. An explicitly configured gateway service token is authoritative and is used
   regardless of the target host.
2. Otherwise, only for a loopback gateway, the owner-scoped desktop attach
   credential when the desktop profile is armed.
3. Otherwise, only for a loopback gateway, the fresh resident discovery token
   whose recorded port matches the request port.

A remote (non-loopback) URL never receives a machine-local credential. When no
credential resolves the caller sends no ``Authorization`` header, preserving the
unauthenticated behaviour a development gateway still permits.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from .config import settings

__all__ = ["read_desktop_attach_credential", "resolve_gateway_bearer"]

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def read_desktop_attach_credential() -> str | None:
    """Return the armed desktop profile's owner-scoped attach credential.

    Reads the dashboard-created attach-control credential from its
    owner-restricted file, the same secret the gateway reads. Returns ``None``
    when the profile is unarmed or the file is absent or malformed, so a caller
    falls through to its other credential sources.
    """
    if not settings.desktop_profile_armed:
        return None
    references = settings.desktop_credential_paths
    if references is None:
        return None
    from ..desktop.credentials import CredentialError, load_attach_credential

    try:
        return load_attach_credential(references.credentials_dir)
    except CredentialError:
        return None


def resolve_gateway_bearer(url: str) -> str | None:
    """Return the bearer token for a gateway request to *url*, or ``None``.

    Applies the configured-token, armed-desktop-attach, and resident-discovery
    tiers in order; the latter two only for a loopback target. No secret is ever
    accepted from a command-line argument, and a remote URL is never handed a
    machine-local credential.
    """
    configured = settings.gateway_service_token
    if configured is not None:
        return configured

    parsed = urlsplit(url)
    if parsed.hostname not in _LOOPBACK_HOSTS:
        return None

    attach = read_desktop_attach_credential()
    if attach is not None:
        return attach

    from ..lifecycle.discovery import DiscoveryState, read_resident_service

    state, info = read_resident_service(settings.a2a_home)
    if state is DiscoveryState.FRESH and info is not None and info.port == parsed.port:
        return info.service_token
    return None
