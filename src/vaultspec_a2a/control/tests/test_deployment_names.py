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
from typing import TYPE_CHECKING, Any, cast

from ...control.config import Settings
from ...control.infra_config import InfraConfig
from ...control.settings_base import field_env_names

if TYPE_CHECKING:
    from collections.abc import Mapping

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


# The served entry of each container and the setting that holds its bind host.
# Both settings default to loopback, which is right on a developer's machine and
# unreachable through a published port or from the next container on the
# Compose network.
_SERVED_BIND_FIELDS = {
    ("/app/.venv/bin/vaultspec-a2a", "serve"): "host",
    ("/app/.venv/bin/python", "-m", "vaultspec_a2a.worker"): "worker_host",
}

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_STAGE = re.compile(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?\s*$", re.IGNORECASE)
_ENV_PAIR = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(\S+)")


def _stages(dockerfile: pathlib.Path) -> dict[str, tuple[str, list[str]]]:
    """Map each named stage to its base and its instructions, lines joined."""
    stages: dict[str, tuple[str, list[str]]] = {}
    current: list[str] | None = None
    pending = ""
    for raw in dockerfile.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not pending and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        line, pending = pending + line, ""
        stage = _STAGE.match(line)
        if stage is not None:
            current = []
            stages[stage.group(2) or stage.group(1)] = (stage.group(1), current)
        elif current is not None:
            current.append(line)
    return stages


def _stage_env(stages: dict[str, tuple[str, list[str]]], name: str) -> dict[str, str]:
    """The ENV a stage runs with, including what it inherits from a local base."""
    base, instructions = stages[name]
    env = _stage_env(stages, base) if base in stages else {}
    for line in instructions:
        if line.upper().startswith("ENV "):
            env.update(_ENV_PAIR.findall(line[4:]))
    return env


def test_every_container_served_app_binds_beyond_loopback() -> None:
    """A served app bound to loopback inside its container is unreachable.

    Its health probe still passes, because the probe runs inside the same
    container, so nothing but the published port and the peer container notices.
    The bind host is a setting whose default is loopback, so every stage that
    serves an app must set it; the serve entries read settings, not flags.
    """
    import json

    served = 0
    for dockerfile in sorted((_SERVICE / "docker").glob("*.Dockerfile")):
        stages = _stages(dockerfile)
        for name, (_, instructions) in stages.items():
            commands = [line for line in instructions if line.startswith("CMD ")]
            if not commands:
                continue
            argv = tuple(json.loads(commands[-1][4:]))
            field = _SERVED_BIND_FIELDS.get(argv)
            if field is None:
                assert not any("vaultspec" in part for part in argv), (
                    f"{dockerfile.name}:{name} serves {argv} with no known bind setting"
                )
                continue
            env = _stage_env(stages, name)
            bound = [env[key] for key in field_env_names(Settings, field) if key in env]
            assert bound, (
                f"{dockerfile.name}:{name} leaves {field} at its loopback default"
            )
            assert not _LOOPBACK_HOSTS.intersection(bound), (
                f"{dockerfile.name}:{name} binds {field} to {bound}"
            )
            served += 1

    assert served >= len(_SERVED_BIND_FIELDS), "no container-served app was checked"


def test_no_compose_file_pins_a_served_app_back_to_loopback() -> None:
    """Compose environment overrides the image's ENV, so it is held to the same."""
    names = {
        key
        for field in set(_SERVED_BIND_FIELDS.values())
        for key in field_env_names(Settings, field)
    }
    pinned = [
        f"{path.name}: {line.strip()}"
        for path in _compose_files()
        for line in path.read_text(encoding="utf-8").splitlines()
        if any(name in line for name in names)
        and any(host in line for host in _LOOPBACK_HOSTS)
    ]

    assert pinned == []


def test_every_served_healthcheck_probes_the_container_by_its_own_hostname() -> None:
    """A loopback probe passes a server that only loopback can reach.

    Docker runs a healthcheck inside the container, where ``localhost`` reaches a
    server no peer container can. A gateway that regressed to a loopback bind
    therefore stayed healthy while it refused the worker's relay. The container's
    own hostname resolves to the address its peers use, so the probe fails exactly
    when they would.
    """
    import yaml

    probes: list[tuple[str, str, str]] = []
    for path in _compose_files():
        composed = cast(
            "Mapping[str, Mapping[str, Mapping[str, Any]]]",
            yaml.safe_load(path.read_text(encoding="utf-8")),
        )
        for name in _SHUTDOWN_SERVICES:
            service: Mapping[str, Any] = composed.get("services", {}).get(name) or {}
            check = service.get("healthcheck")
            if check is None:
                continue
            probes.append((path.name, name, " ".join(map(str, check["test"]))))

    assert len(probes) >= 2 * len(_SHUTDOWN_SERVICES), probes
    loopback = [
        probe for probe in probes if any(h in probe[2] for h in _LOOPBACK_HOSTS)
    ]
    assert loopback == []
    assert all("socket.gethostname()" in probe[2] for probe in probes), probes
