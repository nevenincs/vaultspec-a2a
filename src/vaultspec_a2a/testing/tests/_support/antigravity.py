"""Antigravity credential path used by test prerequisite probes."""

from __future__ import annotations

from pathlib import Path

__all__ = ["antigravity_credential_path"]

_CREDENTIAL_RELATIVE = (".gemini", "antigravity-cli", "antigravity-oauth-token")


def antigravity_credential_path(*, home: str | None = None) -> Path:
    """Return the path where Antigravity persists its OAuth login."""
    root = Path((home or "").strip()) if (home or "").strip() else Path.home()
    return root.joinpath(*_CREDENTIAL_RELATIVE)
