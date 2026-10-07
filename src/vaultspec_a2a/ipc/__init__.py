"""Define the neutral gateway-worker inter-process contract.

:mod:`vaultspec_a2a.ipc.schemas` defines dispatch requests, responses, and
execution-projection payloads. :mod:`vaultspec_a2a.ipc.serializers` encodes
values that cross the process boundary. :mod:`vaultspec_a2a.ipc.body_limit`
bounds the HTTP bodies each process accepts before they are parsed.

:mod:`vaultspec_a2a.api` handlers delegate to :mod:`vaultspec_a2a.control`
services, which produce gateway-side requests. :mod:`vaultspec_a2a.worker`
consumes them and returns projection updates.

Contract models use Pydantic and remain independent of gateway and worker
implementations.
"""

from .body_limit import BoundedHttpBodyMiddleware as BoundedHttpBodyMiddleware
from .body_limit import gateway_body_limit as gateway_body_limit
from .body_limit import worker_body_limit as worker_body_limit
from .schemas import DispatchRequest as DispatchRequest
from .schemas import DispatchResponse as DispatchResponse
from .schemas import ExecutionStateProjectionPayload as ExecutionStateProjectionPayload

__all__ = [
    "BoundedHttpBodyMiddleware",
    "DispatchRequest",
    "DispatchResponse",
    "ExecutionStateProjectionPayload",
    "gateway_body_limit",
    "worker_body_limit",
]
