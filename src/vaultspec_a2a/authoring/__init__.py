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
from .discovery import SERVICE_JSON_ENV as SERVICE_JSON_ENV
from .discovery import EngineEndpoint as EngineEndpoint
from .discovery import resolve_engine as resolve_engine
from .lifecycle import VERDICT_APPROVED as VERDICT_APPROVED
from .lifecycle import VERDICT_REJECTED as VERDICT_REJECTED
from .lifecycle import VERDICT_REQUEST_CHANGES as VERDICT_REQUEST_CHANGES
from .lifecycle import GapSignal as GapSignal
from .lifecycle import LifecycleEvent as LifecycleEvent
from .lifecycle import SseFrame as SseFrame
from .lifecycle import StreamError as StreamError
from .lifecycle import changeset_status_verdict as changeset_status_verdict
from .lifecycle import parse_sse_frame as parse_sse_frame
from .lifecycle import verdict_from_event as verdict_from_event
from .session import AuthoringSession as AuthoringSession
from .session import mint_actor_token as mint_actor_token
from .submitter import CredentialsMissingError as CredentialsMissingError
from .submitter import DocumentConformanceError as DocumentConformanceError
from .submitter import DocumentProposalSubmitter as DocumentProposalSubmitter
from .submitter import DocumentUnavailableError as DocumentUnavailableError
from .submitter import EngineUnavailableError as EngineUnavailableError
from .submitter import PhaseAuthoringSpec as PhaseAuthoringSpec
from .submitter import ProposalDeniedError as ProposalDeniedError
from .submitter import RoleConfigInvalidError as RoleConfigInvalidError
from .submitter import SubmitterError as SubmitterError

__all__ = [
    "ACTOR_TOKEN_HEADER",
    "BEARER_HEADER",
    "CATALOG_SCHEMA_VERSION",
    "MAX_ID_BYTES",
    "SERVICE_JSON_ENV",
    "VERDICT_APPROVED",
    "VERDICT_REJECTED",
    "VERDICT_REQUEST_CHANGES",
    "AgentTool",
    "AuthoringClient",
    "AuthoringError",
    "AuthoringResponse",
    "AuthoringSession",
    "AuthoringTransportError",
    "CatalogSnapshot",
    "CommandEnvelope",
    "CredentialsMissingError",
    "Denial",
    "DocumentConformanceError",
    "DocumentProposalSubmitter",
    "DocumentUnavailableError",
    "EngineEndpoint",
    "EngineUnavailableError",
    "GapSignal",
    "LifecycleEvent",
    "PhaseAuthoringSpec",
    "ProposalDeniedError",
    "RoleConfigInvalidError",
    "SseFrame",
    "StreamError",
    "SubmitterError",
    "changeset_status_verdict",
    "derive_idempotency_key",
    "execute_agent_tool",
    "fetch_catalog",
    "is_valid_id",
    "mint_actor_token",
    "parse_sse_frame",
    "resolve_engine",
    "validate_id",
    "verdict_from_event",
]
