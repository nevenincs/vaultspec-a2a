"""The gateway verbs a test drives, shaped once for every tier.

The run-start stages are :class:`~vaultspec_a2a.testing.verbs.RunVerbs`. Around
them sit the pieces each tier used to retype for itself: the actor-token bundle
a start or commit binds, the complete run-start body an in-process gateway test
posts, the run-start verbs bound to a gateway :func:`booted_gateway` brought up,
and the authenticated reads, cancel and deletion of a run, with the wait on its
served status built on those reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from ..graph.enums import Provider
from .boot import DEFAULT_ATTACH_CREDENTIAL, desktop_workspace
from .catalog import async_catalog_run_fields, fetch_in_process_selection_at
from .polling import is_terminal, ok_body, wait_for_run_status
from .verbs import RunVerbs

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

__all__ = [
    "DEFAULT_PRESET_LANE",
    "DEFAULT_REQUIRED_ROLE",
    "DEFAULT_TEAM_PRESET",
    "GatewayVerbs",
    "actor_tokens_body",
    "async_run_start_body",
    "gateway_run_verbs",
    "role_tokens",
]

# The bundled deterministic preset a booted gateway's runs default to, and the
# one role it requires. It ships only in source checkouts: the gateway loads it
# from the checkout, never a published wheel, which is why the harnesses that run
# it are source-only.
DEFAULT_TEAM_PRESET = "deterministic-success-single"
DEFAULT_REQUIRED_ROLE = "deterministic-coder-success"

# The in-process lane DEFAULT_TEAM_PRESET is pinned to. A run presents ONE
# selection, so the preference is that preset's lane, which never bills.
DEFAULT_PRESET_LANE = Provider.DETERMINISTIC.value

_DEFAULT_AUTHORIZATION = f"Bearer {DEFAULT_ATTACH_CREDENTIAL}"


def role_tokens(roles: Iterable[str]) -> dict[str, str]:
    """A distinct placeholder actor token, ``tok-<role>``, for each of *roles*."""
    return {role: f"tok-{role}" for role in roles}


def actor_tokens_body(
    tokens: Mapping[str, str], *, engine_bearer: str = "bearer"
) -> dict[str, object]:
    """The wire ``actor_tokens`` bundle: per-role *tokens* plus the engine bearer."""
    return {"tokens": dict(tokens), "engine_bearer": engine_bearer}


async def async_run_start_body(
    client: httpx.AsyncClient,
    run_id: str,
    *,
    team_preset: str,
    tokens: Mapping[str, str],
    message: str = "build it",
    engine_bearer: str = "bearer",
) -> dict[str, object]:
    """A complete autonomous run-start body for the in-process gateway at *client*.

    The selection and workspace are the ones that gateway serves, resolved once
    and cached, so a replay that rebuilds the body presents the same request.
    """
    return {
        "team_preset": team_preset,
        "message": message,
        "autonomous": True,
        "actor_tokens": actor_tokens_body(tokens, engine_bearer=engine_bearer),
        "run_id": run_id,
        **await async_catalog_run_fields(client),
    }


def gateway_run_verbs(
    base_url: str,
    *,
    authorization: str = _DEFAULT_AUTHORIZATION,
    team_preset: str = DEFAULT_TEAM_PRESET,
    tokens: Mapping[str, str] | None = None,
    selection: Callable[[str], Mapping[str, object]] | None = None,
) -> RunVerbs:
    """The run-start verbs of a gateway :func:`booted_gateway` brought up.

    Every run is sited in the workspace that boot registered for *base_url*.
    Unless the caller names its own *selection*, a workspace's selection is the
    in-process lane the gateway serves, resolved once and cached so a prepare
    and its commit or release present the same one.
    """

    def served(workspace: str) -> Mapping[str, object]:
        return fetch_in_process_selection_at(
            base_url,
            workspace,
            headers={"Authorization": authorization},
            prefer_provider_id=DEFAULT_PRESET_LANE,
            cache=True,
        )

    return RunVerbs(
        base_url=base_url,
        authorization=authorization,
        team_preset=team_preset,
        workspace_root=desktop_workspace(base_url),
        selection=served if selection is None else selection,
        tokens=tokens,
    )


@dataclass(frozen=True, slots=True)
class GatewayVerbs:
    """An authenticated handle to one gateway's versioned run reads and controls.

    *authorization* is the whole ``Authorization`` header every request
    presents; none uses a test-only authentication bypass.
    """

    base_url: str
    authorization: str

    def client(self, *, timeout: float = 30.0) -> httpx.Client:
        """A synchronous authenticated client bound to the gateway base URL."""
        return httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Authorization": self.authorization},
        )

    def async_client(self, *, timeout: float = 30.0) -> httpx.AsyncClient:
        """An async authenticated client, for the streaming path."""
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Authorization": self.authorization},
        )

    def stream_path(self, run_id: str) -> str:
        """The versioned public progress-stream path for *run_id*."""
        return f"/v1/runs/{run_id}/stream"

    def status(self, run_id: str) -> httpx.Response:
        """Read the authoritative run-status snapshot for *run_id*.

        A run resolves whether it is still active or already terminal.
        """
        with self.client() as client:
            return client.get(f"/v1/runs/{run_id}")

    def active_runs(self) -> httpx.Response:
        """Discover the bounded set of durable non-terminal runs."""
        with self.client() as client:
            return client.get("/v1/runs")

    def cancel(
        self, run_id: str, *, idempotency_key: str | None = None
    ) -> httpx.Response:
        """Cancel *run_id* idempotently through the versioned public verb."""
        headers = (
            None if idempotency_key is None else {"Idempotency-Key": idempotency_key}
        )
        with self.client() as client:
            return client.post(f"/v1/runs/{run_id}/cancel", headers=headers)

    def thread_state(self, run_id: str) -> httpx.Response:
        """Read a run whole through the versioned history verb."""
        with self.client() as client:
            return client.get(f"/v1/runs/{run_id}/history")

    def delete_run(self, run_id: str) -> httpx.Response:
        """Delete *run_id* through the durable cross-store deletion saga."""
        with self.client(timeout=60.0) as client:
            return client.delete(f"/v1/runs/{run_id}")

    def wait_for_status(
        self,
        run_id: str,
        predicate: Callable[[dict[str, Any]], bool] = is_terminal,
        *,
        timeout: float = 120.0,
        interval: float = 0.5,
        label: str | None = None,
    ) -> dict[str, Any]:
        """Poll *run_id*'s run-status until *predicate* holds (default: terminal).

        The wait and its failure diagnostic are :func:`wait_for_run_status`'s;
        *label* names the run in that diagnostic and defaults to its id.
        """
        return wait_for_run_status(
            lambda: ok_body(self.status(run_id)),
            predicate,
            timeout=timeout,
            interval=interval,
            label=f"run {run_id}" if label is None else label,
        )
