"""Real-process boot and authenticated client for the certification stack.

The single source of the certification stack's lifecycle: allocate a loopback
port pair, seat a valid desktop application home (dashboard-created credentials
plus a database seated by the real ``migrate`` entrypoint), spawn the production
gateway armed with the desktop profile so it owns and spawns its own worker, and
wait for readiness with a death-aware poll that fails fast on a child that dies
before it answers rather than after a silent timeout.

The lifecycle primitives themselves live one tier down, in
:mod:`vaultspec_a2a.tests.gateway_boot`, which every real-process tier shares.
This module owns only what is genuinely specific to certification: the bundled
deterministic preset it certifies against, and the authenticated handle
scenarios drive.

The deterministic provider backend the worker proxies to (VidaiMock) is a
separate real process. Where a certifying environment runs it, pass its base URL
as ``MOCK_API_BASE`` through the keyword environment and the gateway-owned worker
inherits it, so runs complete against a real deterministic provider. The
provider is not required to certify the provider-independent gateway contract -
run creation, status, cancellation routing, streaming, deletion, and
authentication all hold whether a run ultimately completes or fails - so those
scenarios drive this stack without it.

``CertifiedGateway`` is the authenticated handle scenarios drive. Its request
helpers are the one place the public verbs are shaped, so a scenario asserts on
responses instead of re-deriving request bodies - no shadowed request logic
spread across scenario files.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from ..testing.catalog_selection import NoSelectableLaneError, in_process_selection
from ..tests.gateway_boot import (
    GatewayBootError,
    armed_gateway_env,
    gateway_script,
    reap_gateway,
    seat_valid_database,
    seed_credentials,
    spawn_gateway,
    spawn_until_ready,
)

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Iterator
    from pathlib import Path

__all__ = [
    "DEFAULT_REQUIRED_ROLE",
    "DEFAULT_TEAM_PRESET",
    "CertifiedGateway",
    "GatewayBootError",
    "certified_gateway",
]

# The bundled deterministic preset the stack certifies against. It ships only in
# source and Compose environments; the gateway loads it from the checkout, never
# a published wheel, which is why this harness is source-only.
DEFAULT_TEAM_PRESET = "mock-success-single"
DEFAULT_REQUIRED_ROLE = "mock-coder-success"


@dataclass(slots=True)
class CertifiedGateway:
    """An authenticated handle to one running armed-desktop certification stack.

    The verb helpers shape the exact public-surface requests once so scenarios
    read as assertions on real responses. Every helper presents the real
    attach-control credential; none uses the test-only authentication bypass.

    Run-start requires an explicit catalog selection revalidated against the
    catalog served for the run's workspace, so the run-bearing helpers resolve
    one from this stack's own served catalog and site every run in the stack's
    dedicated workspace directory. The resolution is cached per handle: prepare
    and release must present byte-identical bodies for the release binding to
    match, and one stack should pay its cold catalog build once.
    """

    base_url: str
    attach_token: str
    app_home: Path
    workspace_root: Path
    _run_fields: dict[str, Any] | None = field(default=None, init=False, repr=False)

    @property
    def auth_header(self) -> dict[str, str]:
        """The real attach-control Authorization header the dashboard presents."""
        return {"Authorization": f"Bearer {self.attach_token}"}

    # -- explicit catalog selection -------------------------------------------

    def run_fields(self) -> dict[str, Any]:
        """The selection and metadata fields every run verb now requires.

        Every verb this stack drives - prepare and release as much as start -
        presents an in-process selection. The frozen selection wins outright at
        compilation, so any other served lane would hand every role to a real
        external provider, and deterministic certification must never spend.
        This stack arms the in-process serving itself, so a catalog without one
        means the arming failed; the scenario then skips naming the missing
        serving rather than freezing whichever provider the host has installed.
        """
        return {
            "selection": self._resolved_run_fields()["selection"],
            "metadata": {"workspace_root": str(self.workspace_root)},
        }

    @property
    def selected_provider_id(self) -> str:
        """The provider id this stack's runs are frozen to.

        Exposed so a scenario can assert that a started run was frozen to the
        lane the harness actually selected, rather than restating a literal that
        would keep passing if the resolution ever picked something else.
        """
        return str(self._resolved_run_fields()["provider_id"])

    def _resolved_run_fields(self) -> dict[str, Any]:
        """Resolve and cache this stack's one in-process selection."""
        if self._run_fields is not None:
            return self._run_fields
        # The first catalog read for a workspace builds it cold, probing every
        # registered lane; its budget is deliberately its own rather than a
        # verb helper's.
        with self.client(timeout=240.0) as client:
            response = client.get(
                "/v1/provider-catalog",
                params={"workspace_root": str(self.workspace_root)},
            )
        if response.status_code != 200:
            raise GatewayBootError(
                f"the certification stack could not serve its provider "
                f"catalog: {response.status_code} {response.text}"
            )
        try:
            selection = in_process_selection(response.json())
        except NoSelectableLaneError as exc:
            pytest.skip(f"this certification stack cannot present a selection: {exc}")
        self._run_fields = {
            "provider_id": selection["provider_id"],
            "selection": selection,
        }
        return self._run_fields

    def client(self, *, timeout: float = 30.0) -> httpx.Client:
        """A synchronous authenticated client bound to the gateway base URL."""
        return httpx.Client(
            base_url=self.base_url, timeout=timeout, headers=self.auth_header
        )

    def async_client(self, *, timeout: float = 30.0) -> httpx.AsyncClient:
        """An async authenticated client, for the streaming certification path."""
        return httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, headers=self.auth_header
        )

    def stream_path(self, run_id: str) -> str:
        """The versioned public progress-stream path for *run_id*."""
        return f"/v1/runs/{run_id}/stream"

    # -- versioned run-start verb (prepare / start / release) ------------------

    def prepare(
        self, run_id: str, *, team_preset: str = DEFAULT_TEAM_PRESET
    ) -> httpx.Response:
        """Reserve a bounded admission slot for *run_id* (readiness-gated)."""
        with self.client(timeout=90.0) as client:
            return client.post(
                "/v1/runs",
                json={
                    "team_preset": team_preset,
                    "stage": "prepare",
                    "run_id": run_id,
                    "autonomous": True,
                    **self.run_fields(),
                },
            )

    def release(
        self,
        run_id: str,
        reservation_id: str,
        *,
        team_preset: str = DEFAULT_TEAM_PRESET,
    ) -> httpx.Response:
        """Explicitly free an uncommitted prepared reservation."""
        with self.client(timeout=30.0) as client:
            return client.post(
                "/v1/runs",
                json={
                    "team_preset": team_preset,
                    "stage": "release",
                    "reservation_id": reservation_id,
                    "run_id": run_id,
                    "autonomous": True,
                    **self.run_fields(),
                },
            )

    def start(
        self,
        run_id: str,
        *,
        team_preset: str = DEFAULT_TEAM_PRESET,
        role: str = DEFAULT_REQUIRED_ROLE,
        message: str = "certify the assembled product",
    ) -> httpx.Response:
        """Drive the one-shot ``start`` stage: create and dispatch in one call."""
        with self.client(timeout=90.0) as client:
            return client.post(
                "/v1/runs",
                json={
                    "team_preset": team_preset,
                    "stage": "start",
                    "run_id": run_id,
                    "message": message,
                    "autonomous": True,
                    "actor_tokens": {
                        "tokens": {role: "tok-certification"},
                        "engine_bearer": "bearer",
                    },
                    **self.run_fields(),
                },
            )

    # -- versioned run reads and cancel ---------------------------------------

    def status(self, run_id: str) -> httpx.Response:
        """Read the authoritative run-status snapshot for *run_id*."""
        with self.client(timeout=30.0) as client:
            return client.get(f"/v1/runs/{run_id}")

    def active_runs(self) -> httpx.Response:
        """Discover the bounded set of durable non-terminal runs."""
        with self.client(timeout=30.0) as client:
            return client.get("/v1/runs")

    def cancel(
        self, run_id: str, *, idempotency_key: str | None = None
    ) -> httpx.Response:
        """Cancel *run_id* idempotently through the versioned public verb."""
        headers = dict(self.auth_header)
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        with self.client(timeout=30.0) as client:
            return client.post(f"/v1/runs/{run_id}/cancel", headers=headers)

    # -- versioned run history and deletion ------------------------------------

    def thread_state(self, run_id: str) -> httpx.Response:
        """Read a run whole through the versioned history verb."""
        with self.client(timeout=30.0) as client:
            return client.get(f"/v1/runs/{run_id}/history")

    def delete_run(self, run_id: str) -> httpx.Response:
        """Delete *run_id* through the durable cross-store deletion saga."""
        with self.client(timeout=60.0) as client:
            return client.delete(f"/v1/runs/{run_id}")


