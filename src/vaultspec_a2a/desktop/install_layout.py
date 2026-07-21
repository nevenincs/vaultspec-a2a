"""Pure install-layout authority for offline desktop closures.

Package verification proves that a wheel or npm tarball is well formed and binds
per-member digest evidence.  This module answers the next, separate question:
given those already-verified members, exactly where does each byte land in the
relocatable capsule tree, and which files are executable entrypoints.

It performs no extraction, no hashing, no filesystem or network access.  It maps
RECORD-verified member evidence to installed destinations under the fixed closure
roots, deriving every installed digest from the supplied evidence rather than a
second trust root.  Wheel installation is spread-plus-``RECORD`` semantics, not the
verbatim prefix projection the generic projector offers; this module is the
wheel-aware placement path beside that deliberate refusal.

Both the production inventory builder and the record-replaying materializer consume
this one definition, so the declared tree and the written tree are the same layout.
The grammar, mode domain, and dashboard bounds are reused verbatim from
:mod:`vaultspec_a2a.desktop.installed_inventory`; unsupported wheel features fail
closed with a named error rather than being skipped or best-effort placed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .closure_inventory import validate_portable_archive_path
from .installed_inventory import (
    _MAX_EXPANDED_BYTES,
    _MAX_FILES,
    _MAX_MEMBER_BYTES,
    ClosureKind,
    FileMode,
    _portable_key,
    _portable_nfc_path,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "ArchiveMember",
    "ClosureLayout",
    "InstallLayoutError",
    "LayoutFile",
    "TarballSource",
    "WheelSource",
    "build_acp_closure_layout",
    "build_python_closure_layout",
]

_PYTHON_INSTALL_ROOT: Final = "runtime/python"
_ACP_INSTALL_ROOT: Final = "runtime/acp"
_NPM_ROOT: Final = "package"
_WHEEL_DATA_SUFFIX: Final = ".data"
_WHEEL_LIBRARY_DATA_KEYS: Final = frozenset({"purelib", "platlib"})
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")


class InstallLayoutError(RuntimeError):
    """Raised when verified members cannot be placed under a supported layout."""


@dataclass(frozen=True, slots=True)
class ArchiveMember:
    """One ``RECORD``-verified member: archive-relative path plus byte evidence."""

    member: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class LayoutFile:
    """One installed file destination with its carried provenance and evidence."""

    relative_path: str
    mode: FileMode
    size: int
    sha256: str
    source_sha256: str
    source_member: str


@dataclass(frozen=True, slots=True)
class WheelSource:
    """One verified wheel: its whole-archive digest, identity, and members."""

    source_sha256: str
    distribution: str
    version: str
    members: tuple[ArchiveMember, ...]


@dataclass(frozen=True, slots=True)
class TarballSource:
    """One verified npm tarball: its digest, nested destination, and members."""

    source_sha256: str
    install_path: str
    members: tuple[ArchiveMember, ...]


@dataclass(frozen=True, slots=True)
class ClosureLayout:
    """The complete installed placement for one closure, sorted and deterministic."""

    closure_kind: ClosureKind
    install_root: str
    entrypoints: tuple[str, ...]
    files: tuple[LayoutFile, ...]


def _validated_source_digest(value: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise InstallLayoutError("verified source digest is invalid")
    return value


def _validated_layout_path(value: str) -> str:
    """Validate one destination against the strict dashboard installed grammar.

    The reused installed-inventory validator is stricter than the archive-member
    validator (it additionally bounds NFC form, ASCII, and the dashboard path
    grammar) and raises ``ValueError``; translate that into the module's named error
    so no untyped exception escapes the layout contract.
    """
    try:
        return _portable_nfc_path(value)
    except (TypeError, ValueError):
        raise InstallLayoutError(
            "layout destination is not a portable dashboard path"
        ) from None


def _validated_member_evidence(member: object) -> ArchiveMember:
    if not isinstance(member, ArchiveMember):
        raise InstallLayoutError("verified member evidence is invalid")
    try:
        path = validate_portable_archive_path(member.member)
    except (TypeError, ValueError):
        raise InstallLayoutError("verified member path is not portable") from None
    if (
        not isinstance(member.size, int)
        or isinstance(member.size, bool)
        or member.size < 0
        or member.size > _MAX_MEMBER_BYTES
    ):
        raise InstallLayoutError("verified member size is out of bounds")
    if not isinstance(member.sha256, str) or _SHA256.fullmatch(member.sha256) is None:
        raise InstallLayoutError("verified member digest is invalid")
    return ArchiveMember(member=path, size=member.size, sha256=member.sha256)


def _wheel_destination(member: str, *, data_dir: str) -> str:
    """Map one archive-root wheel member to its library-root relative destination.

    Every archive-root member lands verbatim under the one library root (the closure
    install root; purelib and platlib coincide for the bundled interpreter).  The
    reserved ``.data`` directory spreads only its ``purelib`` and ``platlib`` subtrees
    to that same root; every other ``.data`` key and any unplaceable member fails
    closed.
    """
    first, slash, remainder = member.partition("/")
    if first != data_dir:
        return member
    if not slash:
        raise InstallLayoutError("wheel member is unplaceable")
    key, key_slash, subpath = remainder.partition("/")
    if key == "scripts":
        raise InstallLayoutError(
            "wheel .data/scripts requires shebang rewriting and is unsupported"
        )
    if key == "headers":
        raise InstallLayoutError("wheel .data/headers is unsupported")
    if key == "data":
        raise InstallLayoutError("wheel .data/data is unsupported")
    if key not in _WHEEL_LIBRARY_DATA_KEYS:
        raise InstallLayoutError("wheel .data key is unsupported")
    if not key_slash or not subpath:
        raise InstallLayoutError("wheel member is unplaceable")
    return subpath


def _assembled_closure(
    *,
    closure_kind: ClosureKind,
    install_root: str,
    placements: Iterable[tuple[str, str, ArchiveMember]],
    entrypoints: Iterable[str],
) -> ClosureLayout:
    """Assemble, deduplicate, bound, and sort one closure's placement."""
    by_path: dict[str, LayoutFile] = {}
    seen_keys: set[str] = set()
    expanded = 0
    entrypoint_paths = frozenset(entrypoints)
    for source_sha256, source_member, evidence in placements:
        relative_path = _validated_layout_path(evidence.member)
        _validated_layout_path(f"{install_root}/{relative_path}")
        key = _portable_key(relative_path)
        if key in seen_keys:
            raise InstallLayoutError("closure layout contains a path collision")
        seen_keys.add(key)
        expanded += evidence.size
        if expanded > _MAX_EXPANDED_BYTES:
            raise InstallLayoutError("closure layout exceeds the dashboard size bound")
        mode: FileMode = "0755" if relative_path in entrypoint_paths else "0644"
        by_path[relative_path] = LayoutFile(
            relative_path=relative_path,
            mode=mode,
            size=evidence.size,
            sha256=evidence.sha256,
            source_sha256=source_sha256,
            source_member=source_member,
        )
    if not by_path:
        raise InstallLayoutError("closure layout must place at least one file")
    if len(by_path) > _MAX_FILES:
        raise InstallLayoutError("closure layout exceeds the dashboard file bound")

    resolved_entrypoints = tuple(sorted(entrypoint_paths))
    for entrypoint in resolved_entrypoints:
        placed = by_path.get(entrypoint)
        if placed is None or placed.mode != "0755":
            raise InstallLayoutError("closure entrypoint does not name a placed file")

    files = tuple(by_path[path] for path in sorted(by_path))
    return ClosureLayout(
        closure_kind=closure_kind,
        install_root=install_root,
        entrypoints=resolved_entrypoints,
        files=files,
    )


