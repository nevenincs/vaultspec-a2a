---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
related: []
---

# `repository-tooling-hardening` audit: `rolling implementation review`

## Scope

Review each implementation Step against the accepted ADR, implementation plan,
and provisioning reference. The rolling audit covers dependency authority,
command ownership, Windows portability, governance convergence, validation,
hosted security, documentation, and close-out behavior.

## Findings

S01 dependency-profile and lockfile review passed with no findings.

### rag-install-mode | medium | RAG recipe used an unsupported public install flag

The initial S02 recipe passed Core's `--mode dependency` spelling to
`vaultspec-rag install`, whose 0.3.2 public help does not expose that option.
The real dry-run would have failed. Status: resolved in S02 by removing the
flag and allowing RAG to detect the project dependency placement.

### windows-module-shell | medium | Standalone modules selected Git Bash on Windows

The first direct-module verification emitted an `/etc/bash.bashrc` error
because standalone Just modules inherited the default shell. Status: resolved
in S02 by declaring native no-profile PowerShell in every module and rerunning
the real previews without the Bash startup error.

### s03-format-conformance | low | Touched test modules initially needed formatter normalization

The first S03 format check reported both touched test modules as needing Ruff
normalization. Status: resolved in S03 by applying the configured formatter and
rerunning lint and format checks successfully.

### inherited-test-double-debt | medium | Existing MCP tests retain prohibited test shortcuts

The MCP test module predating S03 still imports `FakeListChatModel` and mutates
the shared MCP registry in two fail-closed tests. The new S03 coverage imports
production code directly and runs real subprocesses, so it does not add to this
debt. Status: open and queued for the plan's S09 code-health remediation rather
than widening the locked-runtime Step into unrelated test refactoring.

### runtime-lock-ignore-gap | medium | Core 0.1.48 leaves repository runtime and provider lock state trackable

Type: contract drift. Removing the obsolete broad framework ignores exposed
pre-existing `.vaultspec/runtime/` evidence plus `.agents/mcp_config.json.lock`
and `.codex/config.toml.lock`. Core 0.1.48 correctly owns its marker block and
ignores the canonical snapshots, manifest, ownership record, and vault cache,
but its current managed policy does not cover these three runtime surfaces.
Status: open and queued for S05/upstream reconciliation; S04 does not stage the
exposed runtime or lock files and does not add a competing framework policy.

### implicit-tooling-profile | high | Initial native recipes relied on ambient tooling packages

Type: dependency authority. The first S06 code and test modules used frozen
`uv run` commands without selecting the `tooling` group even though the project
declares no default groups. The shared environment masked the fresh-clone
failure. Status: resolved in S06 by adding explicit no-default-group tooling or
development profile selection and proving the packages in an isolated run.

### build-clean-venv-scope | high | Initial cleanup discovery could enter the project virtual environment

Type: destructive-path safety. The first S06 cleanup recipe recursively found
egg metadata from the repository root, which could include the project virtual
environment. Status: resolved in S06 before execution by limiting discovery to
explicit source, test, and documentation roots and retaining an absolute
repository-boundary check before every recursive removal.

### native-module-version-check | medium | Installed Just rejected the documented minimum-version setting

Type: compatibility drift. The initially researched setting was not accepted by
the installed Just 1.46 parser. Status: resolved in S06 by keeping an actionable
root requirement notice and adding a real PowerShell version comparison to the
doctor; Just 1.46.0 satisfies the stable-module minimum of 1.31.0.

### nested-help-option-order | low | Initial developer help passed the module outside the list option

Type: command usability. The first `just dev` run rejected the list command
because its module argument followed another option. Status: resolved in S06 by
binding `dev` directly to `--list`; root and nested help now execute and list all
submodules.

### hook-validation-mutation | medium | Current hook pipeline is not yet a read-only validator

Type: contract debt. S06 preserves hook install, removal, execution, and explicit
repair entry points but deliberately does not describe the current `prek`
pipeline as read-only because its configuration still contains mutating
Vaultspec hooks. Status: open and queued for S08, which owns hook validation and
repair separation.

### test-selection-name-drift | medium | The all-test recipe still inherits the non-service default marker

