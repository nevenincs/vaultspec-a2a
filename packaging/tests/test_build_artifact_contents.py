"""The wheel and the frozen onedir must ship only what their build admits.

Two different pipelines produce these artifacts - Hatch for the wheel,
PyInstaller for the onedir - and both filter their content against the ONE
list this project declares: ``[tool.hatch.build.targets.wheel] exclude`` in
``pyproject.toml``. The onedir spec
(``packaging/pyinstaller/vaultspec-a2a.spec``) reads that exact list and says,
in its own words, that this is "so the two artifacts cannot disagree about
what is product code." A filter can still have a bug, though, and nothing
short of inspecting the real output proves it actually filtered - the static
import-boundary guard (``src/vaultspec_a2a/tests/test_wheel_import_boundary.py``)
proves a different thing (no import reaches an excluded package), not that
the excluded tree is absent from what gets shipped.

The wheel test below builds the real artifact with ``uv build`` and inspects
it; it runs unconditionally. The onedir test needs a real PyInstaller build,
which needs the ``freeze`` dependency group this checkout does not carry, so
it follows this directory's own established convention (see
``native_isolation_artifact.py``): a required environment variable, read with
no graceful skip, because this file is an explicit artifact check invoked
after a real build exists, not a test collected by the ordinary suite. The
scanning logic it depends on is proven directly against a synthetic tree by
the two tests between them, so the one gap in this checkout is "no PyInstaller
here today", not "this logic was never shown to fail".
"""

from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from typing import Final

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_PACKAGE: Final[str] = "vaultspec_a2a"

#: Path components that mean "test-execution machinery", wherever they sit.
#: The wheel's own exclude list names these same trees by path; this is the
#: same policy read off a built artifact's file list rather than off source.
_FORBIDDEN_COMPONENTS: Final[frozenset[str]] = frozenset(
    {"tests", "testing", "service_tests", "desktop_tests", "acceptance"}
)

#: Production data the wheel's exclude list carries a comment promising to
#: retain (see the ``[tool.hatch.build.targets.wheel]`` block). A build that
#: silently dropped one of these would pass every import-boundary check and
#: still ship a product that cannot run its migrations or load its presets.
_REQUIRED_SUBSTRINGS: Final[tuple[str, ...]] = (
    f"{_PACKAGE}/database/migrations/",
    f"{_PACKAGE}/team/presets/",
    f"{_PACKAGE}/context/presets/",
)


def _artifact_violations(paths: list[str]) -> list[str]:
    """Return every *path* (posix, package-rooted) that names a forbidden tier."""
    violations: list[str] = []
    for raw in paths:
        parts = PurePosixPath(raw).parts
        is_conftest = bool(parts) and parts[-1] == "conftest.py"
        if _FORBIDDEN_COMPONENTS & set(parts[:-1]) or is_conftest:
            violations.append(raw)
    return sorted(violations)


def test_the_artifact_scanner_flags_a_planted_test_tier_leak() -> None:
    """Prove the scanner the two real-artifact checks share can actually fail."""
    planted = [
        f"{_PACKAGE}/__init__.py",
        f"{_PACKAGE}/control/config.py",
        f"{_PACKAGE}/control/tests/test_config.py",
        f"{_PACKAGE}/conftest.py",
    ]
    assert _artifact_violations(planted) == [
        f"{_PACKAGE}/conftest.py",
        f"{_PACKAGE}/control/tests/test_config.py",
    ]


def test_the_artifact_scanner_passes_a_clean_file_list() -> None:
    clean = [f"{_PACKAGE}/__init__.py", f"{_PACKAGE}/control/config.py"]
    assert _artifact_violations(clean) == []


def test_the_built_wheel_excludes_every_test_tier_and_ships_required_data() -> None:
    """Build the real wheel with ``uv build`` and inspect its real file list."""
    scratch = _PROJECT_ROOT / ".tmp-wheel-contents"
    scratch.mkdir(exist_ok=True)
    try:
        completed = subprocess.run(
            [
                "uv",
                "build",
                "--build-constraints",
                "build-constraints.txt",
                "--wheel",
                "--out-dir",
                str(scratch),
            ],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        wheels = sorted(scratch.glob("*.whl"))
        assert len(wheels) == 1, f"expected exactly one built wheel, found {wheels}"
        with zipfile.ZipFile(wheels[0]) as archive:
            names = archive.namelist()
    finally:
        for artifact in scratch.iterdir():
            artifact.unlink()
        scratch.rmdir()

    assert len(names) > 100, (
        f"only {len(names)} entries in the built wheel - a broken build must "
        "not pass vacuously"
    )

    violations = _artifact_violations(names)
    assert not violations, (
        "the built wheel ships a test-tier path the build configuration "
        "should have excluded:\n  " + "\n  ".join(violations)
    )

    missing = [
        substring
        for substring in _REQUIRED_SUBSTRINGS
        if not any(substring in name for name in names)
    ]
    assert not missing, (
        f"the built wheel is missing required production data: {missing}"
    )


def test_the_frozen_onedir_excludes_every_test_tier() -> None:
    """The real artifact check. Requires a pre-built onedir; see module docstring.

    Built with::

        uv run --group freeze python scripts/build_binary.py --dist DIR

    then invoked with ``VAULTSPEC_A2A_TEST_FROZEN_RUNTIME_TREE=DIR``.
    """
    tree = Path(os.environ["VAULTSPEC_A2A_TEST_FROZEN_RUNTIME_TREE"])
    paths = [
        path.relative_to(tree).as_posix() for path in tree.rglob("*") if path.is_file()
    ]
    violations = _artifact_violations(paths)
    assert not violations, (
        "the frozen onedir ships a test-tier path the PyInstaller spec's own "
        "exclusion filter should have caught:\n  " + "\n  ".join(violations)
    )
