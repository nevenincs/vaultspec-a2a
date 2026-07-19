"""Desktop product profile: the capsule component contract and its emitter.

Facade re-exporting the public desktop-capsule types. Consumers import from
this package root rather than reaching into sub-modules::

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
from .manifest import AssetSource as AssetSource
from .manifest import ManifestEmissionError as ManifestEmissionError
from .manifest import component_manifest_digest as component_manifest_digest
from .manifest import emit_component_manifest as emit_component_manifest

__all__ = [
    "ACP_VERSION_PIN",
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
    "component_manifest_digest",
    "component_manifest_schema",
    "contract_versions_compatible",
    "emit_component_manifest",
    "export_component_manifest_schema",
]
