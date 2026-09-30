"""One rendering of a conversation into a provider prompt, shared by both lanes.

Neither served transport takes role-separated messages: the Codex app-server
takes one user-input array per turn, and an ACP prompt is a list of content
blocks. Both therefore need the conversation rendered to text, and both need the
SAME rendering - a run whose history says who spoke on one lane and not on the
other is a run whose behaviour depends on which transport served it.

What the rendering has to keep, because a model cannot recover it:

- the ROLE, so a system instruction is not read as something a user asked for;
- the SPEAKER, because a multi-agent run carries other agents' output in the same
  history and their names are the only thing distinguishing them;
- TOOL RESULTS, which are the evidence a later turn reasons from; dropping them
  leaves the model with its own tool call and no answer to it;
- non-text content, named rather than dumped. A message's content can be a list
  of typed blocks, and rendering that list with ``str()`` puts a Python repr of
  the internal structure into the prompt - which is neither what the block says
  nor anything a model should be asked to read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.messages import BaseMessage

    from ._json_contract import JsonObject

__all__ = [
    "render_prompt_blocks",
    "render_prompt_text",
    "rendered_prompt_sections",
    "speaker_label",
]


def speaker_label(message: BaseMessage) -> str | None:
    """Return the heading for one message, or ``None`` when it needs no label.

    An unnamed human turn is the one message that renders bare: it is what the
    run was asked to do, and a label around it would be this layer narrating the
    request back to the model. Everything else says what it is, and says who said
    it when the message carries a name - which is how a multi-agent history
    stops being one anonymous voice.
    """
    if isinstance(message, SystemMessage):
        role = "System"
    elif isinstance(message, ToolMessage):
        role = "Tool error" if message.status == "error" else "Tool result"
    elif isinstance(message, (AIMessage, AIMessageChunk)):
        role = "Assistant"
    elif isinstance(message, HumanMessage):
        if not message.name:
            return None
        role = "User"
    else:
        role = message.type.capitalize()
    return f"{role} ({message.name})" if message.name else role


def _rendered_content(message: BaseMessage) -> str:
    """Return one message's content as text, naming what is not text.

    ``text`` is the library's own concatenation of the message's text blocks, so
    a list-shaped content renders as what it SAYS. A block that carries no text -
    an image, a file, a reasoning trace - is named by its kind instead, because
    the fact that it was there is part of the history while its payload is not
    something to inline into a prompt.
    """
    text = message.text.strip()
    described = [
        f"[{block.get('type', 'content')}]"
        for block in message.content_blocks
        if block.get("type") != "text"
    ]
    return "\n".join([part for part in (text, *described) if part])


def rendered_prompt_sections(messages: Sequence[BaseMessage]) -> list[str]:
    """Return one labelled section per message that carries anything at all."""
    sections: list[str] = []
    for message in messages:
        content = _rendered_content(message)
        if not content:
            continue
        label = speaker_label(message)
        sections.append(f"# {label}\n{content}" if label else content)
    return sections


def render_prompt_text(messages: Sequence[BaseMessage]) -> str:
    """Render the conversation as one prompt string for a single-input turn."""
    return "\n\n".join(rendered_prompt_sections(messages))


def render_prompt_blocks(messages: Sequence[BaseMessage]) -> list[JsonObject]:
    """Render the conversation as ACP prompt content blocks, one per message.

    A block per message rather than one joined block: the protocol models a
    prompt as a sequence, and keeping the sequence keeps the turn boundaries the
    labels refer to.
    """
    return [
        {"type": "text", "text": section}
        for section in rendered_prompt_sections(messages)
    ]
