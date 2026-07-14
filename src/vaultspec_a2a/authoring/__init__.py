"""Engine authoring-API client (ADR R3).

The single package that speaks to the dashboard engine's authoring plane. No
other package in this repo may talk to the engine directly; all envelope,
idempotency, auth, and denial handling lives here.

Consumers import from this facade rather than the private sub-modules::

    from vaultspec_a2a.authoring import AuthoringClient, Denial
"""

from ._envelope import AuthoringResponse as AuthoringResponse
from ._envelope import CommandEnvelope as CommandEnvelope
from ._envelope import Denial as Denial
from ._errors import AuthoringError as AuthoringError
from ._errors import AuthoringTransportError as AuthoringTransportError
from ._ids import MAX_ID_BYTES as MAX_ID_BYTES
from ._ids import derive_idempotency_key as derive_idempotency_key
from ._ids import is_valid_id as is_valid_id
from ._ids import validate_id as validate_id
from .catalog import CATALOG_SCHEMA_VERSION as CATALOG_SCHEMA_VERSION
from .catalog import AgentTool as AgentTool
from .catalog import CatalogSnapshot as CatalogSnapshot
from .catalog import execute_agent_tool as execute_agent_tool
from .catalog import fetch_catalog as fetch_catalog
from .client import ACTOR_TOKEN_HEADER as ACTOR_TOKEN_HEADER
from .client import BEARER_HEADER as BEARER_HEADER
from .client import AuthoringClient as AuthoringClient
from .session import AuthoringSession as AuthoringSession
from .session import mint_actor_token as mint_actor_token

__all__ = [
    "ACTOR_TOKEN_HEADER",
    "BEARER_HEADER",
    "CATALOG_SCHEMA_VERSION",
    "MAX_ID_BYTES",
    "AgentTool",
    "AuthoringClient",
    "AuthoringError",
    "AuthoringResponse",
    "AuthoringSession",
    "AuthoringTransportError",
    "CatalogSnapshot",
    "CommandEnvelope",
    "Denial",
    "derive_idempotency_key",
    "execute_agent_tool",
    "fetch_catalog",
    "is_valid_id",
    "mint_actor_token",
    "validate_id",
]
