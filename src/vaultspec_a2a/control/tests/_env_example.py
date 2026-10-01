"""The service's environment contract as the tests read it from both sides.

One reading of ``.env.example`` and one reading of what the code declares,
shared by every test that holds the two equal, so no test can narrow either
side on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ...control.config import Settings
from ...control.settings_base import field_env_names
from ...protocols.mcp.authoring_stdio import AuthoringBridgeSettings
from ...testing.session_root import TestSessionSettings

__all__ = [
    "DOCUMENTED_BUT_NOT_READ",
    "ENV_EXAMPLE",
    "INTEGRATION_EXAMPLE",
    "REPO_ROOT",
    "Assignment",
    "assignments",
    "declared_names",
    "documented",
    "harness_section",
    "service_section",
    "setting_field_by_name",
]

REPO_ROOT = Path(__file__).resolve().parents[4]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
INTEGRATION_EXAMPLE = REPO_ROOT / ".env.integration.example"

#: The heading of the section the repository's own tooling reads. Its names
#: are held to the harness by ``dev/tests/test_harness_env_names.py``.
_HARNESS_HEADING = "# Development harness\n"

#: Names the example documents that the service does not read, each with the
#: owner that does. Anything else in the file is a dead or misspelled setting.
DOCUMENTED_BUT_NOT_READ = {
    # Read by the langsmith SDK straight from the process environment.
    "LANGSMITH_API_KEY": "langsmith SDK",
    "LANGSMITH_ENDPOINT": "langsmith SDK",
    "LANGSMITH_PROJECT": "langsmith SDK",
    "LANGSMITH_TRACING": "langsmith SDK",
    "LANGCHAIN_TRACING_V2": "langsmith SDK",
    # Read by the Claude CLI from the environment it inherits; the recipes'
    # credential scopes export it from .env, and the service never reads it.
    "CLAUDE_CODE_OAUTH_TOKEN": "Claude CLI",
    # Documented as deliberately absent: the agent scrub strips it.
    "ANTHROPIC_API_KEY": "documented absence",
    # Substituted by the Postgres Compose profile, never read by the service.
    "POSTGRES_PASSWORD": "docker compose",
    # Named in the port table as the place a Postgres port is embedded.
    "DATABASE_URL": "port table prose",
}

_ASSIGNMENT = re.compile(r"^(?P<commented># )?(?P<name>[A-Z][A-Z0-9_]*)=(?P<value>.*)$")


@dataclass(frozen=True, slots=True)
class Assignment:
    """One ``NAME=value`` line an operator can copy or uncomment."""

    line: int
    name: str
    value: str
    commented: bool


def documented(path: Path = ENV_EXAMPLE) -> str:
    """Return an example file's whole text."""
    return path.read_text(encoding="utf-8")


def service_section() -> str:
    """The example up to the development-harness section."""
    text = documented()
    assert _HARNESS_HEADING in text, "the harness section heading moved"
    return text.split(_HARNESS_HEADING, 1)[0]


def harness_section() -> str:
    """The development-harness section of the example."""
    text = documented()
    assert _HARNESS_HEADING in text, "the harness section heading moved"
    return text.split(_HARNESS_HEADING, 1)[1]


def assignments(text: str) -> list[Assignment]:
    """Every assignment line in *text*, in file order with its line number."""
    found: list[Assignment] = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = _ASSIGNMENT.match(line)
        if match is not None:
            found.append(
                Assignment(
                    line=number,
                    name=match["name"],
                    value=match["value"],
                    commented=match["commented"] is not None,
                )
            )
    return found


def setting_field_by_name() -> dict[str, str]:
    """Map every environment name the service settings read to its field."""
    return {
        name: field
        for field in Settings.model_fields
        for name in field_env_names(Settings, field)
    }


def declared_names() -> set[str]:
    """Every environment name any settings class in the code reads.

    The service settings, the authoring bridge's child-process contract, and
    the test harness's own session settings: the three places a name can be
    declared, so the three a name spelled in the code can legitimately mean.
    """
    return {
        name
        for settings_cls in (Settings, AuthoringBridgeSettings, TestSessionSettings)
        for field in settings_cls.model_fields
        for name in field_env_names(settings_cls, field)
    }
