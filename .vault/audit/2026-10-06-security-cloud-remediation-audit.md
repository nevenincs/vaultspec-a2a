---
tags:
  - '#audit'
  - '#security-cloud-remediation'
date: '2026-10-06'
modified: '2026-10-06'
body_schema: 'body-v2'
body_hash: 'sha256:fac6bae82a16b1a7b1c91bbe23753cfa777f3ed04d04cbcb2ed6d1d813259b93'
related:
  - "[[2026-10-06-security-cloud-remediation-plan]]"
---

# `security-cloud-remediation` audit: `Cloud findings and remediation review`

## Scope

October 6 Cloud scan `wfr_a27d78305fddc82937095bc549f47029af3090ad05bb73de70a75f3f2881c9f6` on `21b6f92`; current implementation and fixes under the related plan. Discovery used Core search and an all-feature ADR listing; code semantic search was unavailable because its Qdrant service is not installed, so bounded source searches and direct named modules were used.

## Findings

### claude-oauth | high | Shared environment leaks Claude OAuth across lanes

Type: credential disclosure. Status: confirmed, S01 implementing. `workspace/environment.py:119` retains the token globally; real production scrubber reproduction with a synthetic token fails the absence assertion. Independent investigator confirms Codex, ACP, MCP and terminal consumers. Preserve selected Claude ambient subscription and configured OAuth channels while stripping the common base.

### terminal-authority | high | Unisolated ACP terminals retain host filesystem authority

Type: authorization boundary. Status: confirmed, S02 pending. `_acp_rpc_terminal_handlers.py:203` accepts interpreter scripts and checks cwd only. Existing namespace authority is propagated when present, but absent authority executes with ambient host permissions. `test_native_launch_context.py` already covers isolated private-state denial and project I/O on Linux. Closure requires refusing unisolated terminal creation and withholding its advertised capability. This narrows the prior default-development exception, leaving ordinary provider launch compatibility separate.

### state-links | medium | Linked paths redirect state and journal writes

Type: filesystem integrity. Status: reported, S03 pending. Cloud finding `csf_14852935f75969f4e3276aed` targets state_layout/config, database/session and authoring/_tool_calls. Validate current paths and use real redirected-file controls.

### permission-identity | medium | Permission request IDs and effects cross thread ownership

Type: authorization isolation. Status: reported, S04 pending. Cloud finding `csf_cd9725ff6e54f8b7f5ee6482` targets worker permission hashing, request repository and event application.

### desktop-alias | medium | Linked app-home ancestors defeat capsule separation

Type: filesystem integrity. Status: reported, S05 pending. Cloud finding `csf_cf837ce03e604ff0a702ce43` targets desktop/profile path validation before state changes.

### stderr-secrets | medium | ACP debug logs retain unredacted stderr

Type: credential disclosure. Status: reported, S06 pending. Cloud finding `csf_e367d57d99237808b5d2484b` targets `_acp_stderr.py` logging before redaction.

### native-vault-write | medium | Native Claude write tools bypass protected vault policy

Type: authorization bypass. Status: reported, S07 pending. Cloud finding `csf_13f1c19a0a823694fd1338b7` targets Claude tool policy and permission mediation.

### codex-refresh | medium | Child-controlled auth JSON replaces operator credentials

Type: credential integrity. Status: reported, S08 pending. Cloud finding `csf_85229fd808cc6d427cf6e175` targets `_codex_auth.py` refresh validation and publication.

### ambient-zai | high | Adjacent Z.ai credential survives the common environment

Type: credential disclosure. Status: discovered, deferred pending bounded investigation. Independent pre-patch review notes `ANTHROPIC_AUTH_TOKEN` is not scrubbed and existing tests assert pass-through. The Claude-specific fix does not close this sibling credential family. Owner: follow-up within the credential boundary; verify Z.ai explicit reinjection and compatibility before editing.

### claude-oauth-review | low | S01 candidate closes the reported credential path

Type: verification and review record. Status: resolved. Independent fresh read-only review found no concrete bypass or regression in the five-file OAuth patch. The original synthetic-token absence assertion failed before the fix; real-child tests now confirm absence for Codex, Kimi, Z.ai, MCP and terminal environments and preserve Claude ambient subscription/configured OAuth behavior. `uv run --no-sync python -m pytest src/vaultspec_a2a/workspace/tests/test_environment.py src/vaultspec_a2a/workspace/tests/test_workspace.py src/vaultspec_a2a/providers/tests/test_claude_auth_channel.py -q`: 51 passed. Ruff check, Ruff format --check and ty check on those tests plus environment.py and factory.py passed. Windows Python locked environment. Review verdict PASS for S01. Optional subscription catalog control would extend second-seam coverage; no demonstrated defect. Cloud state remains unchanged.