Type: test contract debt. S06 preserves the current Pytest selection while
making its recipe description honest; the project-level default still excludes
service tests, so `all` is not yet semantically complete. Status: open and
queued for S09 test-selection remediation.

### s05-runtime-staging-escape | high | Recursive shared staging included excluded runtime evidence

Type: process safety and repository hygiene. During S05, the shared index
contained `.vaultspec/runtime/` evidence and `.qdrant-initialized` even though
the Step explicitly excluded runtime, cache, and machine state. Status:
resolved before commit by unstaging only those paths, verifying provider lock
files remained untracked, and requiring a zero-match safety scan of the final
commit inventory. No runtime, lock, secret, cache, or Qdrant path was committed.

### s05-rule-format-conformance | low | Initial retained rule bodies needed Markdown normalization

Type: documentation quality. The first compact canonical bodies were valid but
failed the repository's `mdformat --check` gate. Status: resolved in S05 by
formatting in memory, writing the normalized bodies back through Core's owning
rule verb, regenerating every provider projection, and rerunning the check.

### core-runtime-ignore-ownership | medium | Core exposes no owning configuration for uncovered runtime locks

Type: upstream contract gap. S05 confirmed that Core 0.1.48 has no rule or
configuration verb that extends its managed Git-ignore policy for
`.vaultspec/runtime/`, `.agents/mcp_config.json.lock`, or
`.codex/config.toml.lock`. Status: open upstream; S05 leaves the paths untracked
and unstaged rather than adding a competing repository-owned framework rule.

### core-builtin-content-skew | medium | Locked Core reported nine canonical builtins older than its package

Type: version and generated-content drift. Core 0.1.48 initially reported that
nine canonical builtins, including `rules/vaultspec.builtin.md`, were older
than the installed package. Status: resolved in S05 through a previewed and
then applied project-locked `install all --upgrade`; the owning operation
updated four agents, the CLI reference, one built-in rule, one skill, and two
system sources. A second upgrade preview reported every framework asset
unchanged, while complete provider sync and rule status proved convergence.

### s05-install-mode-drift | medium | Workspace metadata recorded floating tool launch modes

Type: dependency placement and reproducibility. The provisioned workspace
metadata initially recorded both Core and RAG with `install_mode: tool`, which
contradicted the repository's project-locked development and runtime dependency
profiles. Status: resolved in S05 through the owning locked installers: Core
0.1.48 converged with `--mode dev`, and RAG 0.3.2 converged with
`--mode dependency --upgrade --no-mcp --no-provision --no-torch-config --yes`.
The RAG optional dependency profile already supplies its MCP extra, so
`--no-mcp` disables duplicate dependency acquisition without removing runtime
capability. The resulting metadata records `dev` for Core and `dependency` for
RAG without downloading models or Qdrant.

### s05-rag-base-dependency-regression | high | MCP acquisition duplicated RAG into base dependencies

Type: dependency-profile integrity. The first dependency-mode RAG enrollment
used `--mcp`, which invoked dependency acquisition and added an unbounded
`vaultspec-rag[mcp]>=0.3.2` base dependency beside the approved optional
`rag = ["vaultspec-rag[mcp]>=0.3.2,<0.4"]` profile. Status: resolved before
commit by removing only the newly added base entry, regenerating `uv.lock`, and
using `--no-mcp` for idempotent enrollment because the synchronized `rag` extra
already provides MCP. A real owning install preserved dependency-mode workspace
metadata and left both `pyproject.toml` and `uv.lock` byte-identical; locked RAG
0.3.2, the `mcp` import, and `server doctor` all resolved successfully.

### s05-rag-mode-help-correction | medium | Earlier audit evidence misclassified a supported RAG flag

Type: audit accuracy and CLI contract. The S02 audit stated that RAG 0.3.2 did
not expose `--mode`, but the actual project-locked 0.3.2 help used in S05
explicitly supports `--mode [tool|dependency|dev]`. Status: resolved in S05 by
retaining the historical finding, appending this correction, and updating the
RAG setup, install, dry-run, and upgrade recipes to declare dependency mode
explicitly while using `--no-mcp` to preserve the existing optional dependency
profile. Real owning installer previews and application replaced the prior
assumption.

