"""Universal Rule Propagation — RuleManager (ADR-028).

Discovers and compiles project-level coding rules from
``.vaultspec/rules/*.md`` into a single string for injection
into LLM system prompts.

References:
    - ADR-028: Universal Rule Propagation
"""

import contextlib
import logging
from pathlib import Path

__all__ = ["RuleManager"]

_logger = logging.getLogger(__name__)

# The rule corpus lives FLAT directly under ``.vaultspec/rules/`` in the current
# vaultspec-core schema; there is no nested ``rules/rules/`` directory. Aligned
# forward to that schema with no dual-read fallback (ADR-028 / graph-agent-
# framework-harness P02.S13).
_RULES_SUBDIR = Path(".vaultspec") / "rules"


class RuleManager:
    """Discovers and compiles ``.vaultspec/rules/*.md`` rule files.

    Args:
        workspace_root:  Absolute path to the project workspace root.
        include_builtin: When ``True``, include ``*.builtin.md`` files that
                         are normally excluded (they are scaffold/IDE files,
                         not project-specific rules).
    """

    def __init__(self, workspace_root: Path, *, include_builtin: bool = False) -> None:
        """Set up rule discovery rooted at *workspace_root*."""
        self._workspace_root = workspace_root.resolve()
        self._include_builtin = include_builtin

        # mtime-based compile cache (HIGH-01)
        self._cached_result: str | None = None
        self._cache_valid: bool = False
        self._cached_dir_mtime: float = 0.0
        self._cached_file_mtimes: dict[Path, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover(self) -> list[Path]:
        """Return a sorted list of rule file paths.

        Searches ``<workspace_root>/.vaultspec/rules/`` for ``*.md``
        files.  Files ending in ``.builtin.md`` are excluded unless
        ``include_builtin=True`` was passed at construction.

        Returns:
            Sorted list of absolute ``Path`` objects; empty list if the
            directory does not exist or contains no matching files.
        """
        rules_dir = self._workspace_root / _RULES_SUBDIR
        if not rules_dir.is_dir():
            return []

        paths = []
        for p in rules_dir.glob("*.md"):
            if not self._include_builtin and p.name.endswith(".builtin.md"):
                continue
            paths.append(p)

        return sorted(paths)

    def compile(self) -> str | None:
        """Compile all discovered rule files into a single string.

        Uses a two-tier mtime cache (HIGH-01):
        1. Directory mtime check (single stat) to detect added/removed files
        2. Per-file mtime check to detect content edits
        Returns cached result if nothing changed.

        Processes each file in :meth:`discover` order:

        * Strips YAML frontmatter (``---`` block at file start)
        * Resolves ``@include`` directives
        * Concatenates results with double newlines

        Returns:
            Combined rule text, or ``None`` if no rules exist or all
            content is empty after processing.
        """
        if self._cache_valid and not self._has_changes():
            return self._cached_result

        paths = self.discover()
        if not paths:
            self._cached_result = None
            self._cache_valid = True
            self._cached_file_mtimes = {}
            return None

        seen: set[Path] = set()
        parts: list[str] = []

        for path in paths:
            content = self._process_file(path, seen)
            stripped = content.strip()
            if stripped:
                parts.append(stripped)

        result = "\n\n".join(parts) if parts else None

        # Update cache state
        self._cached_result = result
        self._cache_valid = True
        rules_dir = self._workspace_root / _RULES_SUBDIR
        try:
            self._cached_dir_mtime = rules_dir.stat().st_mtime
        except OSError:
            self._cached_dir_mtime = 0.0
        self._cached_file_mtimes = {}
        for p in paths:
            with contextlib.suppress(OSError):
                self._cached_file_mtimes[p] = p.stat().st_mtime

        return result

    def invalidate(self) -> None:
        """Clear the compile cache, forcing a full recompile on next call."""
        self._cache_valid = False
        self._cached_result = None
        self._cached_dir_mtime = 0.0
        self._cached_file_mtimes = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _has_changes(self) -> bool:
        """Check if the rules directory or any cached file has changed.

        Tier 1: single stat on the rules directory detects added/removed files.
        Tier 2: per-file mtime check detects content edits.
        """
        rules_dir = self._workspace_root / _RULES_SUBDIR
        try:
            dir_mtime = rules_dir.stat().st_mtime
        except OSError:
            # Directory gone — if we had cached files, that's a change
            return bool(self._cached_file_mtimes)

        if dir_mtime != self._cached_dir_mtime:
            return True

        for path, cached_mtime in self._cached_file_mtimes.items():
            try:
                if path.stat().st_mtime != cached_mtime:
                    return True
            except OSError:
                return True  # file removed

        return False

    def _process_file(self, path: Path, seen: set[Path]) -> str:
        """Read, strip frontmatter, and resolve @includes for one file."""
        resolved = path.resolve()
        if resolved in seen:
            return ""
        seen.add(resolved)

        try:
            raw = resolved.read_text(encoding="utf-8")
        except OSError:
            _logger.warning("Could not read rule file %s", resolved)
            return ""

        content = _strip_frontmatter(raw)
        return self._resolve_includes(content, resolved.parent, seen)

    def _resolve_includes(
        self,
        content: str,
        base_dir: Path,
        seen: set[Path],
    ) -> str:
        """Replace ``@path`` directives with the referenced file's content.

        Resolution order:
        1. Relative to ``base_dir`` (the including file's directory)
        2. Relative to ``workspace_root``

        Lines starting with ``@http://`` or ``@https://`` are passed through
        unchanged (not treated as includes).
        Backslashes in paths are normalised to forward slashes.

        Security: the resolved path must remain inside ``workspace_root``.
        Cycle detection: files already in ``seen`` are skipped.
        Included content is wrapped in HTML comments for traceability.
        """
        lines = content.splitlines()
        result: list[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("@"):
                include_ref = stripped[1:].strip()
                # Skip URL includes — pass through as-is
                if include_ref.startswith(("http://", "https://")):
                    result.append(line)
                else:
                    result.append(self._expand_include(include_ref, base_dir, seen))
            else:
                result.append(line)

        return "\n".join(result)

    def _expand_include(
        self,
        ref: str,
        base_dir: Path,
        seen: set[Path],
    ) -> str:
        """Resolve a single include reference and return its content."""
        # Normalise backslashes to forward slashes
        ref = ref.replace("\\", "/")

        # Try relative to including file's directory first
        candidate = (base_dir / ref).resolve()
        if not candidate.is_file():
            # Fallback: relative to workspace_root
            candidate = (self._workspace_root / ref).resolve()

        # Security boundary — must stay inside workspace_root
        try:
            candidate.relative_to(self._workspace_root)
        except ValueError:
            _logger.warning(
                "Include %r resolves outside workspace_root %s — skipping",
                ref,
                self._workspace_root,
            )
            return f"<!-- ERROR: Path outside workspace: {ref} -->"

        if not candidate.is_file():
            return f"<!-- ERROR: Missing include: {ref} -->"

        inner = self._process_file(candidate, seen)
        display = ref
        return f"<!-- Included from {display} -->\n{inner}\n<!-- End of {display} -->"


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter from the start of a file.

    If the content begins with a ``---`` line, everything up to and
    including the closing ``---`` line is removed.
    """
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return content

    # Find the closing ---
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            # Return everything after the closing ---
            return "\n".join(lines[i + 1 :])

    # No closing --- found — return content unchanged
    return content
