"""The app factory and in-process worker shared by api/tests/.

``make_app`` injects the root ``session_factory`` and ``checkpointer`` fixtures
- a per-test SQLite file and a real ``AsyncSqliteSaver`` - into app state, so
every test module shares one isolated store setup.

The gateway no longer runs agent execution locally.  Tests wire a
real in-process dispatch receiver (a minimal FastAPI ASGI app served via
``httpx.ASGITransport``) so that HTTP serialisation and routing are exercised
without a live worker process.  No ``MockTransport``, no ``unittest.mock``.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import httpx
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...control._worker_health import internal_auth_headers
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.config import settings
from ...control.event_handlers import CheckpointPruneRegistry
from ...database import create_thread
from ...providers.in_process_catalog import in_process_catalog_key
from ...providers.lane_registry import registered_lanes
from ...streaming import RelayHub
from ...testing import LaneInventoryFactory, adopted_spawner
from ...tests._write_authority import make_test_write_authority
from ...worker._dispatch_contract import CAPACITY_FULL
from ...worker.app import capacity_refusal, verify_dispatch_token
from ..app import create_app
from ..dependencies import LIFECYCLE_CAPABILITY_HEADER
from ..internal import internal_router

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.types import ASGIApp, Receive, Scope, Send

    from ...providers.factory import ProviderCatalogRegistration
    from ...providers.provider_catalog_service import ProviderCatalogService
    from ...thread.enums import ThreadStatus

type SessionFactory = async_sessionmaker[AsyncSession]
type JsonValue = (
    bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
)

# A recorded dispatch body, whose VALUES stay `Any` deliberately. Typing them as
# `JsonValue` describes the wire shape accurately but makes the payload unusable
# to the tests that consume it: a dispatch is navigated several levels deep
# (``d["option_id"]["answers"]["scope"]``), and every step off a recursive union
# is unsubscriptable because the union admits `int`, `str` and `None`. The
# precision is real and unhelpful here - it forces a cast or a narrowing branch
# at each of ~45 assertion sites, which buys no safety in a test that is
# asserting the very structure it would be narrowing. The dict itself stays
# typed, so the container contract is still stated.
type DispatchPayload = dict[str, Any]

__all__: list[str] = []


async def seed_run_with_status(
    session_factory: SessionFactory, thread_id: str, status: ThreadStatus
) -> None:
    """Persist one run in *status* for tests that read durable stream state.

    The stream body reads the run's status from the database rather than being
    handed one, so a test that wants a stream to see a given status has to put
    that status where the stream looks.
    """
    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=thread_id,
            status=status,
        )
        await session.commit()


# ---------------------------------------------------------------------------
# In-process dispatch receiver — real FastAPI ASGI, no mock
# ---------------------------------------------------------------------------


class _InProcessWorker:
    """Minimal in-process worker that accepts /dispatch and /health requests.

    Uses a real FastAPI ASGI app served via ``httpx.ASGITransport`` — real
    HTTP serialisation and Pydantic validation are exercised on every request.
    Not a mock, not a fake transport handler, not ``unittest.mock``.

    The dispatch route is guarded by the worker's own bearer dependency and
    refuses at capacity with the worker's own refusal, so the gateway classifies
    a genuine definite non-delivery from the response the real worker sends.
    The client presents the worker-IPC header for *internal_token*, the secret the
    gateway under test seated.

    Attributes:
        dispatches: All dispatch request bodies received so far.
    """

    def __init__(self, internal_token: str | None) -> None:
        self.dispatches: list[DispatchPayload] = []
        self.dispatch_received = asyncio.Event()
        self.release_dispatch = asyncio.Event()
        self.release_dispatch.set()
        self._at_capacity = False

        _app = FastAPI()

        async def _dispatch(request: Request) -> dict[str, str]:
            body = cast("DispatchPayload", await request.json())
            self.dispatches.append(body)
            self.dispatch_received.set()
            await self.release_dispatch.wait()
            if self._at_capacity:
                raise capacity_refusal(CAPACITY_FULL)
            thread_id = body.get("thread_id", "")
            if not isinstance(thread_id, str):
                thread_id = ""
            return {"status": "dispatched", "thread_id": thread_id}

        async def _health() -> dict[str, str]:
            return {"status": "ok"}

        _app.add_api_route(
            "/dispatch",
            _dispatch,
            methods=["POST"],
            response_model=None,
            dependencies=[Depends(verify_dispatch_token)],
        )
        _app.add_api_route("/health", _health, methods=["GET"])

        self._client = httpx.AsyncClient(
            transport=ASGITransport(app=_app),
            base_url="http://test-worker:8001",
            headers=internal_auth_headers(internal_token),
        )

    @property
    def client(self) -> httpx.AsyncClient:
        """Return the httpx client backed by the in-process worker app."""
        return self._client

    def clear(self) -> None:
        """Clear all recorded dispatch requests."""
        self.dispatches.clear()

    def hold_dispatch_response(self) -> None:
        """Pause a real dispatch response after its request has been recorded."""
        self.dispatch_received.clear()
        self.release_dispatch.clear()

    def refuse_at_capacity(self) -> None:
        """Answer every further dispatch with the worker's real 429 refusal."""
        self._at_capacity = True


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

