"""Expose the lock-vendored Claude CLI to hosted binary-identity tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

CLAUDE_CLI_VERSION = "2.1.207"


def main() -> None:
    """Put the installed platform binary on the next CI step's PATH."""
    github_path = Path(os.environ["GITHUB_PATH"])
    packages = Path(__file__).resolve().parents[1] / "node_modules" / "@anthropic-ai"
    candidates = sorted(
        binary
        for package in packages.glob("claude-agent-sdk-*")
        for name in ("claude", "claude.exe")
        if (binary := package / name).is_file()
    )
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one lock-vendored Claude CLI, found {len(candidates)}"
        )
    cli = candidates[0]
    result = subprocess.run(
        [str(cli), "--version"], check=True, capture_output=True, text=True
    )
    if result.stdout.strip().partition(" ")[0] != CLAUDE_CLI_VERSION:
        raise RuntimeError(
            f"the installed Claude CLI reported {result.stdout.strip()!r}, "
            f"expected {CLAUDE_CLI_VERSION}"
        )
    with github_path.open("a", encoding="utf-8") as output:
        output.write(f"{cli.parent}\n")


if __name__ == "__main__":
    main()
