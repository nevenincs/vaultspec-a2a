"""Real-process proofs that the authenticated pairing verdict governs adoption.

The enforcement decision (2026-07-24 codebase-health record): under the ARMED
desktop profile a worker is adoptable only when its reported gateway lifetime
and spawn generation classify as OWNED; blank evidence, the legacy declared
gateway-URL echo, and a foreign lifetime all fail closed - no adoption, no
eviction, loud refusal.

Every proof runs real processes end to end: a real armed gateway boots over a
migrated application home, the port squatter is a genuine separate process
serving real HTTP on the gateway's private worker port, and the two-gateway
proof pits two complete armed gateways against one REAL spawned worker. The
squatter is the modeled adversary (a stranger process answering health on the
port), not a stand-in for any production code. Assertions observe process
liveness, request logs, and the gateway's admission surface - never internals.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from ..lifecycle.discovery import is_pid_alive
from ..tests.gateway_boot import (
    armed_gateway_env,
    await_gateway_ready,
    free_port,
    gateway_script,
    reap_gateway,
    seat_valid_database,
    seed_credentials,
    spawn_gateway,
    spawn_until_ready,
)
from ._catalog import catalog_selection
from .test_run_admission import _ATTACH, _OWNERSHIP

if TYPE_CHECKING:
    from collections.abc import Iterator

_GATEWAY = gateway_script(log_level="info")

_SQUATTER = """
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(sys.argv[1])
body = json.loads(sys.argv[2])
log_path = sys.argv[3]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with open(log_path, "a", encoding="utf-8") as log:
            log.write("GET " + self.path + "\\n")
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        with open(log_path, "a", encoding="utf-8") as log:
            log.write("POST " + self.path + "\\n")
        self.send_response(503)
        self.end_headers()

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""


@contextmanager
def _squatter(
    tmp_path: Path, port: int, body: dict[str, Any]
) -> Iterator[tuple[subprocess.Popen[bytes], Path]]:
    """Run a real stranger process serving *body* on the worker port."""
    log_path = tmp_path / f"squatter-{port}.log"
    log_path.write_text("", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-c", _SQUATTER, str(port), json.dumps(body), str(log_path)],
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with httpx.Client(timeout=1.0) as client:
                    if client.get(f"http://127.0.0.1:{port}/health").status_code == 200:
                        break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            raise AssertionError("squatter never came up")
        yield proc, log_path
    finally:
        with contextlib.suppress(Exception):
            proc.kill()
            proc.wait(timeout=10)


@contextmanager
def _armed_gateway_on_worker_port(
    tmp_path: Path, worker_port: int, *, home_name: str = "app-home"
) -> Iterator[tuple[str, str, Path]]:
    """Boot a real armed gateway whose private worker port is pinned.

    Unlike the general boot helper this pins ``VAULTSPEC_WORKER_PORT`` so the
    test controls who holds the worker port; the gateway port itself is still
    allocated with bind-race retry. Yields ``(base, bearer, gateway_log)``.
    """
    app_home = tmp_path / home_name
    app_home.mkdir()
    seed_credentials(app_home, attach=_ATTACH, ownership=_OWNERSHIP)
    seat_valid_database(app_home)
    log_path = tmp_path / f"{home_name}-gateway.log"
    log_handle = log_path.open("wb")

    def _spawn(gateway_port: int, _ignored: int) -> subprocess.Popen[bytes]:
        return spawn_gateway(
            script=_GATEWAY,
            gateway_port=gateway_port,
            env=armed_gateway_env(
                app_home, gateway_port=gateway_port, worker_port=worker_port
            ),
            log_handle=log_handle,
        )

    proc, _gateway_port, _ignored, base = spawn_until_ready(_spawn, log_path=log_path)
    try:
        yield base, f"Bearer {_ATTACH}", log_path
    finally:
        reap_gateway(proc)
        log_handle.close()


def _prepare(base: str, auth: str, run_id: str) -> tuple[int, dict[str, Any]]:
    workspace = str(Path.cwd())
    with httpx.Client(base_url=base, timeout=60.0) as client:
        resp = client.post(
            "/v1/runs",
            headers={"Authorization": auth},
            json={
                "team_preset": "mock-success-single",
                "stage": "prepare",
                "autonomous": True,
                "run_id": run_id,
                # The workspace anchors the selection, which run start
                # revalidates against the catalog served for it.
                "metadata": {"workspace_root": workspace},
                "selection": catalog_selection(base, auth, workspace),
            },
        )
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text}
    return resp.status_code, body


