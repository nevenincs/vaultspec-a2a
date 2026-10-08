"""The declarative registry of development verbs and their targets.

This module is the single source of truth for what the harness can do. The
justfile exposes each verb; everything about *what a target runs*, whether it
gates, and how targets compose into aggregates is stated here as data.

The verbs split by CONSEQUENCE, not by tool:

``lint``
    GATES. Read-only, and a finding fails the build.
``fix``
    MUTATES. Everything automatically repairable, in one pass.
``audit``
    Only ``deps`` gates. Every other target is advisory and exits 0 even with
    findings, because each yields a lead to confirm rather than a verdict.
``test``
    GATES. See :data:`TEST` for what each lane proves.
``health``
    MEASURES. Always exits 0.

THRESHOLDS ARE INDUSTRY DEFAULTS, NOT THIS TREE'S CURRENT WORST. Every numeric
limit backing these targets - in ``pyproject.toml`` under ``[tool.ruff.lint]``,
``[tool.pylint.design]``, ``[tool.complexipy]``, and :mod:`dev.health` - is
the published default for its tool or the widely-cited standard the tool was
built around (cyclomatic 10, cognitive 15, module length 1000). They were NOT
calibrated to what this repository currently scores. A dimension that is red is
reporting real debt, and the number to move is the code, not the threshold.

That choice is why :data:`LINT`'s ``all`` aggregate is explicit about which
dimensions it chains: a gate whose burndown is unfinished belongs in ``audit``
until it can hold the line, because a permanently-red gate teaches people to
ignore red.
"""

from __future__ import annotations

from dataclasses import dataclass

from dev.paths import PACKAGE_PATH, PYTHON_PATHS, SKIPPED_DIRS, TEST_TIERS
from dev.runner import (
    Cmd,
    Echo,
    Ref,
    Step,
    ToolOrDocker,
    dev_module,
    uv_run,
    uv_run_env,
)

__all__ = [
    "AUDIT",
    "BUILD",
    "CI",
    "DEFAULTS",
    "DEPS",
    "FIX",
    "HEALTH",
    "LINT",
    "TEST",
    "VERBS",
    "Target",
    "Verb",
    "find_verb",
    "public_targets",
]

#: Shell scripts invoked from outside any Python entry point: by a workflow
#: step, or as a cloud environment's setup script. actionlint shellchecks a
#: `run:` block inline, but not a script the block invokes, so these would
#: otherwise carry no coverage at all.
SHELL_PATHS = (
    "scripts/prove_artifact_lifecycle.sh",
    "scripts/cloud_session_setup.sh",
)

#: complexipy emits status glyphs; Windows consoles default to a codepage that
#: cannot encode them, which aborts the run before any finding is reported.
UTF8 = {"PYTHONIOENCODING": "utf-8"}

#: Complexipy exclusion patterns scoped to the production-only ``lint complexity``
#: target. Patterns are relative to the package; direct and nested forms cover
#: each test tier and skipped directory without changing the test-focused audit
#: target. The nested form is the load-bearing one: most test code lives in
#: per-package `*/tests/` directories, not in the top-level tiers.
COMPLEXIPY_EXCLUDE_PATTERNS = tuple(
    pattern
    for name in (*TEST_TIERS, *sorted(SKIPPED_DIRS))
    for pattern in (f"{name}/**", f"**/{name}/**")
)

#: Complexipy parses repeated ``--exclude`` flags independently, so retain all
#: target-local patterns in the CLI's documented comma-separated form.
COMPLEXIPY_EXCLUDES = ("--exclude", ",".join(COMPLEXIPY_EXCLUDE_PATTERNS))

