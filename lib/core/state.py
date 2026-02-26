"""Core state schema for LangGraph agent orchestration."""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class TeamState(TypedDict):
    """Core state for LangGraph orchestration."""

    messages: Annotated[list[BaseMessage], add_messages]
    next: str
