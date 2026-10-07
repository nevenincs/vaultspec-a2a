"""Safely adopt tracked Vaultspec surfaces without forcing the live workspace.

Run through the harness::

    just vault-install

Vaultspec Core's own ``install`` rewrites every framework surface in place. In
a checkout those surfaces are tracked files that a reviewer has already
accepted, so this driver stages Core's projection into a throwaway clone,
proves byte-for-byte that the locked Core would not change anything tracked,
and only then seeds the untracked runtime state the workspace still needs.
Anything Core would change lands as a deliberate reconciliation commit instead
of an invisible enrollment side effect.
"""

from __future__ import annotations

__all__ = ["main"]

import argparse
import contextlib
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from dev import runner
from dev.paths import REPO_ROOT
from dev.process import run_captured

if TYPE_CHECKING:
    from collections.abc import Sequence

_OWNED_PATHS = (
    ".vaultspec",
    ".claude",
    ".gemini",
    ".agents",
    ".codex",
    ".mcp.json",
    "CLAUDE.md",
    "GEMINI.md",
    "AGENTS.md",
    ".gitattributes",
    ".gitignore",
    "prek.toml",
)
_RUNTIME_SEEDS = (
    ".vaultspec/providers.json",
    ".vaultspec/mcp-ownership.json",
)


def _capture(root: Path, *args: str) -> str:
    return run_captured(args, cwd=root, timeout=None, check=True).stdout


def _stream(root: Path, *args: str) -> None:
    code = runner.run(args, cwd=root)
    if code:
        raise SystemExit(code)


def _require_clean_owned_paths(root: Path) -> None:
    status = _capture(
        root,
        "git",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        *_OWNED_PATHS,
    )
    if status.strip():
        raise SystemExit(
            "Core-owned surfaces contain tracked or untracked changes; "
            "commit, remove, or reconcile them before enrollment:\n" + status
        )


def _tracked_files(root: Path) -> tuple[Path, ...]:
    listing = _capture(root, "git", "ls-files", "-z", "--", *_OWNED_PATHS)
    return tuple(Path(value) for value in listing.split("\0") if value)


def _assert_tracked_projection(root: Path, staged: Path) -> None:
    changed = [
        path.as_posix()
        for path in _tracked_files(root)
        if not (staged / path).is_file()
        or (root / path).read_bytes() != (staged / path).read_bytes()
    ]
    if changed:
        raise SystemExit(
            "Locked Core would change tracked framework surfaces. Review and land "
            "a deliberate framework reconciliation before enrollment:\n"
            + "\n".join(changed)
        )


def _seed_runtime_without_overwrite(root: Path, staged: Path) -> None:
    for relative in _RUNTIME_SEEDS:
        source = staged / relative
        if not source.is_file():
            continue
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb") as stream:
                stream.write(source.read_bytes())
        except FileExistsError:
            raise SystemExit(
                f"Refusing to overwrite concurrently created runtime state: {relative}"
            ) from None


def _core(root: Path, *args: str) -> None:
    # The harness never runs frozen, so Core is reached as a plain module of the
    # interpreter running this script - the locked tooling environment's own.
    _stream(root, sys.executable, "-m", "vaultspec_core", *args)


def main(argv: Sequence[str] | None = None) -> None:
    """Enroll this checkout, or the one ``--root`` names.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.
    """
    parser = argparse.ArgumentParser(
        prog="python -m dev.vault.enroll",
        description="Adopt tracked Vaultspec surfaces without forcing the workspace.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="the checkout to enroll (default: this repository)",
    )
    root: Path = parser.parse_args(argv).root.resolve()
    manifest = root / ".vaultspec/providers.json"

    if manifest.is_file():
        _core(root, "sync", "all")
        return

    _require_clean_owned_paths(root)
    # Staged inside the checkout's ignored .tmp-* space, never the system
    # temporary directory.
    scratch = root / ".tmp-enroll"
    scratch.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix="vaultspec-core-adopt-", dir=scratch
        ) as temporary:
            staged = Path(temporary) / "workspace"
            _stream(
                root,
                "git",
                "clone",
                "--quiet",
                "--no-hardlinks",
                str(root),
                str(staged),
            )
            _core(
                staged,
                "install",
                "all",
                "--mode",
                "dev",
                "--force",
                "--no-hints",
            )
            _assert_tracked_projection(root, staged)
            _seed_runtime_without_overwrite(root, staged)
    finally:
        # The root is removed once empty, so enrollment leaves no folder behind.
        with contextlib.suppress(OSError):
            scratch.rmdir()

    _core(root, "sync", "all")


if __name__ == "__main__":
    main()
