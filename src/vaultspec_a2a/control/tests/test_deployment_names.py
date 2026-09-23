"""The Compose files and the container entrypoint name only real settings.

Both are exercised live only in the Docker lane, so on a host without Docker a
renamed setting would pass every other gate and first fail when a container
starts - with the entrypoint raising at boot, or a Compose key silently doing
nothing. These tests hold both to the settings schema by reading the files.
"""

from __future__ import annotations

import ast
import pathlib
import re

from ...control.config import Settings
from ...control.infra_config import InfraConfig
from ...control.settings_base import field_env_names

_SERVICE = pathlib.Path(__file__).resolve().parents[3].parent / "service"
_NAME = re.compile(r"\b(VAULTSPEC_[A-Z0-9_]+)\b")


def _declared() -> set[str]:
    return {
        name
        for field in Settings.model_fields
        for name in field_env_names(Settings, field)
    }


def _compose_files() -> list[pathlib.Path]:
    files = sorted(_SERVICE.glob("docker-compose*.yml"))
    assert files, f"no Compose files found under {_SERVICE}"
    return files


def test_every_compose_file_sets_only_declared_settings() -> None:
    declared = _declared()
    unknown = {
        f"{path.name}: {name}"
        for path in _compose_files()
        for name in _NAME.findall(path.read_text(encoding="utf-8"))
        if name not in declared
    }

    assert not unknown, (
        f"Compose files name settings a2a does not read: {sorted(unknown)}"
    )


def test_the_entrypoint_resolves_only_declared_fields() -> None:
    entrypoint = _SERVICE / "docker" / "service_entrypoint.py"
    tree = ast.parse(entrypoint.read_text(encoding="utf-8"))
    requested = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_name"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }

    assert requested, "the entrypoint no longer takes its names through _name()"
    assert requested <= set(InfraConfig.model_fields), sorted(
        requested - set(InfraConfig.model_fields)
    )
