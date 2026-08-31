"""Arm-and-restore seams for the two live singletons a test may safely mutate.

Two mechanisms, deliberately kept apart even though both "save, apply, then
restore on exit":

- :func:`armed_environment` mutates ``os.environ``, the process-wide table a
  fresh ``Settings()`` construction reads at boot.
- :func:`settings_override` mutates attributes directly on the shared
  ``settings`` singleton production code already holds a reference to.

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

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = [
    "armed_desktop_app_home",
    "armed_environment",
    "settings_override",
]


@contextlib.contextmanager
def armed_environment(**values: str | None) -> Iterator[None]:
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
def settings_override(**updates: object) -> Iterator[None]:
    """Temporarily set attributes on the shared ``settings`` singleton.

    Restoration runs in the ``finally`` clause, so an assertion raised inside
    the block still leaves the singleton as later tests expect it. Distinct
    from :func:`armed_environment`: this touches the already-constructed
    ``settings`` object directly, not the environment a future construction
    would read.
    """
    originals = {name: getattr(_settings, name) for name in updates}
    for name, value in updates.items():
        setattr(_settings, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(_settings, name, value)


@contextlib.contextmanager
def armed_desktop_app_home(app_home: Path) -> Iterator[None]:
    """Arm the desktop profile on the shared ``settings`` singleton.

    ``desktop_profile_armed`` is a read-only property derived from
    ``desktop_app_home``, so arming means setting the field the property
    reads. Built on :func:`settings_override`, the sanctioned attribute-swap
    seam, and confirms the derived property actually flips before yielding.
    """
    with settings_override(desktop_app_home=app_home):
        assert _settings.desktop_profile_armed is True
        yield
