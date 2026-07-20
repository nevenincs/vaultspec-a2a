---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-20'
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

### s11-feature-label-contract | medium | Feature form requested a label absent from the repository

Type: repository health configuration. The feature form requested the
`enhancement` label while the live repository exposes `feature`. Status:
resolved by aligning the form with the existing `feature` label.

### s11-security-question-route | medium | Security guidance pointed to a disabled public issue path

Type: support routing. The security policy sent non-sensitive questions to
GitHub Issues while blank issues were disabled and no question form existed.
Status: resolved by enabling blank issues while retaining the private
vulnerability-reporting contact for sensitive reports.

### s11-provisioning-vocabulary | medium | Glossary collapsed workspace and external-resource provisioning

Type: architecture terminology. Provisioning was defined only as model or
Qdrant acquisition even though the accepted harness contract also provisions a
workspace through Core installation, synchronization, and verification.
Status: resolved by defining both workspace and external RAG provisioning.

### s11-agent-harness-vocabulary | medium | Glossary omitted required harness surfaces

Type: architecture terminology. The agent-harness definition omitted personas
and command-line or MCP tools required by the accepted harness decision.
Status: resolved by restoring those surfaces and stating the harness purpose.

### s11-preset-command-semantics | low | Operator reference overstated the presets command

Type: command accuracy. The operator reference described generic preset
operations, while the live product command only lists available team presets.
Status: resolved by documenting the exact listing behavior.

### s11-editorial-native-command-boundary | high | Wrapper and native CLI inventories were ambiguous

Type: editorial architecture. The operator guide blurred the complete native
product command inventory, the intentionally shorter Just wrapper set, and the
separate MCP entry point. Status: resolved by naming the native inventory and
distinguishing wrapper and MCP routes explicitly.

### s11-editorial-owner-taxonomy | high | Issue forms used a taxonomy inconsistent with architecture ownership

Type: editorial architecture. Bug and feature forms classified affected
surfaces differently from the accepted single-owner model. Status: resolved by
using the same product CLI, gateway, worker, Just, registry, Compose, Core/RAG,
and documentation areas in both forms.

### s11-editorial-harness-definition | high | Harness inventory buried the term's purpose

Type: editorial comprehension. The glossary led with a long inventory instead
of explaining what the agent harness accomplishes. Status: resolved by stating
the repository-workflow purpose before its component inventory.

### s11-editorial-clarity-cluster | medium | Eight passages obscured standalone technical meaning

Type: editorial clarity. Review found a vague shared sync/reconciliation
definition, an overcompressed README ownership paragraph, ambiguous engine and
authoring-client phrasing, duplicated development diagnostics, unexpanded
acronyms in standalone documents and forms, an unnumbered Compose sequence with
an unclear antecedent, inconsistent `split-brain` jargon, and dense wording for
the warning-fatal Sphinx contract. Status: resolved across the glossary,
README, development and operations guides, architecture page, and issue forms.

### s11-editorial-consistency-cluster | low | Four style inconsistencies remained after technical review

Type: editorial consistency. Review found inconsistent `not run` terminology,
an unnatural pull-request checklist phrase, terse punctuated Ty and Deptry table
items, and excessive uncontracted negative constructions. Status: resolved by
normalizing terminology, checklist language, table phrasing, and contractions.

### s11-private-vulnerability-reporting | low | External confidential-reporting route required verification

Type: external repository configuration. The security policy and issue forms
route sensitive reports to GitHub private vulnerability reporting. Status:
verified enabled through the repository API on 2026-07-19; public issue forms
also warn against submitting credentials or vulnerability details.

### s12-core-adoption-overwrite-risk | critical | Forced adoption wrapper could overwrite concurrent edits