def _assert_refused_without_adoption_or_eviction(
    tmp_path: Path, body: dict[str, Any], run_id: str
) -> None:
    """One squatter scenario: armed demand must refuse, not adopt, not evict."""
    worker_port = free_port()
    with (
        _squatter(tmp_path, worker_port, body) as (squatter, request_log),
        _armed_gateway_on_worker_port(tmp_path, worker_port) as (base, auth, gw_log),
    ):
        status, prepared = _prepare(base, auth, run_id)

        # Refusal on the admission surface: no reservation is minted off a
        # worker whose provenance the armed profile cannot prove.
        assert status == 503, prepared
        assert prepared["detail"] == "run admission is not execution-ready"

        # No eviction: the squatter process survives the refusal untouched.
        assert squatter.poll() is None, "squatter must not be evicted"

        # No adoption: the squatter saw only health probes, never a dispatch.
        requests = request_log.read_text(encoding="utf-8").splitlines()
        assert requests, "gateway never even probed the occupied worker port"
        assert all(line.startswith("GET /health") for line in requests), requests

        # The refusal is loud in the gateway's own log.
        log_text = gw_log.read_bytes().decode("utf-8", errors="replace")
        assert "refusing to spawn" in log_text or "not adoptable" in log_text, (
            "expected a loud provenance refusal in the gateway log"
        )


def test_plain_worker_health_never_authorizes_adoption(tmp_path: Path) -> None:
    """S153: a bare healthy stranger on the worker port is never adopted."""
    _assert_refused_without_adoption_or_eviction(
        tmp_path, {"status": "healthy"}, "run-provenance-plain-health"
    )


def test_blank_worker_pairing_never_authorizes_adoption(tmp_path: Path) -> None:
    """S154: explicitly blank pairing evidence classifies UNIDENTIFIED and refuses."""
    _assert_refused_without_adoption_or_eviction(
        tmp_path,
        {
            "status": "healthy",
            "paired_gateway_lifetime": "",
            "worker_generation": "",
        },
        "run-provenance-blank-pairing",
    )


def test_legacy_gateway_url_echo_never_authorizes_adoption(tmp_path: Path) -> None:
    """S155: the retired lenient signal - an echoed gateway_url - no longer adopts.

    The squatter cannot know the gateway's port before boot, so it echoes a
    wildcard-free loopback URL for every port by reflecting the Host the
    gateway probes with; instead, the proof pins the gateway first and hands
    the squatter that URL. Here the simpler equivalent: the squatter reports a
    syntactically valid loopback gateway_url while carrying no pairing
    evidence - under the retired policy the blank-target-is-ours rule plus a
    matching URL adopted it; under the enforced policy it is UNIDENTIFIED.
    """
    worker_port = free_port()
    gateway_port = free_port()
    body = {
        "status": "healthy",
        "gateway_url": f"http://127.0.0.1:{gateway_port}",
    }
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    seed_credentials(app_home, attach=_ATTACH, ownership=_OWNERSHIP)
    seat_valid_database(app_home)
    log_path = tmp_path / "gateway.log"
    log_handle = log_path.open("wb")
    with _squatter(tmp_path, worker_port, body) as (squatter, request_log):
        proc = spawn_gateway(
            script=_GATEWAY,
            gateway_port=gateway_port,
            env=armed_gateway_env(
                app_home, gateway_port=gateway_port, worker_port=worker_port
            ),
            log_handle=log_handle,
        )
        try:
            base = f"http://127.0.0.1:{gateway_port}"
            await_gateway_ready(base, proc, log_path=log_path)
            status, prepared = _prepare(
                base, f"Bearer {_ATTACH}", "run-provenance-url-echo"
            )
            assert status == 503, prepared
            assert prepared["detail"] == "run admission is not execution-ready"
            assert squatter.poll() is None, "squatter must not be evicted"
            requests = request_log.read_text(encoding="utf-8").splitlines()
            assert all(line.startswith("GET /health") for line in requests), requests
        finally:
            reap_gateway(proc)
            log_handle.close()


