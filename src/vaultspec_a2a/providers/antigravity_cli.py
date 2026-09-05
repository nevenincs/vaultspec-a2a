"""Locate the Antigravity CLI and its login, in one place.

Antigravity is a separate lane from Gemini, not a rename of it: it ships its own
``agy`` binary with its own login, and one ``agy models`` listing spans vendors -
gemini, claude and gpt-oss entries appear side by side. What a turn ran on is
therefore not recoverable from "gemini", which is why the lane is its own
:class:`~vaultspec_a2a.graph.enums.Provider` member.

The awkward part is resolution. The installer does NOT put ``agy`` on PATH; it
writes the binary into a per-user application directory and exposes it through a
wrapper script elsewhere. A plain ``shutil.which("agy")`` therefore reports the
CLI missing on a machine where it works perfectly, which is exactly the class of
false negative that made the credential probes lie earlier in this tree. So the
order is: the operator's explicit override, then PATH for a host that did put it
there, then the installer's own default location.

Resolution lives HERE rather than in each caller so the catalog adapter and the
test-suite prerequisite answer the same question the same way; two copies would
drift and disagree about whether the lane exists.
"""

from __future__ import annotations

import shutil
from pathlib import Path

__all__ = [
    "antigravity_credential_path",
    "resolve_antigravity_command",
]

#: The installer's default location, relative to the user's home. Windows puts
#: it under the local application data root; the POSIX builds use the same leaf.
_DEFAULT_RELATIVE = ("AppData", "Local", "agy", "bin", "agy.exe")
_POSIX_RELATIVE = (".local", "share", "agy", "bin", "agy")

#: The CLI keeps its login beside its own state rather than under the binary.
_CREDENTIAL_RELATIVE = (".gemini", "antigravity-cli", "antigravity-oauth-token")


def resolve_antigravity_command(
    *, cli_path: str | None = None, home: str | None = None
) -> Path | None:
    """Return the ``agy`` executable, or ``None`` when it is genuinely absent.

    ``None`` means "not installed here" and nothing more; callers report that as
    an unavailable lane rather than as a failure, because a host without the CLI
    has made no mistake.
    """
    override = (cli_path or "").strip()
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None

    found = shutil.which("agy") or shutil.which("agy.exe")
    if found is not None:
        return Path(found)

    root = Path((home or "").strip()) if (home or "").strip() else Path.home()
    for relative in (_DEFAULT_RELATIVE, _POSIX_RELATIVE):
        candidate = root.joinpath(*relative)
        if candidate.is_file():
            return candidate
    return None


def antigravity_credential_path(*, home: str | None = None) -> Path:
    """Where the CLI persists its OAuth login.

    A path, not a verdict: presence is the weakest honest claim available
    without asking the CLI, and the caller decides what to do with it.
    """
    root = Path((home or "").strip()) if (home or "").strip() else Path.home()
    return root.joinpath(*_CREDENTIAL_RELATIVE)
