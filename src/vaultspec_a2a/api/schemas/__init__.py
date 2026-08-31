"""Frontend-backend wire contract schema models.

Facade re-exporting all public types from the ``vaultspec_a2a.api.schemas`` subpackage.
Consumers should import from this module rather than reaching into
sub-modules directly::

    from vaultspec_a2a.api.schemas import (
        ServerEvent,
        ThreadStateSnapshot,
    )

Only types this subpackage OWNS are re-exported. Domain types that these models
merely carry as field types are not, however visible they are on the wire:
``PlanEntry`` is serialized inside ``PlanUpdateEvent`` and
``ThreadStateSnapshot`` yet belongs to ``vaultspec_a2a.thread.models``, exactly
as ``ThreadStatus``, ``ToolKind``, and ``Provider`` do to their own modules.
Re-exporting one here would give it a second declared home. Import them from
theirs, as ``enums.py`` says for the domain enums.
"""

from .base import EventEnvelope as EventEnvelope
from .enums import PlanEntryPriority as PlanEntryPriority
from .enums import PlanEntryStatus as PlanEntryStatus
from .events import AgentStatusEvent as AgentStatusEvent
from .events import AgentSummary as AgentSummary
from .events import ArtifactUpdateEvent as ArtifactUpdateEvent
from .events import ClarificationPendingEvent as ClarificationPendingEvent
from .events import ErrorEvent as ErrorEvent
from .events import HeartbeatEvent as HeartbeatEvent
from .events import MessageChunkEvent as MessageChunkEvent
from .events import PermissionOption as PermissionOption
from .events import PermissionRequestEvent as PermissionRequestEvent
from .events import PlanUpdateEvent as PlanUpdateEvent
from .events import ServerEvent as ServerEvent
from .events import TeamStatusEvent as TeamStatusEvent
from .events import ThoughtChunkEvent as ThoughtChunkEvent
from .events import ToolCallContent as ToolCallContent
from .events import ToolCallContentDiff as ToolCallContentDiff
from .events import ToolCallContentTerminal as ToolCallContentTerminal
from .events import ToolCallContentText as ToolCallContentText
from .events import ToolCallLocation as ToolCallLocation
from .events import ToolCallStartEvent as ToolCallStartEvent
from .events import ToolCallUpdateEvent as ToolCallUpdateEvent
from .snapshots import ArtifactSnapshot as ArtifactSnapshot
from .snapshots import ExecutionTaskSnapshot as ExecutionTaskSnapshot
from .snapshots import MessageSnapshot as MessageSnapshot
from .snapshots import ThreadStateSnapshot as ThreadStateSnapshot
from .snapshots import ToolCallSnapshot as ToolCallSnapshot

__all__ = [
    "AgentStatusEvent",
    "AgentSummary",
    "ArtifactSnapshot",
    "ArtifactUpdateEvent",
    "ClarificationPendingEvent",
    "ErrorEvent",
    "EventEnvelope",
    "ExecutionTaskSnapshot",
    "HeartbeatEvent",
    "MessageChunkEvent",
    "MessageSnapshot",
    "PermissionOption",
    "PermissionRequestEvent",
    "PlanEntryPriority",
    "PlanEntryStatus",
    "PlanUpdateEvent",
    "ServerEvent",
    "TeamStatusEvent",
    "ThoughtChunkEvent",
    "ThreadStateSnapshot",
    "ToolCallContent",
    "ToolCallContentDiff",
    "ToolCallContentTerminal",
    "ToolCallContentText",
    "ToolCallLocation",
    "ToolCallSnapshot",
    "ToolCallStartEvent",
    "ToolCallUpdateEvent",
]
