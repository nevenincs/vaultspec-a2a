"""Thread metadata and context discovery.

Provides the ``ThreadMetadata`` and ``ContextRef`` models for thread
provenance tracking, plus utilities for auto-discovering ``.vault/``
documents and generating human-friendly thread nicknames.
"""

import glob
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from ..domain_config import domain_config
from ..thread import sha256_hex
from ..thread.constants import (
    MAX_CALLEE_CHARS,
    MAX_FEEDBACK_BATCH_ID_CHARS,
    MAX_SOURCE_BRANCH_CHARS,
)
from .stage import VAULT_STAGE_PATTERNS

__all__ = [
    "MAX_NICKNAME_SLUG_CHARS",
    "ContextRef",
    "ThreadMetadata",
    "discover_context_refs",
    "generate_nickname",
]

MAX_NICKNAME_SLUG_CHARS: int = 64
"""Longest nickname slug, for the generator and the validator alike.

Declared once because the generator has to fit inside the bound the validator
enforces, and the two are the same fact: a generator that merely concatenated
its inputs produced a nickname the model then refused, which is what the
``feature_tag`` column's much wider bound makes reachable.
"""

# Nickname slug: lowercase alphanumeric + hyphens, 3 to the bound above.
_NICKNAME_PATTERN = re.compile(
    rf"^[a-z0-9][a-z0-9\-]{{1,{MAX_NICKNAME_SLUG_CHARS - 2}}}[a-z0-9]$"
)


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
    source_branch: str = Field(default="", max_length=MAX_SOURCE_BRANCH_CHARS)
    callee: str = Field(default="", max_length=MAX_CALLEE_CHARS)
    continues_run_id: str | None = None

    # --- SDD Pipeline Context ---
    feature_tag: str = ""
    context_refs: list[ContextRef] = Field(default_factory=list)
    # feedback-loop: an OPAQUE engine feedback-batch id for a revision run,
    # persisted so a worker restart re-retrieves the same batch. a2a transports
    # the id only and never owns batch content; empty when the run
    # is not feedback-driven.
    feedback_batch_id: str = Field(default="", max_length=MAX_FEEDBACK_BATCH_ID_CHARS)

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
    pattern). Returns at most ``domain_config.max_context_refs`` results.

    Args:
        workspace_root: Absolute path to the workspace directory.
        feature_tag: The feature grouping key (e.g. ``"auth-flow"``).

    Returns:
        A list of ``ContextRef`` instances for matching documents.
    """
    refs: list[ContextRef] = []
    stage_patterns = VAULT_STAGE_PATTERNS
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


def _slug_segment(value: str) -> str:
    """Reduce one nickname segment to the slug grammar.

    Every run of characters the grammar forbids becomes the separator it already
    uses, rather than being deleted: a topology named ``research_adr`` reads as
    ``research-adr`` instead of ``researchadr``, so the operator still recognises
    the shape of the run from its nickname.
    """
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _bounded_nickname(lead: str, suffix: str) -> str:
    """Fit ``lead`` + ``suffix`` inside the slug bound, spending the lead first.

    The suffix carries the run's shape and the hash that identifies the run, so
    it is what must survive; the lead is the feature tag, whose own column admits
    more than twice the slug's width. Trailing separators left by the cut are
    removed, because the grammar admits neither a leading nor a trailing hyphen.
    """
    room = MAX_NICKNAME_SLUG_CHARS - len(suffix)
    if room >= 1:
        return f"{lead[:room].rstrip('-')}{suffix}"
    return f"{lead}{suffix}"[:MAX_NICKNAME_SLUG_CHARS].rstrip("-")


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
        topology: The topology type (e.g. ``"star"``, ``"research_adr"``).
        thread_id: The thread's own id, hashed for the 4-char suffix.

    Returns:
        A nickname conforming to the slug pattern :class:`ThreadMetadata`
        enforces, for every input. Nothing between here and the stored record
        re-checks: the run-creation seam assigns this onto an already-built
        model, which does not validate on assignment, so a non-conforming
        nickname was persisted and then made the whole record unreadable - every
        later read of it reported the run's provenance absent. Two inputs reached
        that: a topology whose name carries an underscore, which every
        document-authoring run has, and a feature tag longer than the slug bound,
        which the tag's own column admits.
    """
    # P10 finding: a positional thread_id[:4] slice discriminates real UUIDs
    # fine, but collides identically for every caller whose id scheme shares a
    # fixed literal prefix (e.g. the dashboard's "run-<hex>" run_id convention
    # - EVERY such id's first four characters are the constant "run-", so
    # every feature_tag-less dashboard run generated the SAME nickname and the
    # second run of a session 409'd forever). Hashing the full thread_id makes
    # the suffix depend on the whole string, immune to any caller's prefix
    # convention, present or future - and, as a side effect, always produces
    # a full 4-hex-char slug (H2's short/empty guard collapses into the one
    # "no thread_id at all" case below).
    short_hash = sha256_hex(thread_id.encode())[:4] if thread_id else "0000"
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
    # A topology whose name slugifies to nothing names nothing, so the segment is
    # dropped rather than filled with an invented one or left as an empty gap.
    shape = _slug_segment(topology)
    suffix = f"-{shape}-{short_hash}" if shape else f"-{short_hash}"
    return _bounded_nickname(tag or "thread", suffix)
