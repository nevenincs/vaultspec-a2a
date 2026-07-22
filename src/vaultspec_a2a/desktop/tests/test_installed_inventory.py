from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Literal

import pytest
from pydantic import ValidationError

from vaultspec_a2a.desktop.contract import TargetTriple
from vaultspec_a2a.desktop.installed_inventory import (
    INSTALLED_PROVENANCE_EVIDENCE_KEY,
    InstalledClosureDescriptor,
    InstalledClosureInventory,
    InstalledDroppedRecord,
    InstalledFileRecord,
    InstalledInventoryError,
    InstalledLicenseRecord,
    canonical_installed_inventory_bytes,
    installed_tree_digest,
    license_component_token,
    load_installed_closure_inventory,
    validate_dashboard_installed_closure_set,
)

if TYPE_CHECKING:
    from pathlib import Path

_SOURCE_DIGEST = "1" * 64
_LOCK_DIGEST = "2" * 64
_GATEWAY_DIGEST = "3" * 64
_LIBRARY_DIGEST = "4" * 64
_LICENSE_DIGEST = "5" * 64
_PACKAGE_DIGEST = "8" * 64
_TREE_DIGEST = "384d991a289784d373e98e1c6778c46a037845c26a1fb5cb435c1f825f2d8b1a"
_ACP_TREE_DIGEST = "6d9b5cb70bb281938eec8ea6bb9922d4208b63fc7abab9f934860d20c2b654ea"
_LICENSE_MEMBER = "example-1.0.dist-info/licenses/LICENSE"
_GATEWAY_MEMBER = "example-1.0.data/scripts/gateway"
_LIBRARY_MEMBER = "example-1.0/module.py"
_VERIFIED_MEMBERS = {
    _PACKAGE_DIGEST: frozenset({_GATEWAY_MEMBER, _LIBRARY_MEMBER, _LICENSE_MEMBER})
}


def _license(
    kind: Literal["python", "acp"] = "python", *, sha256: str = _LICENSE_DIGEST
) -> InstalledLicenseRecord:
    return InstalledLicenseRecord(
        package="example",
        component=license_component_token(kind, "example"),
        license_expression="MIT",
        source_member=_LICENSE_MEMBER,
        relative_path="licenses/example/LICENSE",
        sha256=sha256,
    )


def _files() -> tuple[InstalledFileRecord, ...]:
    return (
        InstalledFileRecord(
            relative_path="bin/gateway",
            mode="0755",
            size=7,
            sha256=_GATEWAY_DIGEST,
            source_sha256=_PACKAGE_DIGEST,
            source_member=_GATEWAY_MEMBER,
        ),
        InstalledFileRecord(
            relative_path="lib/module.py",
            mode="0644",
            size=11,
            sha256=_LIBRARY_DIGEST,
            source_sha256=_PACKAGE_DIGEST,
            source_member=_LIBRARY_MEMBER,
        ),
        InstalledFileRecord(
            relative_path="licenses/example/LICENSE",
            mode="0644",
            size=13,
            sha256=_LICENSE_DIGEST,
            source_sha256=_PACKAGE_DIGEST,
            source_member=_LICENSE_MEMBER,
        ),
    )


def _inventory(**changes: object) -> InstalledClosureInventory:
    context = changes.pop("context", None)
    fields: dict[str, object] = {
        "inventory_version": "vaultspec-installed-closure-v3",
        "closure_kind": "python",
        "target": TargetTriple.WINDOWS_X86_64,
        "install_root": "runtime/python",
        "source_inventory_sha256": _SOURCE_DIGEST,
        "lock_sha256": _LOCK_DIGEST,
        "file_count": 3,
        "expanded_size": 31,
        "tree_digest": _TREE_DIGEST,
        "entrypoints": ("bin/gateway",),
        "licenses": (_license(),),
        "files": _files(),
    }
    fields.update(changes)
    return InstalledClosureInventory.model_validate(fields, context=context)


def _write_content_addressed(
    cache: Path, inventory: InstalledClosureInventory
) -> InstalledClosureDescriptor:
    payload = canonical_installed_inventory_bytes(inventory)
    digest = hashlib.sha256(payload).hexdigest()
    (cache / digest).write_bytes(payload)
    return InstalledClosureDescriptor(
        descriptor_version="vaultspec-installed-closure-descriptor-v1",
        closure_kind=inventory.closure_kind,
        target=inventory.target,
        install_root=inventory.install_root,
        source_inventory_sha256=inventory.source_inventory_sha256,
        lock_sha256=inventory.lock_sha256,
        inventory_sha256=digest,
        inventory_size=len(payload),
        file_count=inventory.file_count,
        license_count=len(inventory.licenses),
        expanded_size=inventory.expanded_size,
        tree_digest=inventory.tree_digest,
    )


