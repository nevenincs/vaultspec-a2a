"""Certify the desktop ownership prerequisites - and their limit as evidence.

The armed desktop profile rests on three ownership prerequisites, all of which
are certified here against the REAL ``serve`` entrypoint rather than a test boot
of ``create_app``: only ``serve`` runs the production ordering in which the
operating-system runtime singleton is taken over the application home *before*
the listener binds, so a gateway booted any other way skips the acquisition
entirely and cannot evidence it.

1. **Singleton** - one live gateway owns one application home, and a second
   gateway is refused at acquisition.
2. **Credential** - the two dashboard-created planes and the per-boot,
   gateway-minted worker interprocess-communication (IPC) secret are all
   owner-restricted files on disk after the boot that consumed them.
3. **Owned process tree** - the gateway spawns and owns its worker.

The second certification is the reason this module exists. Holding all three
prerequisites says nothing about *which* worker is answering on a port. A real
production worker started outside any gateway spawn, holding the very same
gateway-minted IPC credential, over the same application home, deriving the same
gateway URL, is indistinguishable from the gateway's own worker on every
prerequisite and on every addressing fact - and is still not this gateway's
worker. Identity lives only in the pairing evidence the worker reports, so the
prerequisites are certified here as prerequisites and never as pairing proof.

What this module deliberately does NOT do is re-prove the refusal behaviour that
follows from a pairing verdict; that is certified separately against real
processes. Here the subject is the evidence itself.

Every process is real: the database is seated by the real ``migrate``
entrypoint, both gateways are real ``serve`` invocations, and both workers are
real ``vaultspec_a2a.worker`` processes. No mock, monkeypatch, stub, skip, or
expected failure is used; every child is reaped in a ``finally``.
"""

from __future__ import annotations

import subprocess
import sys
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import httpx

from ..control.worker_management import (
    GATEWAY_LIFETIME_ENV,
    GATEWAY_LIFETIME_ID,
    WORKER_GENERATION_ENV,
)
from ..desktop._platform_acl import credential_file_is_owner_restricted
from ..desktop.credentials import credential_paths
from ..desktop.profile import derive_state_paths
from ..lifecycle.pairing import (
    WorkerPairingVerdict,
    classify_worker_pairing,
)
from ..lifecycle.singleton import (
    SingletonState,
    classify_app_home,
    default_owner,
    recorded_process_is_live,
    singleton_record_path,
)
from ..tests.gateway_boot import (
    READINESS_TIMEOUT,
    armed_gateway_env,
    free_port,
    reap_gateway,
    seat_valid_database,
    seed_credentials,
    spawn_until_ready,
)
from .test_run_admission import _ATTACH, _OWNERSHIP

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_CLI_MODULE = "vaultspec_a2a.cli.main"
_PRESET = "mock-success-single"
# Raised by the runtime singleton when a second gateway contends one home.
_CONFLICT_REFUSAL = "refusing to start a second gateway on one application home"


@contextmanager
def _armed_serve(
    tmp_path: Path, *, auto_spawn: bool
) -> Iterator[tuple[Path, int, int, str]]:
    """Boot a real armed desktop gateway through the production ``serve`` verb.

    Yields ``(app_home, gateway_port, worker_port, base)``. The gateway process
    handle is deliberately not yielded: on Windows the virtual-environment
    interpreter is a launcher stub, so the spawned handle's pid is the launcher
    and not the gateway, and every ownership assertion here reads the published
    records instead.
    """
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    seed_credentials(app_home, attach=_ATTACH, ownership=_OWNERSHIP)
    seat_valid_database(app_home)
    log_path = tmp_path / "gateway.log"
    log_handle = log_path.open("wb")

    def _spawn(gateway_port: int, worker_port: int) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [sys.executable, "-m", _CLI_MODULE, "serve"],
            env=armed_gateway_env(
                app_home,
                gateway_port=gateway_port,
                worker_port=worker_port,
                auto_spawn_worker=auto_spawn,
            ),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )

    proc, gateway_port, worker_port, base = spawn_until_ready(
        _spawn, log_path=log_path, timeout=READINESS_TIMEOUT
    )
    try:
        yield app_home, gateway_port, worker_port, base
    finally:
        reap_gateway(proc)
        log_handle.close()


def _worker_ipc_secret(app_home: Path) -> str:
    """Return the gateway-minted worker IPC secret from its real file."""
    credentials_dir = derive_state_paths(app_home).credentials_dir
    return (
        credential_paths(credentials_dir)
        .worker_ipc_path.read_text(encoding="utf-8")
        .strip()
    )