@contextmanager
def certified_gateway(
    workdir: Path,
    *,
    attach_token: str = "attach-certification-1234567890abcdef",
    ownership_capability: str = "ownership-certification-fedcba0987654321",
    settlement_url: str | None = None,
    log_name: str = "gateway.log",
    **extra_env: str,
) -> Iterator[CertifiedGateway]:
    """Boot one armed-desktop certification stack over *workdir* and reap it.

    Seats the dashboard credentials and a real migrated database under a fresh
    application home, spawns the production gateway with worker auto-spawn so the
    gateway owns its worker, waits for readiness, and yields an authenticated
    :class:`CertifiedGateway`. A certifying environment that runs the
    deterministic provider passes ``MOCK_API_BASE`` through *extra_env* so the
    gateway-owned worker reaches it. The gateway-owned process tree is reaped in
    a ``finally`` regardless of scenario outcome, so no worker or gateway leaks.
    """
    app_home = workdir / "app-home"
    app_home.mkdir(parents=True, exist_ok=True)
    # Every run this stack starts is sited in one real directory: the run-start
    # verb requires the active project, and the catalog it revalidates against is
    # served per workspace, so the handle and the runs it drives must name the
    # same one.
    workspace_root = workdir / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    seed_credentials(app_home, attach=attach_token, ownership=ownership_capability)
    seat_valid_database(app_home)

    log_path = workdir / log_name
    log_handle = log_path.open("wb")
    script = gateway_script(log_level="info")

    def _spawn(gateway_port: int, worker_port: int) -> subprocess.Popen[bytes]:
        env = armed_gateway_env(
            app_home, gateway_port=gateway_port, worker_port=worker_port
        )
        # Arm the in-process lane serving this stack exists to certify against.
        # The lanes are hidden by default so no product deployment can offer
        # fixed content beside a real provider; certification is exactly the
        # deployment that must select one, because an executing run here may
        # never spend. Set before *extra_env* so a caller can still override it.
        env["VAULTSPEC_SERVE_IN_PROCESS_LANES"] = "true"
        if settlement_url is not None:
            env["VAULTSPEC_DESKTOP_SETTLEMENT_URL"] = settlement_url
        env.update(extra_env)
        return spawn_gateway(
            script=script,
            gateway_port=gateway_port,
            env=env,
            log_handle=log_handle,
            new_session=True,
        )

    try:
        proc, _gateway_port, _worker_port, base = spawn_until_ready(
            _spawn, log_path=log_path
        )
    except BaseException:
        # The boot helper has already reaped its tree; the log handle is this
        # frame's to release, and the ``finally`` below is never reached when
        # the boot itself raises.
        log_handle.close()
        raise

    try:
        yield CertifiedGateway(
            base_url=base,
            attach_token=attach_token,
            app_home=app_home,
            workspace_root=workspace_root,
        )
    finally:
        reap_gateway(proc)
        log_handle.close()
