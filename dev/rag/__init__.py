"""Checks on this repository's RAG provider wiring.

The single instrument here replaced a 240-character ``python -c`` embedded in
``dev/just/rag.just``. Import statements, an ``asyncio.run`` call, and a
verification contract packed onto one shell line are unreadable, untypeable,
and unreachable by the linter that covers every other line of this package.
"""

from __future__ import annotations
