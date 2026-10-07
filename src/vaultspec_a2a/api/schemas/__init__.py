"""Frontend-backend wire contract schema models.

Facade re-exporting all public types from the ``vaultspec_a2a.api.schemas`` subpackage.
Consumers should import from this module rather than reaching into
sub-modules directly::

    from vaultspec_a2a.api.schemas import ThreadStateSnapshot

Only types this subpackage OWNS are re-exported. Domain types that these models
merely carry as field types are not, however visible they are on the wire:
``PlanEntry`` is serialized inside ``ThreadStateSnapshot`` yet belongs to
``vaultspec_a2a.thread.models``, exactly as ``ThreadStatus``, ``ToolKind``, and
``Provider`` do to their own modules. Re-exporting one here would give it a
second declared home. Import them from theirs.
"""

from .snapshots import ArtifactSnapshot as ArtifactSnapshot
from .snapshots import ExecutionTaskSnapshot as ExecutionTaskSnapshot
from .snapshots import MessageSnapshot as MessageSnapshot
from .snapshots import ThreadStateSnapshot as ThreadStateSnapshot
from .snapshots import ToolCallContent as ToolCallContent
from .snapshots import ToolCallContentDiff as ToolCallContentDiff
from .snapshots import ToolCallContentTerminal as ToolCallContentTerminal
from .snapshots import ToolCallContentText as ToolCallContentText
from .snapshots import ToolCallLocation as ToolCallLocation
from .snapshots import ToolCallSnapshot as ToolCallSnapshot

__all__ = [
    "ArtifactSnapshot",
    "ExecutionTaskSnapshot",
    "MessageSnapshot",
    "ThreadStateSnapshot",
    "ToolCallContent",
    "ToolCallContentDiff",
    "ToolCallContentTerminal",
    "ToolCallContentText",
    "ToolCallLocation",
    "ToolCallSnapshot",
]
