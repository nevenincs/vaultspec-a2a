from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from vaultspec_a2a.desktop import capsule_assembly
from vaultspec_a2a.desktop.capsule_assembly import (
    CAPSULE_ARCHIVE_OUTPUT_NAME,
    CapsuleAssemblyPlan,
    CapsuleAssemblyPlanError,
    PlanReservationRole,
    ReservedRuntimeSubtree,
    ReservedTreeFile,
    derive_capsule_assembly_plan,
)
from vaultspec_a2a.desktop.contract import (
    ApiVersionRange,
    ComponentAssetKind,
    GatewayApiVersion,
    TargetTriple,
)
from vaultspec_a2a.desktop.installed_inventory import (
    InstalledFileRecord,
    InstalledLicenseRecord,
    build_installed_closure_inventory,
    license_component_token,
)
from vaultspec_a2a.desktop.tests._capsule_inputs import open_real_capsule_session

if TYPE_CHECKING:
    from pathlib import Path

    from vaultspec_a2a.desktop.artifacts import VerifiedCapsuleInputSession

_API_VERSIONS = ApiVersionRange(
    minimum=GatewayApiVersion.V1, maximum=GatewayApiVersion.V1
)

_MAX_FILE_BYTES = capsule_assembly._MAX_FILE_BYTES


@pytest.mark.parametrize(
    "path",
    (
        "rúntime/x",  # non-ASCII segment
        "runtime/pyth on",  # space
        "runtime/../escape",  # traversal
        "/rooted",
        "runtime//double",
        "runtime/name. ",
    ),
)
def test_dashboard_path_rejects_non_ascii_and_non_portable_segments(path: str) -> None:
    with pytest.raises(CapsuleAssemblyPlanError):
        capsule_assembly._validate_dashboard_path(path)


def test_dashboard_path_accepts_a_portable_ascii_capsule_path() -> None:
    assert (
        capsule_assembly._validate_dashboard_path("runtime/python/click/__init__.py")
        == "runtime/python/click/__init__.py"
    )


def test_reserved_tree_file_rejects_oversize_bytes_and_unknown_mode() -> None:
    with pytest.raises(CapsuleAssemblyPlanError, match="out-of-bound size"):
        ReservedTreeFile(
            path="runtime/python/big.bin",
            role=PlanReservationRole.PYTHON_CLOSURE_FILE,
            mode=0o644,
            size=_MAX_FILE_BYTES + 1,
        )
    with pytest.raises(CapsuleAssemblyPlanError, match="invalid mode"):
        ReservedTreeFile(
            path="runtime/python/odd.bin",
            role=PlanReservationRole.PYTHON_CLOSURE_FILE,
            mode=0o600,
            size=1,
        )
    reserved = ReservedTreeFile(
        path="runtime/python/ok.bin",
        role=PlanReservationRole.PYTHON_CLOSURE_FILE,
        mode=0o755,
        size=None,
    )
    assert reserved.size is None


def test_reserved_runtime_subtree_bounds_the_source_archive_size() -> None:
    with pytest.raises(CapsuleAssemblyPlanError, match="out-of-bound source size"):
        ReservedRuntimeSubtree(
            prefix="runtime/cpython",
            role=PlanReservationRole.CPYTHON_RUNTIME,
            source_kind=ComponentAssetKind.PYTHON_RUNTIME,
            source_size=(4 << 30) + 1,
        )


def test_whole_capsule_collision_rejects_case_insensitive_duplicates() -> None:
    with pytest.raises(CapsuleAssemblyPlanError, match="colliding path"):
        capsule_assembly._enforce_whole_capsule_collision(
            ("runtime/python/Click.py", "runtime/python/click.py")
        )


def test_whole_capsule_collision_rejects_file_and_subtree_ancestor_conflicts() -> None:
    with pytest.raises(CapsuleAssemblyPlanError, match="ancestor conflict"):
        capsule_assembly._enforce_whole_capsule_collision(
            ("runtime/python", "runtime/python/click/__init__.py")
        )


def test_whole_capsule_collision_accepts_a_disjoint_reservation_set() -> None:
    capsule_assembly._enforce_whole_capsule_collision(
        (
            "runtime/cpython",
            "runtime/node",
            "runtime/python/click/__init__.py",
            "runtime/acp/node_modules/pkg/index.js",
            "Scripts/vaultspec-a2a.exe",
        )
    )


def test_closure_license_presence_requires_every_package() -> None:
    import hashlib

    payload = b"real license bytes\n"
    digest = hashlib.sha256(payload).hexdigest()
    entry = b"#!/bin/sh\n"
    files = (
        InstalledFileRecord(
            relative_path="bin/entry",
            mode="0755",
            size=len(entry),
            sha256=hashlib.sha256(entry).hexdigest(),
        ),
        InstalledFileRecord(
            relative_path="licenses/click/LICENSE",
            mode="0644",
            size=len(payload),
            sha256=digest,
        ),
    )
    licenses = (
        InstalledLicenseRecord(
            package="click",
            component=license_component_token("python", "click"),
            license_expression="BSD-3-Clause",
            source_member="click-8.3.1.dist-info/licenses/LICENSE.txt",
            relative_path="licenses/click/LICENSE",
            sha256=digest,
        ),
    )
    inventory = build_installed_closure_inventory(
        closure_kind="python",
        target=TargetTriple.WINDOWS_X86_64,
        install_root="runtime/python",
        source_inventory_sha256="a" * 64,
        lock_sha256="b" * 64,
        entrypoints=("bin/entry",),
        licenses=licenses,
        files=files,
    )
    assert capsule_assembly._missing_license_packages(
        inventory, package_names={"click", "rich"}
    ) == {"rich"}
    assert not capsule_assembly._missing_license_packages(
        inventory, package_names={"click"}
    )

    # The predicate feeds the fail-closed coverage bound: an uncovered package
    # raises, a fully covered set does not.
    with pytest.raises(CapsuleAssemblyPlanError, match="Python closure omits"):
        capsule_assembly._assert_closure_license_coverage(
            inventory,
            package_names={"click", "rich"},
            closure_label="Python",
        )
    capsule_assembly._assert_closure_license_coverage(
        inventory,
        package_names={"click"},
        closure_label="Python",
    )