#: Test tiers held out of the security scan, as bandit's own comma-joined form.
#:
#: This is passed on the COMMAND LINE, not through `[tool.bandit] exclude_dirs`
#: in pyproject.toml. The config key is silently ignored under `-r` - setting it
#: left the scan covering all 105k lines and reporting a single High that was a
#: wheel-extraction test validating every member for absolute paths and `..` on
#: the line above the extract. `-x` actually excludes: 356 findings became 51,
#: and the false High disappeared with the tier it lived in.
BANDIT_EXCLUDES = ("-x", ",".join(f"*/{tier}/*" for tier in TEST_TIERS))

#: Ruff rules for per-function shape, selected explicitly rather than through
#: ``[tool.ruff.lint] select`` in pyproject.toml.
#:
#: Keeping them off the everyday gate is the load-bearing part: their limits are
#: industry defaults against a tree that has never measured itself, so folding
#: them into ``lint python`` would bury every style and correctness finding
#: under a burndown backlog. Their thresholds live in ``[tool.ruff.lint.mccabe]``
#: and ``[tool.ruff.lint.pylint]``.
FUNCTION_LIMITS = "C90,PLR0911,PLR0912,PLR0913,PLR0915"

#: The duplication detector's thresholds and scope now live with its runner in
#: `dev/audit/duplication.py`, which owns the whole measurement. They are not
#: restated here: a threshold in two places is a threshold that drifts.


@dataclass(frozen=True)
class Target:
    """One selectable behaviour within a verb.

    Args:
        name: The target token typed on the command line.
        summary: One-line description shown by ``help``.
        steps: The steps to run, in order.
        advisory: When true the target's findings do not gate. Only the
            statuses in `FINDINGS_CODES` ({1}) are suppressed; every other
            non-zero status is the tool failing to RUN, and propagates.
        keep_going: When true a failing step does not stop the remaining steps.
            Aggregate dashboards set this so one red dimension does not hide
            every dimension after it.
    """

    name: str
    summary: str
    steps: tuple[Step, ...]
    advisory: bool = False
    keep_going: bool = False


@dataclass(frozen=True)
class Verb:
    """A top-level harness verb and the targets it dispatches to.

    Args:
        name: The verb token, matching the justfile recipe name.
        summary: One-line description of the verb.
        targets: The selectable targets, in display order.
        note: Optional extra paragraph appended to the verb's ``help`` output.
    """

    name: str
    summary: str
    targets: tuple[Target, ...]
    note: str = ""

    def find(self, name: str) -> Target | None:
        """Return the named target, or ``None`` when it is not defined."""
        return next((t for t in self.targets if t.name == name), None)


def public_targets(verb: Verb) -> tuple[str, ...]:
    """Return the target tokens a user may type, in display order."""
    return tuple(t.name for t in verb.targets if not t.name.startswith("_"))


def _ruff(*prefix: str) -> Cmd:
    return uv_run("ruff", *prefix, *PYTHON_PATHS)


def _verb(verb: str, target: str) -> Cmd:
    """Build a command that re-enters this harness at another verb.

    ``Ref`` composes targets WITHIN one verb. An aggregate that spans verbs -
    only ``ci`` does - re-enters through the documented entry point rather than
    reaching into another verb's internals, so it cannot bypass that verb's own
    advisory-versus-gating decision.
    """
    return uv_run("python", "-m", "dev", verb, target)


def _pytest(*argv: str) -> Cmd:
    """Run pytest beneath the repository's result-to-exit process owner."""
    return uv_run(
        "python",
        "-m",
        "vaultspec_a2a.testing.runner",
        "--",
        *argv,
    )


# ---------------------------------------------------------------------------
#  deps
# ---------------------------------------------------------------------------

