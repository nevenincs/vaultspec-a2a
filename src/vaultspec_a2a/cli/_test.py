"""test group: unit, smoke, benchmark."""

from __future__ import annotations


__all__ = ["test"]

import subprocess
import sys

from pathlib import Path

import click


def _pytest_env() -> dict[str, str]:
    """Build a repo-local pytest environment to avoid temp-dir permission drift."""
    import os  # noqa: PLC0415

    base_dir = Path.home() / ".codex" / "memories" / "vaultspec-pytest"
    tmp_root = base_dir / "tmp"
    cache_dir = base_dir / "cache"
    tmp_root.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    tmp_value = str(tmp_root.resolve())
    env["TMP"] = tmp_value
    env["TEMP"] = tmp_value
    env["TMPDIR"] = tmp_value
    env["PYTEST_DEBUG_TEMPROOT"] = tmp_value
    env["LANGSMITH_TRACING"] = "false"
    env["OTEL_SDK_DISABLED"] = "true"
    env["PYTEST_ADDOPTS"] = (
        f"{env.get('PYTEST_ADDOPTS', '').strip()} "
        f"-o cache_dir={cache_dir.resolve()} --basetemp={tmp_root.resolve()}"
    ).strip()
    return env


@click.group(invoke_without_command=True)
@click.pass_context
def test(ctx: click.Context) -> None:
    """Run tests and benchmarks."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(unit)


@test.command()
@click.argument("path", default="all")
@click.argument("extra", nargs=-1, type=click.UNPROCESSED)
def unit(path: str, extra: tuple[str, ...]) -> None:
    """Run unit tests (default). PATH: all | marker | file path.

    Extra arguments after -- are forwarded to pytest.
    """
    cmd: list[str] = [sys.executable, "-m", "pytest"]

    if path == "all":
        pass
    elif "/" in path or "\\" in path or path.endswith(".py"):
        cmd.append(path)
    else:
        cmd += [
            "--override-ini=addopts=--durations=10 --showlocals -ra --capture=sys",
            "-m",
            path,
        ]

    cmd.extend(extra)
    sys.exit(subprocess.run(cmd, check=False, env=_pytest_env()).returncode)


@test.command()
def smoke() -> None:
    """Run smoke tests (pytest -m smoke)."""
    cmd = [sys.executable, "-m", "pytest", "-m", "smoke"]
    sys.exit(subprocess.run(cmd, check=False, env=_pytest_env()).returncode)


@test.command()
@click.argument(
    "suite",
    required=False,
    default=None,
    type=click.Choice(["smoke", "nightly"], case_sensitive=False),
)
def benchmark(suite: str | None) -> None:
    """Run evaluation benchmarks. SUITE: smoke | nightly (bare = run all)."""
    suites = [suite] if suite else ["smoke", "nightly"]
    for s in suites:
        cmd = [
            sys.executable,
            "-m",
            f"vaultspec_a2a.tests.evals.suites.{s}",
        ]
        returncode = subprocess.run(cmd, check=False).returncode
        if returncode != 0:
            sys.exit(returncode)
