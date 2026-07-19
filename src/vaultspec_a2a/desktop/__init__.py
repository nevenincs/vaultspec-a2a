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
"""

from .contract import ACP_VERSION_PIN as ACP_VERSION_PIN
from .contract import CONTRACT_VERSION as CONTRACT_VERSION
from .contract import CPYTHON_VERSION_PIN as CPYTHON_VERSION_PIN
from .contract import NODEJS_VERSION_PIN as NODEJS_VERSION_PIN
from .contract import ApiVersionRange as ApiVersionRange
from .contract import ComponentAsset as ComponentAsset
from .contract import ComponentAssetKind as ComponentAssetKind
from .contract import ComponentCompatibility as ComponentCompatibility
from .contract import ComponentEntrypoint as ComponentEntrypoint
from .contract import ComponentEntrypoints as ComponentEntrypoints
from .contract import ComponentIdentity as ComponentIdentity
from .contract import ComponentManifest as ComponentManifest
from .contract import DependencyLockIdentity as DependencyLockIdentity
from .contract import DigestAlgorithm as DigestAlgorithm
from .contract import EntrypointKind as EntrypointKind
from .contract import GatewayApiVersion as GatewayApiVersion
from .contract import GatewayEntrypoint as GatewayEntrypoint
from .contract import MigrationRange as MigrationRange
from .contract import StandaloneMcpEntrypoint as StandaloneMcpEntrypoint
from .contract import TargetTriple as TargetTriple
from .contract import component_manifest_schema as component_manifest_schema
from .contract import contract_versions_compatible as contract_versions_compatible
from .contract import (
    export_component_manifest_schema as export_component_manifest_schema,
)
from .manifest import CANONICAL_JSON_VERSION as CANONICAL_JSON_VERSION
from .manifest import AssetSource as AssetSource
from .manifest import ManifestEmissionError as ManifestEmissionError
from .manifest import (
    component_manifest_canonical_bytes as component_manifest_canonical_bytes,
)
from .manifest import component_manifest_digest as component_manifest_digest
from .manifest import emit_component_manifest as emit_component_manifest

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
