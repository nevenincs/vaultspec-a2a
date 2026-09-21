from typing import Annotated, Literal

from langchain_core.messages import AnyMessage, MessageLikeRepresentation
from langgraph.graph.state import StateGraph
from typing_extensions import TypedDict

Messages = list[MessageLikeRepresentation] | MessageLikeRepresentation
REMOVE_ALL_MESSAGES: Literal["__remove_all__"]

def add_messages(
    left: Messages,
    right: Messages,
    *,
    format: Literal["langchain-openai"] | None = None,
) -> Messages: ...

class MessagesState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]

class MessageGraph(StateGraph):
    def __init__(self) -> None: ...
