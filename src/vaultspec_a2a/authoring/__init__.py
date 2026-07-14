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
from .client import ACTOR_TOKEN_HEADER as ACTOR_TOKEN_HEADER
from .client import BEARER_HEADER as BEARER_HEADER
from .client import AuthoringClient as AuthoringClient

__all__ = [
    "ACTOR_TOKEN_HEADER",
    "BEARER_HEADER",
    "MAX_ID_BYTES",
    "AuthoringClient",
    "AuthoringError",
    "AuthoringResponse",
    "AuthoringTransportError",
    "CommandEnvelope",
    "Denial",
    "derive_idempotency_key",
    "is_valid_id",
    "validate_id",
]