def test_two_gateways_one_worker_authenticated_pairing(tmp_path: Path) -> None:
    """S95: a second armed gateway never adopts or evicts the first's worker.

    Gateway A spawns and owns its REAL worker on the shared port; gateway B,
    armed over its own application home but pointed at the same worker port,
    classifies A's worker FOREIGN (a lifetime B never issued): B's demand is
    refused, A's worker survives, and A keeps its execution readiness.
    """
    worker_port = free_port()
    with _armed_gateway_on_worker_port(tmp_path, worker_port, home_name="home-a") as (
        base_a,
        auth_a,
        _log_a,
    ):
        # First demand on A spawns A's real worker and reaches readiness.
        status_a, prepared_a = _prepare(base_a, auth_a, "run-provenance-owner")
        assert status_a == 201, prepared_a

        with _armed_gateway_on_worker_port(
            tmp_path, worker_port, home_name="home-b"
        ) as (base_b, auth_b, log_b):
            status_b, prepared_b = _prepare(base_b, auth_b, "run-provenance-thief")
            assert status_b == 503, prepared_b
            assert prepared_b["detail"] == "run admission is not execution-ready"

            # A's worker survived B's attempt: still ANSWERING on the port.
            # This probe carries no internal bearer, so the real worker
            # challenges it with 401 - an HTTP answer either way is liveness
            # (an evicted worker would refuse the connection outright).
            with httpx.Client(timeout=5.0) as client:
                health = client.get(f"http://127.0.0.1:{worker_port}/health")
            assert health.status_code in (200, 401), health.status_code

            # B's refusal is provenance-shaped, through either fail-closed
            # layer: the worker-IPC credential boundary (A's worker answers
            # B's probe 401 - B cannot even read the pairing evidence of a
            # worker from a foreign application home), or, when the evidence
            # is readable, the classifier's loud refusal. Both leave B
            # without adoption and A's worker untouched.
            log_text = log_b.read_bytes().decode("utf-8", errors="replace")
            assert (
                "401 Unauthorized" in log_text
                or "cannot adopt or evict" in log_text
                or "not adoptable" in log_text
            ), "expected B's log to carry a provenance-shaped refusal"


# A genuinely armed drive of the production ``_spawn_worker`` conflict branch.
#
# The PRIOR_GENERATION authorized-eviction path cannot be reached by a black-box
# gateway subprocess: ``GATEWAY_LIFETIME_ID`` is a per-process ``uuid4`` a
# squatter cannot forge, and a real spawned worker honours ``/admin/shutdown`` so
# its eviction never *fails*. So this runs under a real armed desktop profile,
# reads THIS process's own lifetime - the only value a prior-generation worker of
# this gateway could legitimately carry - hands it to a stubborn squatter that
# reports an earlier generation and refuses to die, then drives the production
# ``_spawn_worker`` at a higher generation. The gateway logic is production code;
# the squatter is the modeled adversary (a wedged prior worker), never a stand-in
# for any code under test.
_PRIOR_GENERATION_CONFLICT_DRIVER = """
import asyncio
import contextlib
import json
import subprocess
import sys
import time

import httpx

from vaultspec_a2a.control.config import settings
from vaultspec_a2a.control.worker_management import (
    GATEWAY_LIFETIME_ID,
    _spawn_worker,
    _worker_stderr_log_path,
)

squatter_file, worker_port_s, squatter_log, result_file = sys.argv[1:5]
worker_port = int(worker_port_s)

if not settings.desktop_profile_armed:
    raise SystemExit("driver requires the armed desktop profile")

# The squatter claims THIS gateway's lifetime at an earlier generation: exactly
# what a prior-generation worker this gateway spawned would report.
body = {
    "status": "healthy",
    "paired_gateway_lifetime": GATEWAY_LIFETIME_ID,
    "worker_generation": "1",
}
# Detach the squatter's std streams: it outlives this driver (the parent reaps
# it), so inheriting the driver's captured pipes would wedge the parent's read on
# a pipe the squatter never closes.
squatter = subprocess.Popen(
    [sys.executable, squatter_file, str(worker_port), json.dumps(body), squatter_log],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    try:
        with httpx.Client(timeout=1.0) as client:
            if client.get(f"http://127.0.0.1:{worker_port}/health").status_code == 200:
                break
    except httpx.HTTPError:
        time.sleep(0.05)
else:
    raise SystemExit("squatter never came up")

worker_url = f"http://127.0.0.1:{worker_port}"
# generation=2 makes the reported generation 1 a PRIOR_GENERATION verdict, which
# authorizes eviction under the armed profile; the squatter's refusal to release
# the port makes that eviction fail.
result = asyncio.run(_spawn_worker(worker_url, worker_port, generation=2))
autospawn_log = _worker_stderr_log_path(worker_port)

# Were the conflict guard absent, _spawn_worker would spawn a real worker onto the
# held port; reap any such handle so the driver leaks nothing, while still
# reporting that a spawn was attempted.
if result is not None:
    with contextlib.suppress(Exception):
        result.kill()
        result.wait(timeout=10)

with open(result_file, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "armed": settings.desktop_profile_armed,
            "squatter_pid": squatter.pid,
            "spawn_result": "process" if result is not None else "none",
            "autospawn_log": str(autospawn_log),
            "autospawn_log_exists": autospawn_log.exists(),
        },
        handle,
    )
"""


