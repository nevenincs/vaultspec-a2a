"""Workspace provisioning.

One verb that turns a bare directory into a harness-ready run workspace: it wraps
``vaultspec-core install`` (scaffold + sync the ``.vaultspec`` corpus) and then
runs the harness verifier over the result, returning a single verdict. This
was previously done by hand; the acceptance harness and service
fixtures call it instead of hand-rolling the recipe.

Two honesty guarantees carry from the design constraints:

- **Version skew is surfaced, not hidden**: the vaultspec-core the environment
  pins (``importlib.metadata``) and the vaultspec-core the CLI resolves to on
  PATH can diverge (the uvx-divergence lesson). Provisioning reports the skew; it
  never silently proceeds as if they agree.
- **Harness completeness is verified, not assumed**: install can succeed and the
  harness still be incomplete (a required template or skill absent), so the
  returned verdict is the verifier's, not the installer's exit code.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from importlib import metadata
from typing import TYPE_CHECKING

from ..context.harness import verify_harness

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ..context.harness import HarnessReadiness

__all__ = ["ProvisionError", "ProvisionResult", "provision_workspace"]

# The vaultspec-core distribution/console-script name.
_CORE_DIST = "vaultspec-core"

# A short, bounded timeout for the read-only ``--version`` probe; install itself
# is unbounded (it scaffolds and syncs a corpus).
_VERSION_PROBE_TIMEOUT = 30.0


class ProvisionError(RuntimeError):
    """A provisioning step could not run (CLI absent, or install failed).

    Distinct from an incomplete harness: an incomplete harness is a normal,
    reportable verdict, while a ``ProvisionError`` means provisioning itself could
    not be attempted or the installer errored. The message is safe to surface.
    """


@dataclass(frozen=True, slots=True)
class ProvisionResult:
    """The outcome of provisioning one workspace.

    ``harness`` is the verifier's verdict over the provisioned tree - the source
    of truth for readiness, independent of the installer's exit code.
    ``version_skew`` is a safe human string when the pinned and resolved
    vaultspec-core versions diverge, else ``None``.
    """

    workspace_root: Path
    harness: HarnessReadiness
    installed: bool
    install_summary: str
    version_skew: str | None = None

    @property
    def ok(self) -> bool:
        """True when the provisioned workspace's harness is complete."""
        return self.harness.ready


def provision_workspace(
    workspace_root: Path,
    *,
    required_skills: Sequence[str] = (),
    install: bool = True,
) -> ProvisionResult:
    """Provision *workspace_root* into a harness-ready state and verify it.

    Runs ``vaultspec-core install --target <workspace_root>`` (unless
    ``install=False``, which verifies an already-provisioned tree), surfaces any
    pinned-vs-resolved vaultspec-core version skew, then returns the S01 harness
    verifier's verdict over the result. Raises :class:`ProvisionError` only when
    provisioning could not be attempted (CLI unresolvable) or the installer
    exited non-zero; an incomplete harness is a normal verdict, not a raise.
    """
    installed = False
    summary = "install skipped (verify-only)"
    if install:
        summary = _run_install(workspace_root)
        installed = True

    skew = _detect_version_skew()
    harness = verify_harness(workspace_root, required_skills=required_skills)
    return ProvisionResult(
        workspace_root=workspace_root,
        harness=harness,
        installed=installed,
        install_summary=summary,
        version_skew=skew,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _core_base_command() -> list[str]:
    """The argv prefix that runs vaultspec-core: the console script or the uvx shim.

    Mirrors the S01 verifier's resolution order (the console script on PATH, else
    the ``uvx --from vaultspec-core`` shim). Raises :class:`ProvisionError` when
    neither resolves so the caller reports a provisioning failure, not a crash.
    """
    if shutil.which(_CORE_DIST) is not None:
        return [_CORE_DIST]
    if shutil.which("uvx") is not None:
        return ["uvx", "--from", _CORE_DIST, _CORE_DIST]
    raise ProvisionError(
        "vaultspec-core CLI does not resolve in this environment; cannot provision"
    )


def _run_install(workspace_root: Path) -> str:
    """Run ``vaultspec-core install --target <workspace_root>`` and summarize it."""
    workspace_root.mkdir(parents=True, exist_ok=True)
    cmd = [*_core_base_command(), "install", "--target", str(workspace_root)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise ProvisionError(f"could not launch vaultspec-core install: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise ProvisionError(
            f"vaultspec-core install failed (exit {proc.returncode}): {detail}"
        )
    return _summarize(proc.stdout)


def _summarize(output: str) -> str:
    """Reduce installer stdout to its last non-empty line (a safe, terse summary)."""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    return lines[-1] if lines else "vaultspec-core install completed"


def _detect_version_skew() -> str | None:
    """Return a safe skew message when pinned and resolved versions diverge."""
    return _compute_skew(_pinned_version(), _resolved_version())


def _pinned_version() -> str | None:
    """The vaultspec-core version the current environment pins, or ``None``."""
    try:
        return metadata.version(_CORE_DIST)
    except metadata.PackageNotFoundError:
        return None


def _resolved_version() -> str | None:
    """The vaultspec-core version the resolved CLI reports, or ``None``."""
    try:
        cmd = [*_core_base_command(), "--version"]
    except ProvisionError:
        return None
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_VERSION_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return _parse_version(proc.stdout)


def _parse_version(output: str) -> str | None:
    """Extract a ``N.N.N`` semantic version from ``--version`` output, or ``None``."""
    match = re.search(r"\d+\.\d+\.\d+(?:[.\-+][0-9A-Za-z.\-]+)?", output)
    return match.group(0) if match else None


def _compute_skew(pinned: str | None, resolved: str | None) -> str | None:
    """Compose a safe skew message from two versions (pure; unit-tested directly).

    ``None`` when either version is unknown (nothing to compare) or the two
    agree; a safe human string naming both versions when they diverge.
    """
    if pinned is None or resolved is None:
        return None
    if pinned == resolved:
        return None
    return (
        f"vaultspec-core version skew: environment pins {pinned} but the resolved "
        f"CLI is {resolved}; provisioning used the resolved CLI"
    )
