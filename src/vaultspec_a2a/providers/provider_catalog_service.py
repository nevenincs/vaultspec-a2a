"""Workspace-scoped composition of prompt-free provider catalog discovery."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..graph.enums import Provider
from .factory import (
    ProviderCatalogRegistration,
    ProviderFactory,
)
from .lane_admission import (
    catalog_lane_admission_reason,
    is_catalog_lane_admissible,
)
from .provider_catalog import (
    AdmissionState,
    AuthenticationState,
    CacheFreshness,
    CatalogRefreshCache,
    CatalogRefreshSuppressedError,
    CatalogState,
    CatalogStatus,
    HealthState,
    ProviderCatalog,
    ProviderCatalogKey,
    ProviderRecord,
    StructuredProviderHealth,
)

logger = logging.getLogger(__name__)

PROVIDER_CATALOG_CACHE_TTL = timedelta(minutes=5)
_MAX_WORKSPACE_SCOPES = 16
_DISPLAY_NAMES = {
    Provider.CLAUDE: "Claude",
    Provider.CODEX: "Codex",
    Provider.GEMINI: "Gemini",
    Provider.KIMI: "Kimi Code",
    Provider.OPENAI: "OpenAI",
    Provider.ZAI: "Z.ai",
    Provider.ZHIPU: "Zhipu AI",
    # The in-process lanes name themselves as such wherever they are displayed.
    # They are served only to a deployment that armed them, but a served lane is
    # a lane a human can read, and one that returns fixed or replayed content
    # must not be presentable as an ordinary provider.
    Provider.DETERMINISTIC: "Deterministic (in-process)",
    Provider.MOCK: "Mock (in-process tape replay)",
}


@dataclass(slots=True)
class _WorkspaceScope:
    registrations: tuple[ProviderCatalogRegistration, ...]
    cache: CatalogRefreshCache
    authentication: dict[ProviderCatalogKey, AuthenticationState]
    configured: dict[ProviderCatalogKey, HealthState]
    transport: dict[ProviderCatalogKey, HealthState]
    active_users: int = 0


class ProviderCatalogScopeCapacityError(RuntimeError):
    """All bounded workspace scopes are in use and none can be evicted safely."""


class ProviderCatalogService:
    """Serve all registered external lanes without running a model completion."""

    def __init__(
        self,
        *,
        factory: ProviderFactory | None = None,
        ttl: timedelta = PROVIDER_CATALOG_CACHE_TTL,
        max_workspace_scopes: int = _MAX_WORKSPACE_SCOPES,
    ) -> None:
        if max_workspace_scopes <= 0:
            raise ValueError("max_workspace_scopes must be positive")
        self._factory = factory or ProviderFactory()
        self._ttl = ttl
        self._max_workspace_scopes = max_workspace_scopes
        self._scopes: OrderedDict[str, _WorkspaceScope] = OrderedDict()
        self._scope_lock = asyncio.Lock()

    async def _acquire_scope(self, workspace_root: str) -> _WorkspaceScope:
        async with self._scope_lock:
            current = self._scopes.get(workspace_root)
            if current is not None:
                self._scopes.move_to_end(workspace_root)
                current.active_users += 1
                return current
            if len(self._scopes) >= self._max_workspace_scopes:
                inactive = next(
                    (
                        identity
                        for identity, scope in self._scopes.items()
                        if scope.active_users == 0
                    ),
                    None,
                )
                if inactive is None:
                    raise ProviderCatalogScopeCapacityError(
                        "provider catalog workspace capacity is busy"
                    )
                del self._scopes[inactive]
            registrations = self._factory.catalog_registrations(Path(workspace_root))
            scope = _WorkspaceScope(
                registrations=registrations,
                cache=CatalogRefreshCache(
                    self._ttl, max_lanes=max(1, len(registrations))
                ),
                authentication={},
                configured={},
                transport={},
                active_users=1,
            )
            self._scopes[workspace_root] = scope
            return scope

    async def _release_scope(self, scope: _WorkspaceScope) -> None:
        async with self._scope_lock:
            if scope.active_users <= 0:
                raise RuntimeError("provider catalog workspace scope release underflow")
            scope.active_users -= 1

    async def records(self, workspace_root: str) -> tuple[ProviderRecord, ...]:
        """Discover each lane independently and preserve registry ordering."""
        scope = await self._acquire_scope(workspace_root)
        try:
            discovered = await asyncio.gather(
                *(
                    self._record(scope, registration)
                    for registration in scope.registrations
                )
            )
            return tuple(discovered)
        finally:
            await self._release_scope(scope)

    async def _record(
        self, scope: _WorkspaceScope, registration: ProviderCatalogRegistration
    ) -> ProviderRecord:
        key = registration.key

        async def load(requested: ProviderCatalogKey) -> ProviderCatalog:
            if requested != key:
                raise ValueError("catalog loader received a different lane")
            result = await registration.discover()
            validate_public_catalog_bounds(result.catalog)
            scope.authentication[key] = result.authentication
            scope.configured[key] = result.configured
            scope.transport[key] = result.transport
            return result.catalog

        refresh_failed = False
        try:
            snapshot = await scope.cache.get(key, load)
        except CatalogRefreshSuppressedError as exc:
            # Not a fresh failure: this lane failed recently and is inside its
            # retry backoff, so no discovery ran. Logged distinctly from a real
            # attempt so a reader can tell a lane that is failing from a lane that
            # is merely being left alone, and at debug because a burst of reads
            # during one outage would otherwise fill the log with one fact.
            logger.debug(
                "provider catalog refresh suppressed for %s/%s after a %s, "
                "retrying in %.1fs",
                key.provider_id,
                key.execution_mode,
                exc.failure_type,
                exc.retry_after_seconds,
            )
            refresh_failed = True
            snapshot = scope.cache.peek(key)
        except Exception as exc:
            # Provider exception text may contain credentials, URLs, or local paths.
            # Keep diagnostics to the type locally and serve a fixed safe reason.
            logger.warning(
                "provider catalog refresh failed for %s/%s (%s)",
                key.provider_id,
                key.execution_mode,
                type(exc).__name__,
            )
            refresh_failed = True
            snapshot = scope.cache.peek(key)

        authentication = scope.authentication.get(key, AuthenticationState.UNKNOWN)
        configured = scope.configured.get(key, HealthState.UNKNOWN)
        transport = scope.transport.get(key, HealthState.UNKNOWN)
        if snapshot is None:
            now = datetime.now(UTC)
            catalog = ProviderCatalog(
                key=key,
                state=CatalogState(
                    status=CatalogStatus.UNAVAILABLE,
                    checked_at=now,
                    reason="provider catalog refresh failed",
                ),
                models=(),
            )
        else:
            state = snapshot.catalog.state
            status = state.status
            reason = state.reason
            if (
                refresh_failed or snapshot.freshness is CacheFreshness.STALE
            ) and state.revision is not None:
                status = CatalogStatus.STALE
                reason = "cached provider catalog is stale after refresh failure"
            elif refresh_failed:
                reason = "provider catalog refresh failed"
            catalog = replace(
                snapshot.catalog,
                state=replace(
                    state,
                    status=status,
                    expires_at=snapshot.expires_at,
                    reason=reason,
                ),
            )

        health = _health_for(key, catalog, authentication, configured, transport)
        provider = Provider(key.provider_id)
        return ProviderRecord(
            provider_id=key.provider_id,
            display_name=_DISPLAY_NAMES[provider],
            execution_mode=key.execution_mode,
            health=health,
            catalog=catalog,
        )


def _health_for(
    key: ProviderCatalogKey,
    catalog: ProviderCatalog,
    authentication: AuthenticationState,
    configured: HealthState,
    transport: HealthState,
) -> StructuredProviderHealth:
    """Compose independent observed facts; do not infer admission from readiness."""
    if authentication is AuthenticationState.AUTHENTICATED:
        configured = HealthState.AVAILABLE
    elif (
        authentication is AuthenticationState.UNAUTHENTICATED
        and configured is HealthState.UNKNOWN
    ):
        configured = HealthState.UNAVAILABLE

    if catalog.state.status is CatalogStatus.AVAILABLE or authentication is (
        AuthenticationState.UNAUTHENTICATED
    ):
        transport = HealthState.AVAILABLE

    admitted = is_catalog_lane_admissible(key)
    admission = AdmissionState.ADMITTED if admitted else AdmissionState.NOT_ADMITTED
    reasons: list[str] = []
    if configured is not HealthState.AVAILABLE:
        reasons.append("provider configuration has not been verified")
    if transport is HealthState.UNAVAILABLE:
        reasons.append("provider transport is unavailable")
    elif transport is HealthState.UNKNOWN:
        reasons.append("provider transport has not been verified")
    if authentication not in {
        AuthenticationState.AUTHENTICATED,
        AuthenticationState.NOT_APPLICABLE,
    }:
        reasons.append("provider authentication is not established")
    if catalog.state.status is not CatalogStatus.AVAILABLE:
        reasons.append(catalog.state.reason or "provider catalog is not available")
    admission_reason = catalog_lane_admission_reason(key)
    if admission_reason is not None:
        reasons.append(admission_reason)

    return StructuredProviderHealth.derive(
        configured=configured,
        transport=transport,
        authentication=authentication,
        catalog=catalog.state.status,
        admission=admission,
        reasons=tuple(dict.fromkeys(reasons)),
        checked_at=datetime.now(UTC),
    )


def _valid_public_id(value: str, *, max_length: int) -> bool:
    return (
        value == value.strip() and 0 < len(value) <= max_length and value.isprintable()
    )


def validate_public_catalog_bounds(catalog: ProviderCatalog) -> None:
    """Reject one unsafe lane before it can poison the whole public response."""
    public_ids = (
        catalog.key.provider_id,
        catalog.key.execution_mode,
        *(model.entry_id for model in catalog.models),
        *(
            option.option_id
            for control in catalog.native_controls
            for option in control.options
        ),
    )
    if catalog.state.revision is not None:
        public_ids = (*public_ids, catalog.state.revision)
    if not all(_valid_public_id(value, max_length=512) for value in public_ids):
        raise ValueError("catalog contains an invalid public identifier")
    control_ids = (
        *(control.control_id for control in catalog.native_controls),
        *(
            control_id
            for model in catalog.models
            for control_id in model.native_control_ids
        ),
    )
    if not all(_valid_public_id(value, max_length=128) for value in control_ids):
        raise ValueError("catalog contains an invalid public control identifier")


__all__ = [
    "PROVIDER_CATALOG_CACHE_TTL",
    "ProviderCatalogScopeCapacityError",
    "ProviderCatalogService",
    "validate_public_catalog_bounds",
]
