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
    MEASURES. Always exits 0; composes the gates rather than restating any
    threshold, so the report and the gate cannot disagree.

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

#: The shipped package. Every production-scoped scan is rooted here.
PACKAGE = "src/vaultspec_a2a"

#: Python trees that carry committed source and are therefore linted. Naming
#: the trees rather than the repository root is what stops a new top-level
#: folder from linting itself into an exception by simply existing.
PYTHON_PATHS = ("src", "dev", "docs", "scripts", "packaging")

#: complexipy emits status glyphs; Windows consoles default to a codepage that
#: cannot encode them, which aborts the run before any finding is reported.
UTF8 = {"PYTHONIOENCODING": "utf-8"}

#: The test tiers, as glob suffixes. Every production-scoped scan excludes all
#: four; naming only the two top-level ones covers a fraction of the tree,
#: because most test code lives in per-package `*/tests/` directories.
TEST_TIERS = ("tests", "service_tests", "desktop_tests", "acceptance")

#: Test tiers held out of the cognitive-complexity scan.
#:
#: A guard test that walks the AST of every module to prove a structural
#: invariant scores badly on every complexity dimension, because branching over
#: a syntax tree is what such a test IS. Gating them at a production threshold
#: would price the guard out rather than simplify it.
COMPLEXIPY_EXCLUDES = tuple(
    part for tier in TEST_TIERS for part in ("--exclude", f"**/{tier}/**")
)

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

#: Duplication-detector thresholds. jscpd's own defaults (5 lines / 50 tokens)
#: report formatting coincidences; 20 lines with 70 tokens is the threshold at
#: which a clone is a maintenance liability rather than a similarity.
JSCPD = ("--min-lines", "20", "--min-tokens", "70", "--reporters", "console")


