---
tags:
  - '#research'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-03-19-control-layer-cli-justfile-separation-adr]]"
  - "[[2026-03-20-service-lifecycle-architecture-adr]]"
  - "[[2026-07-15-dev-process-registry-adr]]"
  - "[[2026-03-31-universal-rule-propagation-adr]]"
  - "[[2026-03-31-docs-vault-authority-retention-adr]]"
---

# `repository-tooling-hardening` research: `Justfile, CI, GitHub, and Vaultspec rule reconciliation`

The repository needs one reproducible developer and CI control surface without
allowing the `Justfile`, provider projections, or hosted workflows to become
independent owners of process lifecycle and governance. The evidence favors a
native `just` module hierarchy that delegates named-process lifecycle to the
accepted process registry and full-stack lifecycle to Compose, backed by one
non-mutating validation contract. The governing ADR must settle that module
interface, reconcile the March foreground-only service decision with the July
process-registry decision, and decide which canonical Vaultspec sources are
tracked in Git.

## Findings

### The current service recipes bypass the repository's newer lifecycle owner

`dev service start` launches gateway and worker processes directly in the
foreground, while `dev service stop` force-kills Python processes selected by a
command-line substring or every process holding a port. That bypasses the
accepted named-process registry and can terminate unrelated work
(`Justfile:105`, `Justfile:129`,
`.vault/adr/2026-07-15-dev-process-registry-adr.md:38`). The default `all`
branch calls the first foreground service before the second, so it does not
provide a usable concurrent stack (`Justfile:91`).

The registry already exposes allocate, attach, kill, list, reap, rebuild,
rerun, resume, and up through the installed CLI. Compose already owns the
integration and PostgreSQL stacks. A thin command map can therefore improve
discoverability without reproducing lifecycle logic. The older foreground-only
ADR remains accepted and conflicts with that newer ownership model
(`.vault/adr/2026-03-20-service-lifecycle-architecture-adr.md:42`).

### Native `just` modules fit the accepted command-namespace boundary

The accepted control-layer ADR requires a structured, hierarchical `just`
namespace while reserving product behavior for `vaultspec-a2a`
(`.vault/adr/2026-03-19-control-layer-cli-justfile-separation-adr.md:35`). The
installed `just@1.46.0` supports stable modules and nested subcommands, allowing
small recipe files such as `dev/service.just`, `dev/test.just`, and
`dev/code.just` without dynamic string dispatch. The official module contract
is documented at https://just.systems/man/en/modules.html.

Keeping the current monolithic dispatcher would preserve hidden branches,
weak completion, and hand-maintained help. A flat file of every recipe would
improve visibility but retain a single large ownership surface. Native modules
best match the already accepted namespace shape, subject to an ADR deciding the
public command contract.

### Local, hook, and hosted validation currently describe three different contracts

`just ci` runs Ruff lint, Ty, and the default Pytest selection, but omits Ruff
format, dependency analysis, Vaultspec validation, workflow validation, and
service tests (`Justfile:149`). The July 19 local audit found Ruff lint clean,
8 files failing Ruff format, 5 Ty diagnostics, and 207 Deptry findings. Deptry
is installed but not configured as a usable gate (`pyproject.toml:70`). The
default Pytest command did not finish within 244 seconds, so its health is not
established by this pass.

Recipe names also overstate coverage: `dev test unit` and `dev test all` both
inherit the global `-m not service` selection, while collection showed 1,955
default tests, 1,171 `unit` tests, and 80 `service` tests excluded by default
(`pyproject.toml:196`, `Justfile:224`). Hosted `Tests` runs on `main` failed in
the last three observed runs, most recently on July 17 because Ruff format
reported four files. `Migration Check` passed separately.

### The hook pipeline mutates governance state during validation

The pre-commit configuration runs `vaultspec-core spec sync --execute` and
`vaultspec-core vault check all --fix`, so a commit-time check can rewrite
tracked or ignored governance material (`.pre-commit-config.yaml:43`). It also
installs Vaultspec Core without a version constraint
(`.pre-commit-config.yaml:4`). A prior execution record reports 159 generated
documentation files rewritten by this pattern
(`.vault/exec/2026-03-31-universal-rule-and-skill-propagation-exec.md:42`).
Validation should be read-only; explicit maintenance commands should own
regeneration and repair.

### Provider projections are current while their canonical content is stale

`vaultspec-core spec rules status` and sync preview report the generated
provider projections as current, so transport is working. The canonical custom
rules still name obsolete skills and nonexistent paths, duplicate built-in
persona contracts, and encode an older workflow taxonomy
(`.vaultspec/rules/01-core.md:14`, `.vaultspec/rules/SKILL.md:26`,
`.vaultspec/rules/vaultspec-writer.md:8`). Reconciliation must use the owning
`vaultspec-core spec rules` verbs and regenerate projections; direct edits to
`.codex`, `.claude`, or `.gemini` would be overwritten.

