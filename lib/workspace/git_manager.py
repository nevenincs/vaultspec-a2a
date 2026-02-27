"""Git worktree lifecycle management for multi-agent isolation.

Provides async git operations with a global mutex to prevent `.git`
database corruption when multiple agents run concurrently (ADR-001).

All git commands are executed via ``asyncio.create_subprocess_exec``
to avoid blocking the Uvicorn event loop (ADR-008).
"""

import asyncio
import logging

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..core.exceptions import MergeConflictError, WorkspaceError


__all__ = [
    "GitManager",
    "MergeStrategy",
    "WorktreeInfo",
]

log = logging.getLogger(__name__)

# Global mutex serializing destructive repo-wide git operations (ADR-001 §2).
_git_mutex = asyncio.Lock()


class MergeStrategy(StrEnum):
    """Supported strategies for merging a worktree back into its target."""

    FAST_FORWARD = "ff"
    REBASE = "rebase"
    MERGE_COMMIT = "merge"


@dataclass(frozen=True, slots=True)
class WorktreeInfo:
    """Metadata for a single git worktree."""

    path: Path
    branch: str
    head_sha: str
    is_main: bool


class GitManager:
    """Async git worktree manager with a global mutex.

    Parameters
    ----------
    repo_root:
        Absolute path to the main repository checkout. All worktree
        operations are relative to this root's ``.git`` directory.
    """

    def __init__(self, repo_root: Path) -> None:
        """Initialise GitManager rooted at *repo_root* (must be an absolute path)."""
        if not repo_root.is_absolute():
            msg = f"repo_root must be an absolute path, got {repo_root}"
            raise WorkspaceError(msg)
        self._root = repo_root

    @property
    def repo_root(self) -> Path:
        """Return the absolute path to the main repository checkout."""
        return self._root

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_git(
        self,
        *args: str,
        cwd: Path | None = None,
        check: bool = True,
    ) -> str:
        """Run a git command asynchronously and return stripped stdout.

        Raises ``WorkspaceError`` when *check* is True and the process
        exits with a non-zero code.
        """
        cmd = ["git", *args]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd or self._root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

        if check and proc.returncode != 0:
            msg = f"git {' '.join(args)} failed (rc={proc.returncode}): {stderr}"
            raise WorkspaceError(msg)

        if stderr:
            log.debug("git stderr: %s", stderr)

        return stdout

    async def run_git(
        self,
        *args: str,
        cwd: Path | None = None,
        check: bool = True,
    ) -> str:
        """Public entry point for running an arbitrary git command.

        Delegates to the internal ``_run_git`` helper.  Intended for use in
        tests and integration code that needs to issue ad-hoc git commands
        (e.g. ``add`` and ``commit`` inside a worktree) without reaching into
        private implementation details.
        """
        return await self._run_git(*args, cwd=cwd, check=check)

    # ------------------------------------------------------------------
    # Worktree lifecycle
    # ------------------------------------------------------------------

    async def create_worktree(
        self,
        agent_id: str,
        base_branch: str = "main",
    ) -> Path:
        """Create an isolated git worktree for an agent.

        Branch naming convention: ``agent/{agent_id}`` (ADR-001).
        The worktree directory is placed under ``agent/`` relative to
        the repository root.

        The global mutex is held for the duration of the checkout to
        prevent concurrent ``git worktree add`` from corrupting the
        ``.git`` index.
        """
        branch_name = f"agent/{agent_id}"
        worktree_path = self._root / "agent" / agent_id

        async with _git_mutex:
            # shield() prevents task cancellation from corrupting .git
            # state mid-operation (research finding: cancellation safety).
            await asyncio.shield(self._run_git("rev-parse", "--verify", base_branch))
            await asyncio.shield(
                self._run_git(
                    "worktree",
                    "add",
                    "-b",
                    branch_name,
                    str(worktree_path),
                    base_branch,
                )
            )

        log.info("Created worktree at %s (branch %s)", worktree_path, branch_name)
        return worktree_path

    async def remove_worktree(self, worktree_path: Path) -> None:
        """Remove a worktree and prune its tracking metadata.

        This is a **manual** operation — never called automatically
        (ADR-001: preserve forensic state).

        The global mutex is held to prevent concurrent prune/remove
        from corrupting the ``.git/worktrees/`` registry.
        """
        async with _git_mutex:
            await asyncio.shield(
                self._run_git("worktree", "remove", str(worktree_path), "--force")
            )
            await asyncio.shield(self._run_git("worktree", "prune"))
        log.info("Removed worktree at %s", worktree_path)

    async def list_worktrees(self) -> list[WorktreeInfo]:
        """List all active worktrees with metadata."""
        raw = await self._run_git("worktree", "list", "--porcelain")
        if not raw:
            return []

        worktrees: list[WorktreeInfo] = []
        current_path: Path | None = None
        current_sha = ""
        current_branch = ""
        is_main = False

        for line in raw.splitlines():
            if line.startswith("worktree "):
                # Flush previous entry
                if current_path is not None:
                    worktrees.append(
                        WorktreeInfo(
                            path=current_path,
                            branch=current_branch,
                            head_sha=current_sha,
                            is_main=is_main,
                        )
                    )
                current_path = Path(line.split(" ", 1)[1])
                current_sha = ""
                current_branch = ""
                is_main = False
            elif line.startswith("HEAD "):
                current_sha = line.split(" ", 1)[1]
            elif line.startswith("branch "):
                # e.g. "branch refs/heads/main"
                ref = line.split(" ", 1)[1]
                current_branch = ref.removeprefix("refs/heads/")
            elif line == "bare":
                is_main = True

        # Flush last entry
        if current_path is not None:
            worktrees.append(
                WorktreeInfo(
                    path=current_path,
                    branch=current_branch,
                    head_sha=current_sha,
                    is_main=is_main,
                )
            )

        return worktrees

    # ------------------------------------------------------------------
    # Merge operations
    # ------------------------------------------------------------------

    async def has_conflicts(
        self,
        worktree_path: Path,
        target_branch: str,
    ) -> bool:
        """Predict merge conflicts without modifying any repository state.

        Uses ``git merge-tree`` (available since Git 2.38) for a
        zero-side-effect simulation of merging into *target_branch*.
        """
        # Resolve the worktree's current branch
        wt_branch = await self._run_git(
            "rev-parse", "--abbrev-ref", "HEAD", cwd=worktree_path
        )
        target_sha = await self._run_git("rev-parse", target_branch)
        wt_sha = await self._run_git("rev-parse", wt_branch)

        # merge-tree writes to stdout and exits 0 on clean, 1 on conflict
        proc = await asyncio.create_subprocess_exec(
            "git",
            "merge-tree",
            "--write-tree",
            target_sha,
            wt_sha,
            cwd=str(self._root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode != 0

    async def merge_worktree(
        self,
        worktree_path: Path,
        target_branch: str = "main",
        strategy: MergeStrategy = MergeStrategy.FAST_FORWARD,
    ) -> str:
        """Merge a worktree's branch back into *target_branch*.

        Returns the resulting merge commit SHA.

        Raises ``MergeConflictError`` if conflicts are detected.
        The global mutex is held for the entire merge to prevent
        concurrent merges from corrupting the branch state.
        """
        wt_branch = await self._run_git(
            "rev-parse", "--abbrev-ref", "HEAD", cwd=worktree_path
        )

        # Pre-flight conflict check
        if await self.has_conflicts(worktree_path, target_branch):
            msg = (
                f"Merge of {wt_branch} into {target_branch} would produce "
                f"conflicts. Manual resolution required."
            )
            raise MergeConflictError(msg)

        async with _git_mutex:
            # shield() prevents task cancellation from leaving the repo
            # in a half-merged state (research finding: cancellation safety).
            await asyncio.shield(self._run_git("checkout", target_branch))

            if strategy == MergeStrategy.FAST_FORWARD:
                await asyncio.shield(self._run_git("merge", "--ff-only", wt_branch))
            elif strategy == MergeStrategy.REBASE:
                await asyncio.shield(self._run_git("rebase", wt_branch))
            elif strategy == MergeStrategy.MERGE_COMMIT:
                await asyncio.shield(
                    self._run_git(
                        "merge",
                        "--no-ff",
                        "-m",
                        f"Merge {wt_branch} into {target_branch}",
                        wt_branch,
                    )
                )

            result_sha = await asyncio.shield(self._run_git("rev-parse", "HEAD"))

        log.info(
            "Merged %s into %s (strategy=%s) -> %s",
            wt_branch,
            target_branch,
            strategy.value,
            result_sha[:12],
        )
        return result_sha

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    async def current_branch(self, cwd: Path | None = None) -> str:
        """Return the currently checked-out branch name."""
        return await self._run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)

    async def head_sha(self, cwd: Path | None = None) -> str:
        """Return the HEAD commit SHA."""
        return await self._run_git("rev-parse", "HEAD", cwd=cwd)
