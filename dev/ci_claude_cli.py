"""Expose the lock-vendored Claude CLI to hosted binary-identity tests."""

from __future__ import annotations

import os
from pathlib import Path

from dev.paths import REPO_ROOT
from dev.process import run_captured

__all__ = ["CLAUDE_CLI_VERSION", "main"]

CLAUDE_CLI_VERSION = "2.1.286"


def main() -> None:
    """Put the installed platform binary on the next CI step's PATH."""
    github_path = Path(os.environ["GITHUB_PATH"])
    packages = REPO_ROOT / "node_modules" / "@anthropic-ai"
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
    result = run_captured([str(cli), "--version"], timeout=None, check=True)
    if result.stdout.strip().partition(" ")[0] != CLAUDE_CLI_VERSION:
        raise RuntimeError(
            f"the installed Claude CLI reported {result.stdout.strip()!r}, "
            f"expected {CLAUDE_CLI_VERSION}"
        )
    with github_path.open("a", encoding="utf-8") as output:
        output.write(f"{cli.parent}\n")


if __name__ == "__main__":
    main()