### claude-live-test-selection | low | Live setup fixtures relied on global OAuth inheritance

Type: test compatibility. Status: fixed in S01 follow-up. Final caller inspection found test_acp_catalog_live.py and test_acp_authoring_bridge.py constructing a raw common environment while assuming Claude OAuth survived. They now use the same explicit claude_auth_env selector as served Claude roots. Focused Ruff lint/format and ty passed; actual live catalog and authoring-bridge service tests passed (4 tests). No production scope expansion or new credential channel.

### terminal-review | low | S02 closes unisolated terminal creation without losing isolated operation

Type: verification and review record. Status: resolved. Independent fresh read-only review traced negotiation, dispatch, creation, shared spawn and Linux namespace acquisition and found no concrete bypass or production regression. Missing authority, cross-workspace authority and replaced filesystem identity refuse; namespace-controlled project writes still succeed while private-state reads fail with ENOENT. The real installed SDK verifies initialize withholds terminal and a direct terminal/create still refuses. Large-output isolated controls verify zero, small and oversized requested caps, including the production server clamp.

Windows focused terminal/security/native-refusal/output/ownership/lifecycle suite initially had 212 passes and one invalid-environment error-order regression. Restoring environment validation before isolation preserves the prior error. Focused security plus new refusal tests then passed 47/47; retained-output tests after final setup adjustment passed 19/19. Explicit SDK and containment service controls passed 2/2. Other original passing results remain applicable. Ruff lint/format and ty passed on all ten changed terminal Python files. A separate Linux environment created with uv sync --locked --python 3.13 --group tooling passed the actual namespace test with the capsule-builder static bubblewrap helper, including final stale-authority and large-output controls. An older Linux environment failed import before tests and was replaced with the locked environment; it supplies no proof. Review verdict PASS for S02; no target eligibility was changed.

### terminal-test-setup | low | Lifecycle controls must start below the newly refused admission boundary

Type: test compatibility. Status: fixed. Existing unisolated output/ownership/cleanup tests created terminals through terminal/create. Their setup now retains real processes using the production spawn and output-capture helpers; they continue exercising real handlers and cleanup without a test bypass of admission. Admission itself is exercised by explicit unisolated refusal, SDK negotiation/refusal and real isolated Linux controls. No mocks, skips or fallback execution added.

### medium-model-selection | low | Requested worker model is unavailable

Type: execution prerequisite. Status: pending user input. The user requested sol 5.1 at xhigh; that model is absent from the agent runtime. An asynchronous question offers gpt-5.6-sol, gpt-6.1-sol or gpt-6-sol at xhigh. No medium remediation worker has been launched under a substituted model. S03-S08 remain open; their source files are untouched.

### ambient-zai-resolution | high | Z.ai ambient credentials isolated to the selected lane

Type: credential disclosure. Status: fixed in S09, superseding the deferred ambient-zai entry. The shared scrubber now removes ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL, ZAI_AUTH_TOKEN, ZAI_API_KEY, ZAI_BASE_URL and ZAI_ANTHROPIC_BASE_URL case-insensitively. Existing Settings selection and explicit Z.ai factory overlay preserve selected credentials; absent or blank selected tokens cannot inherit ambient credentials. Real child controls cover Claude, Codex, Kimi, MCP and terminal bases. No provider eligibility was expanded.

### version-probe-credentials | high | Version subprocess bypassed the credential scrubber

Type: credential disclosure. Status: discovered and fixed in S09. Independent bounded investigation found binary_version.py supplied environment=None to both launch preparation paths. Both now receive the scrubbed environment. A real executable refuses ambient credential aliases, requires a safe inherited option and reports its version; the control passes on Windows and Linux. Native isolation retains deliberately selected provider auth without restoring removed aliases.

### zai-contract-drift | low | Tests and comments asserted global Z.ai inheritance

Type: test and documentation contract drift. Status: fixed in S09. Workspace tests now require absence and include all aliases; factory and ACP comments describe explicit selected-provider reinjection. MCP real probe controls include the six aliases and Claude OAuth.

