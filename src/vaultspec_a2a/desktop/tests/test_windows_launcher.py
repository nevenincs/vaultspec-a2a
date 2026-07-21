"""Composition, determinism, and live execution of the Windows launchers.

The generated ``Scripts/{name}.exe`` product launchers are stub bytes plus a
fixed ASCII shebang plus a deterministic zipapp.  Everything that can be
proven from the pinned inputs alone is proven offline here; the tests that
need the real content-addressed console stub are marked ``service`` because
they acquire it from its declared download URL (the default suite runs with
``-m 'not service'``).  The stub is cached content-addressed between runs, in
the same cache layout the capsule builder uses.

The live-execution test runs a really composed launcher against a real
interpreter and asserts it reaches the intended entrypoint with the capsule's
library root pinned at the head of the import path.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Final
from urllib.request import urlopen

import pytest

from vaultspec_a2a.desktop import capsule_materializer
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
    WINDOWS_LAUNCHER_STUB_LICENSE_MEMBER,
    WINDOWS_LAUNCHER_STUB_LICENSE_SHA256,
    WINDOWS_LAUNCHER_STUB_MEMBER,
    WINDOWS_LAUNCHER_STUB_SHA256,
    CapsuleMaterializationError,
    extract_windows_launcher_stub,
    extract_windows_launcher_stub_license,
    materialize_capsule_closures,
)
from vaultspec_a2a.desktop.contract import (
    ApiVersionRange,
    ComponentEntrypoint,
    EntrypointKind,
    GatewayApiVersion,
    TargetTriple,
)
from vaultspec_a2a.desktop.tests._materializer_inputs import (
    open_real_materializer_session,
)

if TYPE_CHECKING:
    from vaultspec_a2a.desktop.capsule_evidence import ProjectedFile

_REPO_ROOT: Final = Path(__file__).resolve().parents[4]
_INPUTS_FILE: Final = _REPO_ROOT / "scripts" / "desktop_capsule_inputs.toml"
_STUB_CACHE: Final = _REPO_ROOT / "dist" / "capsules" / ".cache" / "launcher-stub"
_DOWNLOAD_TIMEOUT: Final = 300

_API_VERSIONS: Final = ApiVersionRange(
    minimum=GatewayApiVersion.V1, maximum=GatewayApiVersion.V1
)
_SOURCE_DATE_EPOCH: Final = 1_700_000_000
_EXPECTED_SHEBANG: Final = (
    b'#!"<launcher_dir>\\..\\runtime\\cpython\\python.exe" -I -B\n'
)

_PROBE_PACKAGE: Final = "vaultspec_a2a_launcher_probe"
_PROBE_SOURCE: Final = '''"""Real probe package materialized into a capsule root."""

import json
import os
import sys


def main() -> int:
    print(
        json.dumps(
            {
                "argv": sys.argv[1:],
                "path0": sys.path[0],
                "package": __file__,
                "capsule_root": os.environ["VAULTSPEC_A2A_CAPSULE_ROOT"],
                "sys_path": sys.path,
            }
        )
    )
    return 0
'''


def _declared_stub_input() -> dict[str, str]:
    """Return the ``[launcher_stub]`` declaration from the pinned inputs file."""
    document = tomllib.loads(_INPUTS_FILE.read_text(encoding="utf-8"))
    return document["launcher_stub"]


def _cached_donor_wheel() -> Path:
    """Return the content-addressed donor wheel, downloading it when absent."""
    declaration = _declared_stub_input()
    url = declaration["url"]
    expected = declaration["sha256"]
    _STUB_CACHE.mkdir(parents=True, exist_ok=True)
    cached = _STUB_CACHE / url.rsplit("/", 1)[-1]
    if not cached.is_file():
        with urlopen(url, timeout=_DOWNLOAD_TIMEOUT) as response:
            cached.write_bytes(response.read())
    actual = hashlib.sha256(cached.read_bytes()).hexdigest()
    assert actual == expected, f"donor wheel digest mismatch: {actual}"
    return cached


@pytest.fixture(scope="module")
def console_stub() -> bytes:
    """The real, digest-verified console stub extracted from its donor wheel."""
    with _cached_donor_wheel().open("rb") as handle:
        return extract_windows_launcher_stub(handle)


@pytest.fixture(scope="module")
def console_stub_license() -> bytes:
    """The real, digest-verified license notice extracted from the same donor."""
    with _cached_donor_wheel().open("rb") as handle:
        return extract_windows_launcher_stub_license(handle)


def _probe_entrypoint() -> ComponentEntrypoint:
    return ComponentEntrypoint(
        kind=EntrypointKind.GATEWAY,
        console_script="vaultspec-a2a-probe",
        reference=f"{_PROBE_PACKAGE}:main",
        relative_command=("Scripts", "vaultspec-a2a-probe.exe"),
    )


def _donor_archive(members: dict[str, bytes]) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Declared-input and fail-closed behavior (no stub required)
# ---------------------------------------------------------------------------


def test_the_declared_stub_input_matches_the_pinned_member() -> None:
    """The input-cache declaration and the composing code name one artifact."""
    declaration = _declared_stub_input()
    assert declaration["member"] == WINDOWS_LAUNCHER_STUB_MEMBER
    assert declaration["member_sha256"] == WINDOWS_LAUNCHER_STUB_SHA256
    assert declaration["license"] == "PSF-2.0"
    assert declaration["sha256"] != declaration["member_sha256"]
    assert declaration["url"].endswith(".whl")


def test_the_pinned_license_member_and_stub_member_share_no_digest() -> None:
    """The notice and the stub are distinct members of the same donor archive.

    No separate input-cache declaration exists for the notice (it ships from
    the already-declared ``[launcher_stub]`` donor), so this is the only
    static cross-check available offline: the two pinned digests must differ,
    since they name two different bytes ranges of the one donor wheel.
    """
    assert WINDOWS_LAUNCHER_STUB_LICENSE_MEMBER != WINDOWS_LAUNCHER_STUB_MEMBER
    assert WINDOWS_LAUNCHER_STUB_LICENSE_SHA256 != WINDOWS_LAUNCHER_STUB_SHA256


def test_extraction_refuses_a_donor_without_the_pinned_member() -> None:
    with (
        _donor_archive({"distlib/__init__.py": b"# donor module\n"}) as donor,
        pytest.raises(CapsuleMaterializationError, match="absent from its donor"),
    ):
        extract_windows_launcher_stub(donor)


def test_extraction_refuses_a_donor_member_that_is_not_the_pinned_stub() -> None:
    with (
        _donor_archive({WINDOWS_LAUNCHER_STUB_MEMBER: b"MZ not-the-stub"}) as donor,
        pytest.raises(CapsuleMaterializationError, match="pinned stub digest"),
    ):
        extract_windows_launcher_stub(donor)


def test_extraction_refuses_a_donor_that_is_not_an_archive() -> None:
    with (
        io.BytesIO(b"this is not a zip archive") as donor,
        pytest.raises(CapsuleMaterializationError, match="cannot open the Windows"),
    ):
        extract_windows_launcher_stub(donor)


def test_license_extraction_refuses_a_donor_without_the_pinned_member() -> None:
    with (
        _donor_archive({"distlib/__init__.py": b"# donor module\n"}) as donor,
        pytest.raises(CapsuleMaterializationError, match="absent from its donor"),
    ):
        extract_windows_launcher_stub_license(donor)


def test_license_extraction_refuses_a_donor_member_that_is_not_the_pinned_notice() -> (
    None
):
    with (
        _donor_archive(
            {WINDOWS_LAUNCHER_STUB_LICENSE_MEMBER: b"not the pinned notice"}
        ) as donor,
        pytest.raises(CapsuleMaterializationError, match="pinned notice digest"),
    ):
        extract_windows_launcher_stub_license(donor)


def test_license_extraction_refuses_a_donor_that_is_not_an_archive() -> None:
    with (
        io.BytesIO(b"this is not a zip archive") as donor,
        pytest.raises(CapsuleMaterializationError, match="cannot open the Windows"),
    ):
        extract_windows_launcher_stub_license(donor)


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("vaultspec_a2a.cli.main", "malformed"),
        (":main", "malformed"),
        ("vaultspec_a2a.cli.main:", "malformed"),
        ("vaultspec_a2a.cli main:main", "not directly importable"),
        ("vaultspec_a2a.cli.main:main()", "not directly importable"),
        ("vaultspec_a2a.clí.main:main", "not representable in a launcher"),
    ],
)
def test_launcher_composition_refuses_a_malformed_console_reference(
    reference: str, message: str
) -> None:
    """Both launcher generators embed the reference verbatim, so it is validated."""
    with pytest.raises(CapsuleMaterializationError, match=message):
        capsule_materializer._validated_console_reference(reference)


# ---------------------------------------------------------------------------
# Composition against the real content-addressed stub
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_the_composed_launcher_is_stub_plus_shebang_plus_deterministic_zipapp(
    console_stub: bytes,
) -> None:
    entrypoint = _probe_entrypoint()
    first = capsule_materializer._windows_launcher_bytes(entrypoint, console_stub)
    second = capsule_materializer._windows_launcher_bytes(entrypoint, console_stub)
    assert first == second

    assert first.startswith(console_stub)
    remainder = first[len(console_stub) :]
    assert remainder.startswith(_EXPECTED_SHEBANG)

    payload = remainder[len(_EXPECTED_SHEBANG) :]
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == ["__main__.py"]
        info = archive.getinfo("__main__.py")
        assert info.date_time == (1980, 1, 1, 0, 0, 0)
        assert info.create_system == 0
        assert info.compress_type == zipfile.ZIP_STORED
        source = archive.read("__main__.py").decode("ascii")
    assert 'sys.path.insert(0, os.path.join(_capsule_root, "runtime/python"))' in source
    assert f"from {_PROBE_PACKAGE} import main as _entrypoint" in source
    assert "for _ in range(3):" in source


@pytest.mark.service
def test_the_windows_capsule_materializes_the_launcher_pair_byte_exact(
    tmp_path: Path, console_stub: bytes, console_stub_license: bytes
) -> None:
    """A real Windows-target capsule writes both composed launchers, 0755."""
    generations: list[tuple[Path, dict[str, ProjectedFile]]] = []
    with open_real_materializer_session(
        tmp_path, target=TargetTriple.WINDOWS_X86_64
    ) as session:
        plan = derive_capsule_assembly_plan(session, api_versions=_API_VERSIONS)
        manifest = session.emit_component_manifest(api_versions=_API_VERSIONS)
        for name in ("gen-win-first", "gen-win-second"):
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
                    windows_launcher_stub=console_stub,
                    windows_launcher_stub_license=console_stub_license,
                )
            generations.append(
                (capsule.path, {file.relative_path: file for file in projected})
            )

    reserved = {
        file.path
        for file in plan.files
        if file.role
        in {
            PlanReservationRole.GATEWAY_LAUNCHER,
            PlanReservationRole.STANDALONE_MCP_LAUNCHER,
        }
    }
    assert reserved == {
        "Scripts/vaultspec-a2a.exe",
        "Scripts/vaultspec-a2a-mcp.exe",
    }

    (first_root, first), (_, second) = generations
    for entrypoint in (
        manifest.entrypoints.gateway,
        manifest.entrypoints.standalone_mcp,
    ):
        path = "/".join(entrypoint.relative_command)
        expected = capsule_materializer._windows_launcher_bytes(
            entrypoint, console_stub
        )
        assert first[path].mode == 0o755
        assert first[path].sha256 == hashlib.sha256(expected).hexdigest()
        assert first[path].size == len(expected)
        assert (first_root / path).read_bytes() == expected
        assert first[path] == second[path]

    # the donated launcher-stub license notice ships beside the launchers,
    # byte-exact and content-addressed to the real donor member
    notice_path = "Scripts/LICENSE-launcher-stub.txt"
    assert first[notice_path].mode == 0o644
    assert first[notice_path].sha256 == hashlib.sha256(console_stub_license).hexdigest()
    assert first[notice_path].size == len(console_stub_license)
    assert (first_root / notice_path).read_bytes() == console_stub_license
    assert first[notice_path] == second[notice_path]


@pytest.mark.service
def test_the_windows_capsule_refuses_to_materialize_without_the_license_notice(
    tmp_path: Path, console_stub: bytes
) -> None:
    """A Windows target reserves the notice, so materialization without it fails."""
    with open_real_materializer_session(
        tmp_path, target=TargetTriple.WINDOWS_X86_64
    ) as session:
        plan = derive_capsule_assembly_plan(session, api_versions=_API_VERSIONS)
        root = tmp_path / "gen-win-no-notice"
        root.mkdir()
        root_lease = resolve_directory_authority(root)
        with (
            directory_lease(root_lease) as generation,
            claim_new_directory(generation, "capsule") as capsule,
            pytest.raises(CapsuleMaterializationError, match="license bytes were not"),
        ):
            materialize_capsule_closures(
                plan,
                session,
                api_versions=_API_VERSIONS,
                destination_root=capsule.path,
                generation_authority=generation,
                destination_authority=capsule,
                source_date_epoch=_SOURCE_DATE_EPOCH,
                windows_launcher_stub=console_stub,
            )


# ---------------------------------------------------------------------------
# Live execution proof
# ---------------------------------------------------------------------------


def _build_probe_capsule(root: Path, launcher: bytes) -> Path:
    """Lay out a real capsule tree around one composed launcher."""
    package = root / "runtime" / "python" / _PROBE_PACKAGE
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(_PROBE_SOURCE, encoding="utf-8")
    scripts = root / "Scripts"
    scripts.mkdir()
    executable = scripts / "vaultspec-a2a-probe.exe"
    executable.write_bytes(launcher)
    (root / "runtime").mkdir(exist_ok=True)
    if sys.platform == "win32":
        link = root / "runtime" / "cpython"
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), sys.base_prefix],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert (link / "python.exe").is_file(), "standalone layout has no bin/ segment"
    return executable


@pytest.mark.service
def test_the_composed_launcher_reaches_its_entrypoint_when_really_executed(
    tmp_path: Path, console_stub: bytes
) -> None:
    """Execute a really composed launcher and prove where it lands.

    On Windows the executable is run directly, so the console stub itself
    parses the composed shebang, substitutes its own directory for the
    relocation token, and starts the interpreter addressed relative to the
    launcher — the whole mechanism end to end.  Elsewhere the same composed
    bytes are handed to a real interpreter directly with the same isolated
    flags the shebang carries, which exercises everything except the stub's
    own dispatch.  Both paths prove the appended zipapp pins the capsule
    library root and reaches the entrypoint.
    """
    # A capsule root containing a space: the composed shebang quotes the
    # interpreter, so an installation path with spaces must still resolve.
    root = tmp_path / "capsule root"
    root.mkdir()
    executable = _build_probe_capsule(
        root,
        capsule_materializer._windows_launcher_bytes(_probe_entrypoint(), console_stub),
    )

    poison = tmp_path / "ambient-site"
    poison.mkdir()
    (poison / f"{_PROBE_PACKAGE}.py").write_text(
        "raise AssertionError('ambient import path was honored')\n", encoding="utf-8"
    )

    command = (
        [str(executable)]
        if sys.platform == "win32"
        else [sys.executable, "-I", "-B", str(executable)]
    )
    result = subprocess.run(
        [*command, "alpha", "beta"],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(poison)},
    )
    assert result.returncode == 0, result.stdout + result.stderr

    report = json.loads(result.stdout)
    assert report["argv"] == ["alpha", "beta"]
    assert Path(report["path0"]) == root / "runtime" / "python"
    assert Path(report["capsule_root"]) == root
    assert Path(report["package"]).is_relative_to(root / "runtime" / "python")
    assert str(poison) not in report["sys_path"], "-I did not isolate the interpreter"
    assert not tuple((root / "runtime" / "python").rglob("__pycache__")), (
        "-B did not keep bytecode out of the capsule tree"
    )
