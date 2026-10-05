"""Build-time assembly of a declared, pinned native isolation dependency closure."""

from __future__ import annotations

import hashlib
import shutil
import stat
import subprocess
from typing import TYPE_CHECKING

from .native_isolation import LinuxRuntimeClosure, RuntimeFile, RuntimeMount

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def stage_linux_isolation_assets(
    capsule: Path, *, helper: Path, files: Mapping[str, Path]
) -> Path:
    """Copy explicitly selected build inputs into a new capsule generation.

    The producer supplies its resolved dependency closure. Runtime launch never
    discovers libraries or invokes an installer on the user's machine.
    """
    source_helper = helper.resolve(strict=True)
    with source_helper.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise ValueError("native helper build input must be ELF")
    version = subprocess.run(
        [str(source_helper), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
    if version != "bubblewrap 0.11.1":
        raise ValueError("native helper build input must be bubblewrap 0.11.1")
    destination = capsule.resolve(strict=True) / "isolation"
    destination.mkdir()

    def copy(source: Path, relative: str) -> RuntimeFile:
        resolved = source.resolve(strict=True)
        metadata = resolved.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError(
                "native runtime build inputs must be regular single-link files"
            )
        target = capsule / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(resolved, target)
        target.chmod(stat.S_IMODE(metadata.st_mode) & 0o777)
        return RuntimeFile(
            source=relative, sha256=hashlib.sha256(target.read_bytes()).hexdigest()
        )

    helper_record = copy(helper, "isolation/bin/bubblewrap")
    mounts: list[RuntimeMount] = []
    for index, (target, source) in enumerate(sorted(files.items())):
        record = copy(source, f"isolation/files/{index:04d}/{source.name}")
        mounts.append(
            RuntimeMount(source=record.source, sha256=record.sha256, target=target)
        )
    closure = LinuxRuntimeClosure(
        schema_version=1, helper_version="0.11.1", helper=helper_record, files=mounts
    )
    manifest = destination / "runtime.json"
    manifest.write_text(closure.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest
