"""Canonical platform-aware resolution for provider-owned system CLIs."""

from __future__ import annotations

import shutil
import sys

from ..graph.enums import Provider

__all__ = ["resolve_provider_cli_executable"]

_SYSTEM_CLI_NAMES: dict[Provider, str] = {
    Provider.CLAUDE: "claude",
    Provider.CODEX: "codex",
    Provider.KIMI: "kimi",
}


def resolve_provider_cli_executable(provider: Provider) -> str | None:
    """Resolve a provider's system CLI exactly as production will launch it.

    Windows command shims are explicit fallbacks rather than an assumption about
    the caller's ``PATHEXT``. Unix hosts accept only the unsuffixed executable,
    so an unrelated ``.cmd`` file cannot make a lane appear runnable there.
    """

    try:
        name = _SYSTEM_CLI_NAMES[provider]
    except KeyError as exc:
        raise ValueError(f"provider {provider.value} has no system CLI") from exc
    candidates = (
        (name, f"{name}.cmd", f"{name}.exe") if sys.platform == "win32" else (name,)
    )
    for candidate in candidates:
        if executable := shutil.which(candidate):
            return executable
    return None
