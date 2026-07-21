"""Declare what durable artifacts this service creates and how long they live.

:mod:`vaultspec_a2a.artifacts.retention` defines the retention vocabulary and
the declaration record each artifact-creating seam carries.

Declarations sit beside the code that creates the artifact rather than in a
central registry, so a declaration cannot drift away from the call site it
describes.  Nothing in this package deletes anything.
"""

from .retention import (
    ArtifactDeclaration,
    RetentionDeclarationError,
    RetentionDisposition,
)

__all__ = [
    "ArtifactDeclaration",
    "RetentionDeclarationError",
    "RetentionDisposition",
]
