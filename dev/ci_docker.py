"""Provision verified Docker CLI plugins for rootless integration fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

_PLUGINS = {
    "docker-compose": (
        "https://github.com/docker/compose/releases/download/"
        "v5.6.0/docker-compose-linux-x86_64",
        "40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a",
    ),
    "docker-buildx": (
        "https://github.com/docker/buildx/releases/download/"
        "v0.37.2/buildx-v0.37.2.linux-amd64",
        "982ca20490b45ed1ec8d99795974d3d874a358f75938c9c237305010e6b7e548",
    ),
}


def main() -> None:
    """Require a rootless daemon and install plugins in this job's config home."""
    config = Path(os.environ["RUNNER_TEMP"]) / "a2a-docker"
    env = {**os.environ, "DOCKER_CONFIG": str(config)}
    result = subprocess.run(
        ["docker", "info", "--format", "{{json .SecurityOptions}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    if "name=rootless" not in json.loads(result.stdout):
        raise RuntimeError(
            "native integration fixtures require a rootless Docker daemon"
        )
    plugins = config / "cli-plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in _PLUGINS.items():
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = response.read(128 * 1024 * 1024 + 1)
        if hashlib.sha256(payload).hexdigest() != digest:
            raise RuntimeError(f"{name} download did not match its pinned SHA256")
        target = plugins / name
        target.write_bytes(payload)
        target.chmod(0o755)
    for plugin in ("compose", "buildx"):
        subprocess.run(["docker", plugin, "version"], check=True, env=env, timeout=30)
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as output:
        output.write(f"DOCKER_CONFIG={config}\n")


if __name__ == "__main__":
    main()