### postgres-overlay-composition | high | Initial database stack treated an overlay as standalone Compose

Type: stack contract. The first S07 database recipe referenced the PostgreSQL
overlay alone, and real `docker compose config` rejected its gateway and worker
services because their image/build definitions live in the production base.
Status: resolved in S07 by composing the bounded production base and PostgreSQL
overlay together under an isolated project name; configuration then passed.

### engine-seat-conflation | medium | Initial engine helper forced serve and build repositories to match

Type: process contract. The first named engine recipe reused its serve repository
as `--build-repo`, narrowing a production CLI option that explicitly supports
different source and build trees. Status: resolved in S07 by requiring separate
serve, build, and workspace seats and passing each real option unchanged.

### registry-allocate-omission | low | Initial service module omitted one real registry verb

Type: command completeness. The first S07 surface exposed the requested lifecycle
verbs but omitted the production CLI's safe reservation verb. Status: resolved in
S07 by adding an `allocate ROLE` passthrough and validating it with a dry run.

### dead-process-registry-records | medium | Read-only registry listing found three dead records

Type: operational state. The real S07 `procs list` validation reported two dead
gateway records and one dead worker record. Status: open for an operator to review
and clear explicitly with the registry-owned reap recipe; S07 did not mutate or
delete machine-global process state during validation.

### s08-hook-authority-and-mutation | high | Hooks mixed floating tools with commit-time repair

Type: reproducibility and validation integrity. The original pipeline selected
Ruff, Ty, Core, and Lychee through ambient environments and ran Vaultspec repair
and annotation cleanup during validation. Status: resolved in S08 by selecting
the frozen project tooling profile for every Python and Core command, retaining
exact Node dependencies for Taplo and Markdownlint, and moving synchronization,
repair, and annotation cleanup to explicit Just recipes outside commit flow.

### s08-hook-shim-default-profile | medium | Installed hook did not reject default dependency groups

Type: dependency authority. The real installer shim selected the frozen `dev`
group but did not explicitly disable default groups, leaving its authority
dependent on project metadata. Status: resolved in S08 by adding
`--no-default-groups` to the production shim and updating the real linked-worktree
test; both installer scenarios pass.

### s08-ambient-link-check-coverage | medium | Removing floating Lychee also removes hook link coverage

Type: validation coverage. The existing Lychee hook executed whichever system
binary appeared first on `PATH`. The upstream auto-installing hook is also not
deterministic because it installs an unconstrained latest release. Status: open
and queued for S10/S11 link-contract work; S08 removes the ambient hook rather
than claiming reproducibility, while preserving exact Markdownlint validation.

### s08-spec-doctor-warning-contract | medium | Spec Doctor rejects intentional mixed provider state

Type: hook suitability. The locked `spec doctor` command exits one for the
repository's currently intentional mixed provider directories and tracked
annotations, so it cannot be an honest commit gate yet. Status: removed from the
normal hook pipeline and retained under explicit Vaultspec diagnosis. Provider
artifact validation remains an always-run, read-only hook.

### s08-full-pipeline-python-debt | high | All-files hooks expose concurrent lint, format, and type failures

Type: code-health debt. The complete read-only run found 19 Ruff diagnostics,
one file requiring Ruff formatting, and 29 Ty diagnostics in concurrent desktop
manifest work, including unresolved references and call-signature drift. Status:
open and queued for S09; S08 neither suppresses nor repairs these failures.

### s08-full-pipeline-markdown-debt | medium | Markdownlint reports existing rule and skill violations

Type: documentation quality. The complete pipeline reported bare URLs and
untyped fenced code blocks in existing agent rules, skills, and documentation
references. Status: open for S09/S11 remediation; the exact
`markdownlint-cli@0.44.0` hook remains active and read-only.

### s08-shared-worktree-hook-race | low | Concurrent edits produced a false hook-mutation report

Type: validation environment. Prek labeled Vault Doctor as modifying files while
other agents were editing the shared worktree. A direct locked Core run returned
success and identical Git diff hashes before and after execution. Status:
classified as shared-worktree concurrency evidence, not hook mutation.