DEPS = Verb(
    name="deps",
    summary="Resolve dependency profiles and manage the lockfile.",
    note=(
        "These targets deliberately do NOT go through 'uv run --no-sync': changing "
        "the environment is their whole purpose."
    ),
    targets=(
        Target(
            "base",
            "Resolve the base runtime profile from the lock.",
            (Cmd(("uv", "sync", "--locked", "--no-default-groups")),),
        ),
        Target(
            "otlp",
            "Resolve the base runtime plus the optional OTLP exporter from the lock.",
            (
                Cmd(
                    (
                        "uv",
                        "sync",
                        "--locked",
                        "--no-default-groups",
                        "--extra",
                        "otlp",
                    )
                ),
            ),
        ),
        Target(
            "rag",
            "Resolve the RAG runtime profile without provisioning models.",
            (Cmd(("uv", "sync", "--locked", "--no-default-groups", "--extra", "rag")),),
        ),
        Target(
            "tooling",
            "Resolve the repository tooling profile from the lock.",
            (
                Cmd(
                    (
                        "uv",
                        "sync",
                        "--locked",
                        "--no-default-groups",
                        "--group",
                        "tooling",
                    )
                ),
            ),
        ),
        Target(
            "node",
            "Restore the project-pinned ACP runtime from the npm lock.",
            (
                Cmd(("node", "dev/node/check_node_version.mjs")),
                Cmd(("npm", "ci")),
            ),
        ),
        Target(
            "claude-cli",
            "Expose the locked Claude CLI for hosted binary-identity tests.",
            (dev_module("ci_claude_cli"),),
        ),
        Target(
            "codex-cli",
            "Install the proven Codex CLI for hosted binary-identity tests.",
            (dev_module("ci_codex_cli"),),
        ),
        Target(
            "docker-ci",
            "Verify rootless Docker and install the pinned Docker Compose plugin.",
            (dev_module("ci_docker"),),
        ),
        Target(
            "all",
            "Resolve every runtime extra plus the composed 'all' group.",
            (
                Cmd(
                    (
                        "uv",
                        "sync",
                        "--locked",
                        "--no-default-groups",
                        "--all-extras",
                        "--group",
                        "all",
                    )
                ),
            ),
        ),
        Target(
            "check",
            "Verify project metadata and the lock agree, without changing either.",
            (Cmd(("uv", "lock", "--check")),),
        ),
        Target(
            "lock",
            "Regenerate the lockfile.",
            (Cmd(("uv", "lock")),),
        ),
        Target(
            "upgrade",
            "Regenerate the lockfile at the newest allowed versions.",
            (Cmd(("uv", "lock", "--upgrade")),),
        ),
    ),
)


# ---------------------------------------------------------------------------
#  lint - GATES
# ---------------------------------------------------------------------------

