"""Remove generated build artifacts within a repository boundary."""

from __future__ import annotations

import shutil
from pathlib import Path


def _remove_directory(root: Path, target: Path) -> None:
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if resolved_target == resolved_root or not resolved_target.is_relative_to(
        resolved_root
    ):
        raise ValueError(
            f"refusing to remove path outside repository: {resolved_target}"
        )
    if target.is_dir():
        shutil.rmtree(target)


def clean_build_artifacts(root: Path) -> tuple[Path, ...]:
    """Remove known generated directories and return their repository paths."""
    resolved_root = root.resolve()
    targets = {resolved_root / "dist", resolved_root / "docs" / "_build"}
    for relative in ("src", "tests", "docs"):
        scan_root = resolved_root / relative
        if not scan_root.is_dir():
            continue
        targets.update(path for path in scan_root.rglob("*.egg-info") if path.is_dir())
        targets.update(path for path in scan_root.rglob("__pycache__") if path.is_dir())

    removed: list[Path] = []
    for target in sorted(targets, key=lambda path: len(path.parts), reverse=True):
        if not target.exists():
            continue
        _remove_directory(resolved_root, target)
        removed.append(target.relative_to(resolved_root))
    return tuple(removed)


def main() -> None:
    root = Path.cwd()
    for path in clean_build_artifacts(root):
        print(f"removed {path.as_posix()}")


if __name__ == "__main__":
    main()
