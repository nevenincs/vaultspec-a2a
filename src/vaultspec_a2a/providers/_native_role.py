"""Worker-owned native workspace binding and bounded role-home preparation."""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..control.config import settings
from ..desktop._filesystem_authority import (
    assert_directory_authority,
    resolve_directory_authority,
)
from ..desktop._platform_acl import harden_credential_path
from ..desktop.native_isolation import NativeLaunchAuthority, NativeWorkspaceAuthority
from ..desktop.profile import derive_state_paths
from ..utils import ProcessContainmentError
from ..utils.async_cleanup import complete_cleanup
from ._acp_types import require_workspace_root
from ._factory_commands import (
    ANTHROPIC_AUTH_TOKEN_ENV,
    CLAUDE_CONFIG_DIR_ENV,
    CLAUDE_OAUTH_TOKEN,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator, Mapping

    from langchain_core.language_models import BaseChatModel

    from ..desktop._filesystem_authority import DirectoryAuthority

__all__ = [
    "bind_model_native_workspace",
    "capture_native_workspace",
    "prepare_acp_role",
    "prepare_native_version_probe",
    "require_native_workspace",
    "role_environment",
]


@runtime_checkable
class _NativeBindable(Protocol):
    def with_native_workspace(
        self, authority: NativeWorkspaceAuthority
    ) -> BaseChatModel: ...


def capture_native_workspace(
    workspace: str | Path | None,
) -> NativeWorkspaceAuthority | None:
    """Capture only configured profile roots and the admitted worker project."""
    if not settings.desktop_profile_armed:
        return None
    app_home = settings.desktop_app_home
    capsule = settings.capsule_assets_root
    if app_home is None or capsule is None:
        raise ProcessContainmentError("native execution requires a desktop capsule")
    selected = require_workspace_root(
        str(workspace) if workspace is not None else None,
        surface="native worker workspace binding",
    )
    return NativeWorkspaceAuthority.issue(
        app_home=app_home, capsule=capsule, workspace=selected
    )


def bind_model_native_workspace(
    model: BaseChatModel, *, workspace: str | Path | None
) -> BaseChatModel:
    """Bind after composition so a compiled model never owns a run's grants."""
    if not isinstance(model, _NativeBindable):
        return model
    authority = capture_native_workspace(workspace)
    return model.with_native_workspace(authority) if authority is not None else model


def require_native_workspace(
    authority: NativeWorkspaceAuthority | None, workspace: Path
) -> None:
    """Refuse a missing desktop binding or a model pointed at another project."""
    if authority is None:
        if settings.desktop_profile_armed:
            raise ProcessContainmentError("native execution lacks its worker binding")
        return
    authority.validate()
    if workspace.resolve(strict=True) != authority.workspace.path:
        raise ProcessContainmentError("native model workspace differs from its binding")


def role_environment(authority: NativeLaunchAuthority) -> dict[str, str]:
    """Provider configuration resolves only within this prepared home."""
    environment = authority.home_environment()
    home = environment["HOME"]
    return {**environment, "USERPROFILE": home, CLAUDE_CONFIG_DIR_ENV: home}


def _new_home(authority: NativeWorkspaceAuthority) -> DirectoryAuthority:
    authority.validate()
    if sys.platform != "linux":
        raise ProcessContainmentError("native role preparation requires Linux")
    root = derive_state_paths(authority.app_home.path).temp_homes_dir
    created = resolve_directory_authority(
        Path(tempfile.mkdtemp(prefix="vaultspec-native-home-", dir=root))
    )
    try:
        harden_credential_path(created.path)
    except OSError:
        _remove_home(created)
        raise
    return created


def _remove_home(created: DirectoryAuthority) -> None:
    assert_directory_authority(created)
    shutil.rmtree(created.path)


@contextmanager
def prepare_native_version_probe(
    authority: NativeWorkspaceAuthority | None,
) -> Generator[NativeLaunchAuthority | None]:
    """Give a bounded synchronous version probe a fresh, credential-free home."""
    if authority is None:
        yield None
        return
    created = _new_home(authority)
    try:
        yield authority.for_home(created.path)
    finally:
        _remove_home(created)


@asynccontextmanager
async def prepare_acp_role(
    authority: NativeWorkspaceAuthority | None,
    *,
    environment: Mapping[str, str],
    provider: str | None,
) -> AsyncGenerator[NativeLaunchAuthority | None]:
    """Keep unsupported stores and managed policy refused before home creation."""
    if authority is None:
        yield None
        return
    authority.validate()
    if sys.platform != "linux":
        raise ProcessContainmentError("native role preparation requires Linux")
    # An empty namespace must not silently drop organisation-managed policy.
    try:
        Path("/etc/claude-code").lstat()
    except FileNotFoundError:
        pass
    else:
        raise ProcessContainmentError("native Claude managed policy is not qualified")
    if provider == "claude":
        selected = environment.get(CLAUDE_OAUTH_TOKEN.env_name, "")
    elif provider == "zai":
        selected = environment.get(ANTHROPIC_AUTH_TOKEN_ENV, "")
    else:
        raise ProcessContainmentError(
            "native provider role preparation is not qualified"
        )
    if not selected.strip():
        raise ProcessContainmentError(
            "native subscription credential store is not qualified"
        )
    created = _new_home(authority)
    try:
        launch = authority.for_home(created.path)
        yield launch
    finally:
        await complete_cleanup(asyncio.to_thread(_remove_home, created))