def test_failed_owner_authorized_eviction_is_conflict_without_adoption(
    tmp_path: Path,
) -> None:
    """A failed owner-authorized eviction is a conflict, never an adoption.

    Under the armed desktop profile a prior-generation worker this gateway
    spawned is evictable; but when that eviction fails - the worker is wedged and
    ignores the shutdown - the gateway must refuse to spawn onto the held port
    (conflict, no adoption), never adopt the survivor and never spawn a competitor
    onto a port it still holds.

    Discriminating on three independent axes, all against real processes:

    - No adoption: ``_spawn_worker`` returns no worker handle.
    - No spawn after the failed eviction: the deterministic worker-autospawn
      stderr log is never created. Remove the conflict guard and the code falls
      through to spawn a real worker onto the held port, which opens that log
      before it even fails to bind - so this file's absence fails loudly.
    - The eviction was really *authorized and attempted*: the squatter received
      the bearer-authenticated ``POST /admin/shutdown``. That distinguishes the
      PRIOR_GENERATION authorized-eviction branch from the FOREIGN/UNIDENTIFIED
      refuse-*without*-eviction branch, which sends no shutdown at all.
    """
    worker_port = free_port()
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    squatter_file = tmp_path / "squatter.py"
    squatter_file.write_text(_SQUATTER, encoding="utf-8")
    driver_file = tmp_path / "prior_generation_conflict_driver.py"
    driver_file.write_text(_PRIOR_GENERATION_CONFLICT_DRIVER, encoding="utf-8")
    squatter_log = tmp_path / "squatter-requests.log"
    squatter_log.write_text("", encoding="utf-8")
    result_file = tmp_path / "result.json"

    env = os.environ.copy()
    env["VAULTSPEC_DESKTOP_APP_HOME"] = str(app_home)
    env["VAULTSPEC_ENVIRONMENT"] = "production"
    env["VAULTSPEC_PORT"] = str(free_port())
    env["VAULTSPEC_WORKER_PORT"] = str(worker_port)

    driver = subprocess.run(
        [
            sys.executable,
            str(driver_file),
            str(squatter_file),
            str(worker_port),
            str(squatter_log),
            str(result_file),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert driver.returncode == 0, (
        f"driver failed ({driver.returncode}):\n{driver.stdout}\n{driver.stderr}"
    )
    result = json.loads(result_file.read_text(encoding="utf-8"))
    squatter_pid = int(result["squatter_pid"])
    try:
        assert result["armed"] is True, result

        # No adoption: the demand produced no worker handle.
        assert result["spawn_result"] == "none", result

        # No spawn attempted after the failed eviction (checked independently of
        # the driver's own report, on the real filesystem).
        assert result["autospawn_log_exists"] is False, result
        assert not Path(result["autospawn_log"]).exists(), result

        requests = squatter_log.read_text(encoding="utf-8").splitlines()
        # The authorized eviction was really attempted against the occupant.
        assert any(line.startswith("POST /admin/shutdown") for line in requests), (
            requests
        )
        # And it began as a health-provenance read, not a blind kill.
        assert any(line.startswith("GET /health") for line in requests), requests

        # Eviction failed: the wedged squatter ignored the shutdown and still
        # holds the port - and was NOT adopted regardless.
        assert is_pid_alive(squatter_pid), (
            "the wedged prior-generation worker must survive a failed eviction"
        )
    finally:
        import asyncio

        from ..utils import kill_pid_tree_async

        with contextlib.suppress(Exception):
            asyncio.run(
                kill_pid_tree_async(squatter_pid, term_timeout=5.0, kill_timeout=5.0)
            )
