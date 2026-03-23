"""Backwards-compatibility shim — delegates to control.config and domain_config.

All consumers that import ``from vaultspec_a2a.core.config import Settings`` or
``from ..core.config import settings`` continue to work unchanged.  New code
should import from ``vaultspec_a2a.control.config`` or
``vaultspec_a2a.domain_config`` directly.
"""

from ..control.config import Settings as Settings
from ..control.config import settings as settings
from ..domain_config import DomainConfig as DomainConfig

__all__ = ["DomainConfig", "Settings", "settings"]
