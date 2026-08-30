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

#: Characters that disqualify a path segment as a portable install-path
#: component. The space is the one that actually bit us; the rest are the
#: Windows-reserved set, included because a tree that installs on Linux and not
#: on Windows is the same class of defect found later.
_UNPORTABLE_CHARS = frozenset(' \t\n\r<>:"|?*\\')


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


def flatten_links(root: Path) -> int:
    """Replace every symlink in the frozen tree with the bytes it points at.

    The consumer unpacks this tree into an immutable generation directory and
    REFUSES any non-regular entry - symlink, reparse object or device - because
    an immutable tree whose contents can be redirected after verification is not
    immutable. That refusal happens at install time on a user's machine, so a
    tree that breaks it must never be published.

    PyInstaller reproduces the versioned shared-library symlink farms its
    dependencies ship: scipy's OpenBLAS, libgfortran and libquadmath arrive as
    chains of `.so.5.0.0` links. Nothing in this repository asks for them, and a
    dependency bump can introduce more, so the tree is flattened here rather than
    audited by hand.

    A link is only flattened when it resolves to a regular file INSIDE the tree.
    One that escapes, or dangles, is a build fault and fails loudly.
    """
    resolved_root = root.resolve()
    links = [path for path in sorted(root.rglob("*")) if path.is_symlink()]
    for path in links:
        if path.is_dir():
            raise SystemExit(f"symlinked directory in the frozen tree: {path}")
        target = path.resolve()
        if not target.is_file():
            raise SystemExit(f"dangling link in the frozen tree: {path}")
        try:
            target.relative_to(resolved_root)
        except ValueError:
            raise SystemExit(
                f"link escapes the frozen tree: {path} -> {target}"
            ) from None
        payload = target.read_bytes()
        mode = target.stat().st_mode
        path.unlink()
        path.write_bytes(payload)
        path.chmod(mode)
    if links:
        print(f"flattened {len(links)} link(s) into regular files", flush=True)
    return len(links)


def assert_portable_paths(root: Path) -> None:
    """Refuse a frozen tree carrying a name the consumer cannot install.

    Same contract as :func:`flatten_links`, and here for the same reason: the
    dashboard composes this tree into a product generation and validates every
    path against a PORTABLE install-path rule. A name that breaks it is not a
    cosmetic problem - the composed tree is refused outright:

        vaultspec-product-build: composed file name is not a portable install
        path: invalid composed tree: unsafe portable path segment
        "Lorem ipsum.txt"

    That is a real failure, not a hypothetical one. It took out all four Compose
    legs of vaultspec-dashboard v0.1.7, and the diagnosis surfaced two repos
    away from its cause - `setuptools` vendors `jaraco.text`, whose sample data
    file carries a space, and PyInstaller was bundling setuptools.

    So the check belongs HERE, where the tree is produced, rather than in the
    consumer that happens to notice. A dependency bump can vendor another such
    file at any time, and the next one should fail this build with its own name
    in the message instead of a downstream compose step.
    """
    offenders = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if any(_is_unportable(part) for part in path.relative_to(root).parts)
    )
    if offenders:
        listed = "\n  ".join(offenders[:20])
        more = f"\n  ... and {len(offenders) - 20} more" if len(offenders) > 20 else ""
        raise SystemExit(
            f"{len(offenders)} path(s) in the frozen tree are not portable "
            f"install paths:\n  {listed}{more}\n"
            "Exclude the package that ships them in "
            "packaging/pyinstaller/vaultspec-a2a.spec rather than renaming "
            "vendored files, which the next resolve would undo."
        )


def _is_unportable(segment: str) -> bool:
    """Whether one path segment would be refused as an install-path component.

    Deliberately narrow. This mirrors the consumer's rule rather than inventing
    a stricter one: a check that refuses trees the dashboard would happily
    install is a check someone eventually disables.
    """
    if segment in (".", ".."):
        return False
    return bool(set(segment) & _UNPORTABLE_CHARS) or segment != segment.strip()


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
    # Before the smoke gate: a tree the consumer would refuse is not worth
    # proving the dispatch surface of.
    flatten_links(binary.parent)
    assert_portable_paths(binary.parent)
    smoke(binary)


if __name__ == "__main__":
    main()