type AppFixture = tuple[FastAPI, RelayHub, _InProcessWorker, AsyncSqliteSaver]

# The credentials every ``make_app`` gateway holds. Known constants, so a test
# that wants to present them, or to present something else, can name them.
SEATED_ATTACH_TOKEN = "seated-attach-token-0123456789abcdef"
SEATED_LIFECYCLE_CAPABILITY = "seated-lifecycle-capability-0123456789abcdef"

_AUTHORIZATION = b"authorization"
_CAPABILITY = LIFECYCLE_CAPABILITY_HEADER.lower().encode("latin-1")


class _SeatedCredentials:
    """Present the app's own credentials on every request that carries none.

    Route-behaviour suites reach the gateway through clients of their own - a
    ``TestClient``, an ASGI transport, a socket - that do not authenticate. This
    layer is the credentialed client they share: it adds the attach bearer and the
    lifecycle capability the app currently holds, so every request still crosses
    the production gates and is verified by the production comparison. A header a
    request already carries is never replaced, so presenting a wrong credential is
    still refused. The relay plane is skipped because it verifies a different
    credential on the same ``Authorization`` header.

    Credentials are read from app state per request rather than captured, since
    suites reseat them after the factory returns.
    """

    def __init__(self, app: ASGIApp, *, owner: FastAPI) -> None:
        self._app = app
        self._owner = owner

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not scope["path"].startswith(
            internal_router.prefix
        ):
            scope = {**scope, "headers": self._credentialed(scope["headers"])}
        await self._app(scope, receive, send)

    def _credentialed(
        self, headers: list[tuple[bytes, bytes]]
    ) -> list[tuple[bytes, bytes]]:
        presented = {name for name, _ in headers}
        credentialed = list(headers)
        token = getattr(self._owner.state, "v1_service_token", None)
        if isinstance(token, str) and token and _AUTHORIZATION not in presented:
            credentialed.append((_AUTHORIZATION, f"Bearer {token}".encode()))
        capability = getattr(self._owner.state, "lifecycle_capability", None)
        if isinstance(capability, str) and capability and _CAPABILITY not in presented:
            credentialed.append((_CAPABILITY, capability.encode()))
        return credentialed


_session_catalog_service_cache: ProviderCatalogService | None = None


def _in_process_only(
    served: tuple[ProviderCatalogRegistration, ...],
) -> tuple[ProviderCatalogRegistration, ...]:
    """Keep production's in-process registrations, so no provider CLI is probed."""
    in_process = {in_process_catalog_key(lane) for lane in registered_lanes()}
    return tuple(
        registration for registration in served if registration.key in in_process
    )


