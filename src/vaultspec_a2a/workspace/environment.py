"""Dual-mode environment resolution for agent workspaces.

Supports both flat-hierarchy and worktree-based layouts.
In flat mode, ``.venv`` is expected next to the workspace root. In
worktree mode, ``.venv`` may live in the container folder (parent of
the worktrees directory) or in the main repository root.
"""

import os
from collections.abc import Mapping
from pathlib import Path

__all__ = [
    "resolve_env_vars",
    "resolve_venv",
    "scrub_agent_environment",
    "scrub_infrastructure_environment",
]


def resolve_venv(workspace_path: Path) -> Path | None:
    """Locate the nearest Python virtual environment for *workspace_path*.

    Search order:
    1. ``workspace_path / .venv`` (flat hierarchy)
    2. ``workspace_path.parent / .venv`` (container folder for worktrees)
    3. Walk up to the workspace's own repository root (the nearest ``.git``)
       and use its ``.venv``. The walk stops there: a repository that merely
       contains the workspace's repository is not the workspace's project, and
       its interpreter is not the agent's to run. A workspace that is itself a
       repository (an agent ran ``git init`` in it) is therefore its own
       project and gets no interpreter unless it holds one.

    Returns ``None`` if no venv is found.
    """
    # 1. Local .venv (flat mode)
    candidate = workspace_path / ".venv"
    if candidate.is_dir():
        return candidate

    # 2. Container folder (one level up from worktree)
    parent_candidate = workspace_path.parent / ".venv"
    if parent_candidate.is_dir():
        return parent_candidate

    # 3. Walk up to find main repo root (.git dir co-located with .venv)
    current = workspace_path.parent
    # 10 levels is sufficient for any reasonable project hierarchy.
    # A worktree is typically 2-4 levels below the repo root; 10 provides a
    # generous upper bound while preventing unbounded filesystem traversal.
    for _ in range(10):  # bounded to prevent infinite traversal
        if (current / ".git").exists():
            venv = current / ".venv"
            return venv if venv.is_dir() else None
        parent = current.parent
        if parent == current:
            break  # filesystem root
        current = parent

    return None


def scrub_infrastructure_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Remove service authority while preserving explicitly supplied provider auth."""
    forbidden = frozenset(
        {
            "DATABASE_URL",
            "CHECKPOINT_DATABASE_URL",
            "SQLALCHEMY_DATABASE_URI",
            "PGPASSWORD",
            "POSTGRES_PASSWORD",
            "SERVICE_TOKEN",
            "GATEWAY_TOKEN",
            "INTERNAL_TOKEN",
        }
    )
    return {
        name: value
        for name, value in environment.items()
        if name.upper() not in forbidden and not name.upper().startswith("VAULTSPEC_")
    }


def scrub_agent_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Remove infrastructure and ambient provider credentials before role additions."""
    scrub_keys = frozenset(
        {
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "AZURE_OPENAI_API_KEY",
            "ZHIPU_API_KEY",
            "LANGCHAIN_API_KEY",
            "LANGSMITH_API_KEY",
            "LANGCHAIN_TRACING_V2",
            "ANTHROPIC_LOG",
            # Kimi Code's temporary-provider definition is an all-or-none unit.
            # Scrub its current family and retired spellings so only the
            # Settings-owned current definition can be re-injected by the factory.
            "KIMI_API_KEY",
            "KIMI_BASE_URL",
            "KIMI_MODEL_API_KEY",
            "KIMI_MODEL_BASE_URL",
            "KIMI_MODEL_NAME",
            "KIMI_MODEL_MAX_CONTEXT_SIZE",
            "KIMI_MODEL_CAPABILITIES",
            # Test-runner markers of the SPAWNING process, not of the agent.
            # They are set by pytest in this service's own process and would
            # otherwise be inherited by every agent subprocess and ITS tool
            # servers; env-sniffing children (the rag MCP server's own-test
            # guard, for one) then misclassify a live agent run as running
            # inside a test and refuse their real backends.
            "PYTEST_CURRENT_TEST",
            "PYTEST_VERSION",
        }
    )
    claude_code_allowlist = frozenset(
        {
            "CLAUDE_CODE_OAUTH_TOKEN",
            "CLAUDE_CODE_EXECUTABLE",
            # suppress interactive prompts in non-interactive ACP subprocesses.
            "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
        }
    )
    env = {
        k: v
        for k, v in scrub_infrastructure_environment(environment).items()
        if k.upper() not in scrub_keys
        and not (
            k.upper().startswith("CLAUDE_CODE_")
            and k.upper() not in claude_code_allowlist
        )
    }
    return env


def resolve_env_vars(workspace_path: Path) -> dict[str, str]:
    """Build a scrubbed child environment with the workspace Python metadata."""
    env = scrub_agent_environment(os.environ)
    # use PWD (POSIX standard) instead of the non-standard CWD variable
    env["PWD"] = str(workspace_path)

    venv = resolve_venv(workspace_path)
    if venv is not None:
        env["VIRTUAL_ENV"] = str(venv)

        # Windows uses Scripts/, Unix uses bin/
        scripts_dir = venv / "Scripts"
        if not scripts_dir.is_dir():
            scripts_dir = venv / "bin"

        current_path = env.get("PATH", "")
        env["PATH"] = f"{scripts_dir}{os.pathsep}{current_path}"
    else:
        # explicitly remove VIRTUAL_ENV when no .venv is found to
        # prevent the caller's venv from leaking into the agent's environment.
        env.pop("VIRTUAL_ENV", None)

    return env