Type: data-integrity and concurrency safety. The first clean-clone workaround
used a byte-restoring wrapper around a forced Core install. Formal review found
that it could restore stale bytes over edits made during the command and that
the force flag was wider than the intended adoption boundary. Status: resolved.
The wrapper was deleted. Forced adoption now runs only in a disposable clone,
where its tracked projection must match the live repository byte-for-byte. The
live workspace receives only absent runtime seeds through exclusive creation,
then uses Core's non-destructive sync. An untracked `.mcp.json` makes first
adoption fail before Core can touch the live workspace. Upstream ownership is
accepted by open issue `nevenincs/vaultspec-core#229`.

### s12-rag-setup-regression | high | Public setup stopped enrolling the RAG workspace

Type: architectural contract. An intermediate correction synchronized and
reported RAG but no longer ran the installer, contradicting the accepted setup
contract and published documentation. Status: resolved. Setup and install run
the locked dependency-mode installer without MCP, external provisioning, or
Torch configuration. Two successive fresh-clone runs converge without tracked
drift or hook mutation.

### s12-ambient-core-fallback | high | Workspace provisioning could escape the project lock

Type: dependency authority. Product provisioning retained console-script and
unversioned `uvx` fallbacks when Core was absent from the active environment.
Status: resolved. Provisioning now invokes Core only as a module from the active
environment and fails with an actionable locked-tooling instruction otherwise.
Real subprocess tests exercise both the installed authority and the refusal.

### s12-rag-version-authority | high | RAG upgrade and ACP acquisition could diverge

Type: dependency authority. The upgrade recipe could refresh RAG independently
of the exact runtime requirement embedded in ACP MCP composition. Status:
resolved. Setup, install, and upgrade compare the installed distribution against
the exact acquisition requirement before enrollment. Upgrade asks uv to resolve
that source-pinned requirement instead of ambient newest, so a version change
must update the ACP authority in the same reviewed change. The first fresh-clone
run found a Windows quoting defect in this check; the shell-stable correction
then passed with RAG 0.3.2, including the upgrade path.

### s12-build-reproducibility | high | Package build and CI environment were incomplete or floating

Type: build integrity. The first clean-clone gate lacked server and
documentation dependencies required by Ty and package validation, while the
isolated build backend was unconstrained. Status: resolved. CI synchronizes the
locked server plus composed documentation/tooling environment, documentation
commands use the lock, and package construction applies
`build-constraints.txt` with Hatchling 1.31.0. The source distribution and wheel
build successfully from the fresh clone.

### s12-lifecycle-identifiers-in-code | high | Tests and docstrings embedded transient plan language

Type: maintainability. Review found Step identifiers and architecture-process
phrases in production-facing documentation and tests. Status: resolved. The
comments now describe enduring behavior and contracts without lifecycle IDs.

### s12-ci-documentation-drift | medium | Published dependency profile did not match the executable gate

Type: documentation accuracy. An intermediate guide described tooling alone as
the hosted profile and then overstated the corrected profile as including RAG
and Torch. Status: resolved through the documentation pipeline. The README and
development guide now name the exact server, documentation, and tooling
selection and keep RAG and Torch optional.

### s12-workflow-lint-authority | medium | Workflow lint is not project-pinned

Type: validation reproducibility. The available `actionlint-py` 1.7.7.24 label
inventory rejected a concurrently introduced `macos-15-intel` runner, while
actionlint 1.7.12 accepts the current workflow corpus. Status: resolved. The
tooling group pins `actionlint-py` 1.7.12.24, the canonical code gate and Prek
hook invoke it, and an isolated locked run validates every hosted workflow with
actionlint 1.7.12.

### s12-core-prek-regression-coverage | medium | Cross-tool convergence has no committed acceptance test

Type: test coverage. Real clean-clone evidence proves two Core and RAG setup
runs preserve `prek.toml`, avoid the legacy hook file, and leave the tracked
tree unchanged. Existing hook tests do not automate that installed-tool
boundary or the new enrollment helper's dirty-file rejection, projection-drift
rejection, and exclusive-seed conflict paths. Status: resolved. Four committed
real-filesystem enrollment tests cover those rejection paths, build a genuine
Core-managed Git repository, clone it without ignored runtime state, execute
adoption twice as a subprocess, and assert manifest, Prek-byte, and tracked-tree
convergence.

