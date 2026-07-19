"""Authenticated terminal-settlement callbacks to the dashboard.

After a run reaches a durable terminal state the gateway tells the dashboard so
it can revoke that run's lease. This module owns that callback. It is deliberately
narrow: it authenticates with the dashboard-created attach-control credential the
gateway reads - never the private worker interprocess-communication secret - and
its body carries only non-secret identities (the run and its lease) plus the
terminal status, so a settlement can never leak an actor token or the worker IPC
secret.

Delivery is bounded: a small number of attempts with capped backoff and a
per-attempt timeout, after which the callback gives up and reports failure rather
than blocking terminal handling. Settlement never raises into its caller; a
terminal run is already durable, and a lost callback is reconciled by the
dashboard's own status reconciliation, not by retrying forever here.

Configuration is resolved fail-soft: when no dashboard settlement endpoint is
configured (the Compose and development profiles, or a desktop install whose
dashboard has not published one) the callback is simply skipped, never errored.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

    from ..thread.enums import ThreadStatus

__all__ = [
    "SETTLEMENT_URL_ENV",
    "SettlementResult",
    "emit_run_settlement",
    "settlement_endpoint",
]

logger = logging.getLogger(__name__)

# The dashboard publishes the absolute URL of its terminal-settlement receiver
# here. Absent, settlement is not configured for this process and is skipped.
SETTLEMENT_URL_ENV = "VAULTSPEC_DESKTOP_SETTLEMENT_URL"

# Bounded delivery: at most this many attempts, each under this timeout, with an
# exponentially backed-off pause capped so the total wait stays small.
_MAX_ATTEMPTS = 3
_ATTEMPT_TIMEOUT_SECONDS = 5.0
_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_MAX_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class SettlementResult:
    """The bounded outcome of a terminal-settlement callback.

    ``delivered`` is ``True`` only on an accepted callback. ``skipped`` is ``True``
    when settlement is not configured for this process - not a failure, just not
    applicable. ``attempts`` counts the delivery attempts made, and ``reason`` is a
    safe, path-free and secret-free description of a non-delivery.
    """

    delivered: bool
    skipped: bool
    attempts: int
    status_code: int | None = None
    reason: str | None = None


def settlement_endpoint() -> str | None:
    """Return the configured dashboard settlement URL, or ``None`` if unset.

    Reads the published endpoint from the environment and accepts it only when it
    is a non-empty absolute HTTP(S) URL, so a blank or malformed value disables
    settlement fail-soft rather than producing an unusable target.
    """
    raw = os.environ.get(SETTLEMENT_URL_ENV, "").strip()
    if not raw:
        return None
    if not (raw.startswith("http://") or raw.startswith("https://")):
        return None
    return raw


def _resolve_attach_credential() -> str | None:
    """Read the dashboard-created attach-control credential, or ``None``.

    The gateway reads the same attach credential it authenticates dashboard
    control with; a missing or malformed credential (or an unarmed profile with no
    credential paths) disables settlement fail-soft. The secret is never logged.
    """
    from ..control.config import settings
    from .credentials import CredentialError, load_attach_credential

    references = settings.desktop_credential_paths
    if references is None:
        return None
    try:
        return load_attach_credential(references.credentials_dir)
    except CredentialError:
        return None


async def emit_run_settlement(
    *,
    run_id: str,
    lease_id: str,
    terminal_status: ThreadStatus,
    client: httpx.AsyncClient | None = None,
) -> SettlementResult:
    """Deliver one bounded, attach-authenticated terminal-settlement callback.

    Builds the settlement body from the run and its non-secret lease identity plus
    the terminal status, authenticates with the attach-control credential, and
    POSTs it to the configured dashboard endpoint with bounded retries. Returns a
    skipped result when settlement is not configured, a delivered result on an
    accepted callback, and a failed result (never an exception) when every bounded
    attempt is exhausted.
    """
    import httpx

    from ..api.schemas.gateway import TerminalSettlement

    endpoint = settlement_endpoint()
    if endpoint is None:
        return SettlementResult(
            delivered=False,
            skipped=True,
            attempts=0,
            reason="settlement not configured",
        )
    attach_credential = _resolve_attach_credential()
    if attach_credential is None:
        return SettlementResult(
            delivered=False,
            skipped=True,
            attempts=0,
            reason="attach-control credential is unavailable",
        )

    body = TerminalSettlement(
        run_id=run_id, lease_id=lease_id, terminal_status=terminal_status
    )
    headers = {"Authorization": f"Bearer {attach_credential}"}
    payload = body.model_dump(mode="json")

    owned_client = client is None
    active = client or httpx.AsyncClient()
    try:
        return await _deliver(active, endpoint, payload, headers, run_id)
    finally:
        if owned_client:
            await active.aclose()


async def _deliver(
    client: httpx.AsyncClient,
    endpoint: str,
    payload: dict[str, object],
    headers: dict[str, str],
    run_id: str,
) -> SettlementResult:
    """POST the settlement with bounded, backed-off retries."""
    import httpx

    last_status: int | None = None
    last_reason: str | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = await client.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=_ATTEMPT_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError:
            last_reason = "settlement callback transport error"
            logger.warning(
                "Terminal settlement transport error for run %s (attempt %d/%d)",
                run_id,
                attempt,
                _MAX_ATTEMPTS,
            )
        else:
            last_status = response.status_code
            if response.is_success:
                return SettlementResult(
                    delivered=True,
                    skipped=False,
                    attempts=attempt,
                    status_code=response.status_code,
                )
            last_reason = f"settlement callback rejected with status {last_status}"
            logger.warning(
                "Terminal settlement rejected for run %s with status %d"
                " (attempt %d/%d)",
                run_id,
                last_status,
                attempt,
                _MAX_ATTEMPTS,
            )
        if attempt < _MAX_ATTEMPTS:
            await asyncio.sleep(
                min(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)), _BACKOFF_MAX_SECONDS)
            )
    return SettlementResult(
        delivered=False,
        skipped=False,
        attempts=_MAX_ATTEMPTS,
        status_code=last_status,
        reason=last_reason or "settlement callback failed",
    )
