"""Boot-time preparation for a role's serve process: command, env, cwd, build SHA.

Split out of :mod:`.manager` (which composes these into the ``serve_up``/
``resume``/``rerun``/``rebuild`` verbs) purely to keep that module's size within
its declared limit; every name here is a direct extraction, unchanged in
behaviour, of what used to live there.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING, TypedDict, Unpack

from ..authoring.discovery import SERVICE_JSON_ENV as _ENGINE_SERVICE_JSON_ENV
from ..control.infra_config import GATEWAY_URL_ENV, INTERNAL_TOKEN_ENV, WORKER_URL_ENV
from .errors import LifecycleError
from .registry import NAME_ENV

if TYPE_CHECKING:
    from pathlib import Path

    from .procs_config import RoleConfig
    from .registry import ProcRecord

__all__ = [
    "OWNER_ENV",
    "build_cwd_for",
    "build_sha",
    "default_repo",
    "ensure_explicit_repo",
    "read_internal_token",
    "render_command",
    "render_env",
    "serve_cwd_for",
    "serve_env",
]

# The registry-label env var a booted serve process is stamped with, so a
# self-registering serve command converges onto the record THIS boot claimed
# rather than writing a second, foreign-owned one.
OWNER_ENV = "VAULTSPEC_PROCS_OWNER"


def _subst(value: str, *, port: int, workspace: str) -> str:
    """Substitute the ``{python}``/``{port}``/``{workspace}`` tokens in a value.

    ``{python}`` resolves to :data:`sys.executable` - the interpreter of the
    serving process - so a role that shells ``python`` always runs the SAME venv
    interpreter (with ``vaultspec_a2a`` installed), never whatever bare ``python``
    a PATH lookup would otherwise resolve to (a uv-managed base interpreter).
    """
    return (
        value.replace("{python}", sys.executable)
        .replace("{port}", str(port))
        .replace("{workspace}", workspace)
    )


def render_command(template: list[str], *, port: int, workspace: str) -> list[str]:
    """Substitute the ``{python}``/``{port}``/``{workspace}`` tokens in a command."""
    return [_subst(arg, port=port, workspace=workspace) for arg in template]


def render_env(
    env_template: dict[str, str], *, port: int, workspace: str
) -> dict[str, str]:
    """Substitute the ``{port}``/``{workspace}`` tokens in each env-var value.

    A role whose serve reads its port from the environment (the a2a gateway from
    ``VAULTSPEC_PORT``, the worker from ``VAULTSPEC_WORKER_PORT``) declares an
    ``env`` table in procs.toml; the boot verb renders it into the child's
    environment rather than passing a ``--port`` flag the command does not accept.
    """
    return {
        key: _subst(value, port=port, workspace=workspace)
        for key, value in env_template.items()
    }


def build_sha(cwd: Path) -> str | None:
    """Best-effort short git SHA of *cwd*'s HEAD, or ``None`` outside a repo."""
    # A SHA is ASCII, but the captured stderr beside it is not: git names the
    # offending path when *cwd* is not a repository, and a non-ASCII path under a
    # locale decode fails inside subprocess's reader thread rather than raising
    # here. ``run`` would then return with ``stdout`` set to None and the strip
    # below would raise AttributeError - out of a helper whose whole contract is
    # to answer None on failure. Stating the encoding keeps it best-effort.
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return None
    sha = result.stdout.strip()
    return sha or None


def read_internal_token(token_file: str, *, label: str) -> str:
    """Read the internal-IPC token from *token_file*, failing loudly on a bad file.

    The record carries only the PATH (never the secret), so the token is read at
    boot. A role that declares a token file but whose file is missing, unreadable,
    or empty is refused with :class:`LifecycleError` rather than silently booting
    with no token - a silent empty-token fallback would reintroduce the invisible
    gateway/worker mismatch this pairing exists to close.
    """
    from pathlib import Path as _Path

    try:
        token = _Path(token_file).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise LifecycleError(
            f"{label}: internal token file {token_file!r} is unreadable: {exc}"
        ) from exc
    if not token:
        raise LifecycleError(f"{label}: internal token file {token_file!r} is empty")
    return token


