"""Backwards-compatibility shim — delegates to streaming.aggregator.

New code should import from ``vaultspec_a2a.streaming.aggregator`` directly.
"""

from ..streaming.aggregator import EventAggregator as EventAggregator
from ..streaming.aggregator import StreamableGraph as StreamableGraph
from ..streaming.aggregator import classify_tool_kind as classify_tool_kind

__all__ = ["EventAggregator", "StreamableGraph", "classify_tool_kind"]