### zai-review | low | S09 implementation review and verification

Type: verification and review record. Status: resolved. Fresh read-only candidate review found no concrete surviving bypass or regression across shared environment, selected Z.ai overlay, catalog, MCP, terminal, version cache and native launch paths. Supervisor verification supplies the checks deliberately not run by the reviewer: Windows combined environment/workspace/Z.ai/version/factory/Claude/settings tests yielded 131 passes and one unrelated baseline failure recorded below; focused Z.ai factory tests passed 6; real MCP security probes passed 3. Linux locked-environment Z.ai controls and isolated version-cache authority control passed 16. Ruff lint, format and ty passed on all seven changed Python files; git diff --check passed. Original pre-fix real-child controls failed, establishing the trigger. Review verdict PASS for S09 with the unrelated environment limitation retained. Cloud finding state unchanged.

### codex-installed-proof-range | low | Installed Codex version blocks an unrelated factory control

Type: verification environment prerequisite. Status: open follow-up. test_factory_applies_exact_codex_model_scoped_controls fails BINARY_OUT_OF_PROOF_RANGE with installed Codex 0.160.0. A detached clean worktree at pre-S09 commit 64fb0ea2 reproduces the same failure using the locked Windows environment. Baseline and patched version probes both report 0.160.0. Restore a binary within existing completed-turn proof coverage, or establish new proof through the authorized eligibility workflow, before using this factory control as passing evidence. No test or eligibility rule was weakened.

### codex-proof-refresh | low | Current Codex works after refreshing stale admission evidence

Type: verification prerequisite and release drift. Status: fixed in S10, superseding codex-installed-proof-range. Installed Codex 0.160.0 completed a direct production CodexChatModel app-server turn returning pong before the declaration changed. The cited production-factory live-turn test then passed, and the live SQLite identity test passed. PROVEN_TURN_LANES now records that observed version with its next-minor exclusive ceiling; all CI installation, version assertion and signature-audit pins match. No admission predicate or missing-proof refusal was weakened. This updates evidence under provider-binary-policy D2, not the governing decision.

### codex-test-release-coupling | low | Live identity and boundary controls duplicated release pins

Type: test maintenance and coverage. Status: fixed in S10 at the user's request. Admission controls now use declared floor, ceiling and generated adjacent versions; live provider and worker/research identity checks compare persisted identity to an independent probe of the actual resolved command. Synthetic cache and database fixtures use generic test versions independent of installed releases. Tests no longer need release-number edits when proof is refreshed. Independent review found a generated below-floor control would become malformed at a future major rollover; corrected it to handle patch, minor and major predecessors and explicitly reject a zero-only fixture.

### codex-s10-verification | low | Refreshed proof restores the previously failing Codex factory control

Type: verification and review record. Status: verified. Combined credential/factory/admission suite passed 145 tests after proof refresh. After removing release coupling, affected factory/admission/version/SQL identity suite passed 62; actual provider SQL identity and graph worker plus research live service tests passed 2, with observed CLI identity assertions. Final corrected boundary tests passed 5. Ruff lint/format and ty passed on all seven changed Python files; final correction rechecked. Direct CI pin consistency and git diff --check passed. Windows locked uv environment, installed system Codex 0.160.0, catalog-selected gpt-6.1-sol; temporary prompt only requested pong. Linux CI was not run locally. No credentials printed or committed. Review covers this bounded refresh and preserves the unresolved medium Cloud findings.

### codex-s10-review | low | Independent final review passes

Type: review record. Status: resolved. The fresh read-only reviewer verified the actual S10 diff and predecessor correction, accepted the supervisor's applicable test and static-check evidence, and returned PASS with no remaining findings. The earlier low boundary-input finding is fixed; no new production bypass or regression was found.

### build-only-runtime-module | low | CI rejects unreachable capsule staging in the shipped package

Type: packaging boundary and CI regression. Status: fixed in S11. Full Validation 37436892926 at 5ad00794 failed the zero-findings unreachable-module gate for desktop._linux_runtime_assets, used only by build tooling and tests. Moved stage_linux_isolation_assets into its actual scripts/build_linux_isolation.py consumer, deleted the runtime module, and made both test consumers load that real build script using the existing artifact-test runpy pattern. An AST comparison confirms the staging function is unchanged. No gate exemption, dummy runtime import, or copied test implementation was added.

