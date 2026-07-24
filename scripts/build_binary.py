"""Build and smoke-test the dashboard-bundled a2a runtime binary.

The single build entry the dashboard's release pipeline invokes per target:
it drives the versioned PyInstaller onedir spec and then smoke-tests the
produced binary's dispatch surface - version report, help, and the run-module
allowlist refusing an unlisted module loudly. The smoke gate proves the frozen
argv-dispatch paths are wired without booting any service; full behavioural
verification remains the test suites' job against the source tree.

Usage::

    uv run --group freeze python scripts/build_binary.py [--dist DIR]

Requires the ``freeze`` dependency group (PyInstaller plus vaultspec-core,
which the binary dispatches through its run-module verb and must therefore be
present in the build environment for collection).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SPEC = _PROJECT_ROOT / "packaging" / "pyinstaller" / "vaultspec-a2a.spec"
_BINARY_NAME = "vaultspec-a2a.exe" if sys.platform == "win32" else "vaultspec-a2a"


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    print(f"+ {' '.join(command)}", flush=True)
    return subprocess.run(
        command, text=True, cwd=cwd, capture_output=capture_output, check=False
    )


def build(dist_dir: Path) -> Path:
    """Drive the spec and return the built binary path, failing loudly."""
    result = _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist_dir),
            str(_SPEC),
        ],
        cwd=_PROJECT_ROOT,
    )
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller failed (exit {result.returncode})")
    binary = dist_dir / "vaultspec-a2a" / _BINARY_NAME
    if not binary.is_file():
        raise SystemExit(f"expected binary missing after build: {binary}")
    return binary


def smoke(binary: Path) -> None:
    """Prove the frozen dispatch surface without booting a service.

    Three probes: the version report (CLI boots inside the frozen closure),
    the help tree (every registered verb constructs), and the run-module
    allowlist refusing an unlisted module with a non-zero exit (the dispatch
    verb is wired and fails closed).
    """
    version = _run([str(binary), "--version"], capture_output=True)
    if version.returncode != 0:
        raise SystemExit(f"smoke: --version failed: {version.stderr}")
    help_probe = _run([str(binary), "--help"], capture_output=True)
    if help_probe.returncode != 0:
        raise SystemExit(f"smoke: --help failed: {help_probe.stderr}")
    refusal = _run(
        [str(binary), "run-module", "os"],
        capture_output=True,
    )
    if refusal.returncode == 0:
        raise SystemExit(
            "smoke: run-module accepted a module outside the allowlist; the "
            "dispatch surface is not failing closed"
        )
    if "not dispatchable" not in (refusal.stderr + refusal.stdout):
        raise SystemExit(
            "smoke: run-module refusal did not carry the allowlist diagnosis; "
            f"stderr was: {refusal.stderr!r}"
        )
    print(f"smoke OK: {binary}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist",
        type=Path,
        default=_PROJECT_ROOT / "dist" / "binary",
        help="Distribution output directory (default: dist/binary).",
    )
    args = parser.parse_args()
    binary = build(args.dist.resolve())
    smoke(binary)


if __name__ == "__main__":
    main()
