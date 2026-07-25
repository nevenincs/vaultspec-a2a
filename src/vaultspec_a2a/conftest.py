"""Root conftest — runs at collection time, before any test module imports.

Also the single home of the repository's external-prerequisite rule. See
``EXTERNAL_PREREQUISITES`` below: every suite reports an absent external
resource the same way, and a caller that guarantees a resource is present gets
a loud failure rather than a quiet skip when the guarantee is false.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING, NoReturn

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

# Suppress OTel metric exporter noise during tests.  The trace SDK stays
# active so span-creation tests work.  The metric reader's periodic export
# would otherwise hit localhost:4317 and log UNAVAILABLE errors.
# OTEL_METRICS_EXPORTER=none disables the metric export pipeline entirely.
os.environ.setdefault("OTEL_METRICS_EXPORTER", "none")
# Point the trace exporter at a non-routable address so BatchSpanProcessor
# silently drops spans instead of retrying against localhost:4317.
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://198.51.100.1:4317")


# ---------------------------------------------------------------------------
# The external-prerequisite rule — one rule, every suite
# ---------------------------------------------------------------------------
#
# An *external prerequisite* is a resource this repository cannot provide for
# itself: a container runtime, a cross-repository binary, a third-party
# credential. Suites used to disagree about what an absent one means — the
# service suite raised, the provider suite skipped silently — so a missing
# dashboard checkout and a real regression were reported identically, and
# provider gates that never ran anywhere still reported green.
#
# The rule:
#
#   * Absent -> the test SKIPS, and the reason names the prerequisite and the
#     exact runbook line that supplies it. A skip is a report, never a shortcut.
#   * Whether an absent prerequisite is tolerable is NOT the test's judgement.
#     The caller declares what it guarantees with ``--require-prerequisite=<id>``
#     (repeatable). A declared prerequisite that is not actually present aborts
#     the session before collection, and a test that skips for a declared
#     prerequisite fails the session at the end of the run.
#
# Certification jobs therefore declare everything they provision, which keeps
# the standing acceptance criterion — "required certification jobs must fail
# when prerequisites are unavailable" — true without any per-suite restatement.

DECLARE_OPTION = "--require-prerequisite"


class ExternalPrerequisite:
    """A resource this repository cannot provide for itself.

    ``probe`` is ``None`` for a prerequisite only the calling suite can test
    for - a live multi-service topology, say - which the caller probes itself
    and then reports through :meth:`ExternalPrerequisiteRule.absent`.

    ``skip_reason_tokens`` lets the session-end check attribute an inline
    ``skipif`` in a suite that does not call the rule back to the prerequisite
    it is gated on; matching is case-insensitive substring.
    """

    __slots__ = ("id", "probe", "skip_reason_tokens", "supply", "what")

    def __init__(
        self,
        prerequisite_id: str,
        *,
        what: str,
        supply: str,
        probe: Callable[[], bool] | None,
        skip_reason_tokens: tuple[str, ...] = (),
    ) -> None:
        self.id = prerequisite_id
        self.what = what
        self.supply = supply
        self.probe = probe
        self.skip_reason_tokens = skip_reason_tokens

    def absence_reason(self, detail: str = "") -> str:
        """The canonical skip reason for this prerequisite being absent."""
        tail = f" ({detail})" if detail else ""
        return f"{self.what} is unavailable{tail}. Supply it: {self.supply}"


def _on_path(*names: str) -> Callable[[], bool]:
    return lambda: any(shutil.which(name) is not None for name in names)


def _env_set(name: str) -> Callable[[], bool]:
    return lambda: bool((os.environ.get(name) or "").strip())


def _docker_compose_present() -> bool:
    """Docker plus its compose plugin are resolvable and answer their version.

    Deliberately does NOT probe image pulls or daemon health: a Docker that is
    installed but broken is a failure to surface, not an absence to skip on.
    """
    docker = shutil.which("docker") or shutil.which("docker.exe")
    if docker is None:
        return False
    try:
        completed = subprocess.run(
            [docker, "compose", "version"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _mcp_streamable_http_present() -> bool:
    from importlib.util import find_spec

    try:
        return find_spec("mcp.client.streamable_http") is not None
    except (ImportError, ValueError):
        return False


EXTERNAL_PREREQUISITES: tuple[ExternalPrerequisite, ...] = (
    ExternalPrerequisite(
        "docker",
        what="a Docker CLI with the compose plugin",
        supply=(
            "install Docker and confirm `docker compose version` exits zero, then "
            "re-run the service tier"
        ),
        probe=_docker_compose_present,
    ),
    ExternalPrerequisite(
        "dashboard-engine",
        what="the cross-repository dashboard serve command",
        supply=(
            "check out the dashboard repository, build its binary, and export "
            "VAULTSPEC_ENGINE_SERVE_CMD as an absolute `... serve --no-seat "
            "--port {port} --workspace {workspace}` template"
        ),
        probe=_env_set("VAULTSPEC_ENGINE_SERVE_CMD"),
    ),
    ExternalPrerequisite(
        "loopback-stack",
        what="a reachable loopback engine plus a2a gateway and worker",
        supply=(
            "boot a workspace-local `vaultspec serve --no-seat` engine plus this "
            "branch's a2a gateway and worker with "
            "VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true (runbook), then export "
            "VAULTSPEC_ENGINE_SERVICE_JSON and select -m service"
        ),
        probe=None,
    ),
    ExternalPrerequisite(
        "codex-cli",
        what="the Codex CLI on PATH",
        supply=(
            "npm install -g @openai/codex (a live turn additionally needs "
            "`codex login`)"
        ),
        probe=_on_path("codex", "codex.cmd", "codex.exe"),
        skip_reason_tokens=("codex cli",),
    ),
    ExternalPrerequisite(
        "claude-cli",
        what="the Claude Code ACP CLI on PATH",
        supply="npm install -g @anthropic-ai/claude-code",
        probe=_on_path("claude", "claude.cmd", "claude.exe"),
        skip_reason_tokens=("claude cli", "claude acp cli"),
    ),
    ExternalPrerequisite(
        "kimi-cli",
        what="the Kimi CLI on PATH",
        supply="uv tool install kimi-cli",
        probe=_on_path("kimi", "kimi.cmd", "kimi.exe"),
        skip_reason_tokens=("kimi cli",),
    ),
    ExternalPrerequisite(
        "mcp-streamable-http",
        what="the mcp package's streamable-http client transport",
        supply="uv sync --locked --group all",
        probe=_mcp_streamable_http_present,
        skip_reason_tokens=("mcp streamable-http",),
    ),
    ExternalPrerequisite(
        "zai-credential",
        what="a configured Z.ai authentication token",
        supply="export ZAI_AUTH_TOKEN with a valid third-party Z.ai credential",
        probe=_env_set("ZAI_AUTH_TOKEN"),
        skip_reason_tokens=("zai_auth_token",),
    ),
)

_BY_ID: dict[str, ExternalPrerequisite] = {p.id: p for p in EXTERNAL_PREREQUISITES}

# nodeid -> skip reason, for every skip observed in this session.
_SKIPPED_REASONS: dict[str, str] = {}


# Resolved once at configure time; the rule is consulted from places that have
# no access to the pytest config object.
_DECLARED: frozenset[str] = frozenset()


def declared_prerequisites() -> frozenset[str]:
    """The prerequisite ids the caller of this session guarantees are present."""
    return _DECLARED


class ExternalPrerequisiteRule:
    """The repository's one rule for what an absent prerequisite means.

    Call it to probe and decide; call :meth:`absent` when the suite has already
    probed for itself and found the resource missing. Either way the outcome is
    the same: a skip carrying the canonical runbook reason, or - when the caller
    guaranteed the resource with ``--require-prerequisite`` - a failure,
    because a broken guarantee is a defect in the run's environment rather than
    a reason to go quiet.
    """

    def __call__(self, prerequisite_id: str, detail: str = "") -> None:
        prerequisite = _BY_ID[prerequisite_id]
        if prerequisite.probe is None:
            raise LookupError(
                f"prerequisite '{prerequisite_id}' has no probe; the calling suite "
                "must probe it and report through .absent()"
            )
        if prerequisite.probe():
            return
        self.absent(prerequisite_id, detail)

    def absent(self, prerequisite_id: str, detail: str = "") -> NoReturn:
        reason = _BY_ID[prerequisite_id].absence_reason(detail)
        if prerequisite_id in declared_prerequisites():
            pytest.fail(
                f"{DECLARE_OPTION}={prerequisite_id} guarantees it is present, "
                f"but it is not: {reason}"
            )
        pytest.skip(reason)


@pytest.fixture(scope="session")
def external_prerequisite() -> ExternalPrerequisiteRule:
    """The repository's missing-prerequisite rule, as a fixture.

    Session-scoped so session-scoped stack fixtures can depend on it.
    """
    return ExternalPrerequisiteRule()


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the one channel a caller uses to guarantee a prerequisite."""
    parser.addoption(
        DECLARE_OPTION,
        action="append",
        default=[],
        metavar="ID",
        dest="required_prerequisites",
        help=(
            "Declare that an external prerequisite IS present, so its absence "
            "fails the run instead of skipping. Repeatable. Known ids: "
            + ", ".join(sorted(_BY_ID))
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    """Abort before collection when a declared prerequisite is not real."""
    global _DECLARED
    _DECLARED = frozenset(config.getoption("required_prerequisites") or [])
    unknown = sorted(_DECLARED - _BY_ID.keys())
    if unknown:
        raise pytest.UsageError(
            f"{DECLARE_OPTION} names unknown prerequisites: {', '.join(unknown)}. "
            f"Known ids: {', '.join(sorted(_BY_ID))}"
        )
    absent = sorted(
        pid
        for pid in _DECLARED
        if (probe := _BY_ID[pid].probe) is not None and not probe()
    )
    if absent:
        details = "; ".join(f"{pid}: {_BY_ID[pid].supply}" for pid in absent)
        raise pytest.UsageError(
            f"{DECLARE_OPTION} declares prerequisites this host does not have: "
            f"{', '.join(absent)}. {details}"
        )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Remember every skip reason so the session-end rule can attribute it."""
    if not report.skipped or report.when not in {"setup", "call"}:
        return
    longrepr = report.longrepr
    reason = ""
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        reason = str(longrepr[2])
    _SKIPPED_REASONS[report.nodeid] = reason


def _declared_prerequisite_skips() -> list[tuple[str, str, str]]:
    """Skips attributable to a prerequisite the caller declared present."""
    declared = declared_prerequisites()
    violations: list[tuple[str, str, str]] = []
    for nodeid, reason in sorted(_SKIPPED_REASONS.items()):
        folded = reason.casefold()
        for prerequisite_id in sorted(declared):
            tokens = _BY_ID[prerequisite_id].skip_reason_tokens
            if any(token in folded for token in tokens):
                violations.append((prerequisite_id, nodeid, reason))
                break
    return violations


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Name every gate that skipped despite its prerequisite being guaranteed."""
    violations = _declared_prerequisite_skips()
    if not violations:
        return
    terminalreporter.section("declared prerequisites that did not run", red=True)
    for prerequisite_id, nodeid, reason in violations:
        terminalreporter.write_line(f"{prerequisite_id}: {nodeid} skipped: {reason}")
    terminalreporter.write_line(
        f"{DECLARE_OPTION} guarantees these prerequisites, so these gates were "
        "required to execute."
    )


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Fail the session when a guaranteed prerequisite produced a skip instead."""
    if _declared_prerequisite_skips():
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
