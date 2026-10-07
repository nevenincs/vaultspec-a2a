"""Per-run isolated ``KIMI_CODE_HOME`` for the Kimi lane.

The Kimi CLI reads its configuration - the default model, the provider table
and every ``[mcp_servers.*]`` block - from ``KIMI_CODE_HOME`` (default
``~/.kimi-code``). Left on the operator's home, an agent run inherits whatever
the operator configured there, which is the ambient-MCP hole the harness
contract exists to close: the agent's tool surface must be exactly the declared
set. So a served run gets its own home, and the operator's is never handed to a
child.

The accepted Kimi decision records this isolation as a per-run ``--config-file``
argument, read from ``kimi-cli`` 1.49.0. The installed CLI generation is Kimi
Code (``kimi --version`` 0.36.1), whose ``kimi --help`` carries no ``--config``
or ``--config-file`` option at all; ``kimi doctor`` under an explicit
``KIMI_CODE_HOME`` reports reading ``config.toml`` and ``tui.toml`` from exactly
that directory. The home redirect is therefore the mechanism this CLI offers for
the decision's commitment, and it is the same shape the Codex lane already uses
(``_codex_config_home``).

A fresh home carries NOTHING. Copying the operator's persisted login in would
make this lane's cleanup able to retire the operator's own credential - the
failure ``_codex_auth`` exists to prevent, and Kimi's rotation behaviour has no
evidence behind it yet - so the run authenticates from its own injected
environment instead, and a run that has no such credential is refused rather
than quietly served from the operator's home.

Root resolution and the age-gated orphan sweep live in ``_config_home_roots``,
so a crashed run's home is reclaimed and the sweep is scoped to this module's
own prefix, never collecting a directory belonging to another lane.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path

from ..desktop._platform_acl import harden_credential_path
from ._config_home_roots import sweep_orphan_homes, temp_home_root

__all__ = [
    "KIMI_CODE_HOME_ENV",
    "build_kimi_config_home",
    "cleanup_kimi_config_home",
    "resolve_kimi_base_home",
    "sweep_orphan_kimi_homes",
]

logger = logging.getLogger(__name__)

#: The CLI's own name for the directory it reads its configuration from.
KIMI_CODE_HOME_ENV = "KIMI_CODE_HOME"

_HOME_PREFIX = "vaultspec-kimi-home-"


def resolve_kimi_base_home(configured: str | None) -> Path:
    """Resolve the operator's own Kimi home - read from, never handed to a child.

    This is where the operator's provider table and persisted login live, so it
    is what prompt-free catalog discovery enumerates models from. A served turn
    gets :func:`build_kimi_config_home` instead.
    """
    if configured and configured.strip():
        return Path(configured.strip())
    return Path.home() / ".kimi-code"  # storage-anchor-ok


def build_kimi_config_home() -> Path:
    """Create an empty per-run ``KIMI_CODE_HOME`` the caller owns.

    The caller sets :data:`KIMI_CODE_HOME_ENV` to the returned path and must
    call :func:`cleanup_kimi_config_home` once the run's child is reaped.

    Empty is the whole point: with no ``config.toml`` the CLI applies its
    built-in defaults, so no operator-configured MCP server, provider or model
    alias reaches the agent. See the module docstring for why no credential is
    seeded in.
    """
    # mkdtemp creates an owner-only (0700) directory, so nothing the run writes
    # into its home is traversable by another account before its own mode is set.
    home = Path(tempfile.mkdtemp(prefix=_HOME_PREFIX, dir=temp_home_root()))
    # Reclaim what earlier crashed runs left behind, once per home creation -
    # mirrors the Codex call site: there is no supervisor to run this sweep on a
    # schedule, so it piggybacks on every creation instead.
    with suppress(OSError):
        sweep_orphan_kimi_homes(keep=home)
    try:
        harden_credential_path(home)
    except BaseException:
        cleanup_kimi_config_home(home)
        raise
    logger.debug("Kimi isolated config home created at %s", home)
    return home


def cleanup_kimi_config_home(home: Path | None) -> None:
    """Remove a per-run Kimi config home.

    Nothing is written back: the home was seeded with nothing, so it holds only
    what this run's own child put there.
    """
    if home is None:
        return
    try:
        shutil.rmtree(home)
    except FileNotFoundError:
        if home.exists():
            raise


def sweep_orphan_kimi_homes(
    *, keep: Path | None = None, root: Path | None = None
) -> list[Path]:
    """Remove per-run Kimi config homes abandoned by a crashed run.

    A thin, prefix-bound wrapper over the shared
    :func:`~._config_home_roots.sweep_orphan_homes` core, mirroring the Codex
    side - partial application to this module's own prefix, not a re-export
    shim. The age-gating and root-resolution rationale lives once, in the
    shared core.

    Args:
        keep: A home to leave alone regardless of age - the caller's own.
        root: Directory to sweep; defaults to the profile's temporary-home root.

    Returns:
        The homes removed, for the caller to log.
    """
    return sweep_orphan_homes(prefix=_HOME_PREFIX, keep=keep, root=root)
