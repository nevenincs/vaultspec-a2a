"""Universal Rule Propagation — RuleManager (ADR-028).

Discovers and compiles project-level coding rules from
``.vaultspec/rules/rules/*.md`` into a single string for injection
into LLM system prompts.

References:
    - ADR-028: Universal Rule Propagation
"""

import logging

from pathlib import Path


__all__ = ["RuleManager"]

_logger = logging.getLogger(__name__)

_RULES_SUBDIR = Path(".vaultspec") / "rules" / "rules"


class RuleManager:
    """Discovers and compiles ``.vaultspec/rules/rules/*.md`` rule files.

    Args:
        workspace_root:  Absolute path to the project workspace root.
        include_builtin: When ``True``, include ``*.builtin.md`` files that
                         are normally excluded (they are scaffold/IDE files,
                         not project-specific rules).
    """

    def __init__(self, workspace_root: Path, *, include_builtin: bool = False) -> None:
        self._workspace_root = workspace_root.resolve()
        self._include_builtin = include_builtin

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover(self) -> list[Path]:
        """Return a sorted list of rule file paths.

        Searches ``<workspace_root>/.vaultspec/rules/rules/`` for ``*.md``
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

        Processes each file in :meth:`discover` order:

        * Strips YAML frontmatter (``---`` block at file start)
        * Resolves ``@include`` directives
        * Concatenates results with double newlines

        Returns:
            Combined rule text, or ``None`` if no rules exist or all
            content is empty after processing.
        """
        paths = self.discover()
        if not paths:
            return None

        seen: set[Path] = set()
        parts: list[str] = []

        for path in paths:
            content = self._process_file(path, seen)
            stripped = content.strip()
            if stripped:
                parts.append(stripped)

        if not parts:
            return None

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
                if include_ref.startswith("http://") or include_ref.startswith("https://"):
                    result.append(line)
                else:
                    result.append(
                        self._expand_include(include_ref, base_dir, seen)
                    )
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
