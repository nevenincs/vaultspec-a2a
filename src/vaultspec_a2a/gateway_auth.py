"""Resolve the bearer used by local gateway clients.

The operator CLI and MCP bridge share one credential-selection boundary. An
explicitly configured gateway token is authoritative. Local clients may then
use the armed desktop attach credential or the fresh resident-discovery handoff,
but a remote URL never receives a machine-local credential.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from .control.config import settings

__all__ = ["gateway_auth_headers"]

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _read_desktop_attach_credential() -> str | None:
    """Return the armed desktop attach credential when it is valid."""
    if not settings.desktop_profile_armed:
        return None
    references = settings.desktop_credential_paths
    if references is None:
        return None
    from .desktop.credentials import CredentialError, load_attach_credential

    try:
        return load_attach_credential(references.credentials_dir)
    except CredentialError:
        return None


def gateway_auth_headers(url: str) -> dict[str, str]:
    """Return an Authorization header for *url* when a safe bearer resolves."""
    token = settings.gateway_service_token
    parsed = urlsplit(url)
    is_loopback = parsed.hostname in _LOOPBACK_HOSTS

    if token is None and is_loopback:
        token = _read_desktop_attach_credential()
    if token is None and is_loopback:
        from .lifecycle.discovery import DiscoveryState, read_resident_service

        state, info = read_resident_service(settings.a2a_home)
        if (
            state is DiscoveryState.FRESH
            and info is not None
            and info.port == parsed.port
        ):
            token = info.service_token

    if token is None:
        return {}
    return {"Authorization": f"Bearer {token}"}