LINT = Verb(
    name="lint",
    summary="Run gating static analysis; a finding fails the build.",
    note=(
        "'all' chains only the dimensions that hold the line today. complexity, "
        "limits, and size are REAL GATES at "
        "industry thresholds whose burndown is unfinished - run each by name, or "
        "'just health' for the ranked backlog. Chaining a permanently-red gate "
        "would hide every dimension behind it and teach people to ignore red. A "
        "dimension graduates into 'all' when it reaches zero and can hold it; "
        "'imports' was the first, 'type-platforms' followed, and 'type-strict' "
        "and 'nesting' both graduated on 2026-10-01. 'type-platforms' earns its "
        "place for a reason worth stating on its own: `ty` resolves "
        "`sys.platform` against the machine it runs on, so a Windows-only call "
        "in unguarded code passes for everyone on Windows and fails only on the "
        "Linux runner. Advisory, it reported a real defect that shipped anyway; "
        "gating, the sweep answers the same on every machine."
    ),
    targets=(
        Target(
            "python",
            "Ruff lint and format verification.",
            (_ruff("check"), _ruff("format", "--check")),
        ),
        # The three type targets share one harness (`dev.quality.types`)
        # rather than shelling out to the checkers directly. It reads each
        # checker's JSON rather than its console rendering, REFUSES an empty
        # report instead of reading it as zero diagnostics, and prints a
        # summary grouped by rule and file rather than the raw dump - which
        # for the strict pass is 3500 lines nobody reads to the end.
        Target(
            "type",
            "Ty type checking, grouped by rule and file.",
            (dev_module("quality.types", "--no-strict"),),
        ),
        Target(
            "type-platforms",
            "Ty type checking against every target platform, as one verdict.",
            (dev_module("quality.types", "--no-strict", "--platforms"),),
        ),
        Target(
            "type-strict",
            "Ty plus the basedpyright strict pass, grouped.",
            (dev_module("quality.types"),),
        ),
        # Ruff's TC rules move imports INTO the TYPE_CHECKING guard; nothing
        # stock checks the other direction, and a guarded name evaluated at
        # runtime is a NameError a type checker is perfectly happy with.
        Target(
            "type-guards",
            "TYPE_CHECKING-only imports must not be referenced at runtime.",
            (dev_module("quality.type_checking_runtime_use"),),
        ),
        # Static analysis proves a module is REFERENCED. Only importing it
        # proves it LOADS.
        Target(
            "imports-load",
            "Every shipped production module must import in a clean process.",
            (dev_module("quality.import_load_probe"),),
        ),
        # The three zero-target coverage gates over `dev.audit.unreachable_code`.
        # Each has no baseline and no exclusion list: a baseline reports the
        # delta against a number someone wrote down, and the number is what
        # gets updated when the gate goes red.
        Target(
            "reachability",
            "Every shipped module must be reachable from a shipped entry point.",
            (dev_module("quality.unreachable_module_coverage"),),
        ),
        Target(
            "symbols",
            "Every top-level symbol must have a consumer that is not its own test.",
            (dev_module("quality.unused_symbol_coverage"),),
        ),
        Target(
            "exports",
            "Every name published in __all__ must have an importer.",
            (dev_module("quality.unconsumed_export_coverage"),),
        ),
        Target(
            "complexity",
            "Cognitive complexity over production code (Sonar limit 15).",
            (uv_run_env(UTF8, "complexipy", PACKAGE_PATH, *COMPLEXIPY_EXCLUDES),),
        ),
        Target(
            "limits",
            "Function-shape limits: paths, branches, returns, arguments, statements.",
            (uv_run("ruff", "check", PACKAGE_PATH, "--select", FUNCTION_LIMITS),),
        ),
        Target(
            "nesting",
            "Nesting depth (PLR1702, preview-scoped, ruff default of 5).",
            (
                uv_run(
                    "ruff", "check", PACKAGE_PATH, "--select", "PLR1702", "--preview"
                ),
            ),
        ),
        Target(
            "size",
            "Module length and class design limits ruff has no rule for.",
            (
                uv_run(
                    "pylint",
                    PACKAGE_PATH,
                    "--rcfile=pyproject.toml",
                    "--recursive=y",
                    "--score=n",
                ),
            ),
        ),
        Target(
            "imports",
            "Intra-package imports must be relative, per the repository mandate.",
            (dev_module("guards.relative_imports"),),
        ),
        Target(
            "anchors",
            "Production code must not anchor storage to the repository layout.",
            (dev_module("guards.storage_anchors"),),
        ),
        Target(
            "duplication",
            "JSCPD blocking scan (Q.2): every tier plus dev/, against the "
            "adjudicated baseline.",
            (dev_module("audit.duplication", "--blocking"),),
        ),
        Target(
            "dependencies",
            "Deptry dependency-declaration drift.",
            (uv_run("deptry", "."),),
        ),
        Target(
            "toml",
            "Taplo TOML linting.",
            (ToolOrDocker("taplo", ("lint", "*.toml"), "tamasfe/taplo:0.9.3"),),
        ),
        # Two questions about the same artifacts. actionlint asks whether the
        # YAML is well-formed and its expressions resolve; the contract asks
        # whether a `run:` step is calling a recipe or re-implementing one. A
        # workflow can be perfectly valid YAML and still repeat one locked
        # `uv sync` invocation in five jobs, which is what this repository's
        # did.
        Target(
            "workflow",
            "Lint the workflows, then hold them to the CI/justfile contract.",
            (
                uv_run("python", "-m", "dev.actionlint"),
                uv_run("python", "-m", "dev.ci_contract"),
            ),
        ),
        Target(
            "shell",
            "Shellcheck over the scripts workflow steps call out to.",
            (uv_run("shellcheck", "-x", "--shell", "bash", *SHELL_PATHS),),
        ),
        Target(
            "all",
            "Every gate that holds the line today.",
            # `imports` GRADUATED into this chain on 2026-07-31: its burndown
            # reached zero (413 -> 0) and the gate can hold that line, which is
            # the promotion rule every dimension here follows. It is the first
            # to finish. A dimension chained before it reaches zero would make
            # `lint all` permanently red and hide everything after it.
            #
            # `type` is green again as of the mcp 2.0 migration. It was chained
            # while red on purpose before that: its findings were not a
            # threshold backlog but a live production break - `mcp` 2.0.0 had
            # removed `mcp.server.fastmcp`, which the server still imported - and
            # a gate going red on a genuine break is the gate working.
            #
            # `type-guards` and `imports-load` joined on the same rule: both
            # were written green over this tree and both answer a question
            # nothing else here asks - whether a TYPE_CHECKING-only name is
            # evaluated at runtime, and whether every shipped module actually
            # imports.
            #
            # `type-strict` and `nesting` GRADUATED on 2026-10-01: the
            # basedpyright strict pass and the PLR1702 nesting-depth sweep each
            # held zero across two clean locked runs at unchanged scope and
            # threshold, with no new exclusion, suppression, baseline, or
            # duplication behind either number, which is the same bar
            # `imports` set.
            #
            # The reachability trio (`reachability`, `symbols`, `exports`)
            # GRADUATED the same day. It opened at 8, 53 and 155 findings,
            # which is a burndown, and lived in `strict` and `audit` until it
            # reached zero; all three now hold that line without a baseline or
            # exclusion behind any of the three numbers.
            #
            # `duplication` (Q.2) GRADUATED on arrival: it holds zero new and
            # zero stale against its adjudicated baseline from the run that
            # wrote the baseline, the same bar every other entry here met
            # before joining, not an exception to it.
            #
            # `anchors` (Q.3) held zero the whole time it sat outside this
            # chain - its own DEFERRED debt list was emptied before this
            # plan and never refilled - so it was simply never added, not a
            # burndown still in progress.
            tuple(
                Ref(name)
                for name in (
                    "python",
                    "type",
                    "type-platforms",
                    "type-strict",
                    "type-guards",
                    "nesting",
                    "imports",
                    "imports-load",
                    "reachability",
                    "symbols",
                    "exports",
                    "dependencies",
                    "toml",
                    "workflow",
                    "shell",
                    "duplication",
                    "anchors",
                )
            ),
            keep_going=True,
        ),
        Target(
            "strict",
            "Every gate including the unfinished burndowns (expected red).",
            tuple(
                Ref(name)
                for name in (
                    "python",
                    "type",
                    "type-platforms",
                    "type-strict",
                    "type-guards",
                    "complexity",
                    "limits",
                    "nesting",
                    "size",
                    "imports",
                    "imports-load",
                    "reachability",
                    "symbols",
                    "exports",
                    "dependencies",
                    "toml",
                    "workflow",
                    "shell",
                    "duplication",
                    "anchors",
                )
            ),
            keep_going=True,
        ),
    ),
)


