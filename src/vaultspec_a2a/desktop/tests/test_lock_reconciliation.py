from __future__ import annotations

import base64
import hashlib
import json
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from vaultspec_a2a.desktop.closure_inventory import (
    AcpClosureInventory,
    AcpPackageArtifact,
    PythonClosureInventory,
    PythonWheelArtifact,
)
from vaultspec_a2a.desktop.contract import TargetTriple
from vaultspec_a2a.desktop.lock_reconciliation import (
    AcpClosureSelection,
    LockReconciliationError,
    PythonClosureSelection,
    _npm_version_satisfies,
    reconcile_acp_closure_lock_bytes,
    reconcile_python_closure_lock_bytes,
    resolve_acp_closure_selection,
    resolve_python_closure_selection,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PYTHON_RUNTIME = "3.13.5"
_ACP_ROOT = "@agentclientprotocol/claude-agent-acp"
_TARGET_SDK_SUFFIX = {
    TargetTriple.MACOS_ARM64: "darwin-arm64",
    TargetTriple.MACOS_X86_64: "darwin-x64",
    TargetTriple.LINUX_ARM64: "linux-arm64",
    TargetTriple.LINUX_X86_64: "linux-x64",
    TargetTriple.WINDOWS_X86_64: "win32-x64",
}
# The committed closure sizes.  A lock update legitimately moves these numbers;
# they are pinned so that such a move is a reviewed change rather than silent.
_COMMITTED_PYTHON_CLOSURE = {
    TargetTriple.MACOS_ARM64: 82,
    TargetTriple.MACOS_X86_64: 82,
    TargetTriple.LINUX_ARM64: 82,
    TargetTriple.LINUX_X86_64: 82,
    TargetTriple.WINDOWS_X86_64: 84,
}
_COMMITTED_ACP_CLOSURE = 104
# cryptography 49.0.0 publishes macOS wheels for arm64 only, so the Intel-macOS
# target has no compatible artifact.  It reaches the closure through the
# required mcp -> pyjwt[crypto] edge, and preparation for that one target fails
# closed until the lock, the target matrix, or that edge changes.
_KNOWN_WHEEL_GAP = {TargetTriple.MACOS_X86_64: {"cryptography"}}

_PYTHON_TARGET = {
    TargetTriple.MACOS_ARM64: (
        "1.0.1",
        "sys_platform == 'darwin' and platform_machine == 'arm64'",
    ),
    TargetTriple.MACOS_X86_64: (
        "1.0.2",
        "sys_platform == 'darwin' and platform_machine == 'x86_64'",
    ),
    TargetTriple.LINUX_ARM64: (
        "1.0.3",
        "sys_platform == 'linux' and platform_machine == 'aarch64'",
    ),
    TargetTriple.LINUX_X86_64: (
        "1.0.4",
        "sys_platform == 'linux' and platform_machine == 'x86_64'",
    ),
    TargetTriple.WINDOWS_X86_64: ("1.0.5", "sys_platform == 'win32'"),
}
_NPM_TARGET = {
    TargetTriple.MACOS_ARM64: ("darwin", "arm64"),
    TargetTriple.MACOS_X86_64: ("darwin", "x64"),
    TargetTriple.LINUX_ARM64: ("linux", "arm64"),
    TargetTriple.LINUX_X86_64: ("linux", "x64"),
    TargetTriple.WINDOWS_X86_64: ("win32", "x64"),
}
_NODE_VERSION = "22.17.0"


@pytest.mark.parametrize(
    ("specifier", "version", "expected"),
    (
        ("^0", "0.9.0", True),
        ("^0.0", "0.0.5", True),
        ("^0.0.3", "0.0.4", False),
        ("^1.2", "1.9.0", True),
        ("~1.2", "1.3.0", False),
        ("1.2 - 2.3", "2.3.9", True),
        (">= 0.6", "22.17.0", True),
        (">1", "1.0.1", False),
        (">1.2", "1.2.1", False),
        ("<=1.2", "1.2.9", True),
        ("=1.2", "1.2.9", True),
    ),
)
def test_stable_npm_range_subset_matches_semver_boundaries(
    specifier: str, version: str, expected: bool
) -> None:
    assert _npm_version_satisfies(specifier, version) is expected


@pytest.mark.parametrize(
    "specifier",
    ("* || >=2.0.0-beta.1", ">99 nonsense || *", ">99 nonsense"),
)
def test_npm_range_validation_never_short_circuits_invalid_syntax(
    specifier: str,
) -> None:
    with pytest.raises(LockReconciliationError):
        _npm_version_satisfies(specifier, "1.0.0")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _integrity(payload: bytes) -> str:
    encoded = base64.b64encode(hashlib.sha512(payload).digest()).decode("ascii")
    return f"sha512-{encoded}"


def _python_lock() -> bytes:
    records = []
    for version, marker in _PYTHON_TARGET.values():
        filename = f"platform_helper-{version}-py3-none-any.whl"
        url = f"https://files.pythonhosted.org/packages/{filename}"
        payload = f"wheel-{version}".encode()
        records.append(
            f'''[[package]]
name = "platform-helper"
version = "{version}"
source = {{ registry = "https://pypi.org/simple" }}
resolution-markers = ["{marker}"]
dependencies = [{{ name = "shared-runtime" }}]
wheels = [
  {{ url = "{url}", hash = "sha256:{_sha256(payload)}", size = {len(payload)} }},
]
'''
        )
    shared_payload = b"shared-runtime-wheel"
    shared_url = (
        "https://files.pythonhosted.org/packages/shared_runtime-2.0.0-py3-none-any.whl"
    )
    shared_record = (
        "\n[[package]]\n"
        'name = "shared-runtime"\n'
        'version = "2.0.0"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
        "wheels = [\n"
        f'  {{ url = "{shared_url}", hash = "sha256:{_sha256(shared_payload)}", '
        f"size = {len(shared_payload)} }},\n"
        "]\n"
    )
    return (
        """version = 1
revision = 3
requires-python = ">=3.13"

[[package]]
name = "vaultspec-a2a"
version = "0.1.0"
source = { editable = "." }
dependencies = [
  { name = "platform-helper" },
]

[package.optional-dependencies]
rag = [
  { name = "torch" },
  { name = "vaultspec-rag" },
]

"""
        + "\n".join(records)
        + shared_record
    ).encode()


def _python_inventory(
    target: TargetTriple, lock_bytes: bytes
) -> PythonClosureInventory:
    version, _ = _PYTHON_TARGET[target]
    payload = f"wheel-{version}".encode()
    filename = f"platform_helper-{version}-py3-none-any.whl"
    shared_payload = b"shared-runtime-wheel"
    shared_filename = "shared_runtime-2.0.0-py3-none-any.whl"
    packages = (
        PythonWheelArtifact(
            name="platform-helper",
            version=version,
            filename=filename,
            url=f"https://files.pythonhosted.org/packages/{filename}",
            sha256=_sha256(payload),
            size=len(payload),
            license_expression="MIT",
            license_members=("platform_helper.dist-info/LICENSE",),
            redistribution_evidence=("wheel-license:LICENSE",),
            dependencies=("shared-runtime",),
        ),
        PythonWheelArtifact(
            name="shared-runtime",
            version="2.0.0",
            filename=shared_filename,
            url=f"https://files.pythonhosted.org/packages/{shared_filename}",
            sha256=_sha256(shared_payload),
            size=len(shared_payload),
            license_expression="MIT",
            license_members=("shared_runtime.dist-info/LICENSE",),
            redistribution_evidence=("wheel-license:LICENSE",),
        ),
    )
    return PythonClosureInventory(
        inventory_version="vaultspec-python-wheelhouse-v1",
        target=target,
        lock_sha256=_sha256(lock_bytes),
        roots=("platform-helper",),
        packages=tuple(sorted(packages, key=lambda package: package.name)),
    )


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_python_lock_reconciliation_selects_each_python313_target(
    target: TargetTriple,
) -> None:
    lock_bytes = _python_lock()

    reconcile_python_closure_lock_bytes(
        _python_inventory(target, lock_bytes),
        lock_bytes=lock_bytes,
        root_package="vaultspec-a2a",
        python_full_version="3.13.5",
    )


def test_python_lock_reconciliation_rejects_unbounded_target_marker() -> None:
    lock_bytes = _python_lock().replace(
        b"sys_platform == 'win32'", b"platform_release == '10'"
    )

    with pytest.raises(LockReconciliationError, match="unspecified target OS version"):
        reconcile_python_closure_lock_bytes(
            _python_inventory(TargetTriple.WINDOWS_X86_64, lock_bytes),
            lock_bytes=lock_bytes,
            root_package="vaultspec-a2a",
            python_full_version="3.13.5",
        )


def test_python_lock_reconciliation_rejects_unreachable_inventory_package() -> None:
    lock_bytes = _python_lock()
    inventory = _python_inventory(TargetTriple.LINUX_X86_64, lock_bytes)
    stray_payload = b"stray-wheel"
    stray = PythonWheelArtifact(
        name="stray",
        version="1.0",
        filename="stray-1.0-py3-none-any.whl",
        url="https://files.pythonhosted.org/packages/stray-1.0-py3-none-any.whl",
        sha256=_sha256(stray_payload),
        size=len(stray_payload),
        license_expression="MIT",
        license_members=("stray.dist-info/LICENSE",),
        redistribution_evidence=("wheel-license:LICENSE",),
    )
    inventory = PythonClosureInventory(
        inventory_version=inventory.inventory_version,
        target=inventory.target,
        lock_sha256=inventory.lock_sha256,
        roots=("platform-helper", "stray"),
        packages=tuple(
            sorted((*inventory.packages, stray), key=lambda item: item.name)
        ),
    )

    with pytest.raises(LockReconciliationError, match="unreachable extras"):
        reconcile_python_closure_lock_bytes(
            inventory,
            lock_bytes=lock_bytes,
            root_package="vaultspec-a2a",
            python_full_version="3.13.5",
        )


def test_python_lock_reconciliation_uses_exact_runtime_patch_for_markers() -> None:
    lock_bytes = _python_lock().replace(
        b"sys_platform == 'win32'",
        b"sys_platform == 'win32' and python_full_version >= '3.13.4'",
    )

    reconcile_python_closure_lock_bytes(
        _python_inventory(TargetTriple.WINDOWS_X86_64, lock_bytes),
        lock_bytes=lock_bytes,
        root_package="vaultspec-a2a",
        python_full_version="3.13.5",
    )


def _npm_package_lock(target_native_nested: bool = False) -> bytes:
    packages: dict[str, object] = {
        "": {
            "name": "vaultspec-a2a",
            "dependencies": {"@agentclientprotocol/claude-agent-acp": "0.59.0"},
        },
        "node_modules/@agentclientprotocol/claude-agent-acp": {
            "version": "0.59.0",
            "resolved": "https://registry.npmjs.org/@agentclientprotocol/claude-agent-acp/-/claude-agent-acp-0.59.0.tgz",
            "integrity": _integrity(b"acp-root"),
            "dependencies": {"@anthropic-ai/claude-agent-sdk": "0.3.207"},
        },
        "node_modules/@anthropic-ai/claude-agent-sdk": {
            "version": "0.3.207",
            "resolved": "https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/-/claude-agent-sdk-0.3.207.tgz",
            "integrity": _integrity(b"generic-sdk"),
            "optionalDependencies": {
                f"@anthropic-ai/claude-agent-sdk-{os_name}-{cpu}": "0.3.207"
                for os_name, cpu in _NPM_TARGET.values()
            },
            "peerDependencies": {"peer-runtime": ">=2"},
        },
    }
    for os_name, cpu in _NPM_TARGET.values():
        name = f"@anthropic-ai/claude-agent-sdk-{os_name}-{cpu}"
        filename = name.rsplit("/", 1)[-1]
        packages[f"node_modules/{name}"] = {
            "version": "0.3.207",
            "resolved": (f"https://registry.npmjs.org/{name}/-/{filename}-0.3.207.tgz"),
            "integrity": _integrity(name.encode()),
            "optional": True,
            "os": [os_name],
            "cpu": [cpu],
        }
    peer_path = "node_modules/peer-runtime"
    if target_native_nested:
        peer_path = (
            "node_modules/@anthropic-ai/claude-agent-sdk/node_modules/peer-runtime"
        )
    packages[peer_path] = {
        "version": "2.1.0",
        "resolved": "https://registry.npmjs.org/peer-runtime/-/peer-runtime-2.1.0.tgz",
        "integrity": _integrity(b"peer-runtime"),
        "peer": True,
    }
    return json.dumps(
        {
            "name": "vaultspec-a2a",
            "lockfileVersion": 3,
            "requires": True,
            "packages": packages,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _acp_artifact(
    name: str,
    payload: bytes,
    *,
    dependency_paths: tuple[str, ...] = (),
    install_path: str | None = None,
    archive_measurement: bytes | None = None,
) -> AcpPackageArtifact:
    filename = name.rsplit("/", 1)[-1]
    if name == "peer-runtime":
        version = "2.1.0"
    elif name.endswith("claude-agent-acp"):
        version = "0.59.0"
    else:
        version = "0.3.207"
    measured = payload if archive_measurement is None else archive_measurement
    return AcpPackageArtifact(
        name=name,
        version=version,
        install_path=install_path or f"node_modules/{name}",
        url=f"https://registry.npmjs.org/{name}/-/{filename}-{version}.tgz",
        integrity=_integrity(payload),
        sha256=_sha256(measured),
        size=len(measured),
        license_expression="MIT",
        license_members=("package/LICENSE",),
        redistribution_evidence=("tarball-license:LICENSE",),
        dependency_paths=dependency_paths,
    )


def _acp_inventory(
    target: TargetTriple,
    lock_bytes: bytes,
    *,
    peer_path: str = "node_modules/peer-runtime",
) -> AcpClosureInventory:
    os_name, cpu = _NPM_TARGET[target]
    native = f"@anthropic-ai/claude-agent-sdk-{os_name}-{cpu}"
    packages = (
        _acp_artifact(
            "@agentclientprotocol/claude-agent-acp",
            b"acp-root",
            dependency_paths=("node_modules/@anthropic-ai/claude-agent-sdk",),
        ),
        _acp_artifact(
            "@anthropic-ai/claude-agent-sdk",
            b"generic-sdk",
            dependency_paths=tuple(sorted((f"node_modules/{native}", peer_path))),
        ),
        _acp_artifact(native, native.encode()),
        _acp_artifact("peer-runtime", b"peer-runtime", install_path=peer_path),
    )
    return AcpClosureInventory(
        inventory_version="vaultspec-acp-tarballs-v1",
        target=target,
        lock_sha256=_sha256(lock_bytes),
        packages=tuple(sorted(packages, key=lambda item: item.install_path)),
    )


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_acp_lock_reconciliation_selects_one_native_sdk_and_required_peer(
    target: TargetTriple,
) -> None:
    lock_bytes = _npm_package_lock()

    reconcile_acp_closure_lock_bytes(
        _acp_inventory(target, lock_bytes),
        lock_bytes=lock_bytes,
        root_package="@agentclientprotocol/claude-agent-acp",
        node_full_version=_NODE_VERSION,
    )


def test_acp_lock_reconciliation_rejects_graph_disagreement() -> None:
    lock_bytes = _npm_package_lock()
    inventory = _acp_inventory(TargetTriple.LINUX_X86_64, lock_bytes)
    native = "@anthropic-ai/claude-agent-sdk-linux-x64"
    replacements = {
        "@agentclientprotocol/claude-agent-acp": _acp_artifact(
            "@agentclientprotocol/claude-agent-acp",
            b"acp-root",
            dependency_paths=tuple(
                sorted(
                    (
                        "node_modules/@anthropic-ai/claude-agent-sdk",
                        "node_modules/peer-runtime",
                    )
                )
            ),
        ),
        "@anthropic-ai/claude-agent-sdk": _acp_artifact(
            "@anthropic-ai/claude-agent-sdk",
            b"generic-sdk",
            dependency_paths=(f"node_modules/{native}",),
        ),
    }
    packages = tuple(
        replacements.get(package.name, package) for package in inventory.packages
    )
    inventory = AcpClosureInventory(
        inventory_version=inventory.inventory_version,
        target=inventory.target,
        lock_sha256=inventory.lock_sha256,
        packages=packages,
    )

    with pytest.raises(LockReconciliationError, match="dependency graph differs"):
        reconcile_acp_closure_lock_bytes(
            inventory,
            lock_bytes=lock_bytes,
            root_package="@agentclientprotocol/claude-agent-acp",
            node_full_version=_NODE_VERSION,
        )


def test_acp_lock_reconciliation_rejects_unsatisfied_dependency_range() -> None:
    document = json.loads(_npm_package_lock())
    document["packages"]["node_modules/@anthropic-ai/claude-agent-sdk"][
        "peerDependencies"
    ]["peer-runtime"] = ">=999"
    lock_bytes = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    inventory = _acp_inventory(TargetTriple.WINDOWS_X86_64, lock_bytes)

    with pytest.raises(LockReconciliationError, match="does not satisfy"):
        reconcile_acp_closure_lock_bytes(
            inventory,
            lock_bytes=lock_bytes,
            root_package="@agentclientprotocol/claude-agent-acp",
            node_full_version=_NODE_VERSION,
        )


def test_acp_lock_reconciliation_rejects_incompatible_node_engine() -> None:
    document = json.loads(_npm_package_lock())
    document["packages"]["node_modules/@agentclientprotocol/claude-agent-acp"][
        "engines"
    ] = {"node": ">=99"}
    lock_bytes = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    inventory = _acp_inventory(TargetTriple.WINDOWS_X86_64, lock_bytes)

    with pytest.raises(LockReconciliationError, match="incompatible Node"):
        reconcile_acp_closure_lock_bytes(
            inventory,
            lock_bytes=lock_bytes,
            root_package="@agentclientprotocol/claude-agent-acp",
            node_full_version=_NODE_VERSION,
        )


@pytest.mark.parametrize("prerelease_in", ("version", "specifier"))
def test_acp_lock_reconciliation_rejects_unsupported_prerelease_semver(
    prerelease_in: str,
) -> None:
    document = json.loads(_npm_package_lock())
    if prerelease_in == "version":
        document["packages"]["node_modules/peer-runtime"]["version"] = "2.1.0-beta.1"
        document["packages"]["node_modules/@anthropic-ai/claude-agent-sdk"][
            "peerDependencies"
        ]["peer-runtime"] = "*"
    else:
        document["packages"]["node_modules/@anthropic-ai/claude-agent-sdk"][
            "peerDependencies"
        ]["peer-runtime"] = ">=2.0.0-beta.1"
    lock_bytes = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    inventory = _acp_inventory(TargetTriple.WINDOWS_X86_64, lock_bytes)

    with pytest.raises(LockReconciliationError, match="unsupported npm prerelease"):
        reconcile_acp_closure_lock_bytes(
            inventory,
            lock_bytes=lock_bytes,
            root_package="@agentclientprotocol/claude-agent-acp",
            node_full_version=_NODE_VERSION,
        )


def test_acp_lock_reconciliation_rejects_musl_node_for_gnu_target() -> None:
    document = json.loads(_npm_package_lock())
    document["packages"]["node_modules/@anthropic-ai/claude-agent-sdk-linux-x64"][
        "libc"
    ] = ["musl"]
    lock_bytes = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    inventory = _acp_inventory(TargetTriple.LINUX_X86_64, lock_bytes)

    with pytest.raises(LockReconciliationError, match="omits reachable packages"):
        reconcile_acp_closure_lock_bytes(
            inventory,
            lock_bytes=lock_bytes,
            root_package="@agentclientprotocol/claude-agent-acp",
            node_full_version=_NODE_VERSION,
        )


def test_acp_lock_leaves_sha256_and_size_to_real_tarball_verification() -> None:
    lock_bytes = _npm_package_lock()
    inventory = _acp_inventory(TargetTriple.WINDOWS_X86_64, lock_bytes)
    changed_root = _acp_artifact(
        "@agentclientprotocol/claude-agent-acp",
        b"acp-root",
        dependency_paths=("node_modules/@anthropic-ai/claude-agent-sdk",),
        archive_measurement=b"different-real-tarball-measurement",
    )
    packages = tuple(
        changed_root
        if package.name == "@agentclientprotocol/claude-agent-acp"
        else package
        for package in inventory.packages
    )
    inventory = AcpClosureInventory(
        inventory_version=inventory.inventory_version,
        target=inventory.target,
        lock_sha256=inventory.lock_sha256,
        packages=packages,
    )

    reconcile_acp_closure_lock_bytes(
        inventory,
        lock_bytes=lock_bytes,
        root_package="@agentclientprotocol/claude-agent-acp",
        node_full_version=_NODE_VERSION,
    )


def test_acp_lock_reconciliation_preserves_nested_install_identity() -> None:
    lock_bytes = _npm_package_lock(target_native_nested=True)
    peer_path = "node_modules/@anthropic-ai/claude-agent-sdk/node_modules/peer-runtime"
    inventory = _acp_inventory(
        TargetTriple.MACOS_ARM64, lock_bytes, peer_path=peer_path
    )

    reconcile_acp_closure_lock_bytes(
        inventory,
        lock_bytes=lock_bytes,
        root_package="@agentclientprotocol/claude-agent-acp",
        node_full_version=_NODE_VERSION,
    )


def _committed_uv_lock() -> bytes:
    return (_REPO_ROOT / "uv.lock").read_bytes()


def _committed_package_lock() -> bytes:
    return (_REPO_ROOT / "package-lock.json").read_bytes()


def _committed_python_selection(target: TargetTriple) -> PythonClosureSelection:
    return resolve_python_closure_selection(
        lock_bytes=_committed_uv_lock(),
        target=target,
        root_package="vaultspec-a2a",
        python_full_version=_PYTHON_RUNTIME,
    )


def _committed_acp_selection(target: TargetTriple) -> AcpClosureSelection:
    return resolve_acp_closure_selection(
        lock_bytes=_committed_package_lock(),
        target=target,
        root_package=_ACP_ROOT,
        node_full_version=_NODE_VERSION,
    )


def _declared_runtime_requirements() -> tuple[str, ...]:
    """Read the project's own declared runtime dependencies from pyproject."""
    document = tomllib.loads(
        (_REPO_ROOT / "pyproject.toml").read_bytes().decode("utf-8")
    )
    return tuple(
        sorted(
            canonicalize_name(Requirement(entry).name)
            for entry in document["project"]["dependencies"]
        )
    )


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_committed_uv_lock_resolves_one_exact_closure_per_target(
    target: TargetTriple,
) -> None:
    selection = _committed_python_selection(target)

    assert selection.target is target
    assert len(selection.packages) == _COMMITTED_PYTHON_CLOSURE[target]
    names = tuple(package.name for package in selection.packages)
    assert names == tuple(sorted(names))
    assert len(set(names)) == len(names)
    assert "vaultspec-a2a" not in names
    assert not {"torch", "vaultspec-rag"}.intersection(names)


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_committed_closure_roots_are_the_declared_runtime_requirements(
    target: TargetTriple,
) -> None:
    selection = _committed_python_selection(target)

    assert selection.roots == _declared_runtime_requirements()
    assert set(selection.roots).issubset(package.name for package in selection.packages)


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_committed_closure_graph_reaches_every_selected_package(
    target: TargetTriple,
) -> None:
    selection = _committed_python_selection(target)
    by_name = selection.by_name()

    reached: set[str] = set()
    pending = list(selection.roots)
    while pending:
        name = pending.pop()
        if name in reached:
            continue
        reached.add(name)
        pending.extend(by_name[name].dependencies)

    assert reached == set(by_name)


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_committed_closure_binds_a_target_compatible_wheel_per_package(
    target: TargetTriple,
) -> None:
    selection = _committed_python_selection(target)

    without_wheel = {
        package.name for package in selection.packages if not package.compatible_wheels
    }

    assert without_wheel == _KNOWN_WHEEL_GAP.get(target, set())


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_committed_closure_compatible_wheels_exclude_foreign_platforms(
    target: TargetTriple,
) -> None:
    # Compound platform tags legitimately name several architectures in one
    # filename, so only the operating-system families are asserted here.
    foreign = {
        TargetTriple.MACOS_ARM64: ("manylinux", "musllinux", "win_amd64"),
        TargetTriple.MACOS_X86_64: ("manylinux", "musllinux", "win_amd64"),
        TargetTriple.LINUX_ARM64: ("macosx", "musllinux", "win_amd64"),
        TargetTriple.LINUX_X86_64: ("macosx", "musllinux", "win_amd64"),
        TargetTriple.WINDOWS_X86_64: ("macosx", "manylinux", "musllinux"),
    }[target]
    selection = _committed_python_selection(target)

    for package in selection.packages:
        assert set(package.compatible_wheels).issubset(package.wheels)
        for wheel in package.compatible_wheels:
            assert not any(token in wheel.filename for token in foreign), (
                f"{package.name} selected {wheel.filename} for {target.value}"
            )


def test_committed_uv_lock_selection_is_deterministic() -> None:
    first = _committed_python_selection(TargetTriple.LINUX_X86_64)
    second = _committed_python_selection(TargetTriple.LINUX_X86_64)

    assert first == second


def test_windows_closure_adds_exactly_the_windows_marked_packages() -> None:
    linux = _committed_python_selection(TargetTriple.LINUX_X86_64)
    windows = _committed_python_selection(TargetTriple.WINDOWS_X86_64)

    linux_names = {package.name for package in linux.packages}
    windows_names = {package.name for package in windows.packages}

    assert windows_names - linux_names == {"colorama", "pywin32"}
    assert not linux_names - windows_names


def test_python_selection_rejects_a_wheel_record_without_an_exact_pin() -> None:
    lock_bytes = _python_lock().replace(b'hash = "sha256:', b'hash = "md5:')

    with pytest.raises(LockReconciliationError, match="does not exactly pin"):
        resolve_python_closure_selection(
            lock_bytes=lock_bytes,
            target=TargetTriple.LINUX_X86_64,
            root_package="vaultspec-a2a",
            python_full_version=_PYTHON_RUNTIME,
        )


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_committed_package_lock_resolves_one_exact_closure_per_target(
    target: TargetTriple,
) -> None:
    selection = _committed_acp_selection(target)

    assert selection.target is target
    assert selection.root_path == f"node_modules/{_ACP_ROOT}"
    assert len(selection.packages) == _COMMITTED_ACP_CLOSURE
    paths = tuple(package.install_path for package in selection.packages)
    assert paths == tuple(sorted(paths))
    assert selection.root_path in paths


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_committed_acp_closure_selects_exactly_one_native_sdk(
    target: TargetTriple,
) -> None:
    selection = _committed_acp_selection(target)

    natives = tuple(
        package.name
        for package in selection.packages
        if package.name.startswith("@anthropic-ai/claude-agent-sdk-")
    )

    assert natives == (f"@anthropic-ai/claude-agent-sdk-{_TARGET_SDK_SUFFIX[target]}",)


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_committed_acp_closure_binds_every_tarball_identity(
    target: TargetTriple,
) -> None:
    selection = _committed_acp_selection(target)
    by_path = selection.by_install_path()

    for package in selection.packages:
        assert package.url.startswith("https://")
        assert package.integrity.startswith("sha512-")
        assert package.install_path.endswith(f"node_modules/{package.name}")
        assert set(package.dependency_paths).issubset(by_path)


def test_acp_lock_reconciliation_rejects_duplicate_json_keys() -> None:
    lock_bytes = b'{"lockfileVersion":3,"lockfileVersion":3}'
    inventory = _acp_inventory(TargetTriple.WINDOWS_X86_64, _npm_package_lock())
    inventory = AcpClosureInventory(
        inventory_version=inventory.inventory_version,
        target=inventory.target,
        lock_sha256=_sha256(lock_bytes),
        packages=inventory.packages,
    )

    with pytest.raises(LockReconciliationError, match="repeats JSON key"):
        reconcile_acp_closure_lock_bytes(
            inventory,
            lock_bytes=lock_bytes,
            root_package="@agentclientprotocol/claude-agent-acp",
            node_full_version=_NODE_VERSION,
        )
