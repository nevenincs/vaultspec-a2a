"""Desktop runtime profile: the component contract and its runtime authorities.

:mod:`vaultspec_a2a.desktop.contract` defines the versioned component model the
dashboard verifies before launching the bundled runtime. The runtime seam -
:mod:`vaultspec_a2a.desktop.profile`, :mod:`vaultspec_a2a.desktop.credentials`,
:mod:`vaultspec_a2a.desktop.settlement`, and the dashboard-spawnable store
migration in :mod:`vaultspec_a2a.desktop.migration` - is imported by its own
module path; this facade re-exports only the stable component-contract
surface.

Consumers of the stable component-manifest contract import from this package
root::

    from vaultspec_a2a.desktop import ComponentManifest

The contract exports are resolved lazily to break an import cycle: the settings
profile's ``_seat_desktop_profile`` validator imports
:mod:`vaultspec_a2a.desktop.profile` while ``control.config`` is still being
constructed, and eagerly importing ``.contract`` here would drag in the
``database`` package, which imports the half-initialized ``control.config``.
Deferring the exports keeps ``desktop.profile`` and ``desktop.credentials``
importable without closing that cycle.
"""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contract import (
        ACP_VERSION_PIN as ACP_VERSION_PIN,
    )
    from .contract import (
        CONTRACT_VERSION as CONTRACT_VERSION,
    )
    from .contract import (
        CPYTHON_VERSION_PIN as CPYTHON_VERSION_PIN,
    )
    from .contract import (
        NODEJS_VERSION_PIN as NODEJS_VERSION_PIN,
    )
    from .contract import (
        ApiVersionRange as ApiVersionRange,
    )
    from .contract import (
        ComponentAsset as ComponentAsset,
    )
    from .contract import (
        ComponentAssetKind as ComponentAssetKind,
    )
    from .contract import (
        ComponentCompatibility as ComponentCompatibility,
    )
    from .contract import (
        ComponentEntrypoint as ComponentEntrypoint,
    )
    from .contract import (
        ComponentEntrypoints as ComponentEntrypoints,
    )
    from .contract import (
        ComponentIdentity as ComponentIdentity,
    )
    from .contract import (
        ComponentManifest as ComponentManifest,
    )
    from .contract import (
        DependencyLockIdentity as DependencyLockIdentity,
    )
    from .contract import (
        DigestAlgorithm as DigestAlgorithm,
    )
    from .contract import (
        EntrypointKind as EntrypointKind,
    )
    from .contract import (
        GatewayApiVersion as GatewayApiVersion,
    )
    from .contract import (
        GatewayEntrypoint as GatewayEntrypoint,
    )
    from .contract import (
        MigrationRange as MigrationRange,
    )
    from .contract import (
        StandaloneMcpEntrypoint as StandaloneMcpEntrypoint,
    )
    from .contract import (
        TargetTriple as TargetTriple,
    )
    from .contract import (
        component_manifest_schema as component_manifest_schema,
    )
    from .contract import (
        contract_versions_compatible as contract_versions_compatible,
    )
    from .contract import (
        export_component_manifest_schema as export_component_manifest_schema,
    )

# Each public name resolves to its owning submodule on first access.
_LAZY_IMPORTS = {
    "ACP_VERSION_PIN": ".contract",
    "CONTRACT_VERSION": ".contract",
    "CPYTHON_VERSION_PIN": ".contract",
    "NODEJS_VERSION_PIN": ".contract",
    "ApiVersionRange": ".contract",
    "ComponentAsset": ".contract",
    "ComponentAssetKind": ".contract",
    "ComponentCompatibility": ".contract",
    "ComponentEntrypoint": ".contract",
    "ComponentEntrypoints": ".contract",
    "ComponentIdentity": ".contract",
    "ComponentManifest": ".contract",
    "DependencyLockIdentity": ".contract",
    "DigestAlgorithm": ".contract",
    "EntrypointKind": ".contract",
    "GatewayApiVersion": ".contract",
    "GatewayEntrypoint": ".contract",
    "MigrationRange": ".contract",
    "StandaloneMcpEntrypoint": ".contract",
    "TargetTriple": ".contract",
    "component_manifest_schema": ".contract",
    "contract_versions_compatible": ".contract",
    "export_component_manifest_schema": ".contract",
}


def __getattr__(name: str) -> object:
    module_name = _LAZY_IMPORTS.get(name)
    if module_name is not None:
        module = importlib.import_module(module_name, __name__)
        value = getattr(module, name)
        globals()[name] = value  # cache for subsequent access
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return sorted(_LAZY_IMPORTS)


__all__ = [
    "ACP_VERSION_PIN",
    "CONTRACT_VERSION",
    "CPYTHON_VERSION_PIN",
    "NODEJS_VERSION_PIN",
    "ApiVersionRange",
    "ComponentAsset",
    "ComponentAssetKind",
    "ComponentCompatibility",
    "ComponentEntrypoint",
    "ComponentEntrypoints",
    "ComponentIdentity",
    "ComponentManifest",
    "DependencyLockIdentity",
    "DigestAlgorithm",
    "EntrypointKind",
    "GatewayApiVersion",
    "GatewayEntrypoint",
    "MigrationRange",
    "StandaloneMcpEntrypoint",
    "TargetTriple",
    "component_manifest_schema",
    "contract_versions_compatible",
    "export_component_manifest_schema",
]