def _session_catalog_service() -> ProviderCatalogService:
    """Return the process-wide provider catalog service, serving in-process lanes.

    Built once and reused. See the note at its injection site in `make_app` for
    why per-app construction was the wrong default.

    The in-process lanes are armed through the CONSTRUCTOR, never the process
    environment. These suites spawn real gateway subprocesses, and the
    environment is inherited: arming a lane process-wide for this service would
    silently rearm it for every child and change the lane inventory served to
    tests that have nothing to do with selection. The argument declares this
    caller's posture and reaches nothing else.

    Arming at all is what lets the run-bearing fixtures below select a lane that
    bills nothing. Unarmed, the only selectable lane on a developer machine
    holding a live provider session is that real provider - so every suite that
    starts a run was freezing a metered lane to assert on gateway plumbing.
    """
    global _session_catalog_service_cache
    if _session_catalog_service_cache is None:
        from datetime import timedelta

        from ...providers.provider_catalog_service import ProviderCatalogService

        _session_catalog_service_cache = ProviderCatalogService(
            factory=LaneInventoryFactory(_in_process_only),
            ttl=timedelta(hours=6),
            serve_in_process_lanes=True,
        )
    return _session_catalog_service_cache


def make_app(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    aggregator: RelayHub | None = None,
    *,
    stamp_credentials: bool = True,
) -> AppFixture:
    """Create a test FastAPI app with explicit app-state injection.

    Wires a real in-process dispatch receiver (ASGITransport over a
    minimal FastAPI app) for the worker client, and injects the real
    AsyncSqliteSaver checkpointer from the calling fixture.

    The gateway holds ``SEATED_ATTACH_TOKEN`` and ``SEATED_LIFECYCLE_CAPABILITY``
    and enforces them through the production gates. By default every request
    that presents no credential of its own is sent with them; pass
    ``stamp_credentials=False`` for a test that exercises the gates themselves
    and so must present exactly what it chooses, or nothing.

    Returns:
        Tuple of (app, aggregator, worker, checkpointer).
    """

    @asynccontextmanager
    async def _test_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        yield

    app = create_app(lifespan=_test_lifespan)
    app.state.v1_service_token = SEATED_ATTACH_TOKEN
    app.state.lifecycle_capability = SEATED_LIFECYCLE_CAPABILITY
    if stamp_credentials:
        app.add_middleware(cast("Any", _SeatedCredentials), owner=app)

    if aggregator is None:
        aggregator = RelayHub()

    worker = _InProcessWorker(app.state.internal_token)

    # ONE catalog service for the whole session, not one per app.
    #
    # The service owns a real TTL cache, but `make_app` builds a fresh app per
    # test, so a per-app service threw that cache away and re-probed every
    # provider lane on every test - measured at ~15s each, which dominated the
    # runtime of every suite that starts a run. The probe result is a property
    # of the machine and workspace, not of the app under test, so rebuilding it
    # per test is pure waste rather than isolation.
    #
    # Sharing the real production object keeps the real code path: the cache
    # being exercised is the one that ships, its TTL is simply widened past the
    # length of a suite so a long run does not re-probe mid-flight.
    app.state.provider_catalog_service = _session_catalog_service()

    # Store singletons in app.state so WebSocket handlers can read them
    app.state.aggregator = aggregator
    app.state.checkpointer = checkpointer
    # The gateway lifespan seats one beside the store it prunes through, and a
    # relayed terminal schedules nothing without it.
    app.state.checkpoint_prunes = CheckpointPruneRegistry()

    # In-process worker client — real ASGI, no mock
    app.state.worker_client = worker.client

    # circuit breaker for dispatch calls
    cb = WorkerCircuitBreaker(
        failure_threshold=settings.cb_failure_threshold,
        recovery_timeout=settings.cb_recovery_timeout_seconds,
    )
    app.state.circuit_breaker = cb

    # PHASE-1a: lazy worker spawner — pre-marked as spawned for tests
    spawner = adopted_spawner("http://test-worker:8001")
    app.state.worker_spawner = spawner
    app.state.db_session_factory = session_factory

    return app, aggregator, worker, checkpointer
