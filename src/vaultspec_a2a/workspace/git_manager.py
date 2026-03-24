"""Git worktree lifecycle management for multi-agent isolation.

Provides async git operations with a global mutex to prevent `.git`
database corruption when multiple agents run concurrently (ADR-001).

All git commands are executed via ``asyncio.create_subprocess_exec``
to avoid blocking the Uvicorn event loop (ADR-008).
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..thread.errors import MergeConflictError, WorkspaceError

# Validates agent_id: must start with alphanumeric, contain only [a-zA-Z0-9_-].
# Prevents path traversal (../) and git flag injection (--flag).
_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

# Validates branch names: alphanumeric, hyphens, underscores, forward slashes.
# Prevents shell injection and git flag injection.
_BRANCH_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_/.-]*$")

# Index of first worktree entry in `git worktree list --porcelain` output.
# Entry 0 is metadata line "worktree <path>", entry 1 is main worktree (git
# lists main first), entry 2 marks the actual worktree we're processing.
_MAIN_WORKTREE_ENTRY_INDEX = 2


__all__ = [
    "GitManager",
    "MergeStrategy",
    "WorktreeInfo",
]

log = logging.getLogger(__name__)

# Global mutex serializing destructive repo-wide git operations (ADR-001 §2).
# M37/L22: asyncio.Lock() at module level is safe in Python 3.10+ (PEP 641);
# the deprecation warning was removed before Python 3.13.  No cross-loop risk
# since the orchestrator runs a single-process uvicorn event loop.
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

        Raises ``WorkspaceError`` if *agent_id* or *base_branch* contain
        characters that could be used for path traversal or git flag injection.
        """
        # --- Security: validate inputs before they touch the filesystem (C5) --
        if not _AGENT_ID_RE.match(agent_id):
            msg = (
                f"agent_id {agent_id!r} is invalid. "
                "Must match ^[a-zA-Z0-9][a-zA-Z0-9_-]*$"
            )
            raise WorkspaceError(msg)
        if not _BRANCH_NAME_RE.match(base_branch):
            msg = (
                f"base_branch {base_branch!r} is invalid. "
                "Must match ^[a-zA-Z0-9][a-zA-Z0-9_/.-]*$"
            )
            raise WorkspaceError(msg)
        # ----------------------------------------------------------------------

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

        Raises:
            ValueError: If *worktree_path* is not under the repository root.
        """
        # H12: validate that worktree_path is confined to the repo root to
        # prevent path traversal (e.g. "../../../etc") or git flag injection
        # (e.g. "--force").
        resolved = worktree_path.resolve()
        if not resolved.is_relative_to(self._root.resolve()):
            raise ValueError(
                f"Worktree path {worktree_path} is not under repo root {self._root}"
            )
        async with _git_mutex:
            await asyncio.shield(
                self._run_git("worktree", "remove", str(resolved), "--force")
            )
            await asyncio.shield(self._run_git("worktree", "prune"))
        log.info("Removed worktree at %s", worktree_path)

    async def list_worktrees(self) -> list[WorktreeInfo]:
        """List all active worktrees with metadata.

        ``git worktree list --porcelain`` always lists the main worktree first.
        The main worktree is identified by:
        - Being the first entry in the output (H20 fix: most reliable heuristic)
        - OR having the ``bare`` attribute (bare clones only)
        """
        raw = await self._run_git("worktree", "list", "--porcelain")
        if not raw:
            return []

        worktrees: list[WorktreeInfo] = []
        current_path: Path | None = None
        current_sha = ""
        current_branch = ""
        is_bare = False
        entry_index = 0

        for line in raw.splitlines():
            if line.startswith("worktree "):
                # Flush previous entry.
                # Increment entry_index BEFORE the flush so we know which
                # entry we're currently starting.  When flushing, entry_index
                # is the index of the NEW entry being parsed, meaning we are
                # flushing entry (entry_index - 1).  The main worktree is
                # entry 1 (the first entry), so it is flushed when
                # entry_index == 2 (we just started parsing entry 2).
                entry_index += 1
                if current_path is not None:
                    worktrees.append(
                        WorktreeInfo(
                            path=current_path,
                            branch=current_branch,
                            head_sha=current_sha,
                            # The flushed entry is #(entry_index - 1).
                            # is_main iff that entry is #1 (the first, main
                            # worktree listed by git porcelain).
                            is_main=(
                                entry_index == _MAIN_WORKTREE_ENTRY_INDEX or is_bare
                            ),
                        )
                    )
                current_path = Path(line.split(" ", 1)[1])
                current_sha = ""
                current_branch = ""
                is_bare = False
            elif line.startswith("HEAD "):
                current_sha = line.split(" ", 1)[1]
            elif line.startswith("branch "):
                # e.g. "branch refs/heads/main"
                ref = line.split(" ", 1)[1]
                current_branch = ref.removeprefix("refs/heads/")
            elif line == "bare":
                is_bare = True

        # WS-L3/WS-M2: Flush the last parsed entry.
        # entry_index is the count of entries whose "worktree " header line we
        # have seen so far.  When we flush the last entry, entry_index holds
        # the 1-based index of that entry in the porcelain output.
        # - entry_index == 1: only one worktree exists → it is the main worktree.
        # - entry_index > 1: multiple worktrees → the last entry is NOT the main
        #   worktree (the main worktree was already flushed with is_main=True).
        # Bare repos set is_bare=True, which also marks the entry as main.
        if current_path is not None:
            worktrees.append(
                WorktreeInfo(
                    path=current_path,
                    branch=current_branch,
                    head_sha=current_sha,
                    is_main=entry_index == 1 or is_bare,
                )
            )

        return worktrees

    # ------------------------------------------------------------------
    # Merge operations
    # ------------------------------------------------------------------

    def _validate_worktree_path(self, worktree_path: Path) -> Path:
        """Validate and resolve *worktree_path* for use in git operations.

        Ensures the path is absolute, resolves to a real directory, and is
        confined under the repository root to prevent path traversal attacks
        (WS-HIGH-001).

        Returns the resolved absolute path.
        Raises ``WorkspaceError`` if any constraint is violated.
        """
        if not worktree_path.is_absolute():
            msg = f"worktree_path must be an absolute path, got {worktree_path!r}"
            raise WorkspaceError(msg)
        resolved = worktree_path.resolve()
        if not resolved.is_dir():
            msg = f"worktree_path is not an existing directory: {worktree_path!r}"
            raise WorkspaceError(msg)
        if not resolved.is_relative_to(self._root.resolve()):
            msg = (
                f"worktree_path {worktree_path!r} is not under repo root {self._root!r}"
            )
            raise WorkspaceError(msg)
        return resolved

    async def has_conflicts(
        self,
        worktree_path: Path,
        target_branch: str,
    ) -> bool:
        """Predict merge conflicts without modifying any repository state.

        Uses ``git merge-tree`` (available since Git 2.38) for a
        zero-side-effect simulation of merging into *target_branch*.

        M30: Callers must hold ``_git_mutex`` to prevent TOCTOU races
        between the three ``rev-parse`` calls and any concurrent repo
        mutations.  ``merge_worktree`` acquires the mutex before calling
        this method (H21 fix).

        Raises ``WorkspaceError`` if *target_branch* or *worktree_path* is
        invalid to prevent git flag injection and path traversal (WS-C3,
        WS-HIGH-001).
        """
        # WS-HIGH-001: validate worktree_path before using as cwd
        worktree_path = self._validate_worktree_path(worktree_path)

        # WS-C3: validate target_branch before it touches any git command
        if not _BRANCH_NAME_RE.match(target_branch):
            msg = (
                f"target_branch {target_branch!r} is invalid. "
                "Must match ^[a-zA-Z0-9][a-zA-Z0-9_/.-]*$"
            )
            raise WorkspaceError(msg)

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
        Raises ``WorkspaceError`` if *target_branch* is invalid.
        The global mutex is held for the entire merge to prevent
        concurrent merges from corrupting the branch state.
        """
        # WS-HIGH-001: validate worktree_path before using as cwd
        worktree_path = self._validate_worktree_path(worktree_path)

        # WS-C3: validate target_branch before it touches any git command
        if not _BRANCH_NAME_RE.match(target_branch):
            msg = (
                f"target_branch {target_branch!r} is invalid. "
                "Must match ^[a-zA-Z0-9][a-zA-Z0-9_/.-]*$"
            )
            raise WorkspaceError(msg)

        wt_branch = await self._run_git(
            "rev-parse", "--abbrev-ref", "HEAD", cwd=worktree_path
        )
        # M22: handle detached HEAD — git returns literal "HEAD" for detached state
        if wt_branch == "HEAD":
            raise ValueError(
                f"Worktree at {worktree_path} is in detached HEAD state. "
                "Cannot merge a detached HEAD; checkout a named branch first."
            )

        async with _git_mutex:
            # H21: move the pre-flight conflict check inside the mutex to prevent
            # a TOCTOU race where another task modifies the repo between the
            # has_conflicts() check and the actual merge operation.
            if await self.has_conflicts(worktree_path, target_branch):
                msg = (
                    f"Merge of {wt_branch} into {target_branch} would produce "
                    f"conflicts. Manual resolution required."
                )
                raise MergeConflictError(msg)

            # shield() prevents task cancellation from leaving the repo
            # in a half-merged state (research finding: cancellation safety).
            await asyncio.shield(self._run_git("checkout", target_branch))

            if strategy == MergeStrategy.FAST_FORWARD:
                await asyncio.shield(self._run_git("merge", "--ff-only", wt_branch))
            elif strategy == MergeStrategy.REBASE:
                # WS-H7: correct rebase semantics for merging a worktree branch
                # back into target_branch.
                #
                # The worktree's branch is already checked out in worktree_path,
                # so we can't `git checkout wt_branch` in the main repo (git
                # disallows checking out a branch that's live in another worktree).
                #
                # Instead, run `git rebase target_branch` from within the worktree
                # directory — this rebases the worktree's branch (wt_branch) onto
                # target_branch, replaying wt commits on top of target.
                # Then, from the main repo (already on target_branch), fast-forward
                # merge the rebased wt_branch tip.
                #
                # The previous code ran `git rebase wt_branch` while on
                # target_branch in the main repo, which rebased target onto the
                # worktree branch — the inverse of the intended direction.
                await asyncio.shield(
                    self._run_git("rebase", target_branch, cwd=worktree_path)
                )
                await asyncio.shield(self._run_git("merge", "--ff-only", wt_branch))
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
        # End of _git_mutex block

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
