"""Per-package license derivation for the capsule's closure inventories.

The curated overrides input is loaded here, and each acquired wheel's license
identity - expression, license members, external licenses, and redistribution
evidence - is derived to exactly what the package-archive verifier demands and
proven by round-tripping through that real verifier rather than any assertion
against this module's own output.  Selection, acquisition, and inventory
emission live in :mod:`vaultspec_a2a.desktop.capsule_input_authoring`.
"""

from __future__ import annotations

import tomllib
import zipfile
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .capsule_input_authoring import CapsuleInputAuthoringError
from .closure_inventory import (
    ExternalLicenseArtifact,
    PythonWheelArtifact,
    _validate_https_url,
    validate_portable_archive_path,
)
from .package_archives import (
    _LEGACY_LICENSE_BASENAME,
    PackageArchiveError,
    open_verified_python_wheel_archive,
    verify_external_license_artifacts,
)

if TYPE_CHECKING:
    from .contract import TargetTriple
    from .lock_reconciliation import LockedWheel, PythonPackageSelection

__all__ = [
    "ExternalLicenseOverride",
    "LicenseOverride",
    "derive_python_wheel_artifact",
    "load_license_overrides",
]

_MAX_WHEEL_METADATA_BYTES: Final = 1 << 20


class ExternalLicenseOverride(BaseModel):
    """One committed external license blob for a package that ships none."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    member: str = Field(min_length=1, max_length=4096)
    url: str = Field(min_length=1, max_length=2048)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _url_is_credential_free_https(self) -> ExternalLicenseOverride:
        try:
            _validate_https_url(self.url)
        except ValueError:
            raise ValueError(
                "external license URL must be credential-free HTTPS"
            ) from None
        return self


class LicenseOverride(BaseModel):
    """One curated license fact for a package, keyed by name and exact version.

    An expression override supplies a curated SPDX expression for a wheel whose
    metadata lacks one, carrying the verbatim declaration it interprets as
    evidence.  External artifacts additionally bind license bytes for a package
    that ships none.  At least one aspect must be present.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=128)
    expression: str | None = Field(default=None, max_length=128)
    evidence: str | None = Field(default=None, max_length=1024)
    justification: str | None = Field(default=None, max_length=1024)
    external: tuple[ExternalLicenseOverride, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def _override_is_complete(self) -> LicenseOverride:
        if self.expression is None and not self.external:
            raise ValueError("a license override must supply an expression or blobs")
        if self.expression is not None:
            if not self.evidence:
                raise ValueError("an expression override must carry evidence")
            try:
                canonical = canonicalize_license_expression(self.expression)
            except InvalidLicenseExpression:
                raise ValueError("override expression is not valid SPDX") from None
            if canonical != self.expression:
                raise ValueError("override expression must be canonical SPDX")
        members = tuple(item.member for item in self.external)
        digests = tuple(item.sha256 for item in self.external)
        if len(set(members)) != len(members) or len(set(digests)) != len(digests):
            raise ValueError("external license members and digests must be distinct")
        return self


def load_license_overrides(path: Path) -> dict[str, LicenseOverride]:
    """Load the committed curated license overrides, keyed by canonical name."""
    try:
        document = tomllib.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CapsuleInputAuthoringError(
            f"cannot read curated license overrides: {error}"
        ) from None
    table = document.get("license_overrides", {})
    if not isinstance(table, dict):
        raise CapsuleInputAuthoringError("license_overrides must be a table")
    overrides: dict[str, LicenseOverride] = {}
    for name, entry in table.items():
        canonical = canonicalize_name(name)
        if canonical in overrides:
            raise CapsuleInputAuthoringError(
                f"curated license overrides repeat package {canonical}"
            )
        try:
            overrides[canonical] = LicenseOverride.model_validate(entry)
        except ValidationError as error:
            raise CapsuleInputAuthoringError(
                f"curated license override for {canonical} is invalid: {error}"
            ) from None
    return overrides


@dataclass(frozen=True, slots=True)
class _WheelLicenseFacts:
    metadata_version: Version
    expression: str | None
    license_files: tuple[str, ...]
    dist_info_root: str
    member_names: frozenset[str]


def _read_wheel_license_facts(wheel_path: Path, filename: str) -> _WheelLicenseFacts:
    parts = filename.removesuffix(".whl").split("-")
    if len(parts) < 5:
        raise CapsuleInputAuthoringError(
            f"wheel filename identity is invalid: {filename}"
        )
    dist_info_root = f"{parts[0]}-{parts[1]}.dist-info"
    metadata_name = f"{dist_info_root}/METADATA"
    try:
        with zipfile.ZipFile(wheel_path, mode="r") as archive:
            names = frozenset(
                name for name in archive.namelist() if not name.endswith("/")
            )
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
    versions = message.get_all("Metadata-Version", [])
    expressions = message.get_all("License-Expression", [])
    license_files = message.get_all("License-File", [])
    if len(versions) != 1 or len(expressions) > 1:
        raise CapsuleInputAuthoringError("wheel METADATA license identity is invalid")
    try:
        metadata_version = Version(versions[0])
    except InvalidVersion:
        raise CapsuleInputAuthoringError("wheel METADATA version is invalid") from None
    try:
        validated_files = tuple(
            validate_portable_archive_path(value) for value in license_files
        )
    except ValueError:
        raise CapsuleInputAuthoringError("wheel License-File path is invalid") from None
    return _WheelLicenseFacts(
        metadata_version=metadata_version,
        expression=expressions[0] if expressions else None,
        license_files=validated_files,
        dist_info_root=dist_info_root,
        member_names=names,
    )


def _external_license_artifact(
    name: str, override: ExternalLicenseOverride, cache_root: Path
) -> ExternalLicenseArtifact:
    blob = cache_root / override.sha256
    try:
        size = blob.stat().st_size
    except OSError:
        raise CapsuleInputAuthoringError(
            f"external license blob for {name} is not cached: {override.sha256}"
        ) from None
    try:
        return ExternalLicenseArtifact(
            source_id=f"external/{name}/{override.member}",
            declared_member=override.member,
            url=override.url,
            sha256=override.sha256,
            size=size,
        )
    except ValidationError as error:
        raise CapsuleInputAuthoringError(
            f"external license artifact for {name} is invalid: {error}"
        ) from None


def _derive_wheel_license(
    facts: _WheelLicenseFacts,
    *,
    name: str,
    override: LicenseOverride | None,
    cache_root: Path,
) -> tuple[str, tuple[str, ...], tuple[ExternalLicenseArtifact, ...], tuple[str, ...]]:
    if facts.expression is not None:
        expression = facts.expression
        expression_evidence: tuple[str, ...] = ()
    elif override is not None and override.expression is not None:
        expression = override.expression
        expression_evidence = (f"curated-license-expression:{expression}",)
    else:
        raise CapsuleInputAuthoringError(
            f"{name} lacks a metadata license expression and a curated override"
        )

    external_by_member = {
        item.member: item for item in (override.external if override else ())
    }
    members: list[str] = []
    externals: list[ExternalLicenseArtifact] = []

    if facts.license_files:
        for path in facts.license_files:
            if facts.metadata_version >= Version("2.4"):
                candidates = (f"{facts.dist_info_root}/licenses/{path}",)
            else:
                candidates = (
                    f"{facts.dist_info_root}/{path}",
                    f"{facts.dist_info_root}/license_files/{path}",
                    f"{facts.dist_info_root}/licenses/{path}",
                )
            present = [c for c in candidates if c in facts.member_names]
            if present:
                members.append(present[0])
            elif path in external_by_member:
                externals.append(
                    _external_license_artifact(
                        name, external_by_member[path], cache_root
                    )
                )
            else:
                raise CapsuleInputAuthoringError(
                    f"{name} License-File {path} is neither present nor a curated blob"
                )
    else:
        members = [
            member
            for member in sorted(facts.member_names)
            if member.startswith(f"{facts.dist_info_root}/")
            and _LEGACY_LICENSE_BASENAME.fullmatch(PurePosixPath(member).name)
            is not None
        ]
        if not members and override is not None:
            for item in override.external:
                if _LEGACY_LICENSE_BASENAME.fullmatch(item.member) is None:
                    raise CapsuleInputAuthoringError(
                        f"{name} external license {item.member} is not recognizable"
                    )
                externals.append(_external_license_artifact(name, item, cache_root))

    if not members and not externals:
        raise CapsuleInputAuthoringError(f"{name} binds no license bytes")

    evidence = (
        *expression_evidence,
        *(f"wheel-license:{member}" for member in members),
        *(f"external-license:{artifact.source_id}" for artifact in externals),
    )
    return (
        expression,
        tuple(members),
        tuple(sorted(externals, key=lambda artifact: artifact.source_id)),
        evidence,
    )


def derive_python_wheel_artifact(
    package: PythonPackageSelection,
    wheel: LockedWheel,
    *,
    target: TargetTriple,
    cache_root: Path,
    overrides: dict[str, LicenseOverride],
) -> PythonWheelArtifact:
    """Derive one wheel's license identity, proven through the real verifier.

    The derived artifact is round-tripped through the production wheel verifier
    rather than asserted against this function's own output, so an inventory can
    only be emitted for a license identity the consumer will accept.
    """
    override = overrides.get(package.name)
    if override is not None and override.version != package.version:
        raise CapsuleInputAuthoringError(
            f"license override for {package.name} pins {override.version}, "
            f"but the closure locks {package.version}"
        )
    facts = _read_wheel_license_facts(cache_root / wheel.sha256, wheel.filename)
    expression, members, externals, evidence = _derive_wheel_license(
        facts, name=package.name, override=override, cache_root=cache_root
    )
    try:
        artifact = PythonWheelArtifact(
            name=package.name,
            version=package.version,
            filename=wheel.filename,
            url=wheel.url,
            sha256=wheel.sha256,
            size=wheel.size,
            license_expression=expression,
            license_members=members,
            external_licenses=externals,
            redistribution_evidence=evidence,
            dependencies=package.dependencies,
        )
    except ValidationError as error:
        raise CapsuleInputAuthoringError(
            f"derived wheel artifact for {package.name} is invalid: {error}"
        ) from None
    try:
        with open_verified_python_wheel_archive(
            cache_root / wheel.sha256, artifact, target=target
        ) as session:
            if externals:
                verify_external_license_artifacts(session.archive, input_dir=cache_root)
    except PackageArchiveError as error:
        raise CapsuleInputAuthoringError(
            f"derived license identity for {package.name} fails verification: {error}"
        ) from None
    return artifact