class _ServeEnvOptional(TypedDict, total=False):
    engine_service_json: str
    internal_token_file: str
    gateway_url: str
    worker_url: str


class _ServeEnvArgs(_ServeEnvOptional):
    port: int
    workspace: str
    name: str
    owner: str


def serve_env(role_cfg: RoleConfig, **options: Unpack[_ServeEnvArgs]) -> dict[str, str]:
    """The env overlay for a boot: the role's rendered port/config vars plus identity.

    Carrying the managed name and owner into the child means a serve process that
    self-registers (a gateway/worker booted on a band port) converges onto THIS
    record - same ``(role, name)`` and owner - and refreshes it, instead of writing
    a second, foreign-owned record that the owner-check would then refuse.

    A recorded *engine_service_json* is injected under
    :data:`_ENGINE_SERVICE_JSON_ENV` so the worker's engine discovery no longer
    depends on the booting shell having exported it - the reseat-strands-worker gap.
    *internal_token_file* (a PATH, read here) is injected as the internal-IPC token,
    *gateway_url* as the paired gateway URL (worker -> gateway), and *worker_url* as
    the paired worker URL (gateway -> worker dispatch), so a procs-managed gateway-dev
    and worker-dev agree on all of them instead of leaning on shell state. Empty
    values inject nothing, matching the prior behaviour for records predating them.
    """
    port = options["port"]
    workspace = options["workspace"]
    name = options["name"]
    owner = options["owner"]
    engine_service_json = options.get("engine_service_json", "")
    internal_token_file = options.get("internal_token_file", "")
    gateway_url = options.get("gateway_url", "")
    worker_url = options.get("worker_url", "")
    env = render_env(role_cfg.env, port=port, workspace=workspace)
    env[NAME_ENV] = name
    env[OWNER_ENV] = owner
    if engine_service_json:
        env[_ENGINE_SERVICE_JSON_ENV] = engine_service_json
    if internal_token_file:
        env[INTERNAL_TOKEN_ENV] = read_internal_token(
            internal_token_file, label=f"{role_cfg.name}-{name}"
        )
    if gateway_url:
        env[GATEWAY_URL_ENV] = gateway_url
    if worker_url:
        env[WORKER_URL_ENV] = worker_url
    return env


def default_repo() -> Path:
    """The repo root a serve command runs in when a record carries no explicit repo."""
    from ..control.config import settings

    return settings.project_root


def ensure_explicit_repo(role_cfg: RoleConfig, repo: str, label: str) -> None:
    """Refuse to serve a data-seating role from an implicit default cwd.

    A role that declares ``require_repo`` (engine-dev seats its data store from its
    serve cwd) must be booted and resumed with an explicit repo, never defaulted to
    the project root - defaulting there once seated a dev engine's store on top of
    the resident engine's live store. Raises :class:`LifecycleError` when no repo is
    given, so the silent-root fallback is impossible rather than merely discouraged.
    """
    if role_cfg.require_repo and not repo:
        raise LifecycleError(
            f"role {role_cfg.name!r} requires an explicit repo (it seats data from "
            f"its serve cwd); {label} carries none - pass an explicit repo rather "
            "than defaulting to the project root"
        )


def serve_cwd_for(record: ProcRecord) -> Path:
    """The dir a role's SERVE command runs in: the record's repo, else the root."""
    from pathlib import Path as _Path

    if record.repo:
        return _Path(record.repo)
    return default_repo()


def build_cwd_for(record: ProcRecord) -> Path:
    """The dir a role's BUILD command runs in.

    A role whose build tree differs from its serve tree (engine-dev builds the
    cargo workspace in the dashboard repo but serves the wrapper script from the
    a2a repo) captures the build tree in ``build_repo`` at boot; it falls back to
    the serve repo when unset, so single-tree roles need no extra field.
    """
    from pathlib import Path as _Path

    if record.build_repo:
        return _Path(record.build_repo)
    return serve_cwd_for(record)
