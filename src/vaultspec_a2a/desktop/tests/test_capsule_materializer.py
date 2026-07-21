from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.desktop import capsule_assembly, capsule_materializer
from vaultspec_a2a.desktop._filesystem_authority import (
    claim_new_directory,
    directory_lease,
    resolve_directory_authority,
)
from vaultspec_a2a.desktop.capsule_assembly import (
    PlanReservationRole,
    derive_capsule_assembly_plan,
)
from vaultspec_a2a.desktop.capsule_materializer import (
    CapsuleMaterializationError,
    materialize_capsule_closures,
)
from vaultspec_a2a.desktop.contract import (
    ApiVersionRange,
    GatewayApiVersion,
    TargetTriple,
)
from vaultspec_a2a.desktop.installed_inventory import (
    build_verified_installed_closure_inventory,
)
from vaultspec_a2a.desktop.tests._materializer_inputs import (
    open_real_materializer_session,
)

if TYPE_CHECKING:
    from pathlib import Path

    from vaultspec_a2a.desktop.artifacts import VerifiedCapsuleInputSession
    from vaultspec_a2a.desktop.capsule_assembly import CapsuleAssemblyPlan
    from vaultspec_a2a.desktop.installed_inventory import InstalledClosureInventory

_API_VERSIONS = ApiVersionRange(
    minimum=GatewayApiVersion.V1, maximum=GatewayApiVersion.V1
)
_SOURCE_DATE_EPOCH = 1_700_000_000
_POSIX_TARGET = TargetTriple.LINUX_X86_64


def _materialize(
    tmp_path: Path,
    session: VerifiedCapsuleInputSession,
    plan: CapsuleAssemblyPlan,
    *,
    name: str,
) -> tuple[Path, tuple]:
    root = tmp_path / name
    root.mkdir()
    root_lease = resolve_directory_authority(root)
    with (
        directory_lease(root_lease) as generation,
        claim_new_directory(generation, "capsule") as capsule,
    ):
        projected = materialize_capsule_closures(
            plan,
            session,
            api_versions=_API_VERSIONS,
            destination_root=capsule.path,
            generation_authority=generation,
            destination_authority=capsule,
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )
    return capsule.path, projected


def test_materialize_places_every_closure_file_and_launcher_byte_exact(
    tmp_path: Path,
) -> None:
    with open_real_materializer_session(tmp_path, target=_POSIX_TARGET) as session:
        plan = derive_capsule_assembly_plan(session, api_versions=_API_VERSIONS)
        python_installed = session.python_installed
        acp_installed = session.acp_installed
        capsule_root, projected = _materialize(tmp_path, session, plan, name="gen-a")

    projected_by_path = {file.relative_path: file for file in projected}

    for inventory in (python_installed, acp_installed):
        for record in inventory.files:
            path = f"{inventory.install_root}/{record.relative_path}"
            emitted = projected_by_path[path]
            assert emitted.sha256 == record.sha256
            assert emitted.size == record.size
            on_disk = capsule_root / path
            payload = on_disk.read_bytes()
            assert len(payload) == record.size
            assert hashlib.sha256(payload).hexdigest() == record.sha256

    # every reserved closure/license/launcher path was actually materialized
    reserved = {
        file.path
        for file in plan.files
        if file.role
        in {
            PlanReservationRole.PYTHON_CLOSURE_FILE,
            PlanReservationRole.PYTHON_LICENSE,
            PlanReservationRole.ACP_CLOSURE_FILE,
            PlanReservationRole.ACP_LICENSE,
            PlanReservationRole.GATEWAY_LAUNCHER,
            PlanReservationRole.STANDALONE_MCP_LAUNCHER,
        }
    }
    assert reserved == set(projected_by_path)

    # relocatable POSIX launchers: presence, mode, and pinned import path content
    gateway = capsule_root / "bin/vaultspec-a2a"
    standalone = capsule_root / "bin/vaultspec-a2a-mcp"
    assert projected_by_path["bin/vaultspec-a2a"].mode == 0o755
    assert projected_by_path["bin/vaultspec-a2a-mcp"].mode == 0o755
    gateway_content = gateway.read_bytes()
    standalone_content = standalone.read_bytes()
    assert b'sys.path.insert(0, os.path.join(_capsule_root, "runtime/python"))' in (
        gateway_content
    )
    assert b"from vaultspec_a2a.cli.main import main as _entrypoint" in gateway_content
    assert (
        b"from vaultspec_a2a.protocols.mcp.__main__ import main as _entrypoint"
        in standalone_content
    )
    assert b"runtime/cpython/bin/python3.13" in gateway_content


