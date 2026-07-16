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

import yaml

__all__ = ["RuleManager"]

_logger = logging.getLogger(__name__)

# The rule corpus lives FLAT directly under ``.vaultspec/rules/`` in the current
# vaultspec-core schema; there is no nested ``rules/rules/`` directory. Aligned
# forward to that schema with no dual-read fallback (ADR-028 / graph-agent-
# framework-harness P02.S13).
_RULES_SUBDIR = Path(".vaultspec") / "rules"

# Bundled rule defaults shipped inside the a2a package (tracked under ``src/``,
# unlike the gitignored workspace ``.vaultspec/``). A run's workspace copies SHADOW
# these bundled defaults name-for-name - a2a's own bundled-default + workspace-
# override convention, mirroring ``team_config``'s preset resolution
# (graph-agent-framework-harness P02.S03; agent-harness-provisioning-adr's
# workspace-over-bundled principle). Opt-in: a caller passes this directory as
# ``bundled_rules_dir`` (the two graph call sites do); ``RuleManager`` defaults to
# workspace-only so unrelated construction is unaffected.
DEFAULT_BUNDLED_RULES_DIR = Path(__file__).parent / "presets" / "rules"


class RuleManager:
    """Discovers and compiles vaultspec rule files into an LLM system message.

    Reads the flat ``<workspace_root>/.vaultspec/rules/*.md`` corpus and, when a
    ``bundled_rules_dir`` is given, unions it with the a2a-shipped bundled
    defaults - a workspace file SHADOWS a bundled file of the same name entirely
    (no merging), mirroring ``team_config``'s preset resolution.

    Args:
        workspace_root:    Absolute path to the project workspace root.
        include_builtin:   When ``True``, include ``*.builtin.md`` files that are
                           normally excluded (scaffold/IDE files, not project rules).
        bundled_rules_dir: Optional directory of bundled default rules unioned under
                           (shadowed by) the workspace corpus; ``None`` (default) is
                           workspace-only. The graph call sites pass
                           :data:`DEFAULT_BUNDLED_RULES_DIR`.
    """

    def __init__(
        self,
        workspace_root: Path,
        *,
        include_builtin: bool = False,
        bundled_rules_dir: Path | None = None,
    ) -> None:
        """Set up rule discovery rooted at *workspace_root*."""
        self._workspace_root = workspace_root.resolve()
        self._include_builtin = include_builtin
        self._bundled_rules_dir = (
            bundled_rules_dir.resolve() if bundled_rules_dir is not None else None
        )

        # mtime-based compile cache (HIGH-01), keyed by the requested role so a
        # role-scoped turn and a whole-corpus turn never serve each other's
        # compiled string (graph-agent-framework-harness P02.S04). The mtime
        # snapshot watches the FULL corpus across BOTH source dirs, so any rule-file
        # change drops every role's cached entry at once.
        self._cached_results: dict[str | None, str | None] = {}
        self._cache_valid: bool = False
        self._cached_dir_mtimes: dict[Path, float] = {}
        self._cached_file_mtimes: dict[Path, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover(self, role: str | None = None) -> list[Path]:
        """Return a sorted list of rule file paths.

        Searches ``<workspace_root>/.vaultspec/rules/`` for ``*.md``
        files.  Files ending in ``.builtin.md`` are excluded unless
        ``include_builtin=True`` was passed at construction.

        When *role* is given, the result is RESTRICTED to files whose ``roles:``
        frontmatter list includes that role - a document-authoring turn passes its
        persona role and receives only the rules opted in to it, instead of the
        whole corpus (graph-agent-framework-harness P02.S04). Scoping is opt-in and
        restrictive: a file with no ``roles:`` key is not role-scoped and is
        excluded from a scoped turn, so scoping never requires editing the
        vaultspec-core-managed corpus. When *role* is ``None`` the filter is off
        and every non-builtin file is returned (the unchanged whole-corpus path).

        A ``bundled_rules_dir`` (when set) is unioned UNDER the workspace corpus: a
        workspace file SHADOWS a bundled file of the same name entirely (resolved by
        name before any builtin/role filter), so the workspace override wins even if
        it opts into a different role set - mirroring ``team_config``'s preset
        resolution (P02.S03).

        Returns:
            Sorted list of absolute ``Path`` objects; empty list if no source
            directory exists or nothing matches.
        """
        # Resolve the effective file per name first: bundled defaults, then the
        # workspace corpus which shadows them name-for-name (later source wins).
        by_name: dict[str, Path] = {}
        for source in self._rule_source_dirs():
            for p in source.glob("*.md"):
                by_name[p.name] = p

        paths = []
        for name, p in by_name.items():
            if not self._include_builtin and name.endswith(".builtin.md"):
                continue
            if role is not None and role not in _read_frontmatter_roles(p):
                continue
            paths.append(p)

        return sorted(paths)

    def _rule_source_dirs(self) -> list[Path]:
        """Existing rule source dirs, bundled first then workspace (workspace wins).

        Order is load-bearing: :meth:`discover` resolves same-named files by keeping
        the LAST source, so the workspace corpus must come after the bundled defaults
        to shadow them.
        """
        candidates = [self._bundled_rules_dir, self._workspace_root / _RULES_SUBDIR]
        return [d for d in candidates if d is not None and d.is_dir()]

    def compile(self, role: str | None = None) -> str | None:
        """Compile the discovered rule files into a single string.

        Uses a two-tier mtime cache (HIGH-01):
        1. Directory mtime check (single stat) to detect added/removed files
        2. Per-file mtime check to detect content edits
        Returns the cached result if nothing changed.

        When *role* is given, only rules opted in to that role are compiled (see
        :meth:`discover`); results are cached PER ROLE so a scoped turn and a
        whole-corpus turn never serve each other's string. The mtime snapshot
        watches the full corpus, so any rule-file change invalidates every role's
        cached entry at once (graph-agent-framework-harness P02.S04).

        Processes each file in :meth:`discover` order:

        * Strips YAML frontmatter (``---`` block at file start)
        * Resolves ``@include`` directives
        * Concatenates results with double newlines

        Returns:
            Combined rule text, or ``None`` if no rules exist for this role or all
            content is empty after processing.
        """
        if not self._cache_valid or self._has_changes():
            self._cached_results = {}
            self._cache_valid = True
            self._snapshot_mtimes()

        if role in self._cached_results:
            return self._cached_results[role]

        paths = self.discover(role)
        if not paths:
            self._cached_results[role] = None
            return None

        seen: set[Path] = set()
        parts: list[str] = []

        for path in paths:
            content = self._process_file(path, seen)
            stripped = content.strip()
            if stripped:
                parts.append(stripped)

        result = "\n\n".join(parts) if parts else None
        self._cached_results[role] = result
        return result

    def invalidate(self) -> None:
        """Clear the compile cache, forcing a full recompile on next call."""
        self._cache_valid = False
        self._cached_results = {}
        self._cached_dir_mtimes = {}
        self._cached_file_mtimes = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _snapshot_mtimes(self) -> None:
        """Snapshot dir + per-file mtimes over the FULL corpus for change detection.

        Role-independent by design: the snapshot always covers every discoverable
        rule file across BOTH source dirs (role filter off), so a change to ANY rule
        file is seen by :meth:`_has_changes` regardless of which role's cached result
        is being served, and every role entry is dropped together.
        """
        self._cached_dir_mtimes = {}
        for source in self._rule_source_dirs():
            with contextlib.suppress(OSError):
                self._cached_dir_mtimes[source] = source.stat().st_mtime
        self._cached_file_mtimes = {}
        for p in self.discover(None):
            with contextlib.suppress(OSError):
                self._cached_file_mtimes[p] = p.stat().st_mtime

    def _has_changes(self) -> bool:
        """Check if any rule source dir or cached file has changed.

        Tier 1: a stat on each source directory (bundled + workspace) detects
        added/removed files, including a source dir appearing or disappearing.
        Tier 2: per-file mtime check detects content edits.
        """
        # Tier 1: check every directory we snapshotted AND every one that exists now,
        # so an appearing OR disappearing source dir both register as a change.
        candidate_dirs = set(self._cached_dir_mtimes) | set(self._rule_source_dirs())
        for source in candidate_dirs:
            try:
                dir_mtime = source.stat().st_mtime
            except OSError:
                dir_mtime = None
            if dir_mtime != self._cached_dir_mtimes.get(source):
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


def _read_frontmatter_roles(path: Path) -> frozenset[str]:
    """Return the ``roles:`` set declared in a rule file's YAML frontmatter.

    Reads only the leading ``---``-delimited frontmatter block and extracts a
    ``roles:`` sequence (or a bare string) of role names. Returns an empty set
    when the file has no frontmatter, no ``roles:`` key, or an unreadable or
    malformed block - a file that opts in to no role is simply not role-scoped and
    is skipped by a scoped :meth:`RuleManager.discover`. The compile path still
    strips the whole frontmatter afterwards via :func:`_strip_frontmatter`.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return frozenset()
    block: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        block.append(line)
    else:
        return frozenset()  # no closing fence — not valid frontmatter
    try:
        meta = yaml.safe_load("\n".join(block))
    except yaml.YAMLError:
        return frozenset()
    if not isinstance(meta, dict):
        return frozenset()
    roles = meta.get("roles")
    if isinstance(roles, str):
        return frozenset({roles})
    if isinstance(roles, list):
        return frozenset(item for item in roles if isinstance(item, str))
    return frozenset()


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
