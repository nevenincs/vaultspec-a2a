"""Fail validation when the read-only Core annotation check reports findings."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA = "vaultspec.vault.check.annotations.v2"


def _diagnostic_total(stdout: str) -> int:
    """Read the finding count from Core's annotation-check JSON envelope."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Core did not emit valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("Core emitted an unexpected annotation-check schema")
    envelope = cast("dict[str, object]", payload)
    if envelope.get("schema") != _SCHEMA:
        raise ValueError("Core emitted an unexpected annotation-check schema")
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise ValueError("Core JSON has no annotation-check data")
    diagnostics = cast("dict[str, object]", data).get("diagnostics")
    if not isinstance(diagnostics, dict):
        raise ValueError("Core JSON has no annotation diagnostics")
    total = cast("dict[str, object]", diagnostics).get("total")
    if type(total) is not int or total < 0:  # bool is an int subclass.
        raise ValueError("Core JSON has no valid annotation diagnostic total")
    return total


def main(argv: Sequence[str] | None = None) -> int:
    """Run Core's read-only check and gate on its actual diagnostics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, help="Core workspace to inspect")
    args = parser.parse_args(argv)

    command = [
        sys.executable,
        "-m",
        "vaultspec_core",
        "vault",
        "check",
        "annotations",
        "--json",
    ]
    if args.target is not None:
        command.extend(("--target", str(args.target)))

    completed = subprocess.run(
        command,
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    if completed.returncode:
        return completed.returncode

    try:
        total = _diagnostic_total(completed.stdout)
    except ValueError as exc:
        print(
            f"Vault annotation gate could not read Core output: {exc}",
            file=sys.stderr,
        )
        return 1
    if total:
        print(
            f"Vault annotation gate: Core reported {total} finding(s).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
