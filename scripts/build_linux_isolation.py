"""Assemble the Linux onedir's pinned helper and explicitly selected ELF closure.

This runs only in the native build environment. The component consumer can pass
additional capsule executables; freezing A2A alone does not qualify Node or a
provider distribution that the consumer supplies separately.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from vaultspec_a2a.desktop._linux_runtime_assets import stage_linux_isolation_assets

_BWRAP_URL = (
    "https://codeload.github.com/containers/bubblewrap/tar.gz/refs/tags/v0.11.1"
)
_BWRAP_HASH = "fb6ebf0264dfe9fb88777d352deeedf5aecf2e36e78da148157036b647f86e0f"
_LIBCAP_URL = "https://www.kernel.org/pub/linux/libs/security/linux-privs/libcap2/libcap-2.75.tar.xz"
_LIBCAP_HASH = "de4e7e064c9ba451d5234dd46e897d7c71c96a9ebf9a0c445bc04f4742d83632"
_MAX_ARCHIVE_BYTES = 16 * 1024 * 1024


def _source(url: str, digest: str, path: Path) -> None:
    if not path.exists():
        with urllib.request.urlopen(url, timeout=45) as response:
            payload = response.read(_MAX_ARCHIVE_BYTES + 1)
        if len(payload) > _MAX_ARCHIVE_BYTES:
            raise ValueError("native build source exceeds its bound")
        path.write_bytes(payload)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f"native build source differs from its pinned digest: {path}")


def build_static_helper(work: Path) -> Path:
    """Build pinned upstream sources without installing host packages or files."""
    if sys.platform != "linux":
        raise ValueError("native static helper must be built on Linux")
    work.mkdir(parents=True, exist_ok=False)
    compiler = shutil.which("cc")
    make = shutil.which("make")
    if compiler is None or make is None:
        raise ValueError("native helper build requires the declared C/make toolchain")
    bubblewrap = work / "bubblewrap.tar.gz"
    libcap = work / "libcap.tar.xz"
    _source(_BWRAP_URL, _BWRAP_HASH, bubblewrap)
    _source(_LIBCAP_URL, _LIBCAP_HASH, libcap)
    for archive in (bubblewrap, libcap):
        with tarfile.open(archive) as source:
            source.extractall(work, filter="data")
    cap_source = work / "libcap-2.75"
    subprocess.run(
        [
            make,
            "-C",
            str(cap_source / "libcap"),
            "libcap.a",
            f"CC={compiler}",
            f"BUILD_CC={compiler}",
            "SHARED=no",
            "PTHREADS=no",
            "USE_GPERF=no",
        ],
        check=True,
        timeout=120,
    )
    bwrap_source = work / "bubblewrap-0.11.1"
    (bwrap_source / "config.h").write_text(
        '#define PACKAGE_STRING "bubblewrap 0.11.1"\n#define ENABLE_REQUIRE_USERNS 1\n',
        encoding="utf-8",
    )
    helper = work / "bubblewrap"
    subprocess.run(
        [
            compiler,
            "-static",
            "-O2",
            "-D_GNU_SOURCE",
            "-I" + str(bwrap_source),
            "-I" + str(cap_source / "libcap/include"),
            *[
                str(bwrap_source / name)
                for name in ("bubblewrap.c", "bind-mount.c", "network.c", "utils.c")
            ],
            str(cap_source / "libcap/libcap.a"),
            "-o",
            str(helper),
        ],
        check=True,
        timeout=120,
    )
    return helper


def external_dependencies(runtime: Path, executables: list[Path]) -> dict[str, Path]:
    """Resolve trusted build ELFs; runtime receives only the staged manifest."""
    root = runtime.resolve(strict=True)
    inputs = sorted(path for path in root.rglob("*") if path.is_file())
    inputs.extend(path.resolve(strict=True) for path in executables)
    files: dict[str, Path] = {}
    for path in inputs:
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        result = subprocess.run(
            ["ldd", str(path)],
            capture_output=True,
            text=True,
            timeout=15,
            env={"PATH": os.defpath, "LANG": "C"},
        )
        report = result.stdout + result.stderr
        if "not found" in report:
            raise ValueError(f"native build ELF dependency is missing: {path}")
        if result.returncode != 0:
            if "not a dynamic executable" in report or "statically linked" in report:
                continue
            raise ValueError(f"native build ELF dependency inspection failed: {path}")
        for value in re.findall(r"(/[^\s()]+)", result.stdout):
            target = os.path.normpath(value)
            source = Path(target).resolve(strict=True)
            if source.is_relative_to(root):
                continue
            if target in files and files[target] != source:
                raise ValueError(
                    f"native build dependency target is ambiguous: {target}"
                )
            files[target] = source
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--executable", type=Path, action="append", default=[])
    args = parser.parse_args()
    runtime = args.runtime.resolve(strict=True)
    files = external_dependencies(runtime, args.executable)
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-build-", dir=work) as directory:
        sources = Path(directory) / "sources"
        helper = build_static_helper(sources)
        manifest = stage_linux_isolation_assets(runtime, helper=helper, files=files)
        licenses = manifest.parent / "licenses"
        licenses.mkdir()
        shutil.copyfile(
            sources / "bubblewrap-0.11.1/COPYING", licenses / "bubblewrap.txt"
        )
        shutil.copyfile(sources / "libcap-2.75/License", licenses / "libcap.txt")
    print(f"native isolation assets staged: {manifest}", flush=True)


if __name__ == "__main__":
    main()
