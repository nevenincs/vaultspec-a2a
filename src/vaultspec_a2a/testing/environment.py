"""Arm-and-restore seams for the live state a test may safely mutate.

Two mechanisms, deliberately kept apart even though both "save, apply, then
restore on exit":

- :func:`armed_environment` mutates ``os.environ``, the process-wide table a
  fresh ``Settings()`` construction reads at boot.
- :func:`settings_override` mutates attributes directly on the shared
  ``settings`` and ``domain_config`` singletons production code already holds a
  reference to, each name on the singleton that declares it.

Folding these into one function would hide which live object a test is
touching, which is the one distinction that must never be ambiguous at a call
site: an ``os.environ`` change is invisible to an already-constructed
``settings`` object, and a ``settings`` attribute swap is invisible to code
that reads the environment directly.
"""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING

from ..control.config import settings as _settings
from ..domain_config import DomainSettingsConfig
from ..domain_config import domain_config as _domain_config

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

__all__ = [
    "armed_desktop_app_home",
    "armed_environment",
    "settings_override",
]


@contextlib.contextmanager
def armed_environment(**values: str | None) -> Generator[None]:
    """Apply *values* to ``os.environ``, then restore the prior state.

    ``None`` removes a name for the duration of the block rather than setting
    it to an empty string. A name absent beforehand is popped back to absent on
    exit, never left behind as ``""`` - the safest of the several near-identical
    copies this consolidates. Restoration runs in the ``finally`` clause, so an
    assertion raised inside the block still leaves the environment as later
    tests expect it.
    """
    prior = {name: os.environ.get(name) for name in values}
    try:
        for name, value in values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, previous in prior.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous


@contextlib.contextmanager
def settings_override(**updates: object) -> Generator[None]:
    """Temporarily set attributes on the singleton that owns each one.

    A domain knob is set on ``domain_config`` and everything else on
    ``settings``, so one override changes the value every reader of that field
    sees: no field is declared by both singletons.

    Restoration runs in the ``finally`` clause, so an assertion raised inside
    the block still leaves the singletons as later tests expect them. Distinct
    from :func:`armed_environment`: this touches the already-constructed
    singletons directly, not the environment a future construction would read.
    """
    owners = {
        name: _domain_config if name in DomainSettingsConfig.model_fields else _settings
        for name in updates
    }
    originals = {name: getattr(owner, name) for name, owner in owners.items()}
    try:
        for name, value in updates.items():
            setattr(owners[name], name, value)
        yield
    finally:
        for name, value in originals.items():
            setattr(owners[name], name, value)


@contextlib.contextmanager
def armed_desktop_app_home(app_home: Path, **overrides: object) -> Generator[None]:
    """Arm the desktop profile on the shared ``settings`` singleton.

    ``desktop_profile_armed`` is a read-only property derived from
    ``desktop_app_home``, so arming means setting the field the property
    reads. Built on :func:`settings_override`, the sanctioned attribute-swap
    seam, and confirms the derived property actually flips before yielding.

    The desktop profile holds no plugin lane - the product refuses one named
    under it - so arming it also unseats any lane plugins this process holds.
    *overrides* are further fields set for the same block, on the singleton that
    owns each; naming ``desktop_app_home`` or ``lane_plugins`` there is a
    ``TypeError``, since arming owns both.
    """
    with settings_override(desktop_app_home=app_home, lane_plugins=(), **overrides):
        assert _settings.desktop_profile_armed is True
        yield
