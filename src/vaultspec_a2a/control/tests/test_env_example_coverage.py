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

import re
from typing import TYPE_CHECKING

from ...control.config import Settings
from ...control.settings_base import field_env_names
from ._env_example import (
    DOCUMENTED_BUT_NOT_READ,
    ENV_EXAMPLE,
    INTEGRATION_EXAMPLE,
    assignments,
    documented,
    service_section,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# Settings that belong to the packaged desktop profile, whose launcher sets its
# state root, capsule assets and settlement receiver. None is meaningful for a
# native development session, so the example documents their absence instead.
_DESKTOP_ONLY = frozenset(
    {
        "VAULTSPEC_A2A_DESKTOP_APP_HOME",
        "VAULTSPEC_A2A_CAPSULE_ASSETS",
        "VAULTSPEC_A2A_DESKTOP_SETTLEMENT_URL",
    }
)


def _declared_env_names(field_name: str) -> Iterator[str]:
    """Yield every environment name a field is read from, across all forms.

    Delegates to the settings module's own extraction, so the names this test
    checks are exactly the names the service reads: explicit aliases, every
    string choice of an ``AliasChoices``, and the prefix-derived name of an
    un-aliased field.
    """
    yield from field_env_names(Settings, field_name)


def _all_declared_env_names() -> set[str]:
    return {
        name
        for field_name in Settings.model_fields
        for name in _declared_env_names(field_name)
    }


def test_the_env_example_is_present() -> None:
    """A missing example file would make every other assertion vacuous."""
    assert ENV_EXAMPLE.is_file(), ENV_EXAMPLE


def test_the_extraction_reads_past_the_plain_alias() -> None:
    """The extraction must see the alias forms the credential fields use.

    A regression that narrowed :func:`_declared_env_names` back to ``alias``
    would leave the coverage assertion green while covering nothing, which is
    the exact failure this module was rewritten to end. Anchoring on three
    fields that each declare their name a different way makes that narrowing
    fail here rather than pass silently.
    """
    # prefix-derived name of an un-aliased field
    assert set(_declared_env_names("worker_port")) == {"VAULTSPEC_A2A_WORKER_PORT"}
    # plain alias
    assert set(_declared_env_names("a2a_home")) == {"VAULTSPEC_A2A_HOME"}
    # every name of an AliasChoices, the a2a name first
    assert tuple(_declared_env_names("openai_api_key")) == (
        "VAULTSPEC_A2A_OPENAI_API_KEY",
        "OPENAI_API_KEY",
    )
    assert set(_declared_env_names("zai_auth_token")) == {
        "VAULTSPEC_A2A_ZAI_AUTH_TOKEN",
        "ZAI_AUTH_TOKEN",
        "ZAI_API_KEY",
    }


def _assigned_names(text: str) -> set[str]:
    """Names given an assignment line an operator can uncomment and edit."""
    return set(_ASSIGNMENT.findall(text))


_ASSIGNMENT = re.compile(r"^(?:# )?([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def test_every_setting_has_a_line_an_operator_can_edit() -> None:
    """A setting mentioned only in prose leaves the operator nothing to copy.

    Each field needs at least one of its names as an assignment line; its other
    spellings (the a2a name of another tool's variable, or the reverse) may be
    documented in prose beside it.
    """
    assigned = _assigned_names(documented())
    missing = sorted(
        field_env_names(Settings, field)[0]
        for field in Settings.model_fields
        if not set(field_env_names(Settings, field)) & (assigned | _DESKTOP_ONLY)
    )

    assert not missing, f"settings with no editable line in .env.example: {missing}"


def test_every_declared_environment_name_is_documented_or_excluded() -> None:
    """A name that is neither documented nor excluded is drift."""
    text = documented()
    undocumented = sorted(
        name
        for name in _all_declared_env_names()
        if name not in _DESKTOP_ONLY and name not in text
    )

    assert not undocumented, (
        f"undocumented settings in .env.example: {undocumented}. "
        "Document them, or add them to the desktop-only exclusion with a reason."
    )


_NAME = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b")


def test_every_documented_name_is_read_by_the_service() -> None:
    """The reverse direction: the example must not advertise dead settings.

    Four settings the service had stopped reading stayed in the example for
    months, each still looking like a knob an operator could turn.
    """
    declared = _all_declared_env_names()
    dead = sorted(
        name
        for name in set(_NAME.findall(service_section()))
        if name not in declared and name not in DOCUMENTED_BUT_NOT_READ
    )

    assert not dead, (
        f".env.example documents names the service does not read: {dead}. "
        "Remove them, or record which tool reads them."
    )


def test_the_integration_example_names_only_settings_the_service_reads() -> None:
    """The integration profile's example is held to the same reverse check."""
    named = set(_NAME.findall(documented(INTEGRATION_EXAMPLE)))

    admitted = _all_declared_env_names() | set(DOCUMENTED_BUT_NOT_READ)

    assert named, "the integration example names no settings at all"
    assert named <= admitted, sorted(named - admitted)


def test_external_provider_identity_is_documented_as_optional() -> None:
    """Copying the example must not select a retired container launcher or UID."""
    lines = assignments(service_section())
    for field in (
        "provider_identity_launcher",
        "provider_agent_uid",
        "provider_agent_gid",
    ):
        assert Settings.model_fields[field].default is None
        names = set(field_env_names(Settings, field))
        documented_lines = [line for line in lines if line.name in names]
        assert len(documented_lines) == 1, field
        assert documented_lines[0].commented, field
        assert documented_lines[0].value == "", field


def test_the_exclusions_are_named_in_the_file() -> None:
    """An exclusion the file does not mention reads to an operator as an omission."""
    text = documented()

    for alias in sorted(_DESKTOP_ONLY):
        assert alias in text, (
            f"{alias} is excluded but the example never explains its absence"
        )


def test_the_exclusion_set_holds_only_real_settings() -> None:
    """A stale exclusion would hide a genuinely undocumented setting."""
    declared = _all_declared_env_names()

    assert declared >= _DESKTOP_ONLY, _DESKTOP_ONLY - declared