### s12-unix-build-clean-portability | medium | Artifact cleanup remains PowerShell-only

Type: platform portability. Doctor has native Windows and Unix variants, but
the public build-clean recipe embedded a PowerShell implementation. Status:
resolved. The recipe now calls one cross-platform Python implementation with a
resolved repository-containment guard. Real-filesystem tests prove it removes
only `dist`, `docs/_build`, `*.egg-info`, and `__pycache__` directories and
refuses a target outside the repository.

### s12-runtime-ignore-ownership | medium | RAG runtime surfaces remain outside Core's managed policy

Type: generated-state ownership. Fresh setup exposes `.vaultspec/runtime/` and
`.qdrant-initialized`, while Core owns the framework ignore block and does not
currently list them. Status: open and assigned first to the Core/RAG integration
queue. RAG issue `nevenincs/vaultspec-rag#236` now owns the runtime-artifact
contract. Core issue `nevenincs/vaultspec-core#230` owns its provider-native lock
sentinels. No repository fallback duplicates either framework's single-writer
boundary.

### s12-unit-contract-failures | high | Full unit selection exposed product-contract failures

Type: product correctness and test drift. The first clean-clone unit gate
selected 2,141 tests; 2,126 passed and 15 failed across gateway preset
truthfulness, the real synchronized rule corpus, redispatch failure-ladder
deduplication, MCP preset availability, ACP capsule resolution, Codex
config-home behavior, thread error exports, and thread feedback state. Status:
resolved after the owning changes were committed. At exact commit `844cd0ca`,
the canonical `just ci` selected 2,565 tests from 2,706 collected tests: 2,564
passed, one existing POSIX-permission test was inapplicable and skipped on
Windows, and 141 service tests were deliberately deselected by the canonical
unit contract. The run used Python 3.13.11, Node.js 24.18.0, and npm 11.16.0 in
an isolated workspace; every static gate passed and the clone remained clean.

### s12-node-runtime-provisioning | high | Canonical CI omitted the locked ACP runtime

Type: dependency authority and clone reproducibility. The first terminal gate
did not restore `package-lock.json`, so MCP tests could not start the Node-based
ACP runtime from a clean clone. Status: resolved. The repository now pins and
verifies Node.js 24.18.0 with a platform-neutral version script, declares npm
11.16.0 through the package-manager contract, runs `npm ci` from dependency
setup and canonical CI, and provisions the same Node line in GitHub Actions.
The authoritative run used npm 11.16.0, restored 104 packages, and `npm audit`
reported zero vulnerabilities.

### s12-mcp-gateway-auth | high | MCP transport omitted the gateway bearer credential

Type: security-contract integration. Gateway authentication was enforced, but
the MCP HTTP client did not resolve or send the operator credential, producing
authorization failures in the real composition path. Status: resolved through
one shared production credential resolver used by the CLI and MCP transport.
Real authenticated application tests now exercise the bearer path directly.

### s12-desktop-credential-origin | high | Initial resolver could disclose a desktop credential to another loopback port

Type: credential confidentiality. Formal review found that an armed desktop
attach credential could be sent to an arbitrary loopback origin because the
first shared resolver trusted only the host class. Status: resolved before
terminal acceptance. Desktop attachment now requires fresh versioned discovery,
the current protocol, a live matching process identity, the exact HTTP host and
port, and the exact resolved credential reference. Real filesystem and process
tests prove matching-origin use and refusal for a different loopback port or a
remote host.

### s12-concurrent-format-drift | medium | Clean-clone validation found formatter drift in integrated product files

