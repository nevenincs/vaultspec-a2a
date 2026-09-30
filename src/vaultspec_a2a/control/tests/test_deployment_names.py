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


# The services whose shutdown the container runtime has to wait for. Both drain
# admission, close their store and flush telemetry on the way out, and both are
# started by Compose rather than by a person who could wait for them.
_SHUTDOWN_SERVICES = ("gateway", "worker")

_GRACE_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0}


def _seconds(duration: str) -> float:
    """Parse a Compose duration into seconds."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smh])", duration.strip())
    assert match is not None, f"unparsable Compose duration: {duration!r}"
    return float(match.group(1)) * _GRACE_UNITS[match.group(2)]


def _declared_grace(raw: object) -> float:
    """Read the effective grace period, including a Compose variable default."""
    assert isinstance(raw, str), raw
    default = re.fullmatch(r"\$\{[A-Z0-9_]+:-([^}]+)\}", raw.strip())
    return _seconds(default.group(1) if default is not None else raw)


def test_every_composed_service_outlives_its_own_shutdown_budget() -> None:
    """A stop grace shorter than the shutdown budget is a SIGKILL mid-drain.

    Docker's default is ten seconds and the service's own budget is longer, so
    leaving the key unset killed the container before its lifespan could finish.
    The two numbers live in different files, which is exactly why the relation
    between them is asserted rather than commented.
    """
    import yaml

    budget = Settings().shutdown_total_timeout_seconds
    checked = 0
    for path in _compose_files():
        composed = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name in _SHUTDOWN_SERVICES:
            service = composed.get("services", {}).get(name)
            if service is None or "stop_grace_period" not in service:
                continue
            grace = _declared_grace(service["stop_grace_period"])
            assert grace > budget, (
                f"{path.name}: {name} stop_grace_period {grace}s does not outlast "
                f"its {budget}s shutdown budget"
            )
            checked += 1

    assert checked >= len(_SHUTDOWN_SERVICES), (
        "no composed gateway/worker declares a stop_grace_period"
    )


def test_no_container_starts_a_served_app_behind_its_own_entry_point() -> None:
    """Invoking uvicorn directly discards the entry point that owns the server.

    The graceful-shutdown timeout and the bounded total budget are configured in
    the product's own serve entries, so a container that runs ``uvicorn`` against
    an app factory silently replaces both with uvicorn's defaults - which is how
    a stream-holding gateway came to be killed rather than drained.
    """
    for dockerfile in sorted((_SERVICE / "docker").glob("*.Dockerfile")):
        text = dockerfile.read_text(encoding="utf-8")
        launching = [
            line
            for line in text.splitlines()
            if line.startswith(("CMD", "ENTRYPOINT")) and "uvicorn" in line
        ]
        assert launching == [], f"{dockerfile.name}: {launching}"
