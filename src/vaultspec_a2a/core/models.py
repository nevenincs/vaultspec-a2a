"""Helper dataclasses for structured access to TeamState dict entries.

These exist purely for code readability and type-safe construction.
They are **never** stored directly in ``TeamState`` — callers convert
to/from plain dicts via ``.to_dict()`` / ``.from_dict()`` so the state
remains JSON-serializable for the LangGraph SQLite checkpointer.
"""

from dataclasses import asdict, dataclass


__all__ = [
    "ArtifactRef",
    "PlanStep",
    "TokenUsageEntry",
]


@dataclass(frozen=True, slots=True)
class TokenUsageEntry:
    """Per-agent token accounting."""

    agent_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    total: int = 0

    def to_dict(self) -> dict[str, int]:
        """Return the inner counters dict (no agent_id — keyed externally)."""
        return {
            "input": self.input_tokens,
            "output": self.output_tokens,
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, agent_id: str, data: dict[str, int]) -> "TokenUsageEntry":
        """Construct from the dict stored in ``TeamState.token_usage``."""
        return cls(
            agent_id=agent_id,
            input_tokens=data.get("input", 0),
            output_tokens=data.get("output", 0),
            total=data.get("total", 0),
        )


@dataclass(frozen=True, slots=True)
class PlanStep:
    """A single step in the team execution plan."""

    step: str
    status: str = "pending"
    agent: str = ""

    def to_dict(self) -> dict[str, str]:
        """Serialise to a plain dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "PlanStep":
        """Deserialise from a plain dict."""
        return cls(
            step=data.get("step", ""),
            status=data.get("status", "pending"),
            agent=data.get("agent", ""),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Reference to a file artifact produced by an agent."""

    id: str
    path: str
    type: str = "file"
    created_by: str = ""

    def to_dict(self) -> dict[str, str]:
        """Serialise to a plain dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "ArtifactRef":
        """Deserialise from a plain dict."""
        return cls(
            id=data.get("id", ""),
            path=data.get("path", ""),
            type=data.get("type", "file"),
            created_by=data.get("created_by", ""),
        )
