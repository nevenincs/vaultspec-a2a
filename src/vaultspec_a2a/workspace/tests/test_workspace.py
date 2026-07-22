"""Tests for workspace environment resolution.

Every test uses real files and real subprocesses — no mocks, no monkeypatching.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from ..environment import resolve_env_vars, resolve_venv


class TestResolveVenv:
    """Tests for the virtual-environment discovery helper."""

    def test_flat_mode_local_venv(self, tmp_path: Path) -> None:
        """A .venv directly inside the workspace is found in flat mode."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        assert resolve_venv(tmp_path) == venv_dir

    def test_worktree_mode_parent_venv(self, tmp_path: Path) -> None:
        """A .venv in the parent agent/ directory is found in worktree mode."""
        workspace = tmp_path / "agent" / "coder-1"
        workspace.mkdir(parents=True)
        venv_dir = tmp_path / "agent" / ".venv"
        venv_dir.mkdir()
        assert resolve_venv(workspace) == venv_dir

    def test_repo_root_fallback(self, tmp_path: Path) -> None:
        """A .venv at the repo root is found even from a deeply-nested workspace."""
        # Simulate repo root with .git + .venv, workspace is deeply nested
        (tmp_path / ".git").mkdir()
        (tmp_path / ".venv").mkdir()
        workspace = tmp_path / "agent" / "coder" / "123"
        workspace.mkdir(parents=True)
        assert resolve_venv(workspace) == tmp_path / ".venv"

    def test_no_venv_returns_none(self, tmp_path: Path) -> None:
        """Returns None when no .venv can be found in the search hierarchy."""
        workspace = tmp_path / "isolated"
        workspace.mkdir()
        assert resolve_venv(workspace) is None


