"""Tests for workspace management with real git repositories.

Every test creates a fresh temporary git repo — no mocks, no monkeypatching.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from ...thread.errors import WorkspaceError
from ..environment import resolve_env_vars, resolve_venv
from ..git_manager import GitManager, MergeStrategy

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal real git repository with one commit on 'main'."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def _run(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

    _run("init", "-b", "main")
    _run("config", "user.email", "test@test.com")
    _run("config", "user.name", "Test")
    # Create an initial commit so HEAD exists
    (repo / "README.md").write_text("# Test\n")
    _run("add", ".")
    _run("commit", "-m", "initial")
    return repo


@pytest.fixture
def manager(git_repo: Path) -> GitManager:
    """Return a GitManager rooted at the test repository."""
    return GitManager(git_repo)


# ---------------------------------------------------------------------------
# GitManager — construction
# ---------------------------------------------------------------------------


class TestGitManagerInit:
    """Tests for GitManager construction-time validation."""

    def test_requires_absolute_path(self, tmp_path: Path) -> None:
        """Relative repo_root raises WorkspaceError on construction."""
        with pytest.raises(Exception, match="absolute"):
            GitManager(Path("relative/path"))

    def test_accepts_absolute_path(self, git_repo: Path) -> None:
        """Absolute repo_root is stored and exposed via repo_root property."""
        mgr = GitManager(git_repo)
        assert mgr.repo_root == git_repo


# ---------------------------------------------------------------------------
# GitManager — worktree lifecycle
# ---------------------------------------------------------------------------


class TestWorktreeLifecycle:
    """Tests for create/list/remove worktree operations."""

    @pytest.mark.asyncio
    async def test_create_worktree(self, manager: GitManager, git_repo: Path) -> None:
        """create_worktree returns a path that exists and contains repo files."""
        wt_path = await manager.create_worktree("coder-1", base_branch="main")
        assert wt_path.exists()
        assert wt_path == git_repo / "agent" / "coder-1"
        # A file from the main branch should be present
        assert (wt_path / "README.md").exists()

    @pytest.mark.asyncio
    async def test_worktree_creates_branch(
        self, manager: GitManager, git_repo: Path
    ) -> None:
        """create_worktree checks out a new branch named agent/{agent_id}."""
        wt_path = await manager.create_worktree("planner-1", base_branch="main")
        branch = await manager.current_branch(cwd=wt_path)
        assert branch == "agent/planner-1"

    @pytest.mark.asyncio
    async def test_list_worktrees(self, manager: GitManager) -> None:
        """list_worktrees returns all active worktrees including the main checkout."""
        await manager.create_worktree("w1", base_branch="main")
        await manager.create_worktree("w2", base_branch="main")
        wts = await manager.list_worktrees()
        branches = [wt.branch for wt in wts]
        assert "agent/w1" in branches
        assert "agent/w2" in branches
        # Main worktree also present
        assert "main" in branches

    @pytest.mark.asyncio
    async def test_main_worktree_is_main(self, manager: GitManager) -> None:
        """list_worktrees marks the main checkout with is_main=True."""
        await manager.create_worktree("wt-main-check", base_branch="main")
        wts = await manager.list_worktrees()
        main_entries = [wt for wt in wts if wt.is_main]
        assert len(main_entries) == 1, "Exactly one worktree must be is_main=True"
        assert main_entries[0].branch == "main"

    @pytest.mark.asyncio
    async def test_agent_worktrees_are_not_main(self, manager: GitManager) -> None:
        """Agent worktrees must have is_main=False."""
        await manager.create_worktree("not-main", base_branch="main")
        wts = await manager.list_worktrees()
        agent_entries = [wt for wt in wts if wt.branch != "main"]
        assert all(not wt.is_main for wt in agent_entries), (
            "Agent worktrees must not have is_main=True"
        )

    @pytest.mark.asyncio
    async def test_remove_worktree(self, manager: GitManager) -> None:
        """remove_worktree deletes the worktree directory from the filesystem."""
        wt_path = await manager.create_worktree("to-remove", base_branch="main")
        assert wt_path.exists()
        await manager.remove_worktree(wt_path)
        assert not wt_path.exists()

    @pytest.mark.asyncio
    async def test_remove_cleans_from_list(self, manager: GitManager) -> None:
        """After removal the worktree branch no longer appears in list_worktrees."""
        wt_path = await manager.create_worktree("cleanup", base_branch="main")
        await manager.remove_worktree(wt_path)
        wts = await manager.list_worktrees()
        branches = [wt.branch for wt in wts]
        assert "agent/cleanup" not in branches


# ---------------------------------------------------------------------------
# GitManager — merge operations
# ---------------------------------------------------------------------------


class TestMergeOperations:
    """Tests for conflict detection and merge strategies."""

    @pytest.mark.asyncio
    async def test_fast_forward_merge(
        self, manager: GitManager, git_repo: Path
    ) -> None:
        """Fast-forward merge lands the worktree commit onto main."""
        wt_path = await manager.create_worktree("ff-test", base_branch="main")
        # Add a new file in the worktree
        (wt_path / "new_file.txt").write_text("hello")
        await manager.run_git("add", ".", cwd=wt_path)
        await manager.run_git("commit", "-m", "add new file", cwd=wt_path)

        result_sha = await manager.merge_worktree(
            wt_path,
            target_branch="main",
            strategy=MergeStrategy.FAST_FORWARD,
        )
        assert result_sha
        # The new file should now be on main
        assert (git_repo / "new_file.txt").exists()

    @pytest.mark.asyncio
    async def test_merge_commit_strategy(
        self, manager: GitManager, git_repo: Path
    ) -> None:
        """Merge-commit strategy produces a merge commit and lands the file on main."""
        wt_path = await manager.create_worktree("merge-test", base_branch="main")
        (wt_path / "feature.py").write_text("pass")
        await manager.run_git("add", ".", cwd=wt_path)
        await manager.run_git("commit", "-m", "add feature", cwd=wt_path)

        result_sha = await manager.merge_worktree(
            wt_path,
            target_branch="main",
            strategy=MergeStrategy.MERGE_COMMIT,
        )
        assert result_sha
        assert (git_repo / "feature.py").exists()

    @pytest.mark.asyncio
    async def test_has_conflicts_clean(
        self, manager: GitManager, git_repo: Path
    ) -> None:
        """has_conflicts returns False when the worktree adds a brand-new file."""
        wt_path = await manager.create_worktree("clean-merge", base_branch="main")
        (wt_path / "added.txt").write_text("content")
        await manager.run_git("add", ".", cwd=wt_path)
        await manager.run_git("commit", "-m", "add file", cwd=wt_path)

        conflicts = await manager.has_conflicts(wt_path, "main")
        assert conflicts is False

    @pytest.mark.asyncio
    async def test_has_conflicts_detects_conflict(
        self, manager: GitManager, git_repo: Path
    ) -> None:
        """has_conflicts returns True when both branches edit the same file."""
        wt_path = await manager.create_worktree("conflict-test", base_branch="main")

        # Modify README in both the main worktree and the agent worktree
        (git_repo / "README.md").write_text("main change\n")
        await manager.run_git("add", ".", cwd=git_repo)
        await manager.run_git("commit", "-m", "main edit", cwd=git_repo)

        (wt_path / "README.md").write_text("agent change\n")
        await manager.run_git("add", ".", cwd=wt_path)
        await manager.run_git("commit", "-m", "agent edit", cwd=wt_path)

        conflicts = await manager.has_conflicts(wt_path, "main")
        assert conflicts is True

    @pytest.mark.asyncio
    async def test_merge_raises_on_conflict(
        self, manager: GitManager, git_repo: Path
    ) -> None:
        """merge_worktree raises MergeConflictError when conflicts exist."""
        wt_path = await manager.create_worktree("raise-conflict", base_branch="main")

        (git_repo / "README.md").write_text("main version\n")
        await manager.run_git("add", ".", cwd=git_repo)
        await manager.run_git("commit", "-m", "main edit", cwd=git_repo)

        (wt_path / "README.md").write_text("agent version\n")
        await manager.run_git("add", ".", cwd=wt_path)
        await manager.run_git("commit", "-m", "agent edit", cwd=wt_path)

        with pytest.raises(Exception, match="conflict"):
            await manager.merge_worktree(wt_path, target_branch="main")


# ---------------------------------------------------------------------------
# GitManager — utility
# ---------------------------------------------------------------------------


class TestUtility:
    """Tests for current_branch and head_sha helpers."""

    @pytest.mark.asyncio
    async def test_current_branch(self, manager: GitManager) -> None:
        """current_branch returns 'main' for a freshly initialised repository."""
        branch = await manager.current_branch()
        assert branch == "main"

    @pytest.mark.asyncio
    async def test_head_sha(self, manager: GitManager) -> None:
        """head_sha returns a 40-character hex SHA."""
        sha = await manager.head_sha()
        full_sha_len = 40
        assert len(sha) == full_sha_len


# ---------------------------------------------------------------------------
# Environment resolution
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Tests for _AGENT_ID_RE and _BRANCH_NAME_RE validation."""

    # Valid agent IDs
    @pytest.mark.parametrize(
        "agent_id",
        [
            "agent1",
            "my-agent",
            "Agent_123",
            "a",
            "coder1",
            "planner-v2",
        ],
    )
    @pytest.mark.asyncio
    async def test_valid_agent_ids_accepted(
        self, manager: GitManager, agent_id: str
    ) -> None:
        """Valid agent IDs pass validation in create_worktree."""
        # Just verify no WorkspaceError is raised during validation.
        # We can't easily create many real worktrees without branch conflicts,
        # so we check the error is NOT a validation error.
        try:
            await manager.create_worktree(agent_id, base_branch="main")
        except WorkspaceError as exc:
            # Re-raise only if it's a validation error (message contains "invalid")
            if "invalid" in str(exc).lower():
                raise

    # Invalid agent IDs
    @pytest.mark.parametrize(
        "bad_agent_id",
        [
            "../evil",
            "--flag",
            ".hidden",
            "",
            "-start",
            "bad/slash",
            "has space",
        ],
    )
    @pytest.mark.asyncio
    async def test_invalid_agent_ids_rejected(
        self, manager: GitManager, bad_agent_id: str
    ) -> None:
        """Invalid agent IDs raise WorkspaceError."""
        with pytest.raises(WorkspaceError, match="invalid"):
            await manager.create_worktree(bad_agent_id, base_branch="main")

    # Valid branch names
    @pytest.mark.parametrize(
        "branch",
        [
            "main",
            "feature/foo",
            "v1.0.0",
            "release-2026",
            "hotfix/JIRA-123",
        ],
    )
    @pytest.mark.asyncio
    async def test_valid_branch_names_accepted(
        self, manager: GitManager, branch: str
    ) -> None:
        """Valid branch names pass validation in merge_worktree / has_conflicts."""
        # We verify that validation doesn't raise by checking the error message.
        # Actual git errors (branch doesn't exist) are acceptable — validation passes.
        wt_path = await manager.create_worktree("validator-wt", base_branch="main")
        try:
            await manager.has_conflicts(wt_path, branch)
        except WorkspaceError as exc:
            assert "invalid" not in str(exc).lower(), (
                f"Validation incorrectly rejected valid branch {branch!r}: {exc}"
            )

    # Invalid branch names
    @pytest.mark.parametrize(
        "bad_branch",
        [
            "--force",
            "../traversal",
            "",
            "-bad-start",
            ".dotfile",
        ],
    )
    @pytest.mark.asyncio
    async def test_invalid_branch_names_rejected_in_merge_worktree(
        self, manager: GitManager, bad_branch: str
    ) -> None:
        """Invalid branch names raise WorkspaceError in merge_worktree."""
        wt_path = await manager.create_worktree("branch-val-wt", base_branch="main")
        with pytest.raises(WorkspaceError, match="invalid"):
            await manager.merge_worktree(wt_path, target_branch=bad_branch)

    @pytest.mark.parametrize(
        "bad_branch",
        [
            "--force",
            "../traversal",
            "",
            "-bad-start",
        ],
    )
    @pytest.mark.asyncio
    async def test_invalid_branch_names_rejected_in_has_conflicts(
        self, manager: GitManager, bad_branch: str
    ) -> None:
        """Invalid branch names raise WorkspaceError in has_conflicts."""
        wt_path = await manager.create_worktree("hc-val-wt", base_branch="main")
        with pytest.raises(WorkspaceError, match="invalid"):
            await manager.has_conflicts(wt_path, bad_branch)


