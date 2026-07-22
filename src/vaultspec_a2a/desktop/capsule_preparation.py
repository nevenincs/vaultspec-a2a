"""Production preparation orchestration for the capsule input authority.

This is the thin top-level flow the ADR's preparation phase calls for.  It
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

import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .artifacts import ArchiveKind
from .capsule_descriptor import RuntimeSourceInput
from .capsule_input_authoring import CapsuleInputAuthoringError, PinnedSource
from .contract import (
    ACP_VERSION_PIN,
    CPYTHON_VERSION_PIN,
    NODEJS_VERSION_PIN,
    TargetTriple,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "RuntimeSourceFacts",
    "SourceInputs",
    "load_source_inputs",
]

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
