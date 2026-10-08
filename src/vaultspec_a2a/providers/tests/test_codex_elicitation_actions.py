"""The elicitation actions this rung sends are the installed binary's own.

``mcpServer/elicitation/request`` is answered with one action string, and codex
treats an action it does not recognise the way it treats an unanswered frame:
the call resolves as not granted, the model is handed ``user rejected MCP tool
call``, and the turn still settles ``completed``. A wrong spelling is therefore
silent, which is why the vocabulary is pinned to the binary rather than written
from memory.

The pin is checked against the app-server's OWN generated schema, read from the
installed binary through ``codex app-server generate-json-schema``. That probe
spends no credential and opens no session - it is the binary printing its
protocol - so this is an ordinary test gated on the CLI being present, not a
live-turn proof.
"""

from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from ...graph.enums import Provider
from .._codex_permission import (
    ACCEPT_ACTION,
    CANCEL_ACTION,
    DECLINE_ACTION,
    ELICITATION_ACTIONS,
    elicitation_response,
)
from .._factory_commands import classify_provider_command
from .._json_contract import JsonObject, lenient_json_object
from ..binary_version import probe_binary_version

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from ...conftest import ExternalPrerequisiteRule

#: The generated artifact naming the response frame this rung writes.
_RESPONSE_SCHEMA = "McpServerElicitationRequestResponse.json"

#: The generated definition carrying the action vocabulary.
_ACTION_DEFINITION = "McpServerElicitationAction"

_SCHEMA_DOCUMENT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


def _generated_actions(out: Path) -> frozenset[str]:
    """Return the action enum the installed app-server declares for its response."""
    document = _SCHEMA_DOCUMENT.validate_json(
        (out / _RESPONSE_SCHEMA).read_text(encoding="utf-8")
    )
    definitions = lenient_json_object(document.get("definitions"))
    actions = lenient_json_object(definitions.get(_ACTION_DEFINITION)).get("enum")
    assert isinstance(actions, list), (
        f"{_RESPONSE_SCHEMA} carries no {_ACTION_DEFINITION} enum: {document}"
    )
    return frozenset(str(action) for action in actions)


def test_the_installed_app_server_declares_exactly_these_actions(
    tmp_path: Path, external_prerequisite: ExternalPrerequisiteRule
) -> None:
    """The pinned vocabulary is the binary's, proven without spending a credential.

    Discriminating in both directions. A vocabulary missing the abandon action
    would not equal the enum, and an invented spelling would not either - so the
    assertion fails whether the rung under-declares or over-declares. The probed
    version is named in the message because the enum is a property of one
    binary, and a disagreement is a fact about which binary is installed.
    """
    external_prerequisite("codex-cli")
    command = classify_provider_command(Provider.CODEX)
    version = probe_binary_version(command.argv[0])

    generate = subprocess.run(
        [*command.argv, "generate-json-schema", "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert generate.returncode == 0, (
        f"codex {version} could not print its app-server schema "
        f"(exit {generate.returncode}): {generate.stdout}\n{generate.stderr}"
    )

    declared = _generated_actions(tmp_path)

    assert declared == ELICITATION_ACTIONS, (
        f"codex {version} declares {sorted(declared)} for "
        f"{_ACTION_DEFINITION}, and this rung pins "
        f"{sorted(ELICITATION_ACTIONS)}: an action outside the binary's own "
        "enum is answered as a refusal the model is never told about"
    )
    assert {ACCEPT_ACTION, DECLINE_ACTION, CANCEL_ACTION} == declared


def test_an_action_outside_the_pinned_vocabulary_fails_closed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A frame can only carry an action the binary accepts, and says so loudly.

    An unrecognised action reaches codex as a non-answer, so emitting one would
    lose the call silently - the failure this module exists to have noticed. The
    frame is still written, because a missing answer hangs the turn until the
    idle backstop fires; it is written as the refusal, which is the direction a
    decision that cannot be spelled must fail in.
    """
    with caplog.at_level(logging.WARNING, logger="vaultspec_a2a.providers"):
        frame = elicitation_response(5, "abort")

    assert frame == {"id": 5, "result": {"action": DECLINE_ACTION}}
    assert [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING
        and "outside the actions codex accepts" in record.getMessage()
    ], f"the downgraded action logged nothing at WARNING. Saw: {caplog.messages}"


def test_every_pinned_action_builds_its_own_frame() -> None:
    """Each action spells itself, and only an acceptance carries content.

    The protocol types ``content`` as nullable precisely because a decline and
    an abandonment carry no user input, and the requested schema for a bare
    tool-call approval is an empty object.
    """
    assert elicitation_response(1, ACCEPT_ACTION) == {
        "id": 1,
        "result": {"action": "accept", "content": {}},
    }
    assert elicitation_response(2, DECLINE_ACTION) == {
        "id": 2,
        "result": {"action": "decline"},
    }
    assert elicitation_response(3, CANCEL_ACTION) == {
        "id": 3,
        "result": {"action": "cancel"},
    }