def test_source_license_bound_rejects_an_asset_without_license_bytes() -> None:
    with pytest.raises(
        CapsuleAssemblyPlanError, match="node-runtime source omits its license bytes"
    ):
        capsule_assembly._assert_declared_source_licenses(
            (
                ("python-runtime", ("python/LICENSE",)),
                ("node-runtime", ()),  # a source that declares no license member
            )
        )
    capsule_assembly._assert_declared_source_licenses(
        (
            ("python-runtime", ("python/LICENSE",)),
            ("node-runtime", ("node/LICENSE",)),
        )
    )


def test_aggregate_size_bound_rejects_an_over_bound_capsule() -> None:
    # Each reservation stays within the per-file bound; their sum exceeds the
    # aggregate bound, so the fail-closed aggregate check must raise.
    oversized = tuple(
        ReservedTreeFile(
            path=f"runtime/python/blob-{index}.bin",
            role=PlanReservationRole.PYTHON_CLOSURE_FILE,
            mode=0o644,
            size=_MAX_FILE_BYTES,
        )
        for index in range(5)
    )
    assert (
        sum(file.size for file in oversized)
        > capsule_assembly._MAX_KNOWN_AGGREGATE_BYTES
    )
    with pytest.raises(
        CapsuleAssemblyPlanError, match="aggregate known-file size bound"
    ):
        capsule_assembly._enforce_aggregate_size(oversized)

    within_bound = (
        ReservedTreeFile(
            path="runtime/python/small.bin",
            role=PlanReservationRole.PYTHON_CLOSURE_FILE,
            mode=0o644,
            size=1024,
        ),
        ReservedTreeFile(
            path="Scripts/vaultspec-a2a.exe",
            role=PlanReservationRole.GATEWAY_LAUNCHER,
            mode=0o755,
            size=None,
        ),
    )
    assert capsule_assembly._enforce_aggregate_size(within_bound) == 1024


def test_derive_plan_reserves_every_destination_from_a_real_session(
    tmp_path: Path,
) -> None:
    with open_real_capsule_session(tmp_path) as session:
        plan = derive_capsule_assembly_plan(session, api_versions=_API_VERSIONS)
        again = derive_capsule_assembly_plan(session, api_versions=_API_VERSIONS)

    assert isinstance(plan, CapsuleAssemblyPlan)
    assert plan == again  # deterministic
    assert plan.archive_output_name == CAPSULE_ARCHIVE_OUTPUT_NAME

    reserved = plan.reserved_paths()
    # interpreter subtrees
    assert {"runtime/cpython", "runtime/node"} <= reserved
    assert {sub.prefix for sub in plan.subtrees} == {"runtime/cpython", "runtime/node"}
    # installed closure files (from the real installed inventories)
    assert "runtime/python/bin/entry" in reserved
    assert "runtime/acp/bin/entry" in reserved
    assert any(path.startswith("runtime/python/licenses/") for path in reserved)
    assert any(path.startswith("runtime/acp/licenses/") for path in reserved)
    # relocatable launchers (Windows target)
    assert "Scripts/vaultspec-a2a.exe" in reserved
    assert "Scripts/vaultspec-a2a-mcp.exe" in reserved
    # dependency locks, manifest, evidence
    assert {
        "locks/uv.lock",
        "locks/package-lock.json",
        "component-manifest.json",
        "component-manifest.canonical.bin",
        "component-manifest.digest.sha256",
        "installed-tree.cdx.json",
    } <= reserved

    roles = {file.role for file in plan.files}
    assert PlanReservationRole.PYTHON_LICENSE in roles
    assert PlanReservationRole.ACP_LICENSE in roles
    assert PlanReservationRole.GATEWAY_LAUNCHER in roles
    assert PlanReservationRole.STANDALONE_MCP_LAUNCHER in roles

    # known aggregate equals the sum of every sized reservation
    expected = sum(file.size for file in plan.files if file.size is not None)
    assert plan.known_aggregate_bytes == expected

    # sorted, unique paths
    paths = [file.path for file in plan.files]
    assert paths == sorted(paths)
    assert len(reserved) == len(plan.files) + len(plan.subtrees)


def test_derive_plan_rejects_a_non_session_input() -> None:
    not_a_session = cast("VerifiedCapsuleInputSession", object())
    with pytest.raises(CapsuleAssemblyPlanError, match="input is invalid"):
        derive_capsule_assembly_plan(not_a_session, api_versions=_API_VERSIONS)