def test_inventory_is_immutable_canonical_and_dashboard_digest_compatible() -> None:
    inventory = _inventory()

    assert installed_tree_digest(inventory) == _TREE_DIGEST
    assert canonical_installed_inventory_bytes(inventory).endswith(b"\n")
    frozen: Any = inventory
    with pytest.raises(ValidationError, match="frozen"):
        frozen.file_count = 4


def test_acp_inventory_binds_its_own_target_install_root_and_tree() -> None:
    inventory = _inventory(
        closure_kind="acp",
        target=TargetTriple.LINUX_X86_64,
        install_root="runtime/acp",
        tree_digest=_ACP_TREE_DIGEST,
        licenses=(_license("acp"),),
    )

    assert inventory.closure_kind == "acp"
    assert inventory.target is TargetTriple.LINUX_X86_64
    assert installed_tree_digest(inventory) == _ACP_TREE_DIGEST


def test_dropped_records_bind_the_inventory_but_not_the_tree_digest() -> None:
    dropped = (
        InstalledDroppedRecord(
            source_member="example-1.0.data/scripts/tool",
            source_sha256=_PACKAGE_DIGEST,
            size=5,
            sha256="9" * 64,
            reason="data-scripts",
        ),
    )
    without = _inventory()
    with_dropped = _inventory(dropped=dropped)

    # A dropped record changes the inventory's canonical bytes (hence the
    # content digest the descriptor pins) ...
    assert canonical_installed_inventory_bytes(
        with_dropped
    ) != canonical_installed_inventory_bytes(without)
    # ... but never the placed-tree digest: the same tree with or without it.
    assert with_dropped.tree_digest == without.tree_digest == _TREE_DIGEST
    assert installed_tree_digest(with_dropped) == _TREE_DIGEST
    assert with_dropped.dropped == dropped


def test_inventory_rejects_the_superseded_v2_version() -> None:
    with pytest.raises(ValidationError):
        _inventory(inventory_version="vaultspec-installed-closure-v2")


