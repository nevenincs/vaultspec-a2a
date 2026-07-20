"""Resolve the bearer used by local gateway clients.

The operator CLI and MCP bridge share one credential-selection boundary. An
explicitly configured gateway token is authoritative. Local clients may then
use the armed desktop attach credential or the fresh resident-discovery handoff,
but a remote URL never receives a machine-local credential.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import SplitResult, urlsplit

from .control.config import settings

__all__ = ["gateway_auth_headers"]

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _validated_desktop_attach_credential(parsed: SplitResult) -> str | None:
    """Return the credential only for the validated desktop discovery origin."""
    references = settings.desktop_credential_paths
    if references is None:
        return None
    from .lifecycle.discovery import (
        DESKTOP_PROTOCOL_MAX,
        DesktopDiscoveryState,
        classify_desktop_discovery,
        desktop_record_process_is_live,
        service_json_path,
    )

    state, record = classify_desktop_discovery(service_json_path(settings.a2a_home))
    if state is not DesktopDiscoveryState.FRESH or record is None:
        return None
    if not record.supports_protocol(DESKTOP_PROTOCOL_MAX):
        return None
    if not desktop_record_process_is_live(record):
        return None
    try:
        requested_port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "http"
        or parsed.hostname != record.host
        or requested_port != record.port
    ):
        return None
    if record.credential_reference is None:
        return None
    try:
        referenced_credential = Path(record.credential_reference).resolve()
        expected_credential = references.attach_path.resolve()
    except (OSError, RuntimeError):
        return None
    if referenced_credential != expected_credential:
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

    if token is None and is_loopback and settings.desktop_profile_armed:
        token = _validated_desktop_attach_credential(parsed)
    if token is None and is_loopback and not settings.desktop_profile_armed:
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
