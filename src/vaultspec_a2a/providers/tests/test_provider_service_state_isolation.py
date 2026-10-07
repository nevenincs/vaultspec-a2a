"""Provider launch admission fails closed around the Compose identity boundary."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ...testing import settings_override
from ...utils import ProcessContainmentError
from .._provider_execution import provider_execution_command

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Linux identity launcher")


def test_complete_identity_configuration_wraps_command_without_credentials(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "vaultspec-agent-launch"
    launcher.write_bytes(b"launcher")

    with settings_override(
        provider_identity_launcher=launcher,
        provider_agent_uid=1002,
        provider_agent_gid=1002,
    ):
        wrapped = provider_execution_command(["python", "provider.py"])

    assert wrapped == [
        str(launcher),
        "1002",
        "1002",
        "--",
        "python",
        "provider.py",
    ]
    assert not any("token" in argument.casefold() for argument in wrapped)
    assert not any("database" in argument.casefold() for argument in wrapped)


@pytest.mark.parametrize(
    ("launcher", "uid", "gid"),
    (
        (None, 1002, 1002),
        ("launcher", None, 1002),
        ("launcher", 1002, None),
    ),
)
def test_partial_identity_configuration_fails_closed(
    tmp_path: Path,
    launcher: str | None,
    uid: int | None,
    gid: int | None,
) -> None:
    launcher_path = tmp_path / launcher if launcher is not None else None
    if launcher_path is not None:
        launcher_path.write_bytes(b"launcher")

    with (
        settings_override(
            provider_identity_launcher=launcher_path,
            provider_agent_uid=uid,
            provider_agent_gid=gid,
        ),
        pytest.raises(ProcessContainmentError, match="requires launcher"),
    ):
        provider_execution_command(["python", "provider.py"])


def test_missing_identity_launcher_fails_closed(tmp_path: Path) -> None:
    with (
        settings_override(
            provider_identity_launcher=tmp_path / "missing-launcher",
            provider_agent_uid=1002,
            provider_agent_gid=1002,
        ),
        pytest.raises(ProcessContainmentError, match="unavailable"),
    ):
        provider_execution_command(["python", "provider.py"])