@dataclass(frozen=True)
class Target:
    """One selectable behaviour within a verb.

    Args:
        name: The target token typed on the command line.
        summary: One-line description shown by ``help``.
        steps: The steps to run, in order.
        advisory: When true the target reports findings but always exits 0.
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
            "server",
            "Resolve the server runtime profile from the lock.",
            (
                Cmd(
                    (
                        "uv",
                        "sync",
                        "--locked",
                        "--no-default-groups",
                        "--extra",
                        "server",
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
        "cyclomatic, shape, limits, nesting, size and type-strict are REAL GATES at "
        "industry thresholds whose burndown is unfinished - run each by name, or "
        "'just health' for the ranked backlog. Chaining a permanently-red gate "
        "would hide every dimension behind it and teach people to ignore red. A "
        "dimension graduates into 'all' when it reaches zero and can hold it; "
        "'imports' is the first to have done so."
    ),
    targets=(
        Target(
            "python",
            "Ruff lint and format verification.",
            (_ruff("check"), _ruff("format", "--check")),
        ),
        Target(
            "type",
            "Ty type checking.",
            (uv_run("ty", "check", *PYTHON_PATHS),),
        ),
        Target(
            "type-strict",
            "Basedpyright strict-mode type checking.",
            (uv_run("basedpyright"),),
        ),
        Target(
            "complexity",
            "Cognitive complexity over production code (Sonar limit 15).",
            (uv_run_env(UTF8, "complexipy", PACKAGE, *COMPLEXIPY_EXCLUDES),),
        ),
        Target(
            "cyclomatic",
            "Cyclomatic complexity over production code (ceiling 10).",
            (dev_module("health", "--gate", "cyclomatic"),),
        ),
        Target(
            "shape",
            "Module length, function length, parameter count, and nesting.",
            (dev_module("health", "--gate"),),
        ),
        Target(
            "limits",
            "Function-shape limits: paths, branches, returns, arguments, statements.",
            (uv_run("ruff", "check", PACKAGE, "--select", FUNCTION_LIMITS),),
        ),
        Target(
            "nesting",
            "Nesting depth (PLR1702, preview-scoped, ruff default of 5).",
            (uv_run("ruff", "check", PACKAGE, "--select", "PLR1702", "--preview"),),
        ),
        Target(
            "size",
            "Module length and class design limits ruff has no rule for.",
            (
                uv_run(
                    "pylint",
                    PACKAGE,
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
            "dependencies",
            "Deptry dependency-declaration drift.",
            (uv_run("deptry", "."),),
        ),
        Target(
            "toml",
            "Taplo TOML linting.",
            (ToolOrDocker("taplo", ("lint", "*.toml"), "tamasfe/taplo:0.9"),),
        ),
        Target(
            "workflow",
            "Actionlint GitHub workflow checking.",
            (uv_run("actionlint"),),
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
            tuple(
                Ref(name)
                for name in (
                    "python",
                    "type",
                    "imports",
                    "dependencies",
                    "toml",
                    "workflow",
                )
            ),
        ),
        Target(
            "strict",
            "Every gate including the unfinished burndowns (expected red).",
            tuple(
                Ref(name)
                for name in (
                    "python",
                    "type",
                    "type-strict",
                    "complexity",
                    "cyclomatic",
                    "shape",
                    "limits",
                    "nesting",
                    "size",
                    "imports",
                    "dependencies",
                    "toml",
                    "workflow",
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
            (ToolOrDocker("taplo", ("fmt", "*.toml"), "tamasfe/taplo:0.9"),),
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
        "verdict, not a lead. Every other target is advisory and exits 0 even with "
        "findings, because each yields something to confirm: vulture infers "
        "reachability it cannot always see, bandit reports this project's "
        "deliberate subprocess design alongside anything real, and a duplication "
        "clone may be two things that merely look alike."
    ),
    targets=(
        Target(
            "deps",
            "Dependency vulnerability advisories (GATES).",
            (Cmd(("uv", "audit", "--locked", "--preview-features", "audit")),),
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
                    PACKAGE,
                    *BANDIT_EXCLUDES,
                    "-q",
                ),
            ),
            advisory=True,
        ),
        Target(
            "dead-code",
            "Vulture dead-code scan.",
            (uv_run("vulture"),),
            advisory=True,
        ),
        Target(
            "duplication",
            "Copy-paste clone detection over production code.",
            (Cmd(("npx", "--yes", "jscpd@4", PACKAGE, *JSCPD)),),
            advisory=True,
        ),
        Target(
            "docstrings",
            "Docstring coverage over the public surface.",
            (uv_run("interrogate", "-c", "pyproject.toml", PACKAGE),),
            advisory=True,
        ),
        Target(
            "complexity",
            "Cognitive complexity over the test tree.",
            (uv_run_env(UTF8, "complexipy", PACKAGE, "--failed"),),
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
                Echo("=== dead code ==="),
                Ref("dead-code"),
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

#: The service tier needs real local services and is excluded from the default
#: gate by ``addopts`` in pyproject.toml. Overriding ``addopts`` wholesale is
#: how a lane reaches it, so the override string is stated once here rather
#: than copied into every service-shaped target.
ADDOPTS_OVERRIDE = (
    "--override-ini",
    "addopts=--durations=10 --showlocals -ra --capture=sys",
)

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
            (uv_run("pytest", "-m", "not service"),),
        ),
        Target(
            "service",
            "Deterministic service tests against real local services.",
            (uv_run("pytest", *ADDOPTS_OVERRIDE, "-m", "service"),),
        ),
        Target(
            "all",
            "Every collected test, without the default marker exclusion.",
            (uv_run("pytest", *ADDOPTS_OVERRIDE),),
        ),
        Target(
            "coverage",
            "The unit gate with a terminal coverage report.",
            (
                uv_run(
                    "pytest",
                    "-m",
                    "not service",
                    f"--cov={PACKAGE}",
                    "--cov-report=term-missing",
                ),
            ),
        ),
        Target(
            "harness",
            "The development harness's own guards.",
            (uv_run("pytest", "dev"),),
        ),
    ),
)


# ---------------------------------------------------------------------------
#  health - MEASURES, always exits 0
# ---------------------------------------------------------------------------

HEALTH = Verb(
    name="health",
    summary="Rank the worst offenders across every code-health dimension.",
    note=(
        "MEASUREMENT ONLY - always exits 0. Composes the same tools the gates "
        "run, so the report and the gate cannot disagree about a number."
    ),
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
    summary="Run the full local gate.",
    targets=(
        Target(
            "all",
            "Lint, dependency audit, vault checks, and the unit gate.",
            (
                Cmd(
                    (
                        "uv",
                        "sync",
                        "--locked",
                        "--no-default-groups",
                        "--extra",
                        "server",
                        "--group",
                        "all",
                    )
                ),
                _verb("lint", "all"),
                _verb("audit", "deps"),
                uv_run("vaultspec-core", "vault", "check", "all"),
                _verb("test", "unit"),
            ),
        ),
    ),
)


VERBS: tuple[Verb, ...] = (DEPS, LINT, FIX, AUDIT, TEST, HEALTH, CI)

#: The target each verb selects when invoked with no argument.
DEFAULTS: dict[str, str] = {
    "deps": "check",
    "lint": "all",
    "fix": "all",
    "audit": "all",
    "test": "unit",
    "health": "report",
    "ci": "all",
}


def find_verb(name: str) -> Verb | None:
    """Return the named verb, or ``None`` when it is not defined."""
    return next((v for v in VERBS if v.name == name), None)