def _console_script_destination(reference: str) -> str:
    """Derive the module-file destination backing one console-script reference.

    A reference is ``module.path:attribute``; the backing file is the module path with
    dotted separators turned into directories and a ``.py`` suffix.  The package-vs-
    module resolution nuance is deliberately left out: the derived path must name an
    already-placed module file, or placement fails closed.
    """
    if not isinstance(reference, str):
        raise InstallLayoutError("console-script reference is invalid")
    module, separator, attribute = reference.partition(":")
    if not separator or not attribute or not module:
        raise InstallLayoutError("console-script reference is malformed")
    parts = module.split(".")
    if any(not part for part in parts):
        raise InstallLayoutError("console-script module path is malformed")
    destination = "/".join(parts) + ".py"
    try:
        return validate_portable_archive_path(destination)
    except (TypeError, ValueError):
        raise InstallLayoutError("console-script module path is not portable") from None


def build_python_closure_layout(
    *,
    wheels: tuple[WheelSource, ...],
    console_scripts: tuple[tuple[str, str], ...],
) -> ClosureLayout:
    """Map every verified wheel member to its Python-closure destination.

    Members land under the single library root at ``runtime/python``; the reserved
    ``.data`` directory contributes only its ``purelib``/``platlib`` subtrees, and
    every other ``.data`` key, shebang-rewriting script, and unplaceable member fails
    closed.  Entrypoints are the module files backing the contract console-script
    references, promoted to ``0755``; all other files are ``0644``.
    """
    if not isinstance(wheels, tuple) or not wheels:
        raise InstallLayoutError("Python closure requires at least one verified wheel")

    placements: list[tuple[str, str, ArchiveMember]] = []
    for wheel in wheels:
        if not isinstance(wheel, WheelSource):
            raise InstallLayoutError("verified wheel input is invalid")
        source_sha256 = _validated_source_digest(wheel.source_sha256)
        if not wheel.distribution or not wheel.version:
            raise InstallLayoutError("verified wheel identity is invalid")
        data_dir = f"{wheel.distribution}-{wheel.version}{_WHEEL_DATA_SUFFIX}"
        for raw in wheel.members:
            member = _validated_member_evidence(raw)
            destination = _wheel_destination(member.member, data_dir=data_dir)
            placements.append(
                (
                    source_sha256,
                    member.member,
                    ArchiveMember(
                        member=destination,
                        size=member.size,
                        sha256=member.sha256,
                    ),
                )
            )

    placed_paths = {
        _validated_layout_path(evidence.member) for _, _, evidence in placements
    }
    entrypoints: set[str] = set()
    for name, reference in console_scripts:
        if not isinstance(name, str) or not name:
            raise InstallLayoutError("console-script name is invalid")
        destination = _console_script_destination(reference)
        if destination not in placed_paths:
            raise InstallLayoutError(
                "console-script entrypoint does not name a placed module file"
            )
        entrypoints.add(destination)

    return _assembled_closure(
        closure_kind="python",
        install_root=_PYTHON_INSTALL_ROOT,
        placements=placements,
        entrypoints=entrypoints,
    )


