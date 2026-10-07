"""Provision verified Docker CLI plugins for rootless integration fixtures."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dev.download import download_verified
from dev.exit_codes import OK
from dev.process import run_captured
from dev.runner import run

__all__ = ["main"]

#: Each plugin's release path under ``github.com`` and its pinned SHA-256.
_PLUGINS = {
    "docker-compose": (
        "docker/compose/releases/download/v5.6.0/docker-compose-linux-x86_64",
        "40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a",
    ),
    "docker-buildx": (
        "docker/buildx/releases/download/v0.37.2/buildx-v0.37.2.linux-amd64",
        "982ca20490b45ed1ec8d99795974d3d874a358f75938c9c237305010e6b7e548",
    ),
}


def main() -> None:
    """Require a rootless daemon and install plugins in this job's config home."""
    config = Path(os.environ["RUNNER_TEMP"]) / "a2a-docker"
    env = {"DOCKER_CONFIG": str(config)}
    result = run_captured(
        ["docker", "info", "--format", "{{json .SecurityOptions}}"],
        env=env,
        timeout=30,
        check=True,
    )
    if "name=rootless" not in json.loads(result.stdout):
        raise RuntimeError(
            "native integration fixtures require a rootless Docker daemon"
        )
    plugins = config / "cli-plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    for name, (path, digest) in _PLUGINS.items():
        target = plugins / name
        target.write_bytes(download_verified(path, digest, timeout=60))
        target.chmod(0o755)
    for plugin in ("compose", "buildx"):
        if run(["docker", plugin, "version"], env, timeout=30) != OK:
            raise RuntimeError(f"the installed docker {plugin} plugin did not run")
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as output:
        output.write(f"DOCKER_CONFIG={config}\n")


if __name__ == "__main__":
    main()
