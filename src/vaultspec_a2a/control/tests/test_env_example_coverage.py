"""Every operator-facing setting must be documented, or deliberately excluded.

Documentation drifts silently: a setting lands, the example file is not updated,
and an operator deploying the service has no way to discover the knob exists.
Four observability and authoring settings had drifted out of the service example
before this test existed - including the one the live certification lanes require.

The exclusion set is explicit rather than a pattern, so adding a setting to it is
a visible decision in a diff rather than an accident.
"""

from __future__ import annotations

import pathlib

from vaultspec_a2a.control.config import Settings

# Settings that belong to the packaged desktop profile, which seats its own state
# root and capsule assets. Neither is meaningful for a Compose deployment, so the
# service example documents their absence rather than the settings.
_DESKTOP_ONLY = frozenset({"VAULTSPEC_DESKTOP_APP_HOME", "VAULTSPEC_CAPSULE_ASSETS"})

_ENV_EXAMPLE = (
    pathlib.Path(__file__).resolve().parents[3].parent / "service" / ".env.example"
)


def _documented() -> str:
    return _ENV_EXAMPLE.read_text(encoding="utf-8")


def test_the_env_example_is_present() -> None:
    """A missing example file would make every other assertion vacuous."""
    assert _ENV_EXAMPLE.is_file(), _ENV_EXAMPLE


def test_every_aliased_setting_is_documented_or_excluded() -> None:
    """A setting that is neither documented nor excluded is drift."""
    text = _documented()
    undocumented = sorted(
        field.alias
        for field in Settings.model_fields.values()
        if field.alias and field.alias not in _DESKTOP_ONLY and field.alias not in text
    )

    assert not undocumented, (
        f"undocumented settings in service/.env.example: {undocumented}. "
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
    aliases = {field.alias for field in Settings.model_fields.values() if field.alias}

    assert aliases >= _DESKTOP_ONLY, _DESKTOP_ONLY - aliases
