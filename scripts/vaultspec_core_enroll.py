"""Safely adopt tracked Vaultspec surfaces without forcing the live workspace."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

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


def _run(
    root: Path, *args: str, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=root,
        check=True,
        text=True,
        capture_output=capture,
    )


def _require_clean_owned_paths(root: Path) -> None:
    result = _run(
        root,
        "git",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        *_OWNED_PATHS,
        capture=True,
    )
    if result.stdout.strip():
        raise SystemExit(
            "Core-owned surfaces contain tracked or untracked changes; "
            "commit, remove, or reconcile them before enrollment:\n" + result.stdout
        )


def _tracked_files(root: Path) -> tuple[Path, ...]:
    result = _run(
        root,
        "git",
        "ls-files",
        "-z",
        "--",
        *_OWNED_PATHS,
        capture=True,
    )
    return tuple(Path(value) for value in result.stdout.split("\0") if value)


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
    _run(root, sys.executable, "-m", "vaultspec_core", *args)


def main() -> None:
    root = Path(
        _run(
            Path.cwd(), "git", "rev-parse", "--show-toplevel", capture=True
        ).stdout.strip()
    ).resolve()
    manifest = root / ".vaultspec/providers.json"

    if manifest.is_file():
        _core(root, "sync", "all")
        return

    _require_clean_owned_paths(root)
    with tempfile.TemporaryDirectory(prefix="vaultspec-core-adopt-") as temporary:
        staged = Path(temporary) / "workspace"
        _run(root, "git", "clone", "--quiet", "--no-hardlinks", str(root), str(staged))
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

    _core(root, "sync", "all")


if __name__ == "__main__":
    main()