### s09-test-selection-contract | medium | The all-test recipe inherited the default service exclusion

Type: test-contract drift. The repository's named `all` and collection recipes
still inherited Pytest's project-level `not service` marker, so their names did
not describe the tests they selected. Status: resolved by making unit, service,
and all-test selection explicit, adding matching collection recipes, and
proving every recipe through real collection and dry-run execution.

### s09-mcp-test-policy | medium | MCP tests used a fake model and mutated the production registry

Type: evidence integrity. The MCP composition tests used
`FakeListChatModel` and temporarily changed the production server registry to
exercise fail-closed behavior. Status: resolved by using real production model
objects for pass-through coverage and removing the production-global mutation
tests; the focused provider and hook suite passes with direct production
imports.

### s09-generated-markdown-ownership | medium | Markdownlint treated provider projections as authored sources

Type: validation ownership. The all-files hook linted generated provider rule,
skill, and agent projections even though Vaultspec Core owns their bytes and
the provider-artifact guard owns their convergence. Status: resolved with a
hook-local exclusion limited to generated provider subtrees. Root provider
instructions and all repository-authored Markdown remain linted, the
provider-artifact guard remains always-on, and the complete read-only hook
pipeline passes.

### managed-gitattributes-overrides-binary-policy | medium | Managed wildcard attributes followed explicit binary rules

Type: repository integrity. The generated `* text=auto eol=lf` rule appeared
after the repository's explicit binary rules, so Git reported text
auto-detection for PNG and ZIP examples. Status: resolved by ordering the
intact managed block before the repository-owned binary overrides. Explicit
binary attributes now win without editing generated content.

### test-command-documentation-drift | medium | README advertised stale test selection and a removed recipe

Type: documentation correctness. The developer reference described `test all`
as the default non-service selection and still advertised `test collect` after
the implementation split collection by unit, service, and complete scope.
Status: resolved by documenting the actual `all`, `collect-unit`,
`collect-service`, and `collect-all` recipes.

### s09-dependency-gate-drift | high | Deptry was absent from the canonical gate and misclassified first-party imports

Type: dependency integrity. The first full scan reported 221 issues: 212 were
the project package misclassified as transitive, while the remainder exposed a
missing direct PyYAML declaration, an unreferenced APScheduler dependency, and
unclassified dynamic, documentation, and test loaders. Status: resolved by
declaring `vaultspec_a2a` first-party, adding PyYAML directly, removing
APScheduler after a zero-reference search, classifying only verified loaders,
and adding locked Deptry execution to the canonical code gate. The refreshed
lock removed APScheduler and `tzlocal`; Deptry now reports zero issues.

### s09-residual-fake-and-stub-tests | high | Prohibited stand-ins remain outside the focused MCP cleanup

Type: evidence integrity. A syntax-targeted repository inventory found 10
non-prose `FakeChatModel` code references across
`src/vaultspec_a2a/graph/tests/conftest.py`,
`src/vaultspec_a2a/graph/tests/test_compiler.py`, and
`src/vaultspec_a2a/worker/tests/test_isolation_gate.py`. It also found two
named stub classes and two corresponding instantiations across the graph
conftest and `src/vaultspec_a2a/service_tests/test_receipt_role_rules.py`, plus
eight custom structural stand-in classes in
`src/vaultspec_a2a/streaming/tests/test_aggregator.py`. Status: open for
codebase-health steps S101 and S104. The same inventory found zero
`unittest.mock`, Mock-constructor, monkeypatch-fixture, or patch-call/import
uses; production `mock_chat_model` parser tests were not misclassified.

### s09-residual-skip-debt | high | Twenty-eight environment skips remain in seventeen test files

