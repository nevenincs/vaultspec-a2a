from typing import Annotated, Literal

from langchain_core.messages import AnyMessage, MessageLikeRepresentation
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