# ---------------------------------------------------------------------------
#  fix - MUTATES
# ---------------------------------------------------------------------------

FIX = Verb(
    name="fix",
    summary="Apply every available formatter and automatic fix.",
    targets=(
        Target(
            "python",
            "Format and auto-repair Python source.",
            (_ruff("format"), _ruff("check", "--fix")),
        ),
        Target(
            "imports",
            "Sort imports only (ruff I-rule safe fixes).",
            (uv_run("ruff", "check", "--select", "I", "--fix", *PYTHON_PATHS),),
        ),
        Target(
            "toml",
            "Format TOML files.",
            (ToolOrDocker("taplo", ("fmt", "*.toml"), "tamasfe/taplo:0.9.3"),),
        ),
        Target(
            "vault",
            "Repair this repository's own .vault/ corpus.",
            (
                uv_run("vaultspec-core", "vault", "check", "all", "--fix"),
                uv_run("vaultspec-core", "vault", "sanitize", "annotations"),
            ),
        ),
        Target(
            "all",
            "Run every fixer.",
            tuple(Ref(name) for name in ("python", "toml")),
            keep_going=True,
        ),
    ),
)


# ---------------------------------------------------------------------------
#  audit - ADVISORY, except deps
# ---------------------------------------------------------------------------

AUDIT = Verb(
    name="audit",
    summary="Audit dependencies and code quality; only 'deps' gates.",
    note=(
        "Only 'deps' gates - a published advisory against a pinned version is a "
        "verdict, not a lead. Every other target reports findings and still exits "
        "0, because each yields something to confirm: bandit reports this "
        "project's deliberate subprocess design alongside anything real, and a "
        "duplication clone may be two things that merely look alike. What none of "
        "them may do is report a scan that did not happen as a scan that found "
        "nothing - 'duplication' and 'reachability' each own that distinction "
        "themselves and exit 7 when the measurement was unavailable."
    ),
    targets=(
        # `uv audit` exits 0 even when it prints advisories, so this target -
        # labelled GATES since it was written - could not fail; and it saw only
        # Python, while this repository also locks the Node tree that hosts the
        # ACP CLI the worker runs. dev/audit/dependency_audit.py resolves every
        # pinned coordinate out of uv.lock AND package-lock.json and queries
        # OSV for all of them, so the verdict is a property of the finding set
        # rather than of a preview tool's exit code. Accepted advisories live
        # in dependency-audit-allowlist.toml, each with a reason and an expiry;
        # an expired acceptance fails the gate.
        Target(
            "deps",
            "Dependency vulnerability advisories, every ecosystem (GATES).",
            (
                Cmd(
                    (
                        "uv",
                        "run",
                        "--no-sync",
                        "python",
                        "-m",
                        "dev.audit.dependency_audit",
                    )
                ),
            ),
        ),
        Target(
            "security",
            "Bandit security scan over production code.",
            (
                uv_run(
                    "bandit",
                    "-c",
                    "pyproject.toml",
                    "-r",
                    PACKAGE_PATH,
                    *BANDIT_EXCLUDES,
                    "-q",
                ),
            ),
            advisory=True,
        ),
        # These two do NOT carry `advisory=True`, and that is not an
        # oversight. Each runner owns its tool's whole measurement and
        # therefore its own exit contract: it returns OK when the scan RAN,
        # findings and all, and ADVISORY_BROKEN when it could not. Layering
        # the harness's findings-suppression on top would map a scan that
        # never happened onto a clean result, which is the exact failure the
        # runners were written to remove - `npx` exits 0 when it cannot
        # resolve a package, so on a machine with no Node the old duplication
        # target reported exactly like a clean tree.
        Target(
            "duplication",
            "Copy-paste clone detection over production Python.",
            (dev_module("audit.duplication"),),
        ),
        # The reachability audit walks the import graph from the shipped
        # entry points, so a framework-registered FastAPI handler or typer
        # command is not reported as unused.
        Target(
            "reachability",
            "Shipped code no shipped entry point reaches.",
            (dev_module("audit.unreachable_code"),),
        ),
        Target(
            "types",
            "Every type diagnostic verbatim, behind the grouped gate's summary.",
            (dev_module("quality.types", "--full"),),
        ),
        Target(
            "docstrings",
            "Docstring coverage over the public surface.",
            (uv_run("interrogate", "-c", "pyproject.toml", PACKAGE_PATH),),
            advisory=True,
        ),
        Target(
            "complexity",
            "Cognitive complexity over the test tree.",
            (uv_run_env(UTF8, "complexipy", PACKAGE_PATH, "--failed"),),
            advisory=True,
        ),
        Target(
            "all",
            "Every audit dimension, as a dashboard.",
            (
                Echo("=== dependency advisories (GATES) ==="),
                Ref("deps"),
                Echo("=== security ==="),
                Ref("security"),
                Echo("=== reachability ==="),
                Ref("reachability"),
                Echo("=== duplication ==="),
                Ref("duplication"),
                Echo("=== docstring coverage ==="),
                Ref("docstrings"),
            ),
            keep_going=True,
        ),
    ),
)


