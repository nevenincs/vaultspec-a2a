"""Every operator-facing setting must be documented, or deliberately excluded.

Documentation drifts silently: a setting lands, the example file is not updated,
and an operator deploying the service has no way to discover the knob exists.
Four observability and authoring settings had drifted out of the service example
before this test existed - including the one the live certification lanes require.

An environment name reaches a setting through three declarations, not one:
``alias``, a plain ``validation_alias``, and the several names an
``AliasChoices`` admits. Reading only ``alias`` skipped every provider
credential and every dual-spelling knob in ``InfraConfig`` - 21 of the 84
declared names - so the guard passed vacuously over exactly the population most
worth guarding. :func:`_declared_env_names` is the single extraction both the
coverage assertion and the exclusion-liveness assertion read, so neither can
narrow again independently.

The exclusion set is explicit rather than a pattern, so adding a setting to it is
a visible decision in a diff rather than an accident.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from pydantic import AliasChoices

from ...control.config import Settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic.fields import FieldInfo

# Settings that belong to the packaged desktop profile, which seats its own state
# root and capsule assets. Neither is meaningful for a Compose deployment, so the
# service example documents their absence rather than the settings.
_DESKTOP_ONLY = frozenset({"VAULTSPEC_DESKTOP_APP_HOME", "VAULTSPEC_CAPSULE_ASSETS"})

_ENV_EXAMPLE = pathlib.Path(__file__).resolve().parents[3].parent / ".env.example"


def _declared_env_names(field: FieldInfo) -> Iterator[str]:
    """Yield every environment name a field declares, across all alias forms.

    ``AliasChoices`` may also carry ``AliasPath`` entries, which address a
    position inside an already-parsed structure rather than naming an
    environment variable; only the string choices are operator-facing names.
    """
    if field.alias:
        yield field.alias

    validation_alias = field.validation_alias
    if isinstance(validation_alias, str):
        yield validation_alias
    elif isinstance(validation_alias, AliasChoices):
        for choice in validation_alias.choices:
            if isinstance(choice, str):
                yield choice


def _all_declared_env_names() -> set[str]:
    return {
        name
        for field in Settings.model_fields.values()
        for name in _declared_env_names(field)
    }


def _documented() -> str:
    return _ENV_EXAMPLE.read_text(encoding="utf-8")


def test_the_env_example_is_present() -> None:
    """A missing example file would make every other assertion vacuous."""
    assert _ENV_EXAMPLE.is_file(), _ENV_EXAMPLE


def test_the_extraction_reads_past_the_plain_alias() -> None:
    """The extraction must see the alias forms the credential fields use.

    A regression that narrowed :func:`_declared_env_names` back to ``alias``
    would leave the coverage assertion green while covering nothing, which is
    the exact failure this module was rewritten to end. Anchoring on three
    fields that each declare their name a different way makes that narrowing
    fail here rather than pass silently.
    """
    fields = Settings.model_fields

    # plain alias
    assert "VAULTSPEC_MCP_PORT" in set(_declared_env_names(fields["mcp_port"]))
    # plain validation_alias
    assert "OPENAI_API_KEY" in set(_declared_env_names(fields["openai_api_key"]))
    # every name of an AliasChoices
    assert set(_declared_env_names(fields["zai_auth_token"])) == {
        "ZAI_AUTH_TOKEN",
        "ZAI_API_KEY",
    }


def test_every_declared_environment_name_is_documented_or_excluded() -> None:
    """A name that is neither documented nor excluded is drift."""
    text = _documented()
    undocumented = sorted(
        name
        for name in _all_declared_env_names()
        if name not in _DESKTOP_ONLY and name not in text
    )

    assert not undocumented, (
        f"undocumented settings in .env.example: {undocumented}. "
        "Document them, or add them to the desktop-only exclusion with a reason."
    )


def test_the_exclusions_are_named_in_the_file() -> None:
    """An exclusion the file does not mention reads to an operator as an omission."""
    text = _documented()

    for alias in sorted(_DESKTOP_ONLY):
        assert alias in text, (
            f"{alias} is excluded but the example never explains its absence"
        )


def test_the_exclusion_set_holds_only_real_settings() -> None:
    """A stale exclusion would hide a genuinely undocumented setting."""
    declared = _all_declared_env_names()

    assert declared >= _DESKTOP_ONLY, _DESKTOP_ONLY - declared
