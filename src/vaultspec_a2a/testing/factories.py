"""Production constructors with the one input a test chooses.

Two production constructors need a test's hand, and each had grown a private copy
per test file:

- :class:`LaneInventoryFactory` is the production ``ProviderFactory`` serving the
  catalog lanes a test chooses. ``catalog_registrations`` is the catalog service's
  own composition seam: every registration and its awaited discovery is the
  production contract, so the only choice left to a test is WHICH lanes are
  served - a subset of the ones production registers, or lanes of the test's own
  where a host-dependent provider would make the result unreproducible.
- :func:`load_settings` constructs a settings class with exactly the dotenv source
  the test names, and :func:`build_settings` is that for ``Settings``.
  ``BaseSettings.__init__`` accepts ``_env_file``, but pydantic's
  dataclass-transform ``__init__`` synthesis for subclasses hides it from static
  analysis, so the real constructor signature is recovered here, once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast, override

from ..control.config import Settings
from ..providers import ProviderFactory

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pydantic_settings import BaseSettings

    from ..providers.factory import ProviderCatalogRegistration

__all__ = ["LaneInventoryFactory", "build_settings", "load_settings"]

type _Inventory = Callable[
    [tuple[ProviderCatalogRegistration, ...]],
    tuple[ProviderCatalogRegistration, ...],
]


class LaneInventoryFactory(ProviderFactory):
    """The production factory serving only the catalog lanes a test chooses.

    *inventory* receives the registrations production would serve for the
    request and returns the ones to serve instead.
    """

    def __init__(self, inventory: _Inventory) -> None:
        super().__init__()
        self._inventory = inventory

    @override
    def catalog_registrations(
        self, workspace_root: Path, *, serve_in_process_lanes: bool | None = None
    ) -> tuple[ProviderCatalogRegistration, ...]:
        return self._inventory(
            super().catalog_registrations(
                workspace_root, serve_in_process_lanes=serve_in_process_lanes
            )
        )


class _SettingsConstructor[S: BaseSettings](Protocol):
    """A settings class called with pydantic-settings' private ``_env_file``."""

    def __call__(self, *, _env_file: Path | None) -> S: ...


def load_settings[S: BaseSettings](
    settings_cls: type[S], *, env_file: Path | None
) -> S:
    """Construct *settings_cls* reading exactly *env_file* as its dotenv source.

    ``None`` reads no dotenv file at all, so a developer's own ``.env`` cannot
    colour the result; a named file is the construction call's own source.
    """
    return cast("_SettingsConstructor[S]", settings_cls)(_env_file=env_file)


def build_settings(*, env_file: Path | None) -> Settings:
    """Construct ``Settings`` reading exactly *env_file* as its dotenv source."""
    return load_settings(Settings, env_file=env_file)
