"""Dual-mode environment resolution for agent workspaces.

Supports both flat-hierarchy and worktree-based layouts.
In flat mode, ``.venv`` is expected next to the workspace root. In
worktree mode, ``.venv`` may live in the container folder (parent of
the worktrees directory) or in the main repository root.
"""

import os
from pathlib import Path

__all__ = [
    "resolve_env_vars",
    "resolve_venv",
]


def resolve_venv(workspace_path: Path) -> Path | None:
    """Locate the nearest Python virtual environment for *workspace_path*.

    Search order:
    1. ``workspace_path / .venv`` (flat hierarchy)
    2. ``workspace_path.parent / .venv`` (container folder for worktrees)
    3. Walk up parents looking for a ``.venv`` alongside a ``.git`` dir
       (main repository root)

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
        if (current / ".git").exists() and (current / ".venv").is_dir():
            return current / ".venv"
        parent = current.parent
        if parent == current:
            break  # filesystem root
        current = parent

    return None


def resolve_env_vars(workspace_path: Path) -> dict[str, str]:
    """Build an environment dict for an agent running at *workspace_path*.

    Inherits the current process environment, then overlays:
    - ``VIRTUAL_ENV``: points to the resolved venv
    - ``PATH``: prepends the venv's ``Scripts`` (Windows) or ``bin``
      directory
    - ``CWD``: set to *workspace_path* for clarity

    Credential injection (``CLAUDE_CODE_OAUTH_TOKEN`` etc.)
    is handled by the provider layer, never by the workspace module.
    """
    # scrub known secret env vars to prevent credential leakage to
    # agents. Credential injection is handled by the provider
    # layer.  VAULTSPEC_* prefixed keys are scrubbed via a prefix check below.
    scrub_keys = frozenset(
        {
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "AZURE_OPENAI_API_KEY",
            # additional API key providers
            "ZHIPU_API_KEY",
            "LANGCHAIN_API_KEY",
            "LANGSMITH_API_KEY",
            "LANGCHAIN_TRACING_V2",
            # ANTHROPIC_LOG=debug causes the Anthropic SDK to emit
            # debug text to stdout, corrupting the ACP JSON-RPC stream and
            # triggering -32603 parse errors. Strip it unconditionally — the probe
            # re-injects it explicitly only when debug=True via run_probe().
            "ANTHROPIC_LOG",
        }
    )
    # scrub all CLAUDE_CODE_* keys except those the provider layer
    # deliberately injects into the child process: OAUTH_TOKEN (auth),
    # EXECUTABLE (binary override), and the two DISABLE_* keys that
    # suppress interactive prompts in non-interactive subprocesses.  Any other
    # CLAUDE_CODE_* key (e.g. CLAUDE_CODE_SKIP_BROWSER_AUTH, internal session
    # markers set by a parent Claude Code process) must be stripped so that a
    # nested ACP subprocess does not inherit the parent session identity.
    _claude_code_allowlist = frozenset(
        {
            "CLAUDE_CODE_OAUTH_TOKEN",
            "CLAUDE_CODE_EXECUTABLE",
            # suppress interactive prompts in
            # non-interactive ACP subprocesses.
            "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
        }
    )
    env = {
        k: v
        for k, v in os.environ.items()
        # Scrub explicit keys, VAULTSPEC_ secrets,
        # and wildcard CLAUDE_CODE_* except allowlist
        if k not in scrub_keys
        and not k.startswith("VAULTSPEC_")
        and not (k.startswith("CLAUDE_CODE_") and k not in _claude_code_allowlist)
    }
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