# ---------------------------------------------------------------------------
# Path traversal protection
# ---------------------------------------------------------------------------


class TestWorktreePathValidation:
    """Tests that adversarial worktree_path inputs are rejected."""

    @pytest.mark.asyncio
    async def test_has_conflicts_rejects_relative_path(
        self, manager: GitManager
    ) -> None:
        """has_conflicts rejects a relative worktree_path."""
        with pytest.raises(WorkspaceError, match="absolute"):
            await manager.has_conflicts(Path("relative/path"), "main")

    @pytest.mark.asyncio
    async def test_merge_worktree_rejects_relative_path(
        self, manager: GitManager
    ) -> None:
        """merge_worktree rejects a relative worktree_path."""
        with pytest.raises(WorkspaceError, match="absolute"):
            await manager.merge_worktree(Path("../evil"), target_branch="main")

    @pytest.mark.asyncio
    async def test_has_conflicts_rejects_nonexistent_path(
        self, manager: GitManager, tmp_path: Path
    ) -> None:
        """has_conflicts rejects a path that does not exist on disk."""
        nonexistent = tmp_path / "does-not-exist"
        with pytest.raises(WorkspaceError, match="not an existing directory"):
            await manager.has_conflicts(nonexistent, "main")

    @pytest.mark.asyncio
    async def test_merge_worktree_rejects_nonexistent_path(
        self, manager: GitManager, tmp_path: Path
    ) -> None:
        """merge_worktree rejects a path that does not exist on disk."""
        nonexistent = tmp_path / "ghost"
        with pytest.raises(WorkspaceError, match="not an existing directory"):
            await manager.merge_worktree(nonexistent, target_branch="main")

    @pytest.mark.asyncio
    async def test_has_conflicts_rejects_path_outside_repo(
        self, manager: GitManager, tmp_path: Path
    ) -> None:
        """has_conflicts rejects a real directory that is outside the repo root."""
        outside = tmp_path / "outside"
        outside.mkdir()
        with pytest.raises(WorkspaceError, match="not under repo root"):
            await manager.has_conflicts(outside, "main")

    @pytest.mark.asyncio
    async def test_merge_worktree_rejects_path_outside_repo(
        self, manager: GitManager, tmp_path: Path
    ) -> None:
        """merge_worktree rejects a real directory that is outside the repo root."""
        outside = tmp_path / "outside-dir"
        outside.mkdir()
        with pytest.raises(WorkspaceError, match="not under repo root"):
            await manager.merge_worktree(outside, target_branch="main")