class TestResolveEnvVars:
    """Tests for the environment variable builder."""

    def test_includes_cwd(self, tmp_path: Path) -> None:
        """PWD key is set to the stringified workspace path."""
        env = resolve_env_vars(tmp_path)
        assert env["PWD"] == str(tmp_path)

    def test_includes_virtual_env_when_found(self, tmp_path: Path) -> None:
        """VIRTUAL_ENV and PATH are set when a .venv with Scripts/ exists."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        # Create Scripts dir (Windows convention)
        (venv_dir / "Scripts").mkdir()
        env = resolve_env_vars(tmp_path)
        assert env["VIRTUAL_ENV"] == str(venv_dir)
        assert str(venv_dir / "Scripts") in env["PATH"]

    def test_no_virtual_env_when_missing(self, tmp_path: Path) -> None:
        """VIRTUAL_ENV is absent when no .venv found."""
        workspace = tmp_path / "no-venv"
        workspace.mkdir()
        env = resolve_env_vars(workspace)
        # VIRTUAL_ENV must be explicitly removed when no .venv found
        # to prevent the caller's venv from leaking into the agent environment.
        assert "VIRTUAL_ENV" not in env


# ---------------------------------------------------------------------------
# Credential scrubbing
# ---------------------------------------------------------------------------


# A probe that runs the REAL ``resolve_env_vars`` inside a spawned child process
# and emits the resolved environment as JSON. The child reads only the process
# environment its parent hands it, so the scrub is exercised across a real
# process boundary rather than by monkeypatching the running interpreter (mirrors
# the readiness-probe pattern in ``api/tests/test_model_profiles_evidence.py``).
_SCRUB_PROBE_SCRIPT = textwrap.dedent(
    """
    import json
    import sys
    from pathlib import Path

    from vaultspec_a2a.workspace.environment import resolve_env_vars

    resolved = resolve_env_vars(Path(sys.argv[1]))
    print(json.dumps(resolved))
    """
)

_SCRUB_SECRET_KEYS: list[str] = [
    "ANTHROPIC_API_KEY",
    # CLAUDE_CODE_OAUTH_TOKEN is intentionally NOT scrubbed here — it is in the
    # CLAUDE_CODE_* allowlist so the provider layer can re-inject it. See
    # test_claude_code_allowlist_keys_are_preserved below.
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AZURE_OPENAI_API_KEY",
    "ZHIPU_API_KEY",
    "LANGCHAIN_API_KEY",
    "LANGCHAIN_TRACING_V2",
    # ANTHROPIC_LOG causes SDK debug text on stdout → JSON-RPC corruption.
    "ANTHROPIC_LOG",
]

_SCRUB_VAULTSPEC_KEYS: dict[str, str] = {
    "VAULTSPEC_SECRET_TOKEN": "should-not-leak",
    "VAULTSPEC_ANOTHER_KEY": "also-secret",
}

_SCRUB_NON_ALLOWLISTED_CLAUDE_CODE: dict[str, str] = {
    "CLAUDE_CODE_SKIP_BROWSER_AUTH": "1",
    "CLAUDE_CODE_API_KEY_HELPER": "helper-script",
    "CLAUDE_CODE_SOME_INTERNAL_FLAG": "true",
}

_SCRUB_ALLOWLISTED_CLAUDE_CODE: dict[str, str] = {
    "CLAUDE_CODE_OAUTH_TOKEN": "tok-abc123",
    "CLAUDE_CODE_EXECUTABLE": "/usr/local/bin/claude",
    "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
}

_SCRUB_ZAI_KEYS: dict[str, str] = {
    "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
    "ANTHROPIC_AUTH_TOKEN": "zai-token-value",
}

_SCRUB_SAFE_KEYS: dict[str, str] = {"MY_SAFE_VAR": "visible-value"}


@pytest.fixture(scope="module")
def resolved_env(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Spawn one child ``resolve_env_vars`` over a fully controlled env.

    The parent seeds the child environment with a known value for every key the
    scrub contract concerns — secrets, ``VAULTSPEC_*`` keys, both the allowlisted
    and non-allowlisted ``CLAUDE_CODE_*`` keys, the Z.ai pass-through pair, and a
    plainly-safe var — then returns the child's resolved-env dict.
    """
    tmp_path = tmp_path_factory.mktemp("scrub-probe")
    script = tmp_path / "scrub_probe.py"
    script.write_text(_SCRUB_PROBE_SCRIPT, encoding="utf-8")

    env = dict(os.environ)
    for key in _SCRUB_SECRET_KEYS:
        env[key] = "super-secret-value"
    env.update(_SCRUB_VAULTSPEC_KEYS)
    env.update(_SCRUB_NON_ALLOWLISTED_CLAUDE_CODE)
    env.update(_SCRUB_ALLOWLISTED_CLAUDE_CODE)
    env.update(_SCRUB_ZAI_KEYS)
    env.update(_SCRUB_SAFE_KEYS)

    result = subprocess.run(
        [sys.executable, str(script), str(tmp_path)],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


class TestCredentialScrubbing:
    """Tests verifying that known secret env vars are scrubbed.

    ``resolve_env_vars`` is exercised in a spawned child process whose entire
    environment is constructed by the parent — the real settings path over a real
    process boundary, never a monkeypatch of the running interpreter. A single
    module-scoped child spawn produces one resolved-env snapshot; each test asserts
    its own slice of the scrub/preserve contract against that shared real result.
    """

    @pytest.mark.parametrize("secret_key", _SCRUB_SECRET_KEYS)
    def test_known_secret_is_scrubbed(
        self, resolved_env: dict[str, str], secret_key: str
    ) -> None:
        """Known secret env vars are NOT present in the returned env dict."""
        assert secret_key not in resolved_env, (
            f"{secret_key} should be scrubbed but was present in env"
        )

    def test_vaultspec_prefixed_key_is_scrubbed(
        self, resolved_env: dict[str, str]
    ) -> None:
        """VAULTSPEC_ prefixed keys are scrubbed regardless of suffix."""
        for key in _SCRUB_VAULTSPEC_KEYS:
            assert key not in resolved_env, (
                f"VAULTSPEC_-prefixed {key} should be scrubbed but was present"
            )

    def test_non_secret_env_vars_are_preserved(
        self, resolved_env: dict[str, str]
    ) -> None:
        """Non-secret env vars like HOME, PATH, USER are preserved."""
        assert resolved_env.get("MY_SAFE_VAR") == "visible-value"

    def test_scrub_is_comprehensive_no_false_positives(
        self, resolved_env: dict[str, str]
    ) -> None:
        """All known secrets are scrubbed while PWD is preserved."""
        for key in _SCRUB_SECRET_KEYS:
            assert key not in resolved_env, (
                f"secret {key} should be scrubbed but was present"
            )
        # Non-secret keys must still be present
        assert "PWD" in resolved_env, "PWD should be preserved but was absent"

    def test_claude_code_wildcard_scrub_removes_non_allowlisted(
        self, resolved_env: dict[str, str]
    ) -> None:
        """CLAUDE_CODE_* keys not in allowlist are scrubbed."""
        for key in _SCRUB_NON_ALLOWLISTED_CLAUDE_CODE:
            assert key not in resolved_env, (
                f"non-allowlisted {key} should be scrubbed but was present"
            )

    def test_claude_code_allowlist_keys_are_preserved(
        self, resolved_env: dict[str, str]
    ) -> None:
        """Allowlisted CLAUDE_CODE_* keys pass through the wildcard scrub."""
        for key, value in _SCRUB_ALLOWLISTED_CLAUDE_CODE.items():
            assert resolved_env.get(key) == value, (
                f"allowlisted {key} should be preserved as {value!r}, "
                f"got {resolved_env.get(key)!r}"
            )

    def test_zai_gateway_env_vars_are_preserved(
        self, resolved_env: dict[str, str]
    ) -> None:
        """The Z.ai path depends on ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN surviving.

        Z.ai rides the Claude ACP path by injecting these two vars. The provider
        layer sets them in ``env_vars`` after the base scrub, but the base scrub
        must not strip them if they are already present in the process
        environment — this pins that invariant so a future addition to
        ``scrub_keys`` cannot silently break Z.ai auth. ``ANTHROPIC_API_KEY`` (a
        distinct name) remains scrubbed; these two are not secrets-by-name here.
        """
        for key, value in _SCRUB_ZAI_KEYS.items():
            assert resolved_env.get(key) == value, (
                f"Z.ai pass-through {key} should be preserved as {value!r}, "
                f"got {resolved_env.get(key)!r}"
            )
        # The distinct ANTHROPIC_API_KEY name remains scrubbed.
        assert "ANTHROPIC_API_KEY" not in resolved_env, (
            "ANTHROPIC_API_KEY should remain scrubbed even alongside the Z.ai vars"
        )


