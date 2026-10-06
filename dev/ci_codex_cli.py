"""Provision the proven Codex CLI for hosted binary-identity tests."""

from __future__ import annotations

import os
from pathlib import Path

from vaultspec_a2a.graph.enums import Provider
from vaultspec_a2a.providers.lane_admission import PROVEN_TURN_LANES

from .runner import run


def main() -> None:
    """Install the declared proof version and expose it to subsequent CI steps."""
    github_path = Path(os.environ["GITHUB_PATH"])
    prefix = Path(os.environ["RUNNER_TEMP"]) / "a2a-codex-cli"
    version = PROVEN_TURN_LANES[Provider.CODEX].proved_version
    result = run(
        [
            "npm",
            "install",
            "--prefix",
            str(prefix),
            "--save-exact",
            "--ignore-scripts",
            "--no-fund",
            f"@openai/codex@{version}",
        ]
    )
    if result:
        raise SystemExit(result)
    binary_dir = prefix / "node_modules" / ".bin"
    with github_path.open("a", encoding="utf-8") as output:
        output.write(f"{binary_dir}\n")


if __name__ == "__main__":
    main()
