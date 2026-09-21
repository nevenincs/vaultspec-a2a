"""Provider launch admission fails closed around the Compose identity boundary."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ...control.config import settings
from ...utils.process import ProcessContainmentError
from .._subprocess import _provider_execution_command

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Linux identity launcher")


def test_complete_identity_configuration_wraps_command_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = tmp_path / "vaultspec-agent-launch"
    launcher.write_bytes(b"launcher")
    monkeypatch.setattr(settings, "provider_identity_launcher", launcher)
    monkeypatch.setattr(settings, "provider_agent_uid", 1002)
    monkeypatch.setattr(settings, "provider_agent_gid", 1002)

    wrapped = _provider_execution_command(["python", "provider.py"])

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
    monkeypatch: pytest.MonkeyPatch,
    launcher: str | None,
    uid: int | None,
    gid: int | None,
) -> None:
    launcher_path = tmp_path / launcher if launcher is not None else None
    if launcher_path is not None:
        launcher_path.write_bytes(b"launcher")
    monkeypatch.setattr(settings, "provider_identity_launcher", launcher_path)
    monkeypatch.setattr(settings, "provider_agent_uid", uid)
    monkeypatch.setattr(settings, "provider_agent_gid", gid)

    with pytest.raises(ProcessContainmentError, match="requires launcher"):
        _provider_execution_command(["python", "provider.py"])


def test_missing_identity_launcher_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        settings, "provider_identity_launcher", tmp_path / "missing-launcher"
    )
    monkeypatch.setattr(settings, "provider_agent_uid", 1002)
    monkeypatch.setattr(settings, "provider_agent_gid", 1002)

    with pytest.raises(ProcessContainmentError, match="unavailable"):
        _provider_execution_command(["python", "provider.py"])
