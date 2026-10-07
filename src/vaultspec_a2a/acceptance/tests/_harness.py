"""Real-process boot and authenticated client for the certification stack.

The single source of the certification stack's lifecycle: allocate a loopback
port pair, seat a valid desktop application home (dashboard-created credentials
plus a database seated by the real ``migrate`` entrypoint), spawn the production
gateway outside the desktop profile so it can execute in-process lanes, and
wait for readiness with a death-aware poll that fails fast on a child that dies
before it answers rather than after a silent timeout.

The lifecycle primitives and the run-start verb themselves live in
:mod:`vaultspec_a2a.testing`, which every real-process tier shares. This module
owns only what is genuinely specific to certification: the bundled deterministic
preset it certifies against, and the authenticated handle scenarios drive.

The deterministic provider backend the worker proxies to (VidaiMock) is a
separate real process. Where a certifying environment runs it, pass its base URL
as ``VAULTSPEC_A2A_MOCK_API_BASE`` through the keyword environment and the
gateway-owned worker inherits it, so runs complete against a real deterministic
provider. The provider is not required to certify the provider-independent
gateway contract - run creation, status, cancellation routing, streaming,
deletion, and authentication all hold whether a run ultimately completes or
fails - so those scenarios drive this stack without it.

``CertifiedGateway`` is the authenticated handle scenarios drive: the shared
:class:`~vaultspec_a2a.testing.gateway_verbs.GatewayVerbs` reads and controls,
plus a run-start verb that is the shared :class:`~vaultspec_a2a.testing.RunVerbs`
bound to this stack's preset, workspace and selection, so a scenario asserts on
responses instead of re-deriving request bodies - no shadowed request logic
spread across scenario files.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ...conftest import ExternalPrerequisiteRule
from ...testing import (
    DEFAULT_ATTACH_CREDENTIAL,
    DEFAULT_OWNERSHIP_CAPABILITY,
    NoSelectableLaneError,
    RunVerbs,
    booted_gateway,
    broker_gateway_env,
    fetch_in_process_selection,
    gateway_script,
    seat_app_home,
)
from ...testing.gateway_verbs import (
    DEFAULT_PRESET_LANE,
    DEFAULT_REQUIRED_ROLE,
    DEFAULT_TEAM_PRESET,
    GatewayVerbs,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

# ``GatewayBootError`` is raised by this stack's boot and warm-up but declared by
# ``testing.boot``, which holds it as ONE class for every tier - two same-named
# copies once diverged, so an ``except`` written against one silently missed the
# other. Republishing it here would hand the next tier a second place to import it
# from and start that again.
__all__ = [
    "CertifiedGateway",
    "certified_gateway",
]


@dataclass(frozen=True, slots=True)
class CertifiedGateway(GatewayVerbs):
    """An authenticated handle to one running broker certification stack.

    Every request presents the real gateway service credential; none uses the
    test-only authentication bypass. The run reads, cancel, deletion and status
    wait are the shared :class:`~vaultspec_a2a.testing.gateway_verbs.GatewayVerbs`.

    Run-start requires an explicit catalog selection revalidated against the
    catalog served for the run's workspace, so the run-bearing verbs resolve
    one from this stack's own served catalog and site every run in the stack's
    dedicated workspace directory. The resolution is cached: prepare and release
    must present byte-identical bodies for the release binding to match, and one
    stack should pay its cold catalog build once.
    """

    app_home: Path
    workspace_root: Path

    # -- explicit catalog selection -------------------------------------------

    @property
    def selected_provider_id(self) -> str:
        """The provider id this stack's runs are frozen to.

        Exposed so a scenario can assert that a started run was frozen to the
        lane the harness actually selected, rather than restating a literal that
        would keep passing if the resolution ever picked something else.
        """
        return str(self.runs.selection(str(self.workspace_root))["provider_id"])

    def served_in_process_selection(
        self,
        workspace_root: str,
        *,
        prefer_provider_id: str,
        cache: bool = False,
    ) -> dict[str, Any]:
        """Select an in-process lane from the catalog this stack serves.

        Every verb this stack drives - prepare and release as much as start -
        presents an in-process selection. The frozen selection wins outright at
        compilation, so any other served lane would hand every role to a real
        external provider, and deterministic certification must never spend.
        This stack arms in-process serving itself, so a catalog without a
        selectable lane means the arming failed. That is reported as the absent
        ``in-process-lanes`` prerequisite, naming what is missing, rather than
        freezing whichever external provider the host happens to have installed.
        Keeping a billable lane out is the shared mechanism's own guarantee, so the
        refusal is the only thing decided here.
        """
        try:
            with self.client() as client:
                return fetch_in_process_selection(
                    client,
                    workspace_root,
                    prefer_provider_id=prefer_provider_id,
                    cache=cache,
                )
        except NoSelectableLaneError as exc:
            ExternalPrerequisiteRule().absent("in-process-lanes", str(exc))

    # -- versioned run-start verb (prepare / commit / release / start) --------

    @property
    def runs(self) -> RunVerbs:
        """The run-start verb bound to this stack's preset, workspace and lane.

        Every stage presents the one cached selection, and a start or commit
        binds a token for the preset's required role.
        """
        return RunVerbs(
            base_url=self.base_url,
            authorization=self.authorization,
            team_preset=DEFAULT_TEAM_PRESET,
            workspace_root=str(self.workspace_root),
            selection=lambda workspace: self.served_in_process_selection(
                workspace, prefer_provider_id=DEFAULT_PRESET_LANE, cache=True
            ),
            tokens={DEFAULT_REQUIRED_ROLE: "tok-certification"},
            message="certify the assembled product",
        )


@contextmanager
def certified_gateway(
    workdir: Path,
    *,
    attach_token: str = DEFAULT_ATTACH_CREDENTIAL,
    ownership_capability: str = DEFAULT_OWNERSHIP_CAPABILITY,
    log_name: str = "gateway.log",
    **extra_env: str,
) -> Generator[CertifiedGateway]:
    """Boot one authenticated broker certification stack over *workdir* and reap it.

    Seats the dashboard credentials and a real migrated database under a fresh
    application home, spawns the production gateway with worker auto-spawn so the
    gateway owns its worker, waits for readiness, and yields an authenticated
    :class:`CertifiedGateway`. A certifying environment that runs the
    deterministic provider passes ``VAULTSPEC_A2A_MOCK_API_BASE`` through
    *extra_env* so the gateway-owned worker reaches it. The gateway-owned process
    tree is reaped regardless of scenario outcome, so no worker or gateway leaks.

    The broker profile arms the in-process lane serving this stack exists to
    certify against. The lanes are hidden by default so no product deployment
    can offer fixed content beside a real provider; certification is exactly the
    deployment that must select one, because an executing run here may never
    spend. *extra_env* is applied last, so a caller can still override it.
    """
    app_home = workdir / "app-home"
    state = seat_app_home(app_home, attach=attach_token, ownership=ownership_capability)
    # Every run this stack starts is sited in one real directory: the run-start
    # verb requires the active project, and the catalog it revalidates against is
    # served per workspace, so the handle and the runs it drives must name the
    # same one.
    workspace_root = state.workspaces_root / "project"
    workspace_root.mkdir(parents=True, exist_ok=True)
    with booted_gateway(
        broker_gateway_env(app_home, gateway_token=attach_token, extra=extra_env),
        log_path=workdir / log_name,
        script=gateway_script(log_level="info"),
        detached=True,
    ) as gateway:
        running = CertifiedGateway(
            base_url=gateway.base_url,
            authorization=f"Bearer {attach_token}",
            app_home=app_home,
            workspace_root=workspace_root,
        )
        running.runs.warm_first_demand()
        yield running