# ---------------------------------------------------------------------------
#  test - GATES
# ---------------------------------------------------------------------------

TEST = Verb(
    name="test",
    summary="Run the project test suites.",
    note=(
        "'unit' is the default gate and EXCLUDES the service tier, so a green "
        "'unit' says nothing about service certification. 'all' removes the "
        "marker exclusion and is what a suite-clean claim needs."
    ),
    targets=(
        Target(
            "unit",
            "The unit gate, explicitly excluding service tests.",
            (_pytest("-m", "not service"),),
        ),
        Target(
            "parallel",
            "The unit gate under declaration-derived distribution: workers "
            "requested at the core count, then admitted against live peer "
            "sessions and machine capacity by the resource plugin.",
            (
                _pytest(
                    "-m",
                    "not service",
                    "-n",
                    "auto",
                    "--dist=loadgroup",
                ),
            ),
        ),
        Target(
            "frozen-contents",
            "Reject test tiers in the explicitly selected frozen runtime tree.",
            (
                _pytest(
                    "packaging/tests/test_build_artifact_contents.py"
                    "::test_the_frozen_onedir_excludes_every_test_tier"
                ),
            ),
        ),
        Target(
            "merge",
            "Pure unit tests under declaration-derived resource-aware "
            "distribution for the pull-request merge gate.",
            (
                _pytest(
                    "-m",
                    "unit",
                    "-n",
                    "auto",
                    "--dist=loadgroup",
                ),
            ),
        ),
        Target(
            "service",
            "Deterministic service tests against real local services.",
            (_pytest("-m", "service"),),
        ),
        Target(
            "native-integration",
            "Native execution, cancellation, traces and fixture boundaries.",
            (
                _pytest(
                    "-m",
                    "service",
                    "--require-prerequisite=docker",
                    f"{PACKAGE_PATH}/service_tests/test_lifecycle.py",
                    f"{PACKAGE_PATH}/service_tests/test_cancel_health_trace.py",
                    f"{PACKAGE_PATH}/service_tests/test_worker_attach_provenance.py",
                    f"{PACKAGE_PATH}/service_tests/test_development_fixture_boundary.py",
                ),
            ),
        ),
        Target(
            "all",
            "Every collected test, without the default marker exclusion.",
            (_pytest("-m", ""),),
        ),
        Target(
            "coverage",
            "The unit gate with a terminal coverage report.",
            (
                _pytest(
                    "-m",
                    "not service",
                    f"--cov={PACKAGE_PATH}",
                    "--cov-report=term-missing",
                ),
            ),
        ),
        Target(
            "harness",
            "The development harness's own guards.",
            (_pytest("dev"),),
        ),
    ),
)


