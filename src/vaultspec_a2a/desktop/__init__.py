"""Desktop product profile: the capsule component contract and its emitter.

:mod:`vaultspec_a2a.desktop.contract` defines the versioned component model,
while :mod:`vaultspec_a2a.desktop.manifest` emits and hashes deterministic
manifest bytes. This facade re-exports their supported public types.
:mod:`vaultspec_a2a.desktop.artifacts` verifies exact local input identities,
:mod:`vaultspec_a2a.desktop.capsule` projects bounded archive content, and
:mod:`vaultspec_a2a.desktop.capsule_evidence` validates installed-tree evidence
and publishes deterministic archives. Those assembly modules are workflow
internals and aren't re-exported here.

Consumers of the stable component-manifest contract import from this package
root::

    from vaultspec_a2a.desktop import ComponentManifest, emit_component_manifest

The contract and manifest exports are resolved lazily to break an import cycle:
the settings profile's ``_seat_desktop_profile`` validator imports
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
    from .manifest import (
        CANONICAL_JSON_VERSION as CANONICAL_JSON_VERSION,
    )
    from .manifest import (
        AssetSource as AssetSource,
    )
    from .manifest import (
        ManifestEmissionError as ManifestEmissionError,
    )
    from .manifest import (
        component_manifest_canonical_bytes as component_manifest_canonical_bytes,
    )
    from .manifest import (
        component_manifest_digest as component_manifest_digest,
    )
    from .manifest import (
        emit_component_manifest as emit_component_manifest,
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
    "CANONICAL_JSON_VERSION": ".manifest",
    "AssetSource": ".manifest",
    "ManifestEmissionError": ".manifest",
    "component_manifest_canonical_bytes": ".manifest",
    "component_manifest_digest": ".manifest",
    "emit_component_manifest": ".manifest",
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
    "CANONICAL_JSON_VERSION",
    "CONTRACT_VERSION",
    "CPYTHON_VERSION_PIN",
    "NODEJS_VERSION_PIN",
    "ApiVersionRange",
    "AssetSource",
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
    "ManifestEmissionError",
    "MigrationRange",
    "StandaloneMcpEntrypoint",
    "TargetTriple",
    "component_manifest_canonical_bytes",
    "component_manifest_digest",
    "component_manifest_schema",
    "contract_versions_compatible",
    "emit_component_manifest",
    "export_component_manifest_schema",
]