Type: evidence integrity. The inventory found 28 `pytest.skip` or
`pytest.mark.skipif` uses and zero `xfail` uses across
`src/vaultspec_a2a/api/tests/test_harness_gateway.py`,
`src/vaultspec_a2a/authoring/tests/test_live_engine.py`,
`src/vaultspec_a2a/authoring/tests/test_submitter_live.py`,
`src/vaultspec_a2a/context/tests/test_rules.py`,
`src/vaultspec_a2a/control/tests/test_verdict_subscriber_live.py`,
`src/vaultspec_a2a/graph/tests/nodes/test_feedback_grounding_live.py`,
`src/vaultspec_a2a/providers/tests/test_acp_authoring_bridge.py`,
`src/vaultspec_a2a/providers/tests/test_acp_migration_surface.py`,
`src/vaultspec_a2a/providers/tests/test_authoring_stdio_bridge.py`,
`src/vaultspec_a2a/providers/tests/test_codex_chat_model.py`,
`src/vaultspec_a2a/providers/tests/test_kimi_handshake_live.py`,
`src/vaultspec_a2a/providers/tests/test_zai_fidelity.py`,
`src/vaultspec_a2a/service_tests/conftest.py`,
`src/vaultspec_a2a/service_tests/test_pw7_acceptance.py`,
`src/vaultspec_a2a/service_tests/test_s20_solo_coder_bridge_live.py`,
`src/vaultspec_a2a/service_tests/test_tool_cores_floor_live.py`, and
`src/vaultspec_a2a/worker/tests/test_authoring_binding.py`. Status: open for
codebase-health step S102; S09 does not treat collection success as execution
evidence for these paths.

### s10-actionlint-runner-label-authority | low | Custom self-hosted label was undeclared to workflow linting

Type: hosted-validation configuration. Actionlint recognized `self-hosted` but
reported the repository's `dev-runner` label as unknown. Status: resolved by
declaring that exact label in the repository Actionlint configuration. The full
workflow lint now passes without suppressing runner-label validation.

### self-hosted-bootstrap-untrusted-issue-payload | high | Raw issue content crossed the persistent runner boundary beside a credential

Type: hosted security and architecture. The bootstrap workflow fetched an
issue's attacker-controlled title and body on the persistent self-hosted runner
and passed them to an opaque local script while a repository credential was
present. Status: resolved. Trusted manual dispatch and positive-integer checks
now precede a read-only issue-existence lookup with the repository token. The
script receives only the validated action, repository identity, numeric issue
ID, deterministic title, and empty body; the development PAT is reserved for
the local script rather than the lookup.

### s10-mutable-action-supply-chain | high | Hosted automation depended on mutable or invalid action references

Type: supply-chain integrity. Checkout, uv setup, Claude, and project automation
used floating major tags, while the project workflow referenced an unavailable
`add-to-project` v1 tag. Status: resolved. Every action now uses a full commit
resolved from its official upstream reference; project automation uses v2, and
hosted validation provisions uv 0.11.29 and Just 1.46.0 explicitly.

### s10-claude-secret-authorization | high | Secret-bearing Claude jobs lacked an explicit YAML trust boundary

Type: credential authorization. Mention and automatic review jobs could reach
the Claude OAuth secret without a visible trusted-author rule, and automatic
review loaded a floating remote plugin marketplace. Status: resolved. Both jobs
require OWNER, MEMBER, or COLLABORATOR association before the secret-bearing
action; automatic review uses the pinned action's direct prompt and no floating
plugin configuration.

### s10-hosted-contract-drift | medium | Hosted tests and migrations bypassed the canonical locked profiles

Type: validation reproducibility. The test workflow duplicated individual
checks under every dependency group, and migration validation used the legacy
development profile. Status: resolved. Hosted tests synchronize only locked
tooling, invoke canonical `just ci`, and run strict documentation separately;
migrations synchronize and execute the locked server/tooling profile.

### s10-workflow-guardrails | medium | Automation omitted bounded execution and least-privilege defaults

Type: hosted safety. Multiple workflows lacked explicit permissions,
concurrency, or timeouts, and project item output was interpolated directly in
a shell block. Status: resolved. Each job now has bounded execution and
event-specific concurrency, permissions are read-only or empty except for the
Claude OIDC requirement, and shell data crosses through quoted environment
variables.

### s10-repository-sha-policy | medium | Server-side Actions policy still permits mutable references

Type: defense in depth. The read-only repository settings audit reported that
SHA pinning is not required and all actions are allowed. Status: open for owner
review during S12. The checked-in workflows are immutable, but repository
policy does not yet prevent a future change from reintroducing floating action
references.

