"""Run Vaultspec Core installation without replacing repository-owned hooks."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_HOOK_CONFIG = Path(".pre-commit-config.yaml")


def _restore_file(path: Path, content: bytes) -> None:
    """Atomically restore *path* to its exact pre-install contents."""
    handle, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main(arguments: list[str] | None = None) -> int:
    """Run the locked Core CLI and preserve the repository hook contract."""
    core_arguments = sys.argv[1:] if arguments is None else arguments
    hook_config = Path.cwd() / _HOOK_CONFIG
    hook_existed = hook_config.is_file()
    hook_content = hook_config.read_bytes() if hook_existed else None

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "vaultspec_core", *core_arguments],
            check=False,
        )
    finally:
        if hook_content is not None:
            _restore_file(hook_config, hook_content)
        elif not hook_existed:
            hook_config.unlink(missing_ok=True)

    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
