from collections.abc import Sequence
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage


class TeamState(TypedDict):
    """Core state for LangGraph orchestration."""

    messages: Annotated[Sequence[BaseMessage], lambda x, y: x + y]
