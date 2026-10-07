"""Prepare native child authority, command, environment and cwd together."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..control.config import settings
from ..control.provider_execution import native_execution_refusal_reason
from ..desktop.native_isolation import NativeLaunchAuthority, linux_isolated_launch
from ..utils import ProcessContainmentError

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class ProviderLaunch:
    command: tuple[str, ...]
    environment: Mapping[str, str] | None = field(repr=False)
    cwd: str | None


def provider_execution_command(
    command: list[str], *, supervise: bool = False
) -> list[str]:
    """Admit a native command, then apply the POSIX identity boundary."""
    reason = native_execution_refusal_reason()
    if reason is not None:
        raise ProcessContainmentError(reason)
    launcher = settings.provider_identity_launcher
    uid = settings.provider_agent_uid
    gid = settings.provider_agent_gid
    configured = (launcher is not None, uid is not None, gid is not None)
    if not any(configured):
        return command
    if sys.platform == "win32":
        raise ProcessContainmentError(
            "provider identity launcher is configured on unsupported Windows"
        )
    if not all(configured):
        raise ProcessContainmentError(
            "provider identity boundary requires launcher, agent UID, and agent GID"
        )
    assert launcher is not None and uid is not None and gid is not None
    launcher_path = Path(launcher)
    if not launcher_path.is_absolute() or not launcher_path.is_file():
        raise ProcessContainmentError(
            f"provider identity launcher is unavailable: {launcher_path}"
        )
    supervision = ["--supervise"] if supervise else []
    return [str(launcher_path), *supervision, str(uid), str(gid), "--", *command]


def provider_execution_launch(
    command: list[str],
    *,
    environment: Mapping[str, str] | None,
    cwd: str | None,
    native_authority: NativeLaunchAuthority | None = None,
    supervise: bool = False,
) -> ProviderLaunch:
    """Prepare a launch before acquisition or cached proof, retaining refusal."""
    execution = provider_execution_command(command, supervise=supervise)
    if native_authority is None:
        return ProviderLaunch(
            command=tuple(execution),
            environment=(
                MappingProxyType(dict(environment)) if environment is not None else None
            ),
            cwd=cwd,
        )
    if settings.provider_identity_launcher is not None:
        raise ProcessContainmentError(
            "native namespace and identity launchers cannot be combined without proof"
        )
    isolated = linux_isolated_launch(
        native_authority,
        command,
        cwd=cwd if cwd is not None else str(native_authority.workspace.path),
        environment=environment if environment is not None else os.environ,
    )
    return ProviderLaunch(isolated.command, isolated.environment, isolated.cwd)