# ---------------------------------------------------------------------------
#  build - produces artifacts
# ---------------------------------------------------------------------------

BUILD = Verb(
    name="build",
    summary="Build the distributable artifacts.",
    targets=(
        Target(
            "package",
            "Build the Python source distribution and wheel.",
            (Cmd(("uv", "build", "--build-constraints", "build-constraints.txt")),),
        ),
        Target(
            "docs",
            "Run documentation tests and build strict Sphinx HTML.",
            (
                Cmd(
                    (
                        "uv",
                        "run",
                        "--isolated",
                        "--locked",
                        "--group",
                        "docs",
                        "--group",
                        "dev",
                        "python",
                        "-m",
                        "vaultspec_a2a.testing.runner",
                        "--",
                        "docs/tests",
                        "-q",
                    )
                ),
                Cmd(
                    (
                        "uv",
                        "run",
                        "--isolated",
                        "--locked",
                        "--group",
                        "docs",
                        "sphinx-build",
                        "-n",
                        "-W",
                        "--keep-going",
                        "-b",
                        "html",
                        "docs",
                        "docs/_build/html",
                    )
                ),
            ),
        ),
        Target(
            "clean",
            "Remove generated package, documentation, and cache artifacts.",
            (
                Cmd(
                    (
                        "uv",
                        "run",
                        "--no-sync",
                        "--frozen",
                        "--no-default-groups",
                        "python",
                        "-m",
                        "dev.repo.build_clean",
                    )
                ),
            ),
        ),
        Target(
            "all",
            "Build every artifact.",
            (Ref("package"), Ref("docs")),
            keep_going=True,
        ),
    ),
)


