"""Production preparation orchestration for the capsule input authority.

This is the thin top-level flow of the capsule's preparation phase.  It
wires the proven component authorities in one sequence - resolve the
target-selective closures, acquire every pinned byte, derive per-package
license identity, emit the canonical closure inventories, build the installed
inventories, and author plus digest the pinned capsule input descriptor - into
a single ``prepare_capsule_inputs`` that emits the real shippable descriptor the
build stage opens read-only.  Preparation mints; the build stage consumes.

The component libraries stay where they are:
:mod:`vaultspec_a2a.desktop.capsule_input_authoring` (selection, acquisition,
emission, the distribution-wheel build),
:mod:`vaultspec_a2a.desktop.capsule_license` (license derivation), and
:mod:`vaultspec_a2a.desktop.capsule_descriptor` (installed inventories and
descriptor authoring).  This module owns only the sequencing and the mapping
from the committed pinned-inputs document to the descriptor's source facts.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
import tomllib
import zipfile
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from typing import TYPE_CHECKING, Final

from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from pydantic import ValidationError

from .artifacts import (
    _TARGET_SDK_PACKAGES,
    ArchiveKind,
    LockInputDescriptor,
    open_verified_capsule_inputs,
)
from .capsule_descriptor import (
    RuntimeSourceInput,
    author_capsule_descriptor,
    author_capsule_input_descriptor,
    author_source_descriptors,
    build_acp_installed_inventory,
    build_python_installed_inventory,
)
from .capsule_input_authoring import (
    BuiltDistribution,
    CapsuleInputAuthoringError,
    PinnedSource,
    acquire_acp_closure,
    acquire_pinned_sources,
    acquire_python_closure,
    build_a2a_distribution_wheel,
    emit_acp_closure_inventory,
    emit_python_closure_inventory,
)
from .capsule_license import (
    derive_acp_package_artifact,
    derive_python_wheel_artifact,
    load_acp_license_overrides,
    load_license_overrides,
)
from .closure_inventory import PythonWheelArtifact
from .contract import (
    ACP_VERSION_PIN,
    CPYTHON_VERSION_PIN,
    NODEJS_VERSION_PIN,
    TargetTriple,
)
from .lock_reconciliation import (
    _ACP_ROOT_PACKAGE,
    resolve_acp_closure_selection,
    resolve_python_closure_selection,
)
from .package_archives import (
    PackageArchiveError,
    open_verified_python_wheel_archive,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .capsule_input_authoring import ArtifactStreamOpener
    from .lock_reconciliation import AcpClosureSelection

__all__ = [
    "RuntimeSourceFacts",
    "SourceInputs",
    "derive_project_wheel_artifact",
    "load_source_inputs",
    "prepare_capsule_inputs",
]

_MAX_WHEEL_METADATA_BYTES: Final = 1 << 20
_PROJECT_ROOT_PACKAGE: Final = "vaultspec-a2a"
_ACP_ROOT_INSTALL_PATH: Final = f"node_modules/{_ACP_ROOT_PACKAGE}"
_MAX_PACKAGE_JSON_BYTES: Final = 1 << 20

# The committed pinned-inputs document declares version + license + url + sha256
# per source; the remaining descriptor facts (release, build, archive_root,
# license_members, redistribution_evidence) derive deterministically from the
# pinned url, which is itself immutable and content-verified.
_CPYTHON_URL_RE: Final = re.compile(
    r"/(?P<build>\d{8})/cpython-(?P<release>3\.13\.\d+)\+(?P=build)-"
    r"(?P<triple>[a-z0-9_-]+)-install_only\.tar\.gz$"
)
_NODE_URL_RE: Final = re.compile(
    r"/v(?P<release>22\.\d+\.\d+)/(?P<stem>node-v(?P=release)-[a-z0-9-]+)"
    r"\.(?P<ext>tar\.gz|zip)$"
)
_ACP_ARCHIVE_ROOT: Final = "package"
_PYTHON_ARCHIVE_ROOT: Final = "python"
# python-build-standalone install_only archives ship CPython's own license at
# lib/python<minor>/LICENSE.txt under the python root, not at python/LICENSE.
_PYTHON_LICENSE_MEMBER: Final = f"python/lib/python{CPYTHON_VERSION_PIN}/LICENSE.txt"


@dataclass(frozen=True, slots=True)
class RuntimeSourceFacts:
    """One runtime source's full descriptor facts plus its acquisition pin.

    ``facts`` is complete except for ``size``, which acquisition fills from the
    verified bytes; ``pinned`` carries the url + sha256 the acquirer verifies.
    """

    pinned: PinnedSource
    version: str
    release: str
    build: str
    archive_kind: ArchiveKind
    archive_root: str
    license_expression: str
    license_members: tuple[str, ...]
    redistribution_evidence: tuple[str, ...]

    def runtime_source_input(self, *, size: int) -> RuntimeSourceInput:
        """Bind the acquired byte size to produce the descriptor source facts."""
        return RuntimeSourceInput(
            version=self.version,
            release=self.release,
            build=self.build,
            url=self.pinned.url,
            sha256=self.pinned.sha256,
            size=size,
            archive_kind=self.archive_kind,
            archive_root=self.archive_root,
            license_expression=self.license_expression,
            license_members=self.license_members,
            redistribution_evidence=self.redistribution_evidence,
        )


@dataclass(frozen=True, slots=True)
class SourceInputs:
    """The three committed non-package sources one target ships."""

    python: RuntimeSourceFacts
    node: RuntimeSourceFacts
    acp: RuntimeSourceFacts


def _require_str(section: dict[str, object], key: str, label: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value:
        raise CapsuleInputAuthoringError(
            f"pinned inputs [{label}] is missing a non-empty {key}"
        )
    return value


def _python_facts(section: dict[str, object]) -> RuntimeSourceFacts:
    url = _require_str(section, "url", "python")
    match = _CPYTHON_URL_RE.search(url)
    if match is None:
        raise CapsuleInputAuthoringError(
            "python source url is not a pinned cpython install_only archive"
        )
    version = _require_str(section, "version", "python")
    if version != CPYTHON_VERSION_PIN:
        raise CapsuleInputAuthoringError(
            f"python source version must be pinned to {CPYTHON_VERSION_PIN}"
        )
    license_expression = _require_str(section, "license", "python")
    return RuntimeSourceFacts(
        pinned=PinnedSource(url=url, sha256=_require_str(section, "sha256", "python")),
        version=version,
        release=match["release"],
        build=match["build"],
        archive_kind=ArchiveKind.TAR_GZIP,
        archive_root=_PYTHON_ARCHIVE_ROOT,
        license_expression=license_expression,
        license_members=(_PYTHON_LICENSE_MEMBER,),
        redistribution_evidence=(f"archive-license:{_PYTHON_LICENSE_MEMBER}",),
    )


def _node_facts(section: dict[str, object]) -> RuntimeSourceFacts:
    url = _require_str(section, "url", "node")
    match = _NODE_URL_RE.search(url)
    if match is None:
        raise CapsuleInputAuthoringError(
            "node source url is not a pinned nodejs.org release archive"
        )
    version = _require_str(section, "version", "node")
    if version != NODEJS_VERSION_PIN:
        raise CapsuleInputAuthoringError(
            f"node source version must be pinned to {NODEJS_VERSION_PIN}"
        )
    archive_root = match["stem"]
    archive_kind = ArchiveKind.ZIP if match["ext"] == "zip" else ArchiveKind.TAR_GZIP
    license_expression = _require_str(section, "license", "node")
    return RuntimeSourceFacts(
        pinned=PinnedSource(url=url, sha256=_require_str(section, "sha256", "node")),
        version=version,
        release=match["release"],
        build=archive_root,
        archive_kind=archive_kind,
        archive_root=archive_root,
        license_expression=license_expression,
        license_members=(f"{archive_root}/LICENSE",),
        redistribution_evidence=(f"archive-license:{archive_root}/LICENSE",),
    )


def _acp_facts(section: dict[str, object]) -> RuntimeSourceFacts:
    url = _require_str(section, "url", "acp")
    if not url.endswith(".tgz"):
        raise CapsuleInputAuthoringError("acp source url is not a pinned npm tarball")
    version = _require_str(section, "version", "acp")
    if version != ACP_VERSION_PIN:
        raise CapsuleInputAuthoringError(
            f"acp source version must be pinned to {ACP_VERSION_PIN}"
        )
    license_expression = _require_str(section, "license", "acp")
    return RuntimeSourceFacts(
        pinned=PinnedSource(url=url, sha256=_require_str(section, "sha256", "acp")),
        version=version,
        release=version,
        build="npm",
        archive_kind=ArchiveKind.TAR_GZIP,
        archive_root=_ACP_ARCHIVE_ROOT,
        license_expression=license_expression,
        license_members=(f"{_ACP_ARCHIVE_ROOT}/LICENSE",),
        redistribution_evidence=(f"archive-license:{_ACP_ARCHIVE_ROOT}/LICENSE",),
    )


def load_source_inputs(inputs_toml: Path, target: TargetTriple) -> SourceInputs:
    """Parse the committed pinned-inputs document into one target's source facts.

    The runtime facts the descriptor needs beyond the four committed keys
    (release, build, archive_root, license members, redistribution evidence)
    derive deterministically from the pinned, content-verified url; a url that
    does not match its expected immutable release grammar fails closed rather
    than yielding a guessed fact.
    """
    try:
        document = tomllib.loads(inputs_toml.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise CapsuleInputAuthoringError(
            f"cannot read pinned inputs document: {error}"
        ) from None
    targets = document.get("targets")
    acp_section = document.get("acp")
    if not isinstance(targets, dict) or not isinstance(acp_section, dict):
        raise CapsuleInputAuthoringError("pinned inputs document has an invalid shape")
    target_section = targets.get(target.value)
    if not isinstance(target_section, dict):
        raise CapsuleInputAuthoringError(
            f"pinned inputs document does not declare target {target.value}"
        )
    python_section = target_section.get("python")
    node_section = target_section.get("node")
    if not isinstance(python_section, dict) or not isinstance(node_section, dict):
        raise CapsuleInputAuthoringError(
            f"pinned inputs for {target.value} are missing python or node"
        )
    return SourceInputs(
        python=_python_facts(python_section),
        node=_node_facts(node_section),
        acp=_acp_facts(acp_section),
    )


def _read_project_wheel_license(
    wheel_path: Path, filename: str
) -> tuple[str, tuple[str, ...]]:
    parts = filename.removesuffix(".whl").split("-")
    if len(parts) < 5:
        raise CapsuleInputAuthoringError(
            f"wheel filename identity is invalid: {filename}"
        )
    dist_info_root = f"{parts[0]}-{parts[1]}.dist-info"
    metadata_name = f"{dist_info_root}/METADATA"
    try:
        with zipfile.ZipFile(wheel_path, mode="r") as archive:
            names = frozenset(archive.namelist())
            if metadata_name not in names:
                raise CapsuleInputAuthoringError(f"wheel lacks {metadata_name}")
            with archive.open(metadata_name) as handle:
                payload = handle.read(_MAX_WHEEL_METADATA_BYTES + 1)
    except (OSError, zipfile.BadZipFile) as error:
        raise CapsuleInputAuthoringError(
            f"cannot read wheel archive: {error}"
        ) from None
    if len(payload) > _MAX_WHEEL_METADATA_BYTES:
        raise CapsuleInputAuthoringError("wheel METADATA exceeds its size bound")
    message = BytesParser(policy=policy.compat32).parsebytes(payload)
    expressions = message.get_all("License-Expression", [])
    license_files = message.get_all("License-File", [])
    if len(expressions) != 1 or not license_files:
        raise CapsuleInputAuthoringError(
            "project wheel METADATA must declare one SPDX license and its files"
        )
    members = tuple(f"{dist_info_root}/licenses/{name}" for name in license_files)
    if any(member not in names for member in members):
        raise CapsuleInputAuthoringError("project wheel license file is not placed")
    return expressions[0], members


def derive_project_wheel_artifact(
    built: BuiltDistribution, *, cache_root: Path, target: TargetTriple
) -> PythonWheelArtifact:
    """Derive the first-party wheel's license identity, proven through the verifier.

    The distribution is the locally built project wheel, not a lock selection, so
    its identity comes from its own dist-info: name and version from the wheel
    filename, the single SPDX ``License-Expression`` and its placed dist-info
    license members from ``METADATA``.  The wheel bytes must already sit at
    ``cache_root / built.sha256``; the derived artifact is round-tripped through
    the production wheel verifier rather than asserted against this output.
    """
    filename = built.path.name
    try:
        name, version, _, _ = parse_wheel_filename(filename)
    except InvalidWheelFilename as error:
        raise CapsuleInputAuthoringError(
            f"built distribution filename is not a valid wheel: {error}"
        ) from None
    expression, license_members = _read_project_wheel_license(
        cache_root / built.sha256, filename
    )
    try:
        artifact = PythonWheelArtifact(
            name=str(name),
            version=str(version),
            filename=filename,
            url=f"https://example.invalid/{filename}",
            sha256=built.sha256,
            size=built.size,
            license_expression=expression,
            license_members=license_members,
            redistribution_evidence=tuple(
                f"wheel-license:{member}" for member in license_members
            ),
        )
    except ValidationError as error:
        raise CapsuleInputAuthoringError(
            f"derived project wheel artifact is invalid: {error}"
        ) from None
    try:
        with open_verified_python_wheel_archive(
            cache_root / built.sha256, artifact, target=target
        ):
            pass
    except PackageArchiveError as error:
        raise CapsuleInputAuthoringError(
            f"derived project wheel identity fails verification: {error}"
        ) from None
    return artifact


def _read_acp_bin_entrypoints(cache_root: Path, sha256: str) -> tuple[str, ...]:
    """Read the ACP root package.json ``bin`` as placed installed-tree paths."""
    try:
        with tarfile.open(cache_root / sha256, mode="r:gz") as archive:
            member = archive.extractfile("package/package.json")
            if member is None:
                raise CapsuleInputAuthoringError("ACP root tarball lacks package.json")
            payload = member.read(_MAX_PACKAGE_JSON_BYTES + 1)
    except (OSError, tarfile.TarError) as error:
        raise CapsuleInputAuthoringError(
            f"cannot read ACP root package.json: {error}"
        ) from None
    if len(payload) > _MAX_PACKAGE_JSON_BYTES:
        raise CapsuleInputAuthoringError("ACP root package.json exceeds its size bound")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CapsuleInputAuthoringError(
            f"ACP root package.json is invalid: {error}"
        ) from None
    bin_field = document.get("bin")
    if isinstance(bin_field, str):
        paths: tuple[str, ...] = (bin_field,)
    elif (
        isinstance(bin_field, dict)
        and bin_field
        and all(isinstance(value, str) for value in bin_field.values())
    ):
        paths = tuple(bin_field.values())
    else:
        raise CapsuleInputAuthoringError(
            "ACP root package.json bin is missing or invalid"
        )
    return tuple(
        f"{_ACP_ROOT_INSTALL_PATH}/{path.removeprefix('./')}" for path in paths
    )


def _node_integrity(selection: AcpClosureSelection, install_path: str) -> str:
    for node in selection.packages:
        if node.install_path == install_path:
            return node.integrity
    raise CapsuleInputAuthoringError(f"ACP closure is missing {install_path}")


def prepare_capsule_inputs(
    target: TargetTriple,
    *,
    inputs_toml: Path,
    uv_lock: Path,
    package_lock: Path,
    repo_root: Path,
    cache_root: Path,
    output_dir: Path,
    source_date_epoch: int,
    open_stream: ArtifactStreamOpener | None = None,
) -> tuple[Path, str]:
    """Run the full per-target preparation flow, emitting the pinned descriptor.

    Resolves the target's Python and ACP closures, acquires every pinned byte
    into the content-addressed cache (the first-party wheel built from source
    HEAD among them), derives per-package license identity, emits the canonical
    closure inventories, builds the installed inventories, authors and digests
    the capsule input descriptor, and proves the whole set by opening it through
    the production verified-input session.  Returns the written descriptor path
    and its digest.  ``open_stream`` overrides network acquisition with an
    injected byte-stream seam for offline proofs; production omits it.
    """
    sources = load_source_inputs(inputs_toml, target)
    uv_bytes = uv_lock.read_bytes()
    package_bytes = package_lock.read_bytes()

    python_selection = resolve_python_closure_selection(
        lock_bytes=uv_bytes,
        target=target,
        root_package=_PROJECT_ROOT_PACKAGE,
        python_full_version=sources.python.release,
    )
    acp_selection = resolve_acp_closure_selection(
        lock_bytes=package_bytes,
        target=target,
        root_package=_ACP_ROOT_PACKAGE,
        node_full_version=sources.node.release,
    )

    acquired_wheels = acquire_python_closure(
        python_selection, cache_root=cache_root, open_stream=open_stream
    )
    acquired_tarballs = acquire_acp_closure(
        acp_selection, cache_root=cache_root, open_stream=open_stream
    )
    python_pin, node_pin, acp_pin = acquire_pinned_sources(
        (sources.python.pinned, sources.node.pinned, sources.acp.pinned),
        cache_root=cache_root,
        open_stream=open_stream,
    )
    built = build_a2a_distribution_wheel(
        repo_root=repo_root,
        sandbox=cache_root / ".a2a-build",
        source_date_epoch=source_date_epoch,
    )
    shutil.copyfile(built.path, cache_root / built.sha256)

    overrides = load_license_overrides(inputs_toml)
    acp_overrides = load_acp_license_overrides(inputs_toml)
    python_artifacts = tuple(
        derive_python_wheel_artifact(
            package,
            acquired_wheels[package.name].wheel,
            target=target,
            cache_root=cache_root,
            overrides=overrides,
        )
        for package in python_selection.packages
    )
    acp_artifacts = tuple(
        derive_acp_package_artifact(
            node,
            cache_root=cache_root,
            sha256=acquired_tarballs[node.install_path].sha256,
            size=acquired_tarballs[node.install_path].size,
            overrides=acp_overrides,
        )
        for node in acp_selection.packages
    )
    project_wheel = derive_project_wheel_artifact(
        built, cache_root=cache_root, target=target
    )

    python_inventory, python_emitted = emit_python_closure_inventory(
        python_selection,
        python_artifacts,
        lock_bytes=uv_bytes,
        root_package=_PROJECT_ROOT_PACKAGE,
        python_full_version=sources.python.release,
        cache_root=cache_root,
    )
    acp_inventory, acp_emitted = emit_acp_closure_inventory(
        acp_artifacts,
        target=target,
        lock_bytes=package_bytes,
        root_package=_ACP_ROOT_PACKAGE,
        node_full_version=sources.node.release,
        cache_root=cache_root,
    )

    uv_lock_sha256 = hashlib.sha256(uv_bytes).hexdigest()
    package_lock_sha256 = hashlib.sha256(package_bytes).hexdigest()
    root_integrity = _node_integrity(acp_selection, _ACP_ROOT_INSTALL_PATH)
    sdk_install_path = f"node_modules/{_TARGET_SDK_PACKAGES[target]}"
    sdk_integrity = _node_integrity(acp_selection, sdk_install_path)
    acp_root_sha256 = acquired_tarballs[_ACP_ROOT_INSTALL_PATH].sha256

    python_installed, _ = build_python_installed_inventory(
        (*python_artifacts, project_wheel),
        target=target,
        source_inventory_sha256=python_emitted.sha256,
        lock_sha256=uv_lock_sha256,
        cache_root=cache_root,
    )
    acp_installed, _ = build_acp_installed_inventory(
        acp_artifacts,
        target=target,
        source_inventory_sha256=acp_emitted.sha256,
        lock_sha256=package_lock_sha256,
        bin_entrypoints=_read_acp_bin_entrypoints(cache_root, acp_root_sha256),
        cache_root=cache_root,
    )

    descriptor = author_capsule_descriptor(
        target=target,
        source_date_epoch=source_date_epoch,
        sources=author_source_descriptors(
            target=target,
            python=sources.python.runtime_source_input(size=python_pin.size),
            node=sources.node.runtime_source_input(size=node_pin.size),
            acp=sources.acp.runtime_source_input(size=acp_pin.size),
            acp_root_integrity=root_integrity,
            a2a=built,
            a2a_version=project_wheel.version,
            a2a_license_expression=project_wheel.license_expression,
            a2a_license_members=project_wheel.license_members,
            a2a_redistribution_evidence=project_wheel.redistribution_evidence,
        ),
        uv_lock=LockInputDescriptor(sha256=uv_lock_sha256, size=len(uv_bytes)),
        package_lock=LockInputDescriptor(
            sha256=package_lock_sha256, size=len(package_bytes)
        ),
        python_installed=python_installed,
        python_inventory_sha256=python_emitted.sha256,
        python_inventory_size=python_emitted.size,
        python_package_count=len(python_inventory.packages),
        acp_installed=acp_installed,
        acp_inventory_sha256=acp_emitted.sha256,
        acp_inventory_size=acp_emitted.size,
        acp_package_count=len(acp_inventory.packages),
        acp_root_integrity=root_integrity,
        target_sdk_integrity=sdk_integrity,
    )
    authored = author_capsule_input_descriptor(descriptor, output_dir=output_dir)

    # The proof: the production consumer opens exactly the descriptor just
    # written against the same cache and locks. A failure raises loud here.
    with open_verified_capsule_inputs(
        authored.path,
        expected_descriptor_sha256=authored.sha256,
        input_dir=cache_root,
        uv_lock_path=uv_lock,
        package_lock_path=package_lock,
    ):
        pass
    return authored.path, authored.sha256
