"""Parse the committed ``procs.toml``.

The single source of truth for per-role port bands, build/serve command
templates, and staleness windows, plus the fixed resident ports the registry must
never allocate into. Loaded by the registry (for band-constrained allocation) and
by the lifecycle verbs (for build/serve). Port-asserting tests read the same bands
here rather than hardcoding constants, so the picker of a test port and the
allocator of a live port share one definition.

Parsing is strict: bands must be well-formed inclusive ranges, must be pairwise
disjoint (so a port maps to at most one role), and no resident port may fall
inside any band. A malformed file raises :class:`ProcsConfigError` rather than
silently degrading - a wrong band is exactly the contention this registry exists
to end.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..control.config import settings

if TYPE_CHECKING:
    import os
    from collections.abc import Iterator
    from pathlib import Path

__all__ = [
    "PortBand",
    "ProcsConfig",
    "ProcsConfigError",
    "RoleConfig",
    "load_procs_config",
    "procs_config_path",
]

_PROCS_TOML_NAME = "procs.toml"
_PROCS_TOML_ENV = "VAULTSPEC_PROCS_TOML"


class ProcsConfigError(RuntimeError):
    """The procs.toml is missing, unreadable, or violates a band invariant."""


@dataclass(frozen=True, slots=True)
class PortBand:
    """An inclusive ``[start, end]`` port range a role allocates within."""

    start: int
    end: int

    def __contains__(self, port: int) -> bool:
        return self.start <= port <= self.end

    def __iter__(self) -> Iterator[int]:
        return iter(range(self.start, self.end + 1))

    def overlaps(self, other: PortBand) -> bool:
        return self.start <= other.end and other.start <= self.end


@dataclass(frozen=True, slots=True)
class RoleConfig:
    """A dev/test role's band, staleness policy, and command templates."""

    name: str
    band: PortBand
    heartbeat: bool
    staleness_ms: int
    build: list[str]
    serve: list[str]
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProcsConfig:
    """Parsed procs.toml: resident fixed ports and per-role dev/test configuration."""

    resident: dict[str, int]
    roles: dict[str, RoleConfig]

    def role(self, name: str) -> RoleConfig:
        """Return the role config, or raise a clear error naming the known roles."""
        try:
            return self.roles[name]
        except KeyError as exc:
            raise ProcsConfigError(
                f"unknown role {name!r}; declared roles: {sorted(self.roles)!r}"
            ) from exc


def procs_config_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the procs.toml path: explicit arg, env override, or repo root."""
    import os
    from pathlib import Path

    if path is not None:
        return Path(path)
    override = os.environ.get(_PROCS_TOML_ENV)
    if override:
        return Path(override)
    return settings.project_root / _PROCS_TOML_NAME


def _parse_band(role: str, raw: object) -> PortBand:
    if not isinstance(raw, list) or len(raw) != 2:
        raise ProcsConfigError(
            f"role {role!r} band must be a [start, end] pair of ints, got {raw!r}"
        )
    start, end = raw
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
    ):
        raise ProcsConfigError(
            f"role {role!r} band must be a [start, end] pair of ints, got {raw!r}"
        )
    if start <= 0 or end < start:
        raise ProcsConfigError(
            f"role {role!r} band [{start}, {end}] is not a positive ascending range"
        )
    return PortBand(start=start, end=end)


def _parse_command(role: str, key: str, raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ProcsConfigError(
            f"role {role!r} {key} must be a list of strings, got {raw!r}"
        )
    items: list[str] = []
    for value in raw:
        if not isinstance(value, str):
            raise ProcsConfigError(
                f"role {role!r} {key} must be a list of strings, got {raw!r}"
            )
        items.append(value)
    return items


def _parse_env(role: str, raw: object) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ProcsConfigError(
            f"role {role!r} env must be a table of string -> string, got {raw!r}"
        )
    env: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ProcsConfigError(
                f"role {role!r} env must be a table of string -> string, got {raw!r}"
            )
        env[key] = value
    return env


def _parse_role(name: str, raw: object) -> RoleConfig:
    if not isinstance(raw, dict):
        raise ProcsConfigError(
            f"role {name!r} must be a table, got {type(raw).__name__}"
        )
    band = _parse_band(name, raw.get("band"))
    heartbeat = raw.get("heartbeat", False)
    if not isinstance(heartbeat, bool):
        raise ProcsConfigError(f"role {name!r} heartbeat must be a bool")
    staleness_ms = raw.get("staleness_ms", 120000)
    if not isinstance(staleness_ms, int) or isinstance(staleness_ms, bool):
        raise ProcsConfigError(f"role {name!r} staleness_ms must be an int")
    return RoleConfig(
        name=name,
        band=band,
        heartbeat=heartbeat,
        staleness_ms=staleness_ms,
        build=_parse_command(name, "build", raw.get("build")),
        serve=_parse_command(name, "serve", raw.get("serve")),
        env=_parse_env(name, raw.get("env")),
    )


def _validate_disjoint(roles: dict[str, RoleConfig], resident: dict[str, int]) -> None:
    items = list(roles.values())
    for i, left in enumerate(items):
        for right in items[i + 1 :]:
            if left.band.overlaps(right.band):
                raise ProcsConfigError(
                    f"role bands overlap: {left.name!r} {left.band} and "
                    f"{right.name!r} {right.band}"
                )
    for svc, port in resident.items():
        for role in items:
            if port in role.band:
                raise ProcsConfigError(
                    f"resident {svc!r} port {port} falls inside role {role.name!r} "
                    f"band {role.band}"
                )


def load_procs_config(path: str | os.PathLike[str] | None = None) -> ProcsConfig:
    """Load and validate procs.toml. Raises :class:`ProcsConfigError` on any fault."""
    resolved = procs_config_path(path)
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise ProcsConfigError(f"cannot read procs.toml at {resolved}: {exc}") from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ProcsConfigError(f"procs.toml at {resolved} is invalid: {exc}") from exc

    resident_raw = data.get("resident", {})
    if not isinstance(resident_raw, dict):
        raise ProcsConfigError("[resident] must be a table of service -> port")
    resident: dict[str, int] = {}
    for svc, port in resident_raw.items():
        if not isinstance(port, int) or isinstance(port, bool):
            raise ProcsConfigError(
                f"resident {svc!r} port must be an int, got {port!r}"
            )
        resident[svc] = port

    roles_raw = data.get("roles", {})
    if not isinstance(roles_raw, dict) or not roles_raw:
        raise ProcsConfigError("[roles.*] must declare at least one role")
    roles = {name: _parse_role(name, raw_role) for name, raw_role in roles_raw.items()}

    _validate_disjoint(roles, resident)
    return ProcsConfig(resident=resident, roles=roles)
