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
- the BOUNDARIES, so a body cannot open a section of its own. A tool result or
  another agent's output that contains a line reading as a role heading would
  otherwise speak as the system to every later turn;
- non-text content, named rather than dumped. A message's content can be a list
  of typed blocks, and rendering that list with ``str()`` puts a Python repr of
  the internal structure into the prompt - which is neither what the block says
  nor anything a model should be asked to read.
"""

from __future__ import annotations

import re
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
    "speaker_label",
]

# The words a heading would have to carry to read as one of the labels below:
# the roles this layer writes, plus the ones a model would take for one. Shared
# by both forgery patterns, so the two spellings of the same heading cannot come
# to disagree about what reads as a role.
_ROLE_WORDS = "system|developer|user|human|assistant|ai|tool|function|chat"

# A content line that reads as one of the section headings below: the heading
# depth this layer writes, any case, a role word it writes or a model would take
# for one. Deeper headings are left alone, because mounted documents use them for
# their own structure and are shown to the model as written. Markdown also
# starts a line after a lone carriage return, which "^" alone does not see.
_FORGED_ROLE_HEADING = re.compile(
    rf"(?:^|(?<=\r))([ \t]{{0,3}})(#(?!#)[ \t]*(?:{_ROLE_WORDS})\b)",
    re.IGNORECASE | re.MULTILINE,
)

# The same heading written the other way round: a line of "=" under text is the
# setext spelling of the depth-one heading this layer writes, so it opens a
# section exactly as the hash form does and has to be refused by the same rule.
# The UNDERLINE is escaped rather than the words, so the text still reaches the
# model as written.
#
# A setext heading's text is the WHOLE paragraph above the underline, not the
# one line next to it, so the guard reads every line since the last blank one:
# an underline is escaped when any of them could open a role heading. That also
# covers a paragraph a block such as a hash heading interrupted, whose own text
# starts mid-run, and an underline already escaped, which leaves the paragraph
# open for the next underline to promote.
#
# A line may carry a hash of its own, because escaping one turns that line into
# a paragraph - and an underline beneath a paragraph promotes it straight back
# into a depth-one heading, which is why this pass runs before the hash pass.
#
# A "-" underline is deliberately NOT matched: it spells a depth-TWO heading,
# which this layer never writes and a mounted document's own sections do.
_ROLE_PARAGRAPH_LINE = re.compile(
    rf"^[ \t]{{0,3}}(?:\\?#[ \t]*)?(?:{_ROLE_WORDS})\b", re.IGNORECASE
)
_SETEXT_UNDERLINE = re.compile(r"^([ \t]{0,3})(=+[ \t]*)$")

# Markdown ends a line at a carriage return as well as a newline, so a tool's
# Windows-style output underlines its headings exactly as a Unix one does.
_LINE_ENDING = re.compile(r"(\r\n|\r|\n)")


def _defused_underlines(text: str) -> str:
    """Escape each "=" underline beneath a paragraph that could name a role."""
    pieces = _LINE_ENDING.split(text)
    role_paragraph = False
    for index in range(0, len(pieces), 2):
        line = pieces[index]
        if not line.strip():
            role_paragraph = False
            continue
        underline = _SETEXT_UNDERLINE.match(line)
        if underline is not None and role_paragraph:
            pieces[index] = f"{underline[1]}\\{underline[2]}"
        elif _ROLE_PARAGRAPH_LINE.match(line):
            role_paragraph = True
    return "".join(pieces)


def _defused(text: str) -> str:
    """Escape every line of *text* that would read as a section heading."""
    return _FORGED_ROLE_HEADING.sub(r"\1\\\2", _defused_underlines(text))


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
    # A name is caller-chosen, so it is held to one line: a newline inside it
    # would end the heading and let the rest of the name start another.
    name = " ".join(message.name.split()) if message.name else ""
    return f"{role} ({name})" if name else role


def _rendered_content(message: BaseMessage) -> str:
    """Return one message's content as text, naming what is not text.

    ``text`` is the library's own concatenation of the message's text blocks, so
    a list-shaped content renders as what it SAYS. A block that carries no text -
    an image, a file, a reasoning trace - is named by its kind instead, because
    the fact that it was there is part of the history while its payload is not
    something to inline into a prompt.
    """
    text = _defused(message.text)
    described = [
        f"[{block.get('type', 'content')}]"
        for block in message.content_blocks
        if block.get("type") != "text"
    ]
    # Text is passed through as written, never re-wrapped or trimmed: a persona
    # and a tool's output are content this layer carries rather than edits. The
    # one exception is a line that would forge a section boundary, which is
    # escaped rather than removed so the model still sees what was written. Only
    # the decision about whether a message SAYS anything looks past whitespace.
    parts = [*([text] if text.strip() else []), *described]
    return "\n".join(parts)


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