# ---------------------------------------------------------------------------
#  health - MEASURES, always exits 0
# ---------------------------------------------------------------------------

HEALTH = Verb(
    name="health",
    summary="Rank the worst offenders across every code-health dimension.",
    note="MEASUREMENT ONLY - always exits 0.",
    targets=(
        Target(
            "report",
            "Ranked worst-offender report across every dimension.",
            (dev_module("health"),),
            advisory=True,
        ),
        Target(
            "json",
            "The same report, machine-readable.",
            (dev_module("health", "--json"),),
            advisory=True,
        ),
        Target(
            "census",
            "Full per-dimension distributions behind each threshold.",
            (dev_module("health", "--census"),),
            advisory=True,
        ),
    ),
)


# ---------------------------------------------------------------------------
#  ci - the aggregate pipeline
# ---------------------------------------------------------------------------

CI = Verb(
    name="ci",
    summary="Run a composed local gate.",
    targets=(
        Target(
            "merge",
            "Fast Linux merge gate: dependency coherence, blocking lint, "
            "Vault integrity, harness guards, and resource-aware unit tests.",
            (
                _verb("deps", "check"),
                _verb("lint", "all"),
                uv_run("vaultspec-core", "vault", "check", "all"),
                _verb("test", "harness"),
                _verb("test", "merge"),
            ),
        ),
        Target(
            "all",
            "Locked environment, Node runtime, lint, dependency, vault, and "
            "unit gates.",
            (
                Cmd(
                    (
                        "uv",
                        "sync",
                        "--locked",
                        "--no-default-groups",
                        "--extra",
                        "otlp",
                        "--group",
                        "all",
                    )
                ),
                _verb("deps", "node"),
                _verb("lint", "all"),
                _verb("audit", "deps"),
                uv_run("vaultspec-core", "vault", "check", "all"),
                _verb("test", "harness"),
                _verb("test", "unit"),
                # The package and documentation builds. This does NOT freeze
                # the runtime: the onedir a user receives is still produced
                # only by release.yml.
                _verb("build", "all"),
            ),
        ),
    ),
)


VERBS: tuple[Verb, ...] = (DEPS, LINT, FIX, AUDIT, TEST, BUILD, HEALTH, CI)

#: The target each verb selects when invoked with no argument.
DEFAULTS: dict[str, str] = {
    "deps": "check",
    "lint": "all",
    "fix": "all",
    "audit": "all",
    "test": "unit",
    "build": "all",
    "health": "report",
    "ci": "all",
}


def find_verb(name: str) -> Verb | None:
    """Return the named verb, or ``None`` when it is not defined."""
    return next((v for v in VERBS if v.name == name), None)