### s11-linux-verification-environment | low | Mounted checkout and partial dependencies caused local-only verification failures

Type: verification environment. Status: resolved for focused proof. Initial mounted WSL run passed 12 native controls but failed MCP startup because the local environment file lacked Linux 0600 semantics, and timed out copying the MCP runtime through the Windows mount. Initial broad lint also lacked server/docs dependency groups. A clean tracked archive plus the actual patch on Linux /tmp, synchronized with uv sync --locked --no-default-groups --extra server --group all, passed all 14 native isolation and launch-context tests in 15 seconds, including genuine isolated MCP handshake. No credential files were copied or permission checks weakened.

### s11-review | low | Build-tool relocation preserves the native boundary

Type: review and verification record. Status: resolved. Fresh read-only review found no findings: guarded build main remains unexecuted when loaded by tests, consumer paths resolve correctly, and runtime manifest validation is unchanged. Windows native controls passed 9; Linux controls passed 14; focused Ruff lint/format and ty passed; build CLI help, unchanged-function AST comparison and Windows/Linux reachability gates passed. Independent review verdict PASS. Full CI replacement is still to be observed after publication.

### s11-full-lint | low | Complete Linux lint checks pass after environment correction

Type: verification record. Status: resolved. On the clean Linux archive with CI's full locked dependency profile, dev lint all passed Ruff, formatting, baseline/platform/strict type checks, guarded-import use, nesting, relative imports, loadability, reachability, unused symbols, exports, dependencies, TOML and shell checks. Its actionlint step initially rejected the archive because it lacked Git metadata. Initialized a local Git repository in that temporary verification directory and reran dev.actionlint plus dev.ci_contract successfully. No source changes or gate exceptions were needed for either environment correction.

### mako-advisory | medium | Newly reached dependency gate rejects vulnerable transitive Mako

Type: third-party dependency vulnerability. Status: fixed in S12. Replacement Full Validation 37443284479 passes all lint including the original reachability gate, then fails GHSA-5639-2j2p-m4mx (CVE-2026-102991): Mako <=1.4.1 permits Windows drive-letter template URI traversal; upstream identifies 1.4.2 as patched. Source: https://github.com/advisories/GHSA-5639-2j2p-m4mx, reviewed 2026-10-06. Updated with uv lock --upgrade-package mako==1.4.2; semantic TOML comparison confirms only Mako package version/artifact metadata changes. Existing Dependabot PR95 proposes the same release and remains unmodified. No advisory suppression was added.

### mako-verification | low | Patched transitive template dependency preserves migration behavior

Type: verification record. Status: verified. After uv sync --locked --no-default-groups --extra server --group all on Windows, the real dependency audit passed with no unaccepted advisories across 111 Node and 189 Python coordinates. Migration suite passed 19 tests. A temporary real-filesystem control verifies ordinary template rendering, refusal of drive-letter traversal forms, and actual Alembic ScriptDirectory.generate_revision with the repository template followed by Python AST parsing. An initial direct template smoke invocation lacked Alembic's comma helper; invoking the owning Alembic API corrected the test setup. No application source, migration history or test assertions changed.

### mako-review | low | S12 dependency review passes

Type: review record. Status: resolved. Fresh read-only review found no findings: only Mako release/artifact metadata changes; registry, dependency edges, lock schema and constraints remain unchanged. The reviewer confirmed the upstream patched release and accepted the supplied audit, migration and real rendering evidence. Verdict PASS; replacement CI remains the publication check.

### factory-settings-authority | low | Harness gate detects two direct factory authority reads

Type: configuration authority and CI regression. Status: fixed in S13. Run 37444176601 passed lint, dependency audit and vault validation, then the harness storage-anchor gate rejected raw ambient Claude OAuth lookup and a multiline Codex default-home lookup whose existing justification marker was misplaced. Claude subscription auth now uses the registered external credential with Core env_value and an explicit process mapping, excluding dotenv and project-store fallback. Surrounding whitespace is normalized by that accessor. Codex catalog and model construction now share resolve_codex_base_home under the existing external-tool credential-home exception; duplicated lookup removed, no gate relaxation.

### s13-review | low | Credential selection and Codex home semantics remain bounded