### s10-full-gate-shared-worktree-drift | medium | Unrelated formatter drift blocks a green canonical CI run

Type: acceptance evidence. The real `just ci` invocation reached Ruff and
reported that `test_component_contract.py` would be reformatted. Status: open
for the owner of that concurrent out-of-scope edit and terminal S12 acceptance;
S10 did not alter the file. Workflow lint, YAML parsing, immutable-pin checks,
and canonical command dry-runs pass.

### s10-self-hosted-live-evidence | low | Repository-scoped runner inventory cannot prove dispatch readiness

Type: operational evidence. The read-only repository runner query returned no
repository-scoped runner, although an organization runner may own the declared
labels. Status: open for S12 live acceptance. The workflow retains the existing
`self-hosted` and `dev-runner` labels without inventing an environment or runner
group.

### resident-port-reference-drift | medium | Canonical IDE and MCP guidance retained the retired 8000 and 8001 defaults

Type: documentation contract. The accepted resident-port amendment and runtime
surfaces use gateway 18000 and worker 18001, but the canonical setup reference
still prescribed the former defaults in configuration, health, conflict, and
orphan-cleanup examples. Status: resolved by updating every resident-port
example while preserving explicit custom-port examples.

### dev-process-registry-amendment-stamp | low | ADR amendment left stale modified metadata

Type: governance metadata. The dev-process-registry ADR gained a 2026-07-19
resident-port amendment while its `modified` field still named 2026-07-15.
Status: resolved by refreshing the modified date to the amendment date.

### s11-doctor-platform-drift | high | Toolchain diagnosis depended exclusively on PowerShell

Type: architectural portability. The public doctor recipes were implemented
only with PowerShell commands even though the native Just module contract is
portable and the documented setup supports Unix hosts. Status: resolved. The
same recipe names now select official `[windows]` and `[unix]` variants, retain
the Just 1.31 minimum and uv requirement, distinguish optional from required
Docker support, and provide platform-appropriate installation links. Native
Windows execution, formatting, listing, dry-runs, and static Unix branch
presence pass; Unix live execution remains S12 acceptance evidence.

## Recommendations

No open task remains for S01, S02, or the S03 implementation. Preserve the two
S02 corrections when the modules are imported by the root Justfile, retain the
S03 exact-version runtime contract during dependency upgrades, and retire the
inherited MCP test shortcuts in S09.

Keep the newly trackable canonical `.vaultspec` and provider projections in
S05 scope, while classifying the exposed runtime and lock surfaces separately.
Resolve whether Core should expand its managed policy before adding any exact
repository stopgap, so Core remains the single framework-ignore owner.

Preserve S06's explicit dependency groups and cleanup boundary. Complete named
service and stack ownership in S07, make hooks read-only in S08, and correct the
project-wide test selection in S09 before promoting those surfaces into the
terminal CI contract.

Keep the Core runtime-ignore gap upstream-owned and preserve the S05 final
commit inventory gate. Retain the converged Core 0.1.48 framework corpus and
repeat the owning upgrade preview before future framework version changes.

Preserve S07's registry-only host-process boundary and isolated Compose project
names. Review the three dead registry entries before invoking reap, and always
validate the production-plus-PostgreSQL overlay pair together.

Preserve S08's frozen dependency selection and separation between validation and
repair. Remediate the surfaced Python and Markdown debt in S09/S11, then restore
link checking only through a pinned or explicitly provisioned Lychee contract.

Preserve S09's explicit selector and dependency classifications. The
codebase-health plan must replace the inventoried fake, stub, structural
stand-in, and skip cases with direct production behavior or executable
environment boundaries before it certifies global test-policy compliance.

Preserve S10's manual self-hosted authorization, content-free bootstrap
boundary, immutable action references, trusted Claude associations, and
canonical hosted gate. During S12, rerun `just ci` after the concurrent
formatter drift is resolved, exercise the organization-owned runner path, and
decide whether repository policy should require SHA-pinned Actions globally.

Preserve S11's platform-specific doctor variants as one public command contract.
Exercise the Unix branch on a real Unix host during S12 before declaring the
clone-to-CI portability matrix complete.