Type: integration conformance. Six product and test files committed by adjacent
work exposed Ruff formatting drift only after the hardening range was exercised
from a clean clone. Status: resolved with formatter-only commits after focused
tests and read-only review; the final canonical format check covered 519 files.
Uncommitted concurrent work in the shared tree was not staged or overwritten.

### s12-provider-reason-assertion | low | Provider test required an obsolete exact wrapper string

Type: test-contract drift. A live gateway test asserted exact membership for a
safe provider error even though the production boundary can add stable context
around that reason. Status: resolved by asserting the preserved safe reason
without duplicating the wrapper's presentation contract.

### s12-legacy-precommit-lock | low | Existing checkouts can expose an obsolete zero-byte lock

Type: migration residue. Replacing `.pre-commit-config.yaml` with `prek.toml`
correctly removed the legacy lock entry from Core's managed ignore block, so an
old checkout can expose `.pre-commit-config.yaml.lock`. Status: open for local
cleanup guidance. The observed file is zero bytes and runtime-only; it must not
be reintroduced into a competing repository-owned ignore policy. Core issue
`nevenincs/vaultspec-core#230` owns the migration cleanup and managed-ignore fix.

### s12-core-precommit-warning | low | Repeated Core setup reports an unknown PrecommitSignal member

Type: upstream diagnostics. A second Core setup can emit
`Unknown PrecommitSignal member: unrefreshable` while returning success and
converging byte-for-byte. Status: open in
`nevenincs/vaultspec-core#231`; retain as a warning until Core either recognizes
or removes the signal.

### s12-linux-docker-engine | low | Live Unix Docker acceptance was environmentally blocked

Type: acceptance environment. Docker CLI and Compose discovery pass, as do dev,
integration, infrastructure, production, and database configuration resolution.
The available Docker Desktop engine returned HTTP 500 for the Linux-engine
request, preventing a live Unix container run. Status: open operational
evidence, not a repository defect. Repeat on a healthy Unix Docker host.

### runtime-fallback-ownership-drift | high | Initial repository fallback bypassed Core's exclusive ignore ownership

Type: architectural ownership. A follow-up initially added
`.vaultspec/runtime/` to the repository-owned runtime section. The rule was
narrow and effective, but it sat outside Core's marker-bounded block and
contradicted the accepted single-writer constraint plus the open S12 finding.
Status: resolved before commit by removing the tracked fallback, retaining RAG
issue `nevenincs/vaultspec-rag#236` as the shared-policy owner, and adding the
exact path only to this worktree's local `.git/info/exclude`. Refreshed local
and origin refs contain zero runtime-path objects, so no history rewrite or
force-push is warranted. The local exclusion is immediate containment, not a
published replacement for the upstream contract.

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
canonical hosted gate. Exercise the organization-owned runner path and decide
whether repository policy should require SHA-pinned Actions globally.

Preserve S11's platform-specific doctor variants as one public command contract.
Exercise the Unix branch and build-clean parity on a healthy Unix Docker host
before declaring the full portability matrix complete.

Preserve S11's separated onboarding, contributor, operator, architecture,
glossary, security, and contribution surfaces. Keep issue-form taxonomies and
labels aligned with live repository configuration, and repeat the private
reporting API check during security-policy changes.

Preserve the accepted Core/Prek boundary: forced Core adoption remains isolated
to a disposable clone, its tracked projection must match byte-for-byte, runtime
seeds use exclusive creation, and `prek.toml` remains repository-owned. Preserve
the RAG authority check whenever either the project constraint or the ACP
runtime requirement changes.

Preserve the exact Node.js and npm authorities, locked `npm ci` restoration,
desktop credential origin binding, committed Core adoption and build-clean
real-filesystem tests, and exact workflow-lint pin as repository-tooling
regression gates. Repeat canonical `just ci` from a clean commit whenever those
contracts change. Keep the single Windows skip limited to its existing
POSIX-permission boundary; do not suppress any portable behavior.