def _prepare(base: str, run_id: str) -> tuple[int, dict[str, Any]]:
    """Drive one authenticated prepare, which spawns the gateway-owned worker."""
    with httpx.Client(base_url=base, timeout=120.0) as client:
        resp = client.post(
            "/v1/runs",
            headers={"Authorization": f"Bearer {_ATTACH}"},
            json={
                "team_preset": _PRESET,
                "stage": "prepare",
                "autonomous": True,
                "run_id": run_id,
            },
        )
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {"raw": resp.text}


def _worker_health(port: int, secret: str, *, timeout: float = 60.0) -> dict[str, Any]:
    """Await one real worker's authenticated health body on *port*."""
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(
                    f"http://127.0.0.1:{port}/health",
                    headers={"Authorization": f"Bearer {secret}"},
                )
            if resp.status_code == 200:
                body = resp.json()
                assert isinstance(body, dict), body
                return body
            last = resp.status_code
        except httpx.HTTPError as exc:
            last = repr(exc)
        time.sleep(0.25)
    raise AssertionError(f"worker on port {port} never served health (last: {last})")


def test_armed_serve_holds_the_singleton_and_hardens_every_credential(
    tmp_path: Path,
) -> None:
    """A real ``serve`` boot owns its home exclusively and leaves no loose secret.

    Discriminating on both prerequisites independently:

    - **Singleton.** A second real ``serve`` over the same application home is
      refused at acquisition. It is given a DIFFERENT gateway port, so its
      non-zero exit cannot be a listener bind collision - only the runtime
      singleton can refuse it, and the refusal message names that conflict.
      Remove the acquisition from the serve path and this second gateway boots
      happily onto its own port. The refused contender is also proven to leave
      no residue: the resident keeps serving and its owner record is unchanged.
    - **Credential.** All three planes are asserted owner-restricted through the
      production predicate on the real files the boot left behind - including
      the worker IPC secret the gateway MINTED during this boot. Mint that
      secret with a plain write instead of the hardened path and every other
      desktop certification still passes (the gateway boots, the planes stay
      isolated, the secret is still distinct) while this assertion fails.
    """
    with _armed_serve(tmp_path, auto_spawn=False) as (app_home, _port, _wport, base):
        owner = default_owner()
        state, record = classify_app_home(app_home, owner=owner)
        assert state is SingletonState.HELD, (state, record)
        assert record is not None
        assert record.owner == owner
        assert recorded_process_is_live(record), record

        record_before = singleton_record_path(app_home).read_bytes()

        # A second gateway, same home, DIFFERENT port: refused at acquisition.
        second = subprocess.run(
            [sys.executable, "-m", _CLI_MODULE, "serve"],
            env=armed_gateway_env(
                app_home,
                gateway_port=free_port(),
                worker_port=free_port(),
                auto_spawn_worker=False,
            ),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert second.returncode != 0, second.stdout
        assert _CONFLICT_REFUSAL in second.stderr, second.stderr

        # The refused contender left no residue and never disturbed the resident.
        assert singleton_record_path(app_home).read_bytes() == record_before
        with httpx.Client(base_url=base, timeout=10.0) as client:
            assert client.get("/health").status_code == 200

        # Every credential plane is owner-restricted on disk after the boot that
        # loaded two of them and minted the third.
        credentials_dir = derive_state_paths(app_home).credentials_dir
        paths = credential_paths(credentials_dir)
        for plane, path in (
            ("attach", paths.attach_path),
            ("ownership", paths.ownership_path),
            ("worker_ipc", paths.worker_ipc_path),
        ):
            assert path.is_file(), f"{plane} credential missing at {path}"
            assert credential_file_is_owner_restricted(path), (
                f"{plane} credential at {path} is not owner-restricted"
            )

        minted = _worker_ipc_secret(app_home)
        assert minted, "the gateway minted no worker IPC secret"
        assert minted not in (_ATTACH, _OWNERSHIP), (
            "the gateway-minted worker IPC secret must not reuse a dashboard plane"
        )


def test_ownership_prerequisites_never_identify_a_worker(tmp_path: Path) -> None:
    """Every prerequisite can hold for a worker that is not this gateway's.

    A real armed gateway holds its runtime singleton, its credential planes are
    owner-restricted, and it has spawned and owns its worker. A second REAL
    production worker is then started outside any gateway spawn, holding the
    very same gateway-minted IPC credential over the same application home and
    the same gateway port. It is a genuine worker, not an adversary stand-in.

    Discriminating in three independent directions:

    - **The credential does not identify.** The stranger answers the same
      authenticated probe 200 and refuses the unauthenticated one 401, exactly
      as the gateway's own worker does. Possession of the prerequisite secret is
      therefore satisfied by a worker this gateway never started.
    - **The addressing does not identify.** Both workers report a byte-identical
      declared ``gateway_url``, so the legacy declared-target comparison cannot
      separate them at all.
    - **Only the reported pairing evidence identifies.** Against the exact
      lifetime that makes the gateway's own worker ``OWNED``, the stranger
      classifies ``UNIDENTIFIED``; and the gateway's own worker classifies
      ``FOREIGN`` against a different real gateway incarnation (this test
      process's own production-minted lifetime identity). Let the worker default
      its pairing evidence to anything non-blank, and the first of those two
      flips to an adoptable verdict.
    """
    with _armed_serve(tmp_path, auto_spawn=True) as (app_home, port, worker_port, base):
        # Premise: the ownership prerequisites really do hold for this gateway.
        assert classify_app_home(app_home, owner=default_owner())[0] is (
            SingletonState.HELD
        )
        secret = _worker_ipc_secret(app_home)
        ipc_path = credential_paths(
            derive_state_paths(app_home).credentials_dir
        ).worker_ipc_path
        assert credential_file_is_owner_restricted(ipc_path)

        # First demand spawns the worker this gateway owns.
        status, prepared = _prepare(base, "run-ownership-prerequisites")
        assert status == 201, prepared

        owned = _worker_health(worker_port, secret)
        with httpx.Client(timeout=10.0) as client:
            owned_unauth = client.get(f"http://127.0.0.1:{worker_port}/health")
        assert owned_unauth.status_code == 401, owned_unauth.text

        # A real production worker that no gateway spawned, holding the same
        # gateway-minted credential. The two pairing variables are cleared so an
        # inherited value from the test host cannot forge the evidence at issue.
        stray_port = free_port()
        stray_env = armed_gateway_env(
            app_home,
            gateway_port=port,
            worker_port=stray_port,
            auto_spawn_worker=False,
        )
        stray_env["VAULTSPEC_INTERNAL_TOKEN"] = secret
        stray_env.pop(GATEWAY_LIFETIME_ENV, None)
        stray_env.pop(WORKER_GENERATION_ENV, None)
        stray_log = (tmp_path / "stray-worker.log").open("wb")
        stray = subprocess.Popen(
            [sys.executable, "-m", "vaultspec_a2a.worker"],
            env=stray_env,
            stdout=stray_log,
            stderr=subprocess.STDOUT,
        )
        try:
            stranger = _worker_health(stray_port, secret)
            with httpx.Client(timeout=10.0) as client:
                stray_unauth = client.get(f"http://127.0.0.1:{stray_port}/health")

            # The credential prerequisite is satisfied by a worker that is not ours.
            assert stray_unauth.status_code == 401, stray_unauth.text
            assert stranger["status"] == "ok", stranger

            # So is every addressing fact the legacy signal could compare.
            assert stranger["gateway_url"] == owned["gateway_url"], (
                stranger["gateway_url"],
                owned["gateway_url"],
            )

            # Only the reported pairing evidence separates them.
            owned_lifetime = owned["paired_gateway_lifetime"]
            owned_generation = owned["worker_generation"]
            assert owned_lifetime.strip(), owned
            assert owned_generation.strip(), owned
            assert stranger["paired_gateway_lifetime"] == "", stranger
            assert stranger["worker_generation"] == "", stranger

            generation = int(owned_generation)
            assert generation > 0, owned
            # LOAD-BEARING: against the very lifetime that makes the gateway's own
            # worker adoptable, the stranger is still not identified.
            assert (
                classify_worker_pairing(
                    reported_lifetime=stranger["paired_gateway_lifetime"],
                    reported_generation=stranger["worker_generation"],
                    gateway_lifetime=owned_lifetime,
                    current_generation=generation,
                )
                is WorkerPairingVerdict.UNIDENTIFIED
            )
            # Reference point, not a discriminator: with the lifetime matching by
            # construction this restates the definition of an adoptable worker,
            # and is asserted only to fix the contrast the line above measures.
            assert (
                classify_worker_pairing(
                    reported_lifetime=owned_lifetime,
                    reported_generation=owned_generation,
                    gateway_lifetime=owned_lifetime,
                    current_generation=generation,
                )
                is WorkerPairingVerdict.OWNED
            )
            # LOAD-BEARING: a different real gateway incarnation. This test
            # process minted its own production lifetime identity on import, and
            # it is definitively not the gateway that spawned the worker above,
            # so the worker's evidence must bind to that one incarnation alone.
            assert owned_lifetime != GATEWAY_LIFETIME_ID
            assert (
                classify_worker_pairing(
                    reported_lifetime=owned_lifetime,
                    reported_generation=owned_generation,
                    gateway_lifetime=GATEWAY_LIFETIME_ID,
                    current_generation=generation,
                )
                is WorkerPairingVerdict.FOREIGN
            )
        finally:
            reap_gateway(stray)
            stray_log.close()