The compact custom rule set can retain repository-specific constraints in
`01-core`, `02-operations`, `03-vaultspec`, and `90-custom`, including the
rolling implementation-review-queue mandate. Obsolete duplicated rule files
are candidates for removal only after the ADR defines the retained contract.

### Governance persistence is not reproducible from a fresh clone

`.gitignore` excludes `.vaultspec/`, provider directories, and `AGENTS.md`
(`.gitignore:168`). The only tracked provider-facing governance file observed
in this pass is `.pre-commit-config.yaml`. A fresh clone therefore cannot
reconstruct the local canonical rule set or the audit mandate from the Git
tree. The ADR must decide whether `.vaultspec/` canonical inputs are tracked
and generated provider projections remain ignored, or whether another tracked
bootstrap source becomes authoritative.

### GitHub controls and project hygiene do not yet form a hardened boundary

The repository has 14 open issues across three old milestones, one open pull
request from April, no issue forms, no `CODEOWNERS`, no security policy, no
license file, and no Dependabot configuration. The community profile API
reported 14 percent completeness. Project-board inspection was blocked because
the active token lacks `read:project`; branch protection and rulesets were
unavailable through the private repository's current plan.

Actions permit all marketplace actions and do not require full-SHA pinning.
Workflows use mutable action tags (`.github/workflows/tests.yml:32`). More
critically, issue events can dispatch an issue title and body plus a PAT to a
self-hosted runner without an actor or association authorization check
(`.github/workflows/bootstrap-branch.yml:1`). GitHub's secure-use guidance
recommends full commit SHA pinning and treating self-hosted runners as
potentially persistent compromise surfaces:
https://docs.github.com/en/actions/reference/security/secure-use.

### User-facing instructions no longer match the executable surface

The README advertises recipes including `just prod`, `just dev doctor`, and
service health/probe commands that the current `Justfile` does not implement
(`README.md:89`, `Justfile:19`). The installed product CLI instead exposes
doctor, presets, procs, run, serve, and workspace. The rewritten documentation
needs an onboarding-oriented README, a concise operating model and vocabulary,
and linked command/configuration references rather than a second hand-written
command implementation.

### Vaultspec provisioning is version-skewed and profile-incomplete

The project lock resolves `vaultspec-core@0.1.42` and
`vaultspec-rag@0.2.28`, while the machine-global tools inspected in this pass
are Core 0.1.48 and RAG 0.3.2 (`uv.lock:3242`, `uv.lock:3261`). RAG is an
optional project extra, so the current `uv sync --all-groups` bootstrap does
not install it (`pyproject.toml:39`, `Justfile:335`). Provisioning must name
base, server, RAG, and all profiles explicitly and execute both CLIs from the
project lock rather than whichever global version happens to be first on PATH.

Current Core already writes and reconciles a marker-bounded Git-ignore block
through `install` and `sync`. Its policy keeps authored `.vaultspec` content and
provider projections shareable while ignoring only runtime state
(`vaultspec_core/core/gitignore.py:22`). The repository's broad provider and
`.vaultspec` ignores sit outside that block, so Core correctly preserves them as
user-owned content (`.gitignore:29`). The migration is therefore a one-time
removal of obsolete repository entries followed by the existing Core sync verb;
recipes must not reproduce Core's block-rewrite logic. A dedicated upstream
Git-ignore subcommand could improve diagnostics later but is not required for
this repository's reconciliation.

### The decision boundary is repository tooling, not product behavior

The contemplated change may reorganize `just` recipes, validation commands,
hooks, workflows, canonical Vaultspec rules, and supporting documentation. It
must not move product behavior into recipes or alter gateway/worker semantics.
This pass did not evaluate production performance, protocol conformance,
deployment topology, or provider implementation correctness except where their
commands affect tooling ownership.

## Sources

- `Justfile:19`
- `Justfile:91`
- `Justfile:105`
- `Justfile:129`
- `Justfile:149`
- `Justfile:224`
- `Justfile:335`
- `README.md:89`
- `pyproject.toml:39`
- `pyproject.toml:70`
- `pyproject.toml:196`
- `.gitignore:168`
- `.pre-commit-config.yaml:4`
- `.pre-commit-config.yaml:43`
- `.github/workflows/bootstrap-branch.yml:1`
- `.github/workflows/tests.yml:32`
- `.vault/adr/2026-03-19-control-layer-cli-justfile-separation-adr.md:35`
- `.vault/adr/2026-03-20-service-lifecycle-architecture-adr.md:42`
- `.vault/adr/2026-07-15-dev-process-registry-adr.md:38`
- `.vault/exec/2026-03-31-universal-rule-and-skill-propagation-exec.md:42`
- `.vaultspec/rules/01-core.md:14`
- `.vaultspec/rules/SKILL.md:26`
- `.vaultspec/rules/vaultspec-writer.md:8`
- `vaultspec_core/core/gitignore.py:22`
- `uv.lock:3242`
- `uv.lock:3261`
- `just@1.46.0`
- https://just.systems/man/en/modules.html
- https://docs.github.com/en/actions/reference/security/secure-use
