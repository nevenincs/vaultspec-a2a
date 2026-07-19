---
tags:
  - '#audit'
  - '#module-docstrings'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-03-31-docs-vault-authority-retention-adr]]"
  - "[[2026-02-26-approved-module-hierarchy-adr]]"
---

# `module-docstrings` audit: `major module documentation health`

## Scope

Formal review of the major-module documentation implementation: the Sphinx
configuration and static-docstring extension, the module reference and
navigation pages, the root and package documentation links, the documentation
dependency/build integration, and the changed package/module docstrings. The
review was grounded in the vault-authority, approved-module-hierarchy,
development-process-registry, and A2A-edge-conformance decisions and excluded
unrelated dirty-worktree changes.

Review disposition: **PASS**. Final re-review confirmed that all implementation
findings are resolved, the six real-behavior regression tests run in both the
local documentation build and CI, and the strict Sphinx build succeeds. No
critical, high, medium, or low implementation finding remains open. The
separate repository-health findings below remain queued as out-of-scope
follow-up work and do not change this bounded implementation disposition.

## Findings

### lifecycle-responsibility | MEDIUM | The lifecycle docstring excludes an exported thread-reconciliation responsibility

Open documentation-accuracy finding. `src/vaultspec_a2a/lifecycle/__init__.py:1-5`
defines the package as machine-global process management and explicitly says it
does not concern thread state, while `src/vaultspec_a2a/lifecycle/reconciliation.py:1-5`
computes restart reconciliation from thread snapshots and the package exports
that API at `src/vaultspec_a2a/lifecycle/__init__.py:43,82`. The major-module
description therefore hides and contradicts a real public responsibility.

### thread-dependency-direction | MEDIUM | The thread docstring claims a nonexistent persistence dependency

Open architecture-accuracy finding. `src/vaultspec_a2a/thread/__init__.py:11`
says the thread domain depends on persistence modules. Production imports under
`src/vaultspec_a2a/thread/` reference graph enums but do not import the database
package; the actual direction is the reverse, as documented and implemented at
`src/vaultspec_a2a/database/__init__.py:9-10,16-22`. This misstates a major
boundary that the documentation is intended to clarify.

### compile-team-graph-signature | MEDIUM | The Python reference hides a required keyword-only dependency

Open API-reference correctness finding. `docs/api/modules.rst:160` presents
`compile_team_graph(team_config, agent_configs, **options)`, but
`src/vaultspec_a2a/graph/compiler.py:328-344` requires the keyword-only
`provider_factory` argument. Symbol resolution and Sphinx cross-reference
validation cannot detect this hand-authored signature mismatch, so a reader
following the reference receives an immediate missing-argument error.

### static-docstring-path-boundary | LOW | The custom directive does not enforce its in-project source boundary

Open safety/hardening finding. `docs/_ext/module_docstrings.py:21-32` checks only
the first dot-separated component and then joins all remaining text as path
parts without identifier validation or a resolved-path containment check. A
rooted path argument retaining the `vaultspec_a2a` prefix can resolve to an
arbitrary accessible Python file outside `src/vaultspec_a2a`, contrary to the
helper contract at line 22. The build inputs are repository-controlled, which
limits severity, but the extension should enforce the boundary it declares and
cover rejection with a real-behavior test.

### resolved-technical-editorial-review | LOW | Earlier review corrections are closed and verified

Resolved review summary. Technical review corrected cold-import isolation,
CLI/workspace ownership, workspace consumers, IPC request construction,
telemetry trace injection, provider laziness rationale, and a utility consumer.
Editorial review expanded acronyms, normalized package and command terminology,
replaced abstract verbs and negative dependency descriptions, and tightened
instruction ordering and voice. Targeted Ruff check and format-check passed for
the changed Python modules; CLI help probes passed; a clean Sphinx 9.1 build
with nitpicky mode, warnings as errors, and keep-going passed; and `git diff
--check` passed. These resolved items are not queued for further work.

### control-all-contract | HIGH | Out-of-scope control exports name unbound attributes

Open out-of-scope API-contract finding. `src/vaultspec_a2a/control/__init__.py:21-39`
lists child-module names in `__all__` without binding those attributes, so star
import and introspection consumers encounter a broken public contract. The new
reference acknowledges the defect at `docs/api/modules.rst:51-52`; documenting
it does not repair it.

### root-readme-drift | HIGH | Out-of-scope setup, CLI, and Just commands are stale

Open out-of-scope user-documentation finding. The root quickstart and command
reference still prescribe stale setup/service commands and the removed
`vaultspec team` surface at `README.md:43-77,96-244`. These instructions conflict
with the implemented `vaultspec-a2a` surface described by `docs/operations.rst:4-20`
and can prevent a new user from starting the current application.

### service-docker-guide-drift | HIGH | Out-of-scope service documentation describes removed UI and runtime paths

