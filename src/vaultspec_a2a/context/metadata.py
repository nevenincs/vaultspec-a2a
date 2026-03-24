"""Thread metadata and context discovery for ADR-014.

Provides the ``ThreadMetadata`` and ``ContextRef`` models for thread
provenance tracking, plus utilities for auto-discovering ``.vault/``
documents and generating human-friendly thread nicknames.

References:
    - ADR-014: Thread Metadata & Context Injection
    - ADR-012 §2.8: Workspace-local TOML overrides
"""

import glob
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from vaultspec_a2a.domain_config import domain_config

__all__ = [
    "ContextRef",
    "ThreadMetadata",
    "discover_context_refs",
    "generate_nickname",
]

# Nickname slug: lowercase alphanumeric + hyphens, 3-64 characters.
_NICKNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$")


class ContextRef(BaseModel):
    """Reference to a context document in the .vault hierarchy."""

    path: str
    stage: str
    summary: str = ""

    @field_validator("path")
    @classmethod
    def path_must_be_relative(cls, v: str) -> str:
        """Reject absolute paths — context refs are relative to workspace_root."""
        if Path(v).is_absolute():
            msg = f"ContextRef path must be relative, got absolute: {v!r}"
            raise ValueError(msg)
        return v


class ThreadMetadata(BaseModel):
    """Provenance and context attached to an orchestration thread."""

    # --- Identity ---
    nickname: str = ""

    # --- Provenance ---
    workspace_root: str
    source_repo: str = ""
    source_branch: str = ""
    callee: str = ""

    # --- SDD Pipeline Context ---
    feature_tag: str = ""
    context_refs: list[ContextRef] = Field(default_factory=list)

    @field_validator("nickname")
    @classmethod
    def nickname_must_be_valid_slug(cls, v: str) -> str:
        """Validate nickname as a slug: lowercase alphanumeric + hyphens, 3-64 chars."""
        if v and not _NICKNAME_PATTERN.match(v):
            msg = (
                f"nickname must be a valid slug (lowercase alphanumeric + hyphens, "
                f"3-64 chars), got: {v!r}"
            )
            raise ValueError(msg)
        return v

    @field_validator("workspace_root")
    @classmethod
    def workspace_root_must_be_absolute(cls, v: str) -> str:
        """Workspace root must be an absolute path."""
        if not Path(v).is_absolute():
            msg = f"workspace_root must be an absolute path, got: {v!r}"
            raise ValueError(msg)
        return v


def discover_context_refs(
    workspace_root: Path,
    feature_tag: str,
) -> list[ContextRef]:
    """Scan .vault/ for documents matching the feature tag.

    Uses filename-based glob discovery (O(1) filesystem calls per stage
    pattern). Returns at most ``settings.max_context_refs`` results.

    Args:
        workspace_root: Absolute path to the workspace directory.
        feature_tag: The feature grouping key (e.g. ``"auth-flow"``).

    Returns:
        A list of ``ContextRef`` instances for matching documents.
    """
    refs: list[ContextRef] = []
    stage_patterns: dict[str, str] = {
        "research": ".vault/research/*{tag}*.md",
        "reference": ".vault/reference/*{tag}*.md",
        "adr": ".vault/adr/*{tag}*.md",
        "plan": ".vault/plan/*{tag}*.md",
        "exec": ".vault/exec/*{tag}*/**/*.md",
        "audit": ".vault/audit/*{tag}*.md",
    }
    # C3: sanitize feature_tag by escaping glob metacharacters before injecting
    # it into the pattern.  glob.escape() quotes *, ?, [, ] so they are treated
    # as literal characters rather than glob wildcards.  This prevents crafted
    # feature_tag values (e.g. "../../secret", "*.py") from matching unintended
    # paths during .vault/ auto-discovery.
    safe_tag = glob.escape(feature_tag) if feature_tag else ""
    for stage, pattern in stage_patterns.items():
        resolved = pattern.replace("{tag}", safe_tag)
        try:
            matches = sorted(workspace_root.glob(resolved))
        except (OSError, UnicodeDecodeError):
            # M9: handle encoding errors in filenames on exotic filesystems
            continue
        for match in matches:
            try:
                rel_path = str(match.relative_to(workspace_root))
            except ValueError:
                continue
            refs.append(ContextRef(path=rel_path, stage=stage))
            if len(refs) >= domain_config.max_context_refs:
                return refs
    return refs


def generate_nickname(
    feature_tag: str,
    topology: str,
    thread_id: str,
) -> str:
    """Generate a human-friendly thread nickname.

    Format: ``{feature_tag}-{topology}-{4-char-hex}``
    Example: ``"auth-flow-star-a3f2"``

    Args:
        feature_tag: The feature grouping key.
        topology: The topology type (e.g. ``"star"``, ``"pipeline"``).
        thread_id: The thread UUID (first 4 chars used as suffix).

    Returns:
        A nickname string conforming to the slug pattern.
    """
    # H2: Guard against empty/short thread_id producing trailing-hyphen slugs
    # that violate _NICKNAME_PATTERN (must end with [a-z0-9]).
    short_hash = thread_id[:4] if thread_id else "0000"
    if not short_hash:
        short_hash = "0000"
    # M1: sanitize feature_tag — lowercase and strip all non-alphanumeric-hyphen
    # characters so the generated nickname always satisfies _NICKNAME_PATTERN.
    # Uppercase feature_tags would fail ThreadMetadata validation without this.
    if feature_tag:
        tag = feature_tag.lower()
        # Strip characters that are not alphanumeric or hyphen
        tag = re.sub(r"[^a-z0-9\-]", "", tag)
        # Collapse consecutive hyphens and strip leading/trailing hyphens
        tag = re.sub(r"-{2,}", "-", tag).strip("-")
    else:
        tag = ""
    if tag:
        return f"{tag}-{topology}-{short_hash}"
    return f"thread-{topology}-{short_hash}"