Type: review and verification record. Status: verified for the scoped repair. Fresh read-only review of the actual diff found no findings and returned PASS. It traced Core's explicit-mapping source behavior and shared configured/default Codex home resolution. Windows auth/factory/home controls passed 117; final storage-anchor tests passed 18 after correcting formatter placement of the existing marker. Ruff lint/format and ty passed on all three changed source files. Linux complete harness passed 157. The complete canonical Linux CI sequence is being run locally before publication.

### preexisting-vault-hygiene | low | Full vault validation reports nonblocking maintenance warnings

Type: documentation metadata hygiene. Status: queued follow-up. Run 37444176601 reports extra blank lines in desktop-product-profile and provider-binary-policy ADRs, and stale body fingerprints in service-lifecycle-architecture ADR, workspace-root-authority-compose-provider-boundary ADR and container-release audit. The full vault check exits successfully; these unrelated documents are not changed by the CI code repair. Reconcile through owning Core maintenance verbs when addressing the documentation queue.

### ci-fixture-contract-drift | medium | Queued: desktop success fixtures conflict with accepted execution refusal

Type: test contract drift. The full Linux CI run now passes lint, dependency audit, vault validation and all 157 harness tests. Unit execution exposed nine acceptance fixture errors and the catalog restart test expecting successful new-run admission under an armed desktop profile. The accepted workspace-root-authority desktop-native-admission decision requires start, prepare and commit to refuse before worker startup even for in-process lanes. Move independent broker execution tests outside the desktop profile while preserving authenticated real subprocesses and explicit desktop refusal coverage. The same run found a stale OpenAPI components artifact, queued for regeneration and review. Interrupted after 1000 passing unit tests to address these failures; this is not full-suite success.

### s14-broker-fixtures | medium | Fixed: execution proofs use the supported broker profile

Type: test contract drift. Shared broker_gateway_env extracts the existing desktop_tests/test_run_admission.py unarmed test setup, retaining explicit SQLite stores, separate real gateway/worker credentials, worker ownership and in-process lane opt-in. Acceptance certification and catalog restart now consume it; production admission is unchanged. Seventeen Linux acceptance/restart/OpenAPI tests pass. Existing desktop readiness tests assert authenticated start/prepare/commit refusal, no durable runs, and a cold worker. OpenAPI regeneration changed only DesktopReadiness and RunAdmission descriptions.

### s14-review | low | Independent review passed with full suite verification pending

Type: verification. Independent read-only review of the actual S14 diff found no security, auth, profile, consumer-override or store-isolation defects. Ruff check/format and strict type checks pass for the six changed Python files. Full Linux unit and focused Windows desktop runs are ongoing; no full CI success is claimed.

### s14-platform-verification | low | Passed: Windows desktop boundary and broker admission

Type: verification. Windows test_readiness_model.py and test_run_admission.py pass all nine real-process cases with the final shared helper. Linux build all passes source/wheel build, documentation tests and strict Sphinx generation. The clean base-installation telemetry probe passes for gateway and worker with OTLP absent. The full Linux unit run remains in progress and is not counted as passing evidence.

### s15-desktop-lifecycle-drift | medium | In progress: lifecycle proofs must start below desktop admission

Type: test contract drift. Full Linux unit execution at a7bd3177 found stale desktop lazy-worker, owned-terminal, worker-pairing, provenance and terminal-settlement expectations. Independent review recommends broker profile for execution proofs, retained real subprocesses for terminal cleanup, and explicit production lifespan/spawner composition for armed pairing and cleanup below run admission. Desktop run entries remain refused. Settlement will use a genuine broker-completed durable run and the production settlement handler under desktop settings, retaining real database and HTTP authentication/retry assertions.

### full-unit-followups | medium | Queued: remaining contract and environment failures

Type: verification and test contract drift. Full local run completed with 5609 passed, 28 failed, 33 existing skips, 3 errors. Nine native tests lacked VAULTSPEC_A2A_TEST_LINUX_ISOLATION_HELPER; three component packaging errors came from the archive snapshot lacking Git HEAD (actual objects restored via Git bundle and all three then passed); three Claude identity tests lacked the service CLI PATH; a Codex factory case lacked its proven binary; one storage test incorrectly forbids a checkout under the OS temporary parent. Further source failures: native packet environment family not documented to the drift guard, two authoring wiring expectations still read gateway credentials from an environment now deliberately scrubbed, and _subprocess republishes provider_execution_command from its declaration home. Address these without weakening gates, hardcoding provider releases in tests, or disabling security boundaries. No full-suite success is claimed.

