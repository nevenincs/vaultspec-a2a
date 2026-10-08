"""Settings and domain config must declare disjoint fields (T-F23).

``Settings`` is infrastructure-only; every domain knob is read through
``domain_config.DomainSettingsConfig`` instead (the D6/D24-era split this
package settled on). A field name declared on both would answer "which class
configures this operator-facing variable?" two different ways depending on
which one a reader happened to import, and nothing short of reading both
class bodies would reveal the collision - exactly the kind of drift a
mechanical check exists to keep from recurring.

Both classes derive from the same ``ProjectSettings`` base, which declares no
pydantic fields of its own (only the shared source-ranking classmethods), so
the comparison needs no carve-out for an inherited common field: a name
appearing in both ``model_fields`` dicts can only come from one class
restating what the other already owns.
"""

from __future__ import annotations

from ..control.config import Settings
from ..domain_config import DomainSettingsConfig

#: Below either count, the comparison is treated as mis-rooted rather than as
#: two classes that genuinely shrank to nothing worth checking against.
_MINIMUM_SETTINGS_FIELDS = 50
_MINIMUM_DOMAIN_FIELDS = 10


def test_settings_and_domain_config_declare_disjoint_fields() -> None:
    """``Settings`` and ``DomainSettingsConfig`` share no ``model_fields`` name."""
    settings_fields = set(Settings.model_fields)
    domain_fields = set(DomainSettingsConfig.model_fields)

    assert len(settings_fields) >= _MINIMUM_SETTINGS_FIELDS, (
        f"only {len(settings_fields)} Settings field(s) were found - a "
        "mis-rooted comparison must not pass vacuously"
    )
    assert len(domain_fields) >= _MINIMUM_DOMAIN_FIELDS, (
        f"only {len(domain_fields)} DomainSettingsConfig field(s) were found "
        "- a mis-rooted comparison must not pass vacuously"
    )

    overlap = settings_fields & domain_fields
    assert not overlap, (
        f"Settings and DomainSettingsConfig both declare {sorted(overlap)}. "
        "Settings is infrastructure-only; move the domain knob to "
        "DomainSettingsConfig alone, or the infrastructure one to Settings "
        "alone - whichever class actually owns it - rather than declaring it "
        "on both."
    )