def test_dropped_records_must_be_distinct_and_sorted() -> None:
    unsorted = (
        InstalledDroppedRecord(
            source_member="pkg.data/scripts/b",
            source_sha256=_PACKAGE_DIGEST,
            size=1,
            sha256="9" * 64,
            reason="data-scripts",
        ),
        InstalledDroppedRecord(
            source_member="pkg.data/scripts/a",
            source_sha256=_PACKAGE_DIGEST,
            size=1,
            sha256="9" * 64,
            reason="data-scripts",
        ),
    )
    with pytest.raises(ValidationError, match="dropped records must be distinct"):
        _inventory(dropped=unsorted)


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"file_count": 2}, "file count"),
        ({"expanded_size": 30}, "expanded size"),
        ({"tree_digest": "0" * 64}, "tree digest"),
        ({"entrypoints": ("lib/module.py",)}, "0755"),
        (
            {"licenses": (_license(sha256="6" * 64),)},
            "license does not match",
        ),
    ),
)
def test_inventory_rejects_contradictory_derived_authority(
    change: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _inventory(**change)


def test_inventory_rejects_unsorted_non_nfc_and_casefold_colliding_paths() -> None:
    files = _files()
    with pytest.raises(ValidationError, match="sorted"):
        _inventory(files=tuple(reversed(files)))

    with pytest.raises(ValidationError, match="NFC"):
        InstalledFileRecord(
            relative_path="licenses/cafe\u0301",
            mode="0644",
            size=1,
            sha256="7" * 64,
            source_sha256=_PACKAGE_DIGEST,
            source_member=_LIBRARY_MEMBER,
        )

    with pytest.raises(ValidationError, match="ASCII"):
        InstalledFileRecord(
            relative_path="licenses/caf\u00e9",
            mode="0644",
            size=1,
            sha256="7" * 64,
            source_sha256=_PACKAGE_DIGEST,
            source_member=_LIBRARY_MEMBER,
        )

    for invalid in ("lib/foo bar.py", "lib/foo~bar.py", "lib/foo#bar.py"):
        with pytest.raises(ValidationError, match="dashboard path grammar"):
            InstalledFileRecord(
                relative_path=invalid,
                mode="0644",
                size=1,
                sha256="7" * 64,
                source_sha256=_PACKAGE_DIGEST,
                source_member=_LIBRARY_MEMBER,
            )

    collision = InstalledFileRecord(
        relative_path="BIN/GATEWAY",
        mode="0644",
        size=1,
        sha256="7" * 64,
        source_sha256=_PACKAGE_DIGEST,
        source_member="example-1.0/collision.py",
    )
    with pytest.raises(ValidationError, match="collision"):
        _inventory(files=(collision, *_files()))


def test_license_metadata_matches_dashboard_token_and_spdx_bounds() -> None:
    with pytest.raises(ValidationError, match="at most 128"):
        InstalledLicenseRecord(
            package="example",
            component=license_component_token("python", "example"),
            license_expression="M" * 129,
            source_member="example-1.0.dist-info/licenses/LICENSE",
            relative_path="licenses/example/LICENSE",
            sha256=_LICENSE_DIGEST,
        )

    with pytest.raises(ValidationError, match="valid SPDX"):
        InstalledLicenseRecord(
            package="example",
            component=license_component_token("python", "example"),
            license_expression="MIT AND",
            source_member="example-1.0.dist-info/licenses/LICENSE",
            relative_path="licenses/example/LICENSE",
            sha256=_LICENSE_DIGEST,
        )

    contradictory = _license().model_copy(update={"component": "python-other"})
    with pytest.raises(ValidationError, match="component does not match"):
        _inventory(licenses=(contradictory,))

    duplicate_path = InstalledLicenseRecord(
        package="other",
        component=license_component_token("python", "other"),
        license_expression="Apache-2.0",
        source_member="other-1.0.dist-info/licenses/LICENSE",
        relative_path="licenses/example/LICENSE",
        sha256=_LICENSE_DIGEST,
    )
    with pytest.raises(ValidationError, match="distinct"):
        _inventory(licenses=(_license(), duplicate_path))


def test_dashboard_installed_closure_bounds_are_aggregate(tmp_path: Path) -> None:
    descriptor = _write_content_addressed(tmp_path, _inventory())
    validate_dashboard_installed_closure_set((descriptor, descriptor))

    oversized = descriptor.model_copy(update={"file_count": 80_000})
    with pytest.raises(ValueError, match="dashboard file bound"):
        validate_dashboard_installed_closure_set((descriptor, oversized))

    overlicensed = descriptor.model_copy(update={"license_count": 4_096})
    with pytest.raises(ValueError, match="dashboard license bound"):
        validate_dashboard_installed_closure_set((descriptor, overlicensed))


def test_exact_content_addressed_loader_reconciles_every_authority(
    tmp_path: Path,
) -> None:
    inventory = _inventory()
    descriptor = _write_content_addressed(tmp_path, inventory)

    loaded = load_installed_closure_inventory(descriptor, input_dir=tmp_path)

    assert loaded.value == inventory
    assert loaded.sha256 == descriptor.inventory_sha256
    assert loaded.path == tmp_path / descriptor.inventory_sha256

    contradictory = descriptor.model_copy(update={"file_count": 4})
    with pytest.raises(InstalledInventoryError, match="file count"):
        load_installed_closure_inventory(contradictory, input_dir=tmp_path)


def test_loader_rejects_noncanonical_and_digest_mutated_bytes(tmp_path: Path) -> None:
    inventory = _inventory()
    canonical = canonical_installed_inventory_bytes(inventory)
    document = json.loads(canonical)
    noncanonical = json.dumps(document, indent=2).encode("utf-8") + b"\n"
    digest = hashlib.sha256(noncanonical).hexdigest()
    (tmp_path / digest).write_bytes(noncanonical)
    descriptor = InstalledClosureDescriptor(
        descriptor_version="vaultspec-installed-closure-descriptor-v1",
        closure_kind=inventory.closure_kind,
        target=inventory.target,
        install_root=inventory.install_root,
        source_inventory_sha256=inventory.source_inventory_sha256,
        lock_sha256=inventory.lock_sha256,
        inventory_sha256=digest,
        inventory_size=len(noncanonical),
        file_count=inventory.file_count,
        license_count=len(inventory.licenses),
        expanded_size=inventory.expanded_size,
        tree_digest=inventory.tree_digest,
    )
    with pytest.raises(InstalledInventoryError, match="not canonical"):
        load_installed_closure_inventory(descriptor, input_dir=tmp_path)

    exact = _write_content_addressed(tmp_path, inventory)
    (tmp_path / exact.inventory_sha256).write_bytes(canonical[:-1] + b" ")
    with pytest.raises(InstalledInventoryError, match="digest"):
        load_installed_closure_inventory(exact, input_dir=tmp_path)


def test_loader_requires_an_ordinary_inventory_file(tmp_path: Path) -> None:
    inventory = _inventory()
    payload = canonical_installed_inventory_bytes(inventory)
    digest = hashlib.sha256(payload).hexdigest()
    (tmp_path / digest).mkdir()
    descriptor = InstalledClosureDescriptor(
        descriptor_version="vaultspec-installed-closure-descriptor-v1",
        closure_kind=inventory.closure_kind,
        target=inventory.target,
        install_root=inventory.install_root,
        source_inventory_sha256=inventory.source_inventory_sha256,
        lock_sha256=inventory.lock_sha256,
        inventory_sha256=digest,
        inventory_size=len(payload),
        file_count=inventory.file_count,
        license_count=len(inventory.licenses),
        expanded_size=inventory.expanded_size,
        tree_digest=inventory.tree_digest,
    )

    with pytest.raises(InstalledInventoryError, match="ordinary regular file"):
        load_installed_closure_inventory(descriptor, input_dir=tmp_path)


def test_provenance_membership_join_proves_verified_closure_members() -> None:
    context = {INSTALLED_PROVENANCE_EVIDENCE_KEY: _VERIFIED_MEMBERS}
    proven = _inventory(context=context)
    assert proven.inventory_version == "vaultspec-installed-closure-v3"
    assert proven.files[0].source_sha256 == _PACKAGE_DIGEST
    assert proven.files[0].source_member == _GATEWAY_MEMBER

    files = _files()
    unverified = files[1].model_copy(update={"source_member": "example-1.0/unknown.py"})
    with pytest.raises(
        ValidationError, match="does not name a verified closure member"
    ):
        _inventory(files=(files[0], unverified, files[2]), context=context)

    unknown_package = {INSTALLED_PROVENANCE_EVIDENCE_KEY: {"a" * 64: frozenset()}}
    with pytest.raises(
        ValidationError, match="does not name a verified closure member"
    ):
        _inventory(context=unknown_package)

    with pytest.raises(ValidationError, match="provenance evidence is malformed"):
        _inventory(context={INSTALLED_PROVENANCE_EVIDENCE_KEY: {_PACKAGE_DIGEST: 5}})


def test_v2_literal_rejects_unprovenanced_v1_inventory(tmp_path: Path) -> None:
    inventory = _inventory()
    document = json.loads(canonical_installed_inventory_bytes(inventory))
    document["inventory_version"] = "vaultspec-installed-closure-v1"
    with pytest.raises(ValidationError, match="inventory_version"):
        InstalledClosureInventory.model_validate(document)

    downgraded = (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    digest = hashlib.sha256(downgraded).hexdigest()
    (tmp_path / digest).write_bytes(downgraded)
    descriptor = InstalledClosureDescriptor(
        descriptor_version="vaultspec-installed-closure-descriptor-v1",
        closure_kind=inventory.closure_kind,
        target=inventory.target,
        install_root=inventory.install_root,
        source_inventory_sha256=inventory.source_inventory_sha256,
        lock_sha256=inventory.lock_sha256,
        inventory_sha256=digest,
        inventory_size=len(downgraded),
        file_count=inventory.file_count,
        license_count=len(inventory.licenses),
        expanded_size=inventory.expanded_size,
        tree_digest=inventory.tree_digest,
    )
    with pytest.raises(InstalledInventoryError, match="invalid"):
        load_installed_closure_inventory(descriptor, input_dir=tmp_path)


def test_tree_digest_is_byte_identical_across_provenance() -> None:
    baseline = _inventory()
    files = _files()
    reprovenanced = tuple(
        file.model_copy(
            update={
                "source_sha256": "9" * 64,
                "source_member": f"other-2.0/{index}",
            }
        )
        for index, file in enumerate(files)
    )
    shifted = _inventory(
        files=reprovenanced,
        licenses=(_license().model_copy(update={"source_member": "other-2.0/2"}),),
    )

    assert installed_tree_digest(baseline) == _TREE_DIGEST
    assert installed_tree_digest(shifted) == _TREE_DIGEST
    assert baseline.tree_digest == shifted.tree_digest
    assert canonical_installed_inventory_bytes(
        baseline
    ) != canonical_installed_inventory_bytes(shifted)


def test_canonical_inventory_bytes_are_deterministic() -> None:
    assert canonical_installed_inventory_bytes(
        _inventory()
    ) == canonical_installed_inventory_bytes(_inventory())