### s15-settlement-review | medium | Fixed: automatic terminal-event settlement coverage retained

Type: test coverage regression. Independent review found that directly invoking the callback helper would miss a removed terminal-event scheduling call. The revised test opens the actual completed broker run's database and checkpoint, drives production _handle_terminal_event under desktop settings, requires one newly owned settlement task and awaits its real HTTP callback. The focused Linux settlement/provenance set passes all seven cases. Read-only re-review PASS, no remaining code findings.

### s15-verification | low | Passed: lifecycle and provenance proofs on Linux and Windows

Type: verification. All 16 affected desktop lifecycle tests pass on Windows. Linux focused runs cover the same behavior, including real provider/terminal descendants, receipt-authorized worker cleanup, broker worker pairing, refused armed provenance, two-owner conflict and settlement retry. Three packaging tests also pass after restoring actual Git history to the native test snapshot. Ruff and strict typing pass. Remaining full-suite failures are separately queued; no green CI claim.

### ci-prerequisite-portability | medium | Native test inputs and Codex prerequisite depended on runner state

Type: verification portability. Status: resolved in S16. Full Validation 37447403496 completed with 25 failures and 5619 passes. In addition to the already tracked lifecycle and declaration drift, native tests assumed /usr/bin/node and /usr/bin/bwrap and an external helper variable. Fixtures now resolve the provisioned Node executable, build the genuine pinned static helper through the production build script, and reject a copied real dynamic Node ELF as a helper before staging. Copying gives the negative input its own inode, avoiding npm's hardlink count being rejected before the intended dynamic-ELF check. Canonical CI explicitly installs Codex using the declared completed-turn proof version and exposes its task-local bin directory. No production admission relaxation or release-specific test literals were added.

### s16-contract-reconciliation | low | Full-suite fixtures now assert current credential and storage contracts

Type: test contract drift. Status: resolved in S16. Authoring stdio tests assert actor-scoped relay credentials and absence of machine bearer/base URL instead of the obsolete direct-gateway binding. The temp-home test asserts exact ownership under configured A2A home, which may itself live under the OS temporary directory. Private native launch-packet environment fields are documented with their decoder owner and included in the existing owned declaration check. Removed the provider_execution_command re-export and imported its actual owner in consumers. Independent review passed without findings. Windows focused verification: 33 passed, 5 existing Linux-only skips. Linux native/factory/identity checks: 78 passed before the runner-path correction; native path correction additionally verified against the provisioned Node. Full suite remains in progress; its outcome is not claimed here.

### native-fixture-runner-capability | medium | Docker-backed test gate selected a runner prohibited from using Docker

Type: CI prerequisite routing. Status: resolved in S17. Full Validation 37451244881 at b13e7884 passed full Linux CI, provider prerequisites and Windows/Linux x64 plus ARM64 desktop tests. The remaining native-integration job had 13 passes and three fixture setup errors: permission denied at the Windows docker_engine pipe. Fleet declares the runner account nonadministrative and explicitly rejects docker-users membership. Preserve that boundary and schedule the portable native gateway/worker lifecycle, cancellation and real Jaeger trace tests on the existing Linux runner with its private rootless daemon. Declare docker-rootless in ci-fleet fleet.yml and register the same label on A2A runner id 63. Windows native desktop coverage remains mandatory. Compose and Buildx were also absent from the rootless image: provision official release binaries with SHA256 verification in job-owned Docker configuration, and reject a non-rootless daemon before using it. Actual unprivileged runner verification passed all 16 integration tests in 54.32 seconds, including live Jaeger traces and teardown. No tests are removed, skipped or weakened.

### docker-config-validation-identity | medium | Rootless preflight initially checked a different Docker configuration

Type: security validation. Status: resolved in S17 after independent review. The first helper validated ambient Docker configuration before changing DOCKER_CONFIG. It now constructs the final job configuration first and uses the identical environment for daemon validation and every plugin command, then exports that configuration to the test step. Real provisioning was rerun successfully on the actual rootless runner. Independent re-review passed. Eleven workflow/placement tests, 34 fleet manifest/label tests and canonical lint passed; the fleet declaration loads successfully with its owning environment loader.

## Recommendations

Complete each original finding with real trigger and legitimate-control proof, then independent patch review and recorded verification. Reconcile terminal availability with the native-admission decision before changing its default-development exception. Do not claim platform certification from Windows refusal tests.
