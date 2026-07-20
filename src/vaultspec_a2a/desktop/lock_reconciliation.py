"""Fail-closed reconciliation of offline closure inventories with lock files.

The Python lock is authoritative for the selected wheel URL, SHA-256, size,
version, target markers, requested extras, and dependency graph.  npm lockfile
v3 is authoritative for tarball URL, SHA-512 SRI, version, target constraints,
and the dependency graph.  Standard npm lockfiles do not record tarball size or
SHA-256; those remain bound by the digest-pinned closure inventory and must be
verified against the real tarball bytes by the artifact verifier.

This module reconciles :mod:`vaultspec_a2a.desktop.closure_inventory`; exact lock
snapshots and verified package bytes are owned by
:mod:`vaultspec_a2a.desktop.artifacts` and
:mod:`vaultspec_a2a.desktop.package_archives`.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections import deque
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Final, cast
from urllib.parse import urlsplit

from packaging.markers import InvalidMarker, Marker
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .contract import TargetTriple

if TYPE_CHECKING:
    from .closure_inventory import (
        AcpClosureInventory,
        PythonClosureInventory,
        PythonWheelArtifact,
    )

__all__ = [
    "LockReconciliationError",
    "reconcile_acp_closure_lock_bytes",
    "reconcile_python_closure_lock_bytes",
]

_ACP_ROOT_PACKAGE: Final = "@agentclientprotocol/claude-agent-acp"
_TARGET_SDK_PREFIX: Final = "@anthropic-ai/claude-agent-sdk-"
_TARGET_SDK: Final = {
    TargetTriple.MACOS_ARM64: f"{_TARGET_SDK_PREFIX}darwin-arm64",
    TargetTriple.MACOS_X86_64: f"{_TARGET_SDK_PREFIX}darwin-x64",
    TargetTriple.LINUX_ARM64: f"{_TARGET_SDK_PREFIX}linux-arm64",
    TargetTriple.LINUX_X86_64: f"{_TARGET_SDK_PREFIX}linux-x64",
    TargetTriple.WINDOWS_X86_64: f"{_TARGET_SDK_PREFIX}win32-x64",
}
_TARGET_ENVIRONMENT: Final = {
    TargetTriple.MACOS_ARM64: ("posix", "arm64", "Darwin", "darwin"),
    TargetTriple.MACOS_X86_64: ("posix", "x86_64", "Darwin", "darwin"),
    TargetTriple.LINUX_ARM64: ("posix", "aarch64", "Linux", "linux"),
    TargetTriple.LINUX_X86_64: ("posix", "x86_64", "Linux", "linux"),
    TargetTriple.WINDOWS_X86_64: ("nt", "AMD64", "Windows", "win32"),
}
_TARGET_NPM: Final = {
    TargetTriple.MACOS_ARM64: ("darwin", "arm64"),
    TargetTriple.MACOS_X86_64: ("darwin", "x64"),
    TargetTriple.LINUX_ARM64: ("linux", "arm64"),
    TargetTriple.LINUX_X86_64: ("linux", "x64"),
    TargetTriple.WINDOWS_X86_64: ("win32", "x64"),
}
_UNBOUNDED_MARKER_VARIABLES: Final = re.compile(
    r"\b(?:platform_release|platform_version)\b"
)
_NPM_STABLE_VERSION: Final = re.compile(
    r"(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)


class LockReconciliationError(ValueError):
    """A lock cannot prove the supplied target-selected closure."""


def _verify_lock_digest(payload: bytes, expected: str, *, label: str) -> None:
    if hashlib.sha256(payload).hexdigest() != expected:
        raise LockReconciliationError(f"{label} does not match the inventory digest")


def _target_marker_environment(
    target: TargetTriple, *, extra: str, python_full_version: str
) -> dict[str, str]:
    os_name, machine, system, sys_platform = _TARGET_ENVIRONMENT[target]
    return {
        "implementation_name": "cpython",
        "implementation_version": python_full_version,
        "os_name": os_name,
        "platform_machine": machine,
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_system": system,
        "platform_version": "",
        "python_full_version": python_full_version,
        "python_version": "3.13",
        "sys_platform": sys_platform,
        "extra": extra,
    }


def _marker_applies(
    value: object,
    target: TargetTriple,
    *,
    extras: frozenset[str],
    python_full_version: str,
) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or not value:
        raise LockReconciliationError("lock dependency marker must be a string")
    if _UNBOUNDED_MARKER_VARIABLES.search(value):
        raise LockReconciliationError(
            "lock marker depends on an unspecified target OS version"
        )
    try:
        marker = Marker(value)
        contexts = ("", *sorted(extras))
        return any(
            marker.evaluate(
                _target_marker_environment(
                    target, extra=extra, python_full_version=python_full_version
                )
            )
            for extra in contexts
        )
    except (InvalidMarker, KeyError, TypeError, ValueError) as exc:
        raise LockReconciliationError(f"unsupported lock marker: {value}") from exc


def _python_record_applies(
    record: dict[str, Any], target: TargetTriple, python_full_version: str
) -> bool:
    markers = record.get("resolution-markers")
    if markers is None:
        return True
    if not isinstance(markers, list) or not markers:
        raise LockReconciliationError("package resolution-markers must be non-empty")
    decisions = [
        _marker_applies(
            value,
            target,
            extras=frozenset(),
            python_full_version=python_full_version,
        )
        for value in markers
    ]
    return any(decisions)


def _python_name(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LockReconciliationError(f"{label} package name is invalid")
    normalized = canonicalize_name(value)
    if value != normalized:
        raise LockReconciliationError(f"{label} package name is not canonical")
    return normalized


def _dependency_extras(dependency: dict[str, Any]) -> frozenset[str]:
    value = dependency.get("extra", [])
    if not isinstance(value, list) or any(
        not isinstance(extra, str) or not extra for extra in value
    ):
        raise LockReconciliationError("uv dependency extras have an unsupported shape")
    if len(set(value)) != len(value):
        raise LockReconciliationError("uv dependency extras are duplicated")
    return frozenset(cast("list[str]", value))


def _select_python_record(
    records: list[dict[str, Any]],
    dependency: dict[str, Any],
    target: TargetTriple,
    python_full_version: str,
) -> dict[str, Any]:
    name = _python_name(dependency.get("name"), label="dependency")
    version = dependency.get("version")
    source = dependency.get("source")
    if version is not None and not isinstance(version, str):
        raise LockReconciliationError("uv dependency version is invalid")
    if source is not None and not isinstance(source, dict):
        raise LockReconciliationError("uv dependency source is invalid")
    candidates = [
        record
        for record in records
        if record.get("name") == name
        and (version is None or record.get("version") == version)
        and (source is None or record.get("source") == source)
        and _python_record_applies(record, target, python_full_version)
    ]
    if len(candidates) != 1:
        raise LockReconciliationError(
            f"uv lock selects {len(candidates)} records for {name}; "
            "expected exactly one"
        )
    return candidates[0]


def _python_dependencies(
    record: dict[str, Any],
    target: TargetTriple,
    extras: frozenset[str],
    python_full_version: str,
) -> list[dict[str, Any]]:
    dependencies = record.get("dependencies", [])
    if not isinstance(dependencies, list) or any(
        not isinstance(dependency, dict) for dependency in dependencies
    ):
        raise LockReconciliationError(
            "uv package dependencies have an unsupported shape"
        )
    selected = [
        dependency
        for dependency in dependencies
        if _marker_applies(
            dependency.get("marker"),
            target,
            extras=extras,
            python_full_version=python_full_version,
        )
    ]
    optional = record.get("optional-dependencies", {})
    if not isinstance(optional, dict):
        raise LockReconciliationError(
            "uv optional dependencies have an unsupported shape"
        )
    for extra in sorted(extras):
        extra_dependencies = optional.get(extra)
        if not isinstance(extra_dependencies, list) or any(
            not isinstance(dependency, dict) for dependency in extra_dependencies
        ):
            raise LockReconciliationError(
                f"uv lock does not define requested extra {extra}"
            )
        selected.extend(
            dependency
            for dependency in extra_dependencies
            if _marker_applies(
                dependency.get("marker"),
                target,
                extras=frozenset({extra}),
                python_full_version=python_full_version,
            )
        )
    return selected


def reconcile_python_closure_lock_bytes(
    inventory: PythonClosureInventory,
    *,
    lock_bytes: bytes,
    root_package: str,
    python_full_version: str,
) -> None:
    """Prove a Python closure against exact uv.lock bytes for one target."""
    _verify_lock_digest(lock_bytes, inventory.lock_sha256, label="uv lock")
    try:
        lock = tomllib.loads(lock_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise LockReconciliationError("uv lock is not valid UTF-8 TOML") from exc
    if lock.get("version") != 1 or lock.get("revision") != 3:
        raise LockReconciliationError("unsupported uv lock version or revision")
    requires_python = lock.get("requires-python")
    if not isinstance(requires_python, str):
        raise LockReconciliationError("uv lock requires-python is absent")
    try:
        runtime_version = Version(python_full_version)
        if runtime_version.release[:2] != (3, 13) or len(runtime_version.release) != 3:
            raise LockReconciliationError("Python runtime must be one exact 3.13 patch")
        if runtime_version not in SpecifierSet(requires_python):
            raise LockReconciliationError("uv lock does not support Python 3.13")
    except (InvalidSpecifier, InvalidVersion) as exc:
        raise LockReconciliationError("uv lock requires-python is invalid") from exc
    records_value = lock.get("package")
    if not isinstance(records_value, list) or any(
        not isinstance(record, dict) for record in records_value
    ):
        raise LockReconciliationError("uv package records have an unsupported shape")
    records: list[dict[str, Any]] = records_value
    for record in records:
        record["name"] = _python_name(record.get("name"), label="uv lock")
        if not isinstance(record.get("version"), str):
            raise LockReconciliationError("uv package version is invalid")
    root_name = _python_name(root_package, label="approved root")
    root = _select_python_record(
        records,
        {"name": root_name},
        inventory.target,
        python_full_version,
    )

    selected: dict[str, dict[str, Any]] = {root_name: root}
    requested_extras: dict[str, frozenset[str]] = {root_name: frozenset()}
    expected_graph: dict[str, set[str]] = {}
    pending = deque([root_name])
    while pending:
        name = pending.popleft()
        record = selected[name]
        child_names: set[str] = set()
        for dependency in _python_dependencies(
            record,
            inventory.target,
            requested_extras[name],
            python_full_version,
        ):
            child = _select_python_record(
                records, dependency, inventory.target, python_full_version
            )
            child_name = child["name"]
            if child_name in {"torch", "vaultspec-rag"}:
                raise LockReconciliationError(
                    "selected Python graph enables rag or torch"
                )
            child_names.add(child_name)
            child_extras = _dependency_extras(dependency)
            existing = selected.get(child_name)
            if existing is not None and existing is not child:
                raise LockReconciliationError(
                    f"uv graph selects multiple identities for {child_name}"
                )
            combined = requested_extras.get(child_name, frozenset()) | child_extras
            if existing is None or combined != requested_extras.get(child_name):
                selected[child_name] = child
                requested_extras[child_name] = combined
                pending.append(child_name)
        expected_graph[name] = child_names

    inventory_by_name = {package.name: package for package in inventory.packages}
    expected_names = set(selected) - {root_name}
    if set(inventory_by_name) != expected_names:
        raise LockReconciliationError(
            "Python inventory contains unreachable extras or omits reachable packages"
        )
    if inventory.roots != tuple(sorted(expected_graph[root_name])):
        raise LockReconciliationError(
            "Python inventory roots differ from the approved root dependencies"
        )
    for name, package in inventory_by_name.items():
        record = selected[name]
        if tuple(sorted(expected_graph.get(name, set()))) != package.dependencies:
            raise LockReconciliationError(
                f"Python inventory dependency graph differs for {name}"
            )
        _verify_python_artifact_fields(record, package)


def _verify_python_artifact_fields(
    record: dict[str, Any], package: PythonWheelArtifact
) -> None:
    if record.get("version") != package.version:
        raise LockReconciliationError(f"uv version does not match {package.name}")
    wheels = record.get("wheels")
    if not isinstance(wheels, list) or any(
        not isinstance(wheel, dict) for wheel in wheels
    ):
        raise LockReconciliationError(
            f"uv wheel records are invalid for {package.name}"
        )
    matches = [
        wheel
        for wheel in wheels
        if wheel.get("url") == package.url
        and wheel.get("hash") == f"sha256:{package.sha256}"
        and wheel.get("size") == package.size
    ]
    if len(matches) != 1:
        raise LockReconciliationError(
            f"uv lock does not bind the exact wheel artifact for {package.name}"
        )
    if PurePosixPath(urlsplit(package.url).path).name != package.filename:
        raise LockReconciliationError(
            f"wheel URL filename does not match {package.name}"
        )


def _reject_duplicate_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise LockReconciliationError(f"package lock repeats JSON key {key}")
        value[key] = item
    return value


def _parse_package_lock(lock_bytes: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            lock_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                LockReconciliationError(f"package lock contains {constant}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LockReconciliationError("package lock is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise LockReconciliationError("package lock root must be an object")
    return value


def _npm_constraint_allows(value: object, selected: str, *, label: str) -> bool:
    if value is None:
        return True
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise LockReconciliationError(f"npm {label} constraint is invalid")
    constraints = cast("list[str]", value)
    denied = {item[1:] for item in constraints if item.startswith("!")}
    allowed = {item for item in constraints if not item.startswith("!")}
    return selected not in denied and (not allowed or selected in allowed)


def _npm_node_allows(record: dict[str, Any], target: TargetTriple) -> bool:
    os_name, cpu = _TARGET_NPM[target]
    platform_allowed = _npm_constraint_allows(
        record.get("os"), os_name, label="os"
    ) and _npm_constraint_allows(record.get("cpu"), cpu, label="cpu")
    libc = record.get("libc")
    if os_name != "linux":
        return platform_allowed and libc is None
    return platform_allowed and _npm_constraint_allows(libc, "glibc", label="libc")


def _stable_npm_version(value: str) -> Version:
    match = _NPM_STABLE_VERSION.fullmatch(value)
    if match is None:
        raise LockReconciliationError(
            "unsupported npm prerelease or non-SemVer version"
        )
    return Version(
        f"{match.group('major')}.{match.group('minor')}.{match.group('patch')}"
    )


def _npm_version_satisfies(specifier: str, version: object) -> bool:
    """Evaluate the stable npm range forms mechanically present in this lock."""
    if not isinstance(version, str):
        raise LockReconciliationError("npm resolved dependency version is absent")
    selected = _stable_npm_version(version)
    normalized = re.sub(r"(\^|~|>=|<=|>|<|=)\s+(?=\d)", r"\1", specifier.strip())
    if not normalized or len(normalized) > 256:
        raise LockReconciliationError("npm dependency range is invalid")
    decisions = tuple(
        _npm_range_clause_satisfies(clause.strip(), selected)
        for clause in normalized.split("||")
    )
    return any(decisions)


def _npm_range_clause_satisfies(clause: str, selected: Version) -> bool:
    if not clause:
        raise LockReconciliationError("npm dependency range is invalid")
    hyphen = re.fullmatch(r"([^ ]+)\s+-\s+([^ ]+)", clause)
    if hyphen is not None:
        lower, _ = _npm_partial_version(hyphen.group(1))
        upper, upper_parts = _npm_partial_version(hyphen.group(2))
        if len(upper_parts) < 3:
            upper = _npm_partial_upper(upper_parts)
            return lower <= selected < upper
        return lower <= selected <= upper
    decisions = tuple(
        _npm_comparator_satisfies(token, selected) for token in clause.split()
    )
    return all(decisions)


def _npm_partial_version(value: str) -> tuple[Version, tuple[int, ...]]:
    if value in {"*", "x", "X"}:
        return Version("0.0.0"), ()
    match = re.fullmatch(
        r"(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*|[xX*]))?"
        r"(?:\.(0|[1-9][0-9]*|[xX*]))?",
        value,
    )
    if match is None:
        parsed = _stable_npm_version(value)
        return parsed, tuple(int(part) for part in parsed.release)
    parts: list[int] = []
    for raw in match.groups():
        if raw is None or raw in {"x", "X", "*"}:
            break
        parts.append(int(raw))
    padded = (*parts, *(0 for _ in range(3 - len(parts))))
    return Version(".".join(str(part) for part in padded)), tuple(parts)


def _npm_partial_upper(parts: tuple[int, ...]) -> Version:
    if not parts:
        return Version("999999999.0.0")
    if len(parts) == 1:
        return Version(f"{parts[0] + 1}.0.0")
    return Version(f"{parts[0]}.{parts[1] + 1}.0")


def _npm_comparator_satisfies(token: str, selected: Version) -> bool:
    match = re.fullmatch(r"(\^|~|>=|<=|>|<|=)?(.+)", token)
    if match is None:
        raise LockReconciliationError("unsupported npm dependency range")
    operator, raw = match.groups()
    base, parts = _npm_partial_version(raw)
    if operator == "^":
        if not parts:
            return True
        major, minor, patch = (*parts, *(0 for _ in range(3 - len(parts))))
        if len(parts) == 1 or major:
            upper = Version(f"{major + 1}.0.0")
        elif len(parts) == 2 or minor:
            upper = Version(f"0.{minor + 1}.0")
        else:
            upper = Version(f"0.0.{patch + 1}")
        return base <= selected < upper
    if operator == "~":
        return base <= selected < _npm_partial_upper(parts[:2])
    if operator == "=" and len(parts) < 3:
        return base <= selected < _npm_partial_upper(parts)
    if operator == ">" and len(parts) < 3:
        return selected >= _npm_partial_upper(parts)
    if operator == "<=" and len(parts) < 3:
        return selected < _npm_partial_upper(parts)
    if operator in {">=", "<=", ">", "<", "="}:
        return {
            ">=": selected >= base,
            "<=": selected <= base,
            ">": selected > base,
            "<": selected < base,
            "=": selected == base,
        }[operator]
    if len(parts) < 3:
        return base <= selected < _npm_partial_upper(parts)
    return selected == base


def _npm_resolve_node(
    packages: dict[str, Any], current_path: str, name: str
) -> tuple[str, dict[str, Any]] | None:
    candidates: list[str] = []
    base = current_path
    while base:
        candidates.append(f"{base}/node_modules/{name}")
        marker = base.rfind("/node_modules/")
        if marker < 0:
            break
        base = base[:marker]
    candidates.append(f"node_modules/{name}")
    for candidate in dict.fromkeys(candidates):
        record = packages.get(candidate)
        if record is not None:
            if not isinstance(record, dict):
                raise LockReconciliationError(f"npm node {candidate} is not an object")
            return candidate, record
    return None


def _npm_dependency_maps(record: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    values = []
    for key in ("dependencies", "optionalDependencies", "peerDependencies"):
        value = record.get(key, {})
        if not isinstance(value, dict) or any(
            not isinstance(name, str) or not isinstance(specifier, str)
            for name, specifier in value.items()
        ):
            raise LockReconciliationError(f"npm {key} has an unsupported shape")
        values.append(value)
    return tuple(values)


def _selected_npm_dependencies(
    packages: dict[str, Any],
    path: str,
    record: dict[str, Any],
    target: TargetTriple,
) -> list[tuple[str, str, dict[str, Any]]]:
    normal, optional, peers = _npm_dependency_maps(record)
    peer_meta = record.get("peerDependenciesMeta", {})
    if not isinstance(peer_meta, dict):
        raise LockReconciliationError("npm peerDependenciesMeta is invalid")
    selected: dict[str, tuple[str, dict[str, Any]]] = {}

    def add(name: str, resolved: tuple[str, dict[str, Any]], specifier: str) -> None:
        if not _npm_version_satisfies(specifier, resolved[1].get("version")):
            raise LockReconciliationError(
                f"npm dependency {name} does not satisfy {specifier}"
            )
        existing = selected.get(name)
        if existing is not None and existing[0] != resolved[0]:
            raise LockReconciliationError(
                f"npm dependency classes resolve {name} to different nodes"
            )
        selected[name] = resolved

    for name in normal.keys() - optional.keys():
        resolved = _npm_resolve_node(packages, path, name)
        if resolved is None:
            raise LockReconciliationError(f"npm dependency {name} is absent")
        if not _npm_node_allows(resolved[1], target):
            raise LockReconciliationError(
                f"required npm dependency {name} rejects the selected target"
            )
        add(name, resolved, normal[name])
    expected_sdk = _TARGET_SDK[target]
    for name in optional:
        if name.startswith(_TARGET_SDK_PREFIX) and name != expected_sdk:
            continue
        resolved = _npm_resolve_node(packages, path, name)
        if resolved is None:
            continue
        node_path, node = resolved
        if _npm_node_allows(node, target):
            add(name, (node_path, node), optional[name])
    for name in peers:
        metadata = peer_meta.get(name, {})
        if not isinstance(metadata, dict):
            raise LockReconciliationError("npm peer dependency metadata is invalid")
        optional_peer = metadata.get("optional", False)
        if not isinstance(optional_peer, bool):
            raise LockReconciliationError("npm peer optional flag is invalid")
        resolved = _npm_resolve_node(packages, path, name)
        if resolved is None:
            if optional_peer:
                continue
            raise LockReconciliationError(f"required npm peer {name} is absent")
        node_path, node = resolved
        if not _npm_node_allows(node, target):
            if optional_peer:
                continue
            raise LockReconciliationError(
                f"required npm peer {name} rejects the selected target"
            )
        add(name, (node_path, node), peers[name])
    return [(name, *resolved) for name, resolved in selected.items()]


def _verify_node_engine(record: dict[str, Any], node_full_version: str) -> None:
    engines = record.get("engines")
    if engines is None:
        return
    if not isinstance(engines, dict) or any(
        not isinstance(name, str) or not isinstance(specifier, str)
        for name, specifier in engines.items()
    ):
        raise LockReconciliationError("npm engines has an unsupported shape")
    node_specifier = engines.get("node")
    if node_specifier is not None and not _npm_version_satisfies(
        node_specifier, node_full_version
    ):
        raise LockReconciliationError(
            f"npm package requires incompatible Node {node_specifier}"
        )


def reconcile_acp_closure_lock_bytes(
    inventory: AcpClosureInventory,
    *,
    lock_bytes: bytes,
    root_package: str,
    node_full_version: str,
) -> None:
    """Prove an ACP closure against exact package-lock v3 bytes.

    SHA-256 and size are intentionally not checked here because standard npm
    lockfile v3 does not carry those fields.  The digest-pinned inventory and
    real-tarball artifact verifier jointly retain that authority.
    """
    _verify_lock_digest(lock_bytes, inventory.lock_sha256, label="package lock")
    runtime_version = _stable_npm_version(node_full_version)
    if runtime_version.release[:2] != (22, 17):
        raise LockReconciliationError("Node runtime must be one exact 22.17 patch")
    lock = _parse_package_lock(lock_bytes)
    if lock.get("lockfileVersion") != 3 or lock.get("requires") is not True:
        raise LockReconciliationError("unsupported package-lock version or shape")
    packages = lock.get("packages")
    if not isinstance(packages, dict) or any(
        not isinstance(path, str) or not isinstance(record, dict)
        for path, record in packages.items()
    ):
        raise LockReconciliationError("package-lock packages are invalid")
    if root_package != _ACP_ROOT_PACKAGE:
        raise LockReconciliationError("ACP approved root must be explicit and exact")
    root_record = packages.get("")
    if not isinstance(root_record, dict):
        raise LockReconciliationError("package-lock project root is absent")
    root_dependencies = root_record.get("dependencies")
    if not isinstance(root_dependencies, dict) or set(root_dependencies) != {
        root_package
    }:
        raise LockReconciliationError("package-lock project root is not ACP-only")
    resolved_root = _npm_resolve_node(packages, "", root_package)
    if resolved_root is None:
        raise LockReconciliationError("ACP root package is absent")
    root_path, acp_root = resolved_root
    if root_dependencies[root_package] != acp_root.get("version"):
        raise LockReconciliationError("ACP project pin is not an exact root version")

    selected: dict[str, dict[str, Any]] = {root_path: acp_root}
    expected_graph: dict[str, set[str]] = {}
    pending = deque([root_path])
    while pending:
        path = pending.popleft()
        record = selected[path]
        _verify_node_engine(record, node_full_version)
        dependencies = _selected_npm_dependencies(
            packages, path, record, inventory.target
        )
        child_paths: set[str] = set()
        for _child_name, child_path, child in dependencies:
            child_paths.add(child_path)
            existing = selected.get(child_path)
            if existing is None:
                selected[child_path] = child
                pending.append(child_path)
            elif existing != child:
                raise LockReconciliationError(
                    f"package lock repeats contradictory node {child_path}"
                )
        expected_graph[path] = child_paths

    inventory_by_path = {
        package.install_path: package for package in inventory.packages
    }
    if set(inventory_by_path) != set(selected):
        raise LockReconciliationError(
            "ACP inventory contains unreachable extras or omits reachable packages"
        )
    target_sdk = _TARGET_SDK[inventory.target]
    selected_sdks = tuple(
        package
        for package in inventory.packages
        if package.name.startswith(_TARGET_SDK_PREFIX)
    )
    if len(selected_sdks) != 1 or selected_sdks[0].name != target_sdk:
        raise LockReconciliationError(
            "ACP inventory does not select exactly one target SDK"
        )
    for path, package in inventory_by_path.items():
        record = selected[path]
        if (
            record.get("version") != package.version
            or record.get("resolved") != package.url
            or record.get("integrity") != package.integrity
        ):
            raise LockReconciliationError(
                f"package lock does not bind the exact tarball identity for {path}"
            )
        if tuple(sorted(expected_graph.get(path, set()))) != package.dependency_paths:
            raise LockReconciliationError(
                f"ACP inventory dependency graph differs for {path}"
            )
