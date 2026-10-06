"""Test producer copies the genuine registry-selected MCP Python closure."""

from __future__ import annotations

import json
import os
import re
import runpy
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .._acp_mcp import resolve_harness_mcp_servers

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...desktop.native_isolation import NativeLaunchAuthority

stage_linux_isolation_assets = cast(
    "Callable[..., Path]",
    runpy.run_path(
        str(Path(__file__).resolve().parents[4] / "scripts/build_linux_isolation.py")
    )["stage_linux_isolation_assets"],
)


def install_mcp_runtime(authority: NativeLaunchAuthority) -> Path:
    """Resolve the real production spec only during test capsule assembly."""
    spec = resolve_harness_mcp_servers(["vaultspec-rag"])[0]
    command, raw_args = spec["command"], spec["args"]
    assert isinstance(command, str) and isinstance(raw_args, list)
    args = [value for value in raw_args if isinstance(value, str)]
    assert len(args) == len(raw_args)
    assert args[-2:] == ["vaultspec-search-mcp", "--read-only"]
    facts = subprocess.run(
        [
            command,
            *args[:-2],
            "python",
            "-c",
            "import sys,json,importlib.metadata; "
            "d=importlib.metadata.distribution('vaultspec-rag'); "
            "print(json.dumps({'base':sys.base_prefix,'executable':sys.executable,"
            "'site':str(d.locate_file('')),'version':str(sys.version_info.major)+'.'+"
            "str(sys.version_info.minor)}))",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=90,
    )
    metadata = json.loads(facts.stdout)
    runtime = authority.capsule.path / "python"
    shutil.copytree(
        Path(metadata["base"]) / "lib",
        runtime / "lib",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    site = runtime / "lib" / ("python" + metadata["version"]) / "site-packages"
    shutil.copytree(
        Path(metadata["site"]),
        site,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    executable = runtime / "bin" / "python"
    executable.parent.mkdir()
    shutil.copyfile(metadata["executable"], executable)
    executable.chmod(0o755)
    libraries: dict[str, Path] = {}
    for binary in [executable, *runtime.rglob("*.so"), *runtime.rglob("*.so.*")]:
        dependencies = subprocess.run(
            ["ldd", str(binary)],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
        for name in re.findall(r"(/[^\s()]+)", dependencies):
            target = Path(os.path.normpath(name))
            if target.is_relative_to(authority.capsule.path):
                # These copied libraries already belong to the read-only capsule.
                continue
            libraries[str(target)] = target
    stage_linux_isolation_assets(
        authority.capsule.path,
        helper=Path(os.environ["VAULTSPEC_A2A_TEST_LINUX_ISOLATION_HELPER"]),
        files=libraries,
    )
    return executable
