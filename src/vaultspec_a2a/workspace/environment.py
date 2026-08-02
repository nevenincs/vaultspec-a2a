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
    - ``PWD``: set to *workspace_path* for clarity

    The base environment is scrubbed, never inherited wholesale. A spawned agent
    is a lower-trust process than the service that spawns it, so a credential the
    operator happens to carry must not become a credential the agent can spend.
    Five removal families:

    - Known provider secrets by name. The provider layer re-injects only the auth
      a lane intentionally supports (``_build_gemini_env``, ``_build_zai_env``),
      so removing them here costs nothing a supported lane depends on. Two
      concrete hazards this closes: the Z.ai lane retargets
      ``ANTHROPIC_BASE_URL`` at a third-party gateway, and an inherited
      ``ANTHROPIC_API_KEY`` would then be presented to that gateway; and an
      ``ANTHROPIC_API_KEY`` alongside a Claude OAuth token silently downgrades a
      flat-rate subscription to metered API billing.
    - ``CLAUDE_CODE_*`` except a narrow allowlist. Anything outside it (internal
      session markers set by a parent Claude Code process, auth-helper hooks)
      would hand a nested ACP subprocess the parent session's identity.
    - ``VAULTSPEC_*``: this service's OWN infrastructure state (gateway/internal
      bearer tokens, port wiring). Handing agents the tokens that authenticate
      the control plane would let a spawned agent impersonate the
      infrastructure. Additive ``VAULTSPEC_AUTHORING_*`` bridge values are
      re-injected explicitly by the provider layer after this base.
    - ``ANTHROPIC_LOG``: ``debug`` makes the Anthropic SDK emit debug text to
      stdout, corrupting the ACP JSON-RPC stream (-32603 parse errors). The
      probe re-injects it explicitly only when debug=True via run_probe().
    - ``PYTEST_*`` markers: the spawning process's own test-runner state.
      Env-sniffing agent tool servers (the rag MCP's own-test guard) read them
      as "I am running inside a test" and refuse their live backends.

    ``ANTHROPIC_BASE_URL``/``ANTHROPIC_AUTH_TOKEN`` are deliberately NOT scrubbed:
    they are endpoint/token names the Z.ai lane rides, distinct from
    ``ANTHROPIC_API_KEY``.
    """
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
            # Scrub its current family and retained legacy spellings so only the
            # Settings-owned definition can be re-injected by the factory.
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
        for k, v in os.environ.items()
        if k not in scrub_keys
        and not k.startswith("VAULTSPEC_")
        and not (k.startswith("CLAUDE_CODE_") and k not in claude_code_allowlist)
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
