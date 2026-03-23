"""Backwards-compatibility shim — canonical source: vaultspec_a2a.context.metadata"""

from vaultspec_a2a.context.metadata import (
    ContextRef as ContextRef,
)
from vaultspec_a2a.context.metadata import (
    ThreadMetadata as ThreadMetadata,
)
from vaultspec_a2a.context.metadata import (
    discover_context_refs as discover_context_refs,
)
from vaultspec_a2a.context.metadata import (
    generate_nickname as generate_nickname,
)

__all__ = [
    "ContextRef",
    "ThreadMetadata",
    "discover_context_refs",
    "generate_nickname",
]