Open out-of-scope user-documentation finding. `service/README.md:10,19-26` and
`service/docker/README.md:25-55,69-126` describe a frontend/Vite service,
frontend assets, obsolete compose usage, and mutable `.vault/runtime` output.
Those claims conflict with the accepted headless edge and machine-global
runtime-path decisions and can lead operators to deploy or inspect the wrong
topology.

### api-facade-test-tautology | MEDIUM | Out-of-scope facade test compares two aliases imported from the same module

Open out-of-scope test-adequacy finding. `src/vaultspec_a2a/api/tests/test_websocket.py:19-20`
imports both names directly from `api.websocket`, then
`src/vaultspec_a2a/api/tests/test_websocket.py:515-517` asserts they are the same
while claiming to verify the `vaultspec_a2a.api` package facade. The test cannot
detect a missing or incorrect facade export and violates the repository rule
against tautological tests.

### lifecycle-responsibility-resolution | MEDIUM | RESOLVED with both lifecycle responsibilities documented

Resolution evidence. `src/vaultspec_a2a/lifecycle/__init__.py:1-17` now names
machine-global development-process management and the separately exported pure
gateway-restart reconciliation of non-terminal thread state. The
Sphinx module cross-reference to `vaultspec_a2a.lifecycle.reconciliation`
resolves in the strict build, and the implementation remains registered through the
package exports at `src/vaultspec_a2a/lifecycle/__init__.py:46,85`.

### thread-dependency-direction-resolution | MEDIUM | RESOLVED with the actual import direction stated

Resolution evidence. `src/vaultspec_a2a/thread/__init__.py:3-12` now identifies
graph enums as the package's cross-package runtime dependency and explicitly
states that control and database consume the thread API without being imported
by it. This matches the production import graph reviewed under
`src/vaultspec_a2a/thread/`.

### compile-team-graph-signature-resolution | MEDIUM | RESOLVED with the required keyword-only dependency exposed

Resolution evidence. `docs/api/modules.rst:160` now declares
`compile_team_graph(team_config, agent_configs, *, provider_factory, **options)`,
matching the required keyword-only parameter in
`src/vaultspec_a2a/graph/compiler.py:328-344`. The declaration builds cleanly
under Sphinx nitpicky mode with warnings treated as errors.

### static-docstring-path-boundary-resolution | LOW | RESOLVED with identifier and containment validation

Resolution evidence. `docs/_ext/module_docstrings.py:17-38` now establishes a
resolved package root, rejects every non-identifier dotted segment, resolves
each candidate, and accepts it only when contained by the package root. The six
real-behavior cases in `docs/tests/test_module_docstrings.py:8-33` pass without
fakes, mocks, stubs, patches, or monkeypatches, covering a real package, foreign
package, empty segment, forward- and backslash traversal forms, and a missing
module.

### docs-extension-test-collection | MEDIUM | New regression tests are not part of routine pytest or CI collection

Open test-integration finding. `pyproject.toml:139` limits pytest `testpaths` to
`src/vaultspec_a2a`, while the new suite lives at
`docs/tests/test_module_docstrings.py`. The unit and all-test recipes invoke
bare pytest at `Justfile:285-294`, and CI does the same at
`.github/workflows/test.yml:16`; none supplies the docs test path. The six tests
pass when explicitly targeted with both dev and docs dependency groups, but the
routine regression gate will not collect them, so the hardened boundary can
regress without failing CI.

### docs-extension-test-collection-resolution | MEDIUM | RESOLVED with local and CI documentation gates

Resolution evidence. `Justfile:313-315` now runs the six real-behavior tests in
an isolated environment carrying both docs and dev dependency groups before
the strict Sphinx build. `.github/workflows/test.yml:12,17-18` syncs all groups,
runs the docs test path explicitly after the normal suite, and runs Sphinx with
nitpicky mode, warnings as errors, and keep-going. Final local execution of
`just dev build docs` passed all six tests and the Sphinx 9.1 build; `git diff
--check` also passed. The regression suite is therefore part of both the
documented local build path and the repository CI gate.

## Recommendations

1. Revise the lifecycle docstring to cover both development-process management
   and the exported thread-reconciliation API, without conflating the two.
2. Remove the claimed thread-to-persistence dependency and state the actual
   database-to-thread direction.
3. Publish the real `compile_team_graph` keyword-only signature, including the
   required `provider_factory`, or omit a hand-authored signature in favor of a
   mechanism that derives it from source without importing runtime modules.
4. Restrict `automoduledoc` arguments to valid in-package dotted identifiers,
   verify the resolved source remains under the package root, and add direct
   real-behavior tests for accepted and rejected paths.
5. Schedule separate health passes for the control export contract, the root
   README, the service/Docker guides, and the tautological API facade test. The
   documentation passes must follow the documentation pipeline; the facade test
   replacement must import the package facade and compare it with the direct
   implementation symbol.
6. Add `docs/tests` to routine pytest collection, or invoke it explicitly from
   the documentation/CI gate with both dev and docs dependencies, and verify the
   standard command reports all six cases rather than relying on a one-off
   targeted run.