def test_materialize_is_deterministic_across_two_generations(tmp_path: Path) -> None:
    with open_real_materializer_session(tmp_path, target=_POSIX_TARGET) as session:
        plan = derive_capsule_assembly_plan(session, api_versions=_API_VERSIONS)
        _, first = _materialize(tmp_path, session, plan, name="gen-first")
        _, second = _materialize(tmp_path, session, plan, name="gen-second")

    key = lambda file: file.relative_path  # noqa: E731
    assert sorted(first, key=key) == sorted(second, key=key)


def test_materialize_rejects_the_windows_launcher_stub(tmp_path: Path) -> None:
    with open_real_materializer_session(
        tmp_path, target=TargetTriple.WINDOWS_X86_64
    ) as session:
        plan = derive_capsule_assembly_plan(session, api_versions=_API_VERSIONS)
        root = tmp_path / "gen-windows"
        root.mkdir()
        root_lease = resolve_directory_authority(root)
        with (
            directory_lease(root_lease) as generation,
            claim_new_directory(generation, "capsule") as capsule,
            pytest.raises(CapsuleMaterializationError, match="Windows launcher stub"),
        ):
            materialize_capsule_closures(
                plan,
                session,
                api_versions=_API_VERSIONS,
                destination_root=capsule.path,
                generation_authority=generation,
                destination_authority=capsule,
                source_date_epoch=_SOURCE_DATE_EPOCH,
            )


def _ordinary_file(inventory: InstalledClosureInventory):
    license_paths = {license.relative_path for license in inventory.licenses}
    return next(
        record
        for record in inventory.files
        if record.relative_path not in license_paths
    )


def _reconstructed_evidence(
    inventory: InstalledClosureInventory,
) -> dict[str, frozenset[str]]:
    evidence: dict[str, set[str]] = {}
    for record in inventory.files:
        evidence.setdefault(record.source_sha256, set()).add(record.source_member)
    return {key: frozenset(value) for key, value in evidence.items()}


def test_materialize_closure_fails_closed_on_a_tampered_digest(
    tmp_path: Path,
) -> None:
    with open_real_materializer_session(tmp_path, target=_POSIX_TARGET) as session:
        inventory = session.python_installed
        target_record = _ordinary_file(inventory)
        tampered_files = tuple(
            record.model_copy(update={"sha256": "e" * 64})
            if record is target_record
            else record
            for record in inventory.files
        )
        tampered = build_verified_installed_closure_inventory(
            closure_kind=inventory.closure_kind,
            target=inventory.target,
            install_root=inventory.install_root,
            source_inventory_sha256=inventory.source_inventory_sha256,
            lock_sha256=inventory.lock_sha256,
            entrypoints=inventory.entrypoints,
            licenses=inventory.licenses,
            files=tampered_files,
            verified_closure_members=_reconstructed_evidence(inventory),
        )
        plan_files = {
            file.path: file
            for file in capsule_assembly._closure_files(
                tampered,
                file_role=PlanReservationRole.PYTHON_CLOSURE_FILE,
                license_role=PlanReservationRole.PYTHON_LICENSE,
            )
        }
        closure_sources = capsule_materializer._indexed_closure_sources(session)
        root = tmp_path / "gen-tamper"
        root.mkdir()
        root_lease = resolve_directory_authority(root)
        with (
            directory_lease(root_lease) as generation,
            claim_new_directory(generation, "capsule") as capsule,
            pytest.raises(
                CapsuleMaterializationError, match="does not match its installed digest"
            ),
        ):
            capsule_materializer._materialize_closure(
                tampered,
                plan_files=plan_files,
                allowed_roles=frozenset(
                    {
                        PlanReservationRole.PYTHON_CLOSURE_FILE,
                        PlanReservationRole.PYTHON_LICENSE,
                    }
                ),
                closure_sources=closure_sources,
                destination_root=capsule.path,
                generation_authority=generation,
                destination_authority=capsule,
                parent_identities={},
                source_date_epoch=_SOURCE_DATE_EPOCH,
            )


