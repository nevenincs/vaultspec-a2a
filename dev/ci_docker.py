"""Provision the verified Docker Compose plugin for rootless integration fixtures."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dev.download import download_verified
from dev.exit_codes import OK
from dev.process import run_captured
from dev.runner import run

__all__ = ["main"]

#: The compose plugin's release path under ``github.com`` and its pinned SHA-256.
_COMPOSE_PLUGIN = (
    "docker/compose/releases/download/v5.6.0/docker-compose-linux-x86_64",
    "40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a",
)


def main() -> None:
    """Require a rootless daemon and install the compose plugin in this job's home."""
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
    path, digest = _COMPOSE_PLUGIN
    target = plugins / "docker-compose"
    target.write_bytes(download_verified(path, digest, timeout=60))
    target.chmod(0o755)
    if run(["docker", "compose", "version"], env, timeout=30) != OK:
        raise RuntimeError("the installed docker compose plugin did not run")
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as output:
        output.write(f"DOCKER_CONFIG={config}\n")


if __name__ == "__main__":
    main()