# ---------------------------------------------------------------------------
# MergeStrategy.REBASE
# ---------------------------------------------------------------------------


class TestRebaseStrategy:
    """Tests for the corrected MergeStrategy.REBASE."""

    @pytest.mark.asyncio
    async def test_rebase_strategy_lands_commit_on_target(
        self, manager: GitManager, git_repo: Path
    ) -> None:
        """Rebase strategy replays worktree commits on target and updates HEAD."""
        wt_path = await manager.create_worktree("rebase-test", base_branch="main")
        # Add a new file in the worktree (no conflicts with main)
        (wt_path / "rebase_file.txt").write_text("rebased content")
        await manager.run_git("add", ".", cwd=wt_path)
        await manager.run_git("commit", "-m", "add rebase_file", cwd=wt_path)

        result_sha = await manager.merge_worktree(
            wt_path,
            target_branch="main",
            strategy=MergeStrategy.REBASE,
        )
        assert result_sha
        # The file should now be on main
        assert (git_repo / "rebase_file.txt").exists()
        assert (git_repo / "rebase_file.txt").read_text() == "rebased content"

    @pytest.mark.asyncio
    async def test_rebase_strategy_leaves_target_branch_checked_out(
        self, manager: GitManager, git_repo: Path
    ) -> None:
        """After a rebase merge, the main (target) branch is checked out."""
        wt_path = await manager.create_worktree("rebase-checkout", base_branch="main")
        (wt_path / "checkout_verify.txt").write_text("test")
        await manager.run_git("add", ".", cwd=wt_path)
        await manager.run_git("commit", "-m", "checkout verify", cwd=wt_path)

        await manager.merge_worktree(
            wt_path,
            target_branch="main",
            strategy=MergeStrategy.REBASE,
        )
        # Confirm we ended up on target branch
        branch = await manager.current_branch()
        assert branch == "main"