def test_materialize_closure_fails_closed_on_an_unavailable_source(
    tmp_path: Path,
) -> None:
    with open_real_materializer_session(tmp_path, target=_POSIX_TARGET) as session:
        inventory = session.python_installed
        target_record = _ordinary_file(inventory)
        unavailable_sha256 = "f" * 64
        tampered_files = tuple(
            record.model_copy(update={"source_sha256": unavailable_sha256})
            if record is target_record
            else record
            for record in inventory.files
        )
        evidence = _reconstructed_evidence(inventory)
        evidence[unavailable_sha256] = frozenset({target_record.source_member})
        tampered = build_verified_installed_closure_inventory(
            closure_kind=inventory.closure_kind,
            target=inventory.target,
            install_root=inventory.install_root,
            source_inventory_sha256=inventory.source_inventory_sha256,
            lock_sha256=inventory.lock_sha256,
            entrypoints=inventory.entrypoints,
            licenses=inventory.licenses,
            files=tampered_files,
            verified_closure_members=evidence,
        )
        plan_files = {
            file.path: file
            for file in capsule_assembly._closure_files(
                tampered,
                file_role=PlanReservationRole.PYTHON_CLOSURE_FILE,
                license_role=PlanReservationRole.PYTHON_LICENSE,
            )
        }
        closure_sources = capsule_materializer._indexed_closure_sources(session)
        root = tmp_path / "gen-missing"
        root.mkdir()
        root_lease = resolve_directory_authority(root)
        with (
            directory_lease(root_lease) as generation,
            claim_new_directory(generation, "capsule") as capsule,
            pytest.raises(
                CapsuleMaterializationError, match="unavailable materializer"
            ),
        ):
            capsule_materializer._materialize_closure(
                tampered,
                plan_files=plan_files,
                allowed_roles=frozenset(
                    {
                        PlanReservationRole.PYTHON_CLOSURE_FILE,
                        PlanReservationRole.PYTHON_LICENSE,
                    }
                ),
                closure_sources=closure_sources,
                destination_root=capsule.path,
                generation_authority=generation,
                destination_authority=capsule,
                parent_identities={},
                source_date_epoch=_SOURCE_DATE_EPOCH,
            )


def test_materialized_runtime_python_root_is_really_importable(
    tmp_path: Path,
) -> None:
    """Real, host-limited import smoke test for the runtime import-path pin.

    The bundled per-target CPython interpreter is not present on this host (the
    interpreter subtree is a verbatim projection this module never writes), so
    this proves the materialized ``runtime/python`` tree is import-correct by
    placing it on the *current* interpreter's ``sys.path`` in a fresh
    subprocess (no bundled-interpreter substitution risk to this test process)
    and importing a real materialized module from it. The generated launcher's
    own pinned import path is asserted separately, by content, above.
    """
    with open_real_materializer_session(tmp_path, target=_POSIX_TARGET) as session:
        plan = derive_capsule_assembly_plan(session, api_versions=_API_VERSIONS)
        capsule_root, _ = _materialize(tmp_path, session, plan, name="gen-smoke")

    runtime_python = capsule_root / "runtime" / "python"
    probe = (
        "import importlib, os, sys\n"
        "sys.path.insert(0, os.environ['VAULTSPEC_A2A_MATERIALIZED_ROOT'])\n"
        "module = importlib.import_module('vaultspec_a2a.desktop.contract')\n"
        "print(module.__file__)\n"
        "print(module.CPYTHON_VERSION_PIN)\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        env={
            **os.environ,
            "VAULTSPEC_A2A_MATERIALIZED_ROOT": str(runtime_python),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].startswith(str(runtime_python))
    assert lines[1] == "3.13"