def build_acp_closure_layout(
    *,
    tarballs: tuple[TarballSource, ...],
    bin_entrypoints: tuple[str, ...],
) -> ClosureLayout:
    """Map every verified npm member to its nested ``node_modules`` destination.

    Each tarball projects verbatim to its declared nested-``node_modules`` install
    path with no ``.bin`` links and no hoisting; the ``package`` tarball root is
    replaced by that install path.  The declared bin entrypoints are promoted to
    ``0755``; all other files are ``0644``.
    """
    if not isinstance(tarballs, tuple) or not tarballs:
        raise InstallLayoutError("ACP closure requires at least one verified tarball")

    placements: list[tuple[str, str, ArchiveMember]] = []
    for tarball in tarballs:
        if not isinstance(tarball, TarballSource):
            raise InstallLayoutError("verified tarball input is invalid")
        source_sha256 = _validated_source_digest(tarball.source_sha256)
        try:
            install_path = validate_portable_archive_path(tarball.install_path)
        except (TypeError, ValueError):
            raise InstallLayoutError(
                "verified tarball install path is invalid"
            ) from None
        for raw in tarball.members:
            member = _validated_member_evidence(raw)
            root, slash, subpath = member.member.partition("/")
            if root != _NPM_ROOT or not slash or not subpath:
                raise InstallLayoutError("npm member is outside the package root")
            destination = f"{install_path}/{subpath}"
            placements.append(
                (
                    source_sha256,
                    member.member,
                    ArchiveMember(
                        member=destination,
                        size=member.size,
                        sha256=member.sha256,
                    ),
                )
            )

    entrypoints: set[str] = set()
    for entrypoint in bin_entrypoints:
        try:
            entrypoints.add(validate_portable_archive_path(entrypoint))
        except (TypeError, ValueError):
            raise InstallLayoutError("ACP bin entrypoint is not portable") from None

    return _assembled_closure(
        closure_kind="acp",
        install_root=_ACP_INSTALL_ROOT,
        placements=placements,
        entrypoints=entrypoints,
    )
