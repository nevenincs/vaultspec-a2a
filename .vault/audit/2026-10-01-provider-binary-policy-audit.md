---
tags:
  - '#audit'
  - '#provider-binary-policy'
date: '2026-10-01'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:fac2aa33e757a2238e201b2e54d50e093a28f6029d5ca0cdb1139d4ad91ae729'
related:
  - "[[2026-10-01-provider-binary-policy-plan]]"
---

# `provider-binary-policy` audit: `execution of the vendored adapter upgrade`

## Scope

Findings raised while executing P01.S17 of `2026-10-01-provider-binary-policy-plan`, the move of the vendored Claude ACP adapter from 0.59.0 to 0.84.0 (Agent SDK 0.3.207 to 0.3.284, CLI 2.1.207 to 2.1.284), read against `2026-10-01-provider-binary-policy-acp-adapter-upgrade-research`. Rolling: later Steps append here.

P01.S01 review (2026-10-02): PASS for the capsule CLI path authority and installed-binary version probe. The path stays under the capsule npm closure, uses the ACP adapter platform and libc preference order, and the focused real-binary test, lint, format, and targeted type check pass. No new review finding was queued.

P03.S11 review (2026-10-02): PASS for the additive identity table and write-once repository. The migration upgrades and downgrades on SQLite and PostgreSQL, model/schema parity passes, and an exact retry keeps one row while changed binary evidence is refused without poisoning the transaction. No new review finding was queued.

P01.S03 review (2026-10-02): PASS for the explicit absolute-path setting declaration and operator example. A real settings load accepts an absolute CLI path and refuses a relative one before project-root rebasing; the example-profile, lint, format, and targeted type checks pass. Launch consumption is scheduled by P01.S04. No new review finding was queued.

P01.S05 review (2026-10-02): PASS for typed CLI unavailability at Claude and Z.ai construction, at served-turn environment resolution, and in Claude catalog discovery. The resolver owns the reason; the catalog returns unavailable without spawning a child. The 131 focused identity, factory and compiler tests, changed-file lint, format and type checks pass. Full CI remains a shared integration gate owned by the plan supervisor. The previously queued catalog finding is fixed; no new review finding was raised.

P01.S06 review (2026-10-02): PASS for the Compose worker image's exact Claude CLI 2.1.284 install and explicit absolute service setting. The CLI stage and complete worker image build, the CLI reports 2.1.284 as agentuser, the image's resolver selects /usr/local/bin/claude as explicit_setting, and Compose config parses. No new review finding was raised.

P01 integrated review (2026-10-02): PENDING shared integration gates. S01-S06 jointly give one profile-scoped CLI resolution, refuse a missing selected asset before ACP spawn, and name an exact Compose binary. Focused behavior, type, lint, image and Compose checks pass. The plan supervisor owns just ci and ci-merge on the integrated branch, which also carries baseline CI fixes. No new code finding was raised.
## Findings

### root-session-armed-skip-permissions | critical | a root host with IS_SANDBOX set could open no Claude session

Fixed in P01.S17. The adapter computes bypass availability as not-root or `IS_SANDBOX`, and when available passes the CLI's skip-permissions flag, which the CLI refuses for root regardless of `IS_SANDBOX`; on this host (root, `IS_SANDBOX=yes`) every served session and the catalog probe failed at `session/new`. The defect existed at 0.59.0, which offered no way to decline; 0.84.0 reads the client's `allowDangerouslySkipPermissions: false`, which `claude_session_options` and the catalog probe now send (`src/vaultspec_a2a/providers/_claude_tool_policy.py`, `claude_bypass_declined_meta`). Declining also keeps `bypassPermissions` out of the advertised catalog on any host.

### new-error-kinds-resolved-to-unknown | high | three new provider error kinds reached clients as unknown

Fixed in P01.S17. The Agent SDK added `account_on_hold`, `verification_required` and `cloud_credential_error`; they are mapped as the adapter's own classifier files them, the first as exhausted credits and the other two as unauthenticated (`src/vaultspec_a2a/providers/conditions.py`).

### powershell-not-denied-to-terminal-less-persona | high | a persona with no terminal could still run commands through PowerShell

Fixed in P01.S17. The adapter treats `PowerShell` as a shell tool beside `Bash`, and on Windows without Git Bash the CLI requires it; it is now in `CLAUDE_TERMINAL_TOOLS`.

### managed-policy-env-reaches-the-child | high | the adapter injects managed-policy environment into the CLI child before any session

Fixed in P06.S20; ruled by the 2026-10-01 amendment to `2026-10-01-provider-binary-policy-adr`. At module load the adapter reads the managed-policy settings tier, which includes macOS MDM and the Windows policy registry hives, and writes its `env` entries into its own process environment, which the CLI child inherits. Session documentation now distinguishes ordinary settings scopes from managed policy, and a bounded session log records the adapter-controlled best-effort resolution without claiming a policy was present. Type: runtime policy and contract wording.

### permission-request-carries-tool-identity | medium | the permission request now names its tool and MCP server, which the rung does not read

Open, owned by P03.S23 of `2026-10-01-tool-permission-model-plan`. Since SDK 0.3.274 a permission request carries `_meta.claudeCode.toolName` and `mcpServer{name,source}`, a more reliable identity than the prose title the rung parses today.

### session-updates-dropped-silently | medium | three session update kinds that reach this lane are dropped with no log

Fixed in P06.S19. The adapter emits eighteen update kinds; `usage_update`, `config_option_update` and `session_info_update` reached this lane ungated and previously fell through a dispatcher with no default branch. The dispatcher now logs bounded context occupancy, configuration-option count, and session-info receipt without copying provider payloads into logs. Eight other adapter kinds are logged by kind, and a bounded fallback records future kinds. Terminal per-model usage remains the accounting source; context occupancy never adds turn tokens. Type: protocol observability and accounting boundary.

### terminal-handlers-unreachable-on-claude | low | the client terminal handlers are never called by this adapter

Open. 0.84.0 calls no `terminal/*` client method; shell output rides the tool call's metadata. The five terminal handlers stay for other ACP lanes but are dead on the Claude lane, and the lane still handles `tool_call_chunk`, which this adapter never emits.

### ambient-is-sandbox-forwarded | low | the child environment forwards an ambient IS_SANDBOX

Open. `resolve_env_vars` passes `IS_SANDBOX` through; inert now that bypass is declined, but it is uncurated ambient state reaching the CLI.

### vendored-cli-behind-latest | low | the vendored CLI is two patches behind the latest SDK

Recorded. The adapter pins SDK 0.3.284 (CLI 2.1.284) while 0.3.286 exists; forcing it would override an exact pin upstream has not tested.

### claude-lane-proof-predates-the-binary | medium | the Claude lane's completed-turn proof was earned on an older binary

Open; the current Claude binary still lacks a completed-turn proof. P02.S07 withheld served admission after the 2.1.286 prompt failed authentication; P02.S21 will reenroll it only when its cited live turn completes on the resolved binary.

### workspace-scope-test-posix-only | low | workspace read grant test assumed POSIX temporary paths

Fixed in P05.S16. The workspace read grant assertion expected a POSIX spelling of tmp_path. On Windows the production rule correctly anchors the drive, so the assertion failed despite correct behavior. It now composes the separately tested production path renderer with the workspace rule. Type: test portability.

### desktop-test-still-passed-resume-option | low | desktop process test used the removed model option

Fixed in P05.S16. After removing AcpChatModel.session_id, the owned-process-tree test still passed session_id=None. The typed gate found the stale constructor call at src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py:158. Type: test compatibility. The argument is removed and the targeted type check passes.

### ownership-test-used-absolute-import | low | new test violated the relative-import guard

Fixed in P05.S16. The new model-field assertion initially imported the provider with an absolute intra-package path. The repository guard found it; the test now imports the production model relatively. Type: test convention.

### capsule-cli-symlink-escaped-root | medium | desktop arming could accept an externally owned CLI

Fixed in P01.S02. The desktop profile previously validated runtime assets only with is_file(), which follows a symlink outside the capsule. Adding the Claude CLI as a third asset would have admitted a host-owned binary through that path. The profile now resolves each of the three assets against the resolved capsule root and refuses an escape; a real symlink test proves the refusal. Type: runtime authority and asset containment.

### catalog-missing-cli-propagates-configuration-error | medium | catalog lacks a typed unavailable result for a missing CLI

Fixed in P01.S05. A missing selected CLI raises ProviderRuntimeUnavailableError with the typed claude_cli_unavailable reason during construction or served-turn environment resolution. Claude catalog discovery maps the same reason to an unavailable result before spawning ACP. Type: error mapping and availability.

### catalog-binary-test-was-posix-only | low | catalog pin proof was skipped on Windows

Fixed in P01.S04. The previous capsule catalog test used a POSIX shell script as its fake Node executable and skipped the Windows host. It now copies the installed Node binary into a real capsule tree and uses a tiny JavaScript entry to write the child environment, so the same catalog probe runs on both hosts. Type: test coverage and portability.
### claude-current-binary-auth-refused | high | the current Claude CLI could not complete its cited live turn

Open auth integration finding, with served admission withheld in P02.S07 and reenrollment owned by P02.S21. The host CLI reported logged in, and the production ACP child initialized and opened a session, but `test_claude_live_turn_completes_and_returns_content` failed on its first prompt with `ACP Error [-32000]: Authentication required`. The resolved host CLI reported 2.1.286; no completed-turn proof was earned for that version. Type: runtime authentication and proof invalidation. Investigate the child authentication context before rerunning the proof; a successful CLI status or ACP handshake does not qualify.

### zai-current-binary-proof-unavailable | medium | Z.ai had no credential for a current-binary live turn

Open external prerequisite, with served admission withheld in P02.S07 and reenrollment owned by P02.S21. Neither `ZAI_AUTH_TOKEN` nor `ZAI_API_KEY` was present on the proof host, so the cited `test_zai_streaming_shape_is_faithful` could not establish a version-bound completed turn. Type: verification gap. Record the resolved binary's reported version only after that test completes with a valid credential.

### codex-proof-citation-mismatched-to-current-run | low | the old citation named a stack acceptance test that was not rerun

Fixed in P02.S07. The original citation named the PW7 document-authoring acceptance run, which requires a gateway and engine stack absent from this proof host. The production-factory `test_codex_live_turn_returns_output` completed a real turn through the catalog's `codex-app-server` mode on resolved Codex 0.159.2, so the lane declaration now cites that test and claims only the work it completed. Type: evidence precision.
### scoop-shim-target-changes-behind-launcher | medium | caching only the shim EXE would miss a Codex package update

Fixed in P02.S08. The resolved Codex path on the proof host is Scoop's `codex.EXE`, whose file stat predates the installed CLI version; its `.shim` points at the moving `apps/codex/current/bin/codex.exe` target. The version probe's process cache now keys on the shim, sidecar, and resolved target file identities, so replacing the package while the service stays up causes a new `--version` probe. Type: runtime identity and cache invalidation. A real target-change test and a direct probe of the installed launcher pass.
### codex-ci-install-was-unpinned | medium | provider prerequisite CI could certify an unproved Codex version

Fixed in P02.S10. The provider prerequisite job installed `@openai/codex` without a version, while the lane's completed turn was on 0.159.2. The job now globally installs exactly 0.159.2, asserts the CLI reports that version, and audits the same exact package in an isolated npm tree before running the provider gates. The isolated audit verified both registry signatures and attestations. Type: CI supply-chain and proof drift.

### codex-ci-allowance-described-obsolete-risk | low | the CI contract allowance still called Codex unpinned

Fixed in P02.S10. The allowlist rationale named the old unpinned command. It now describes the exact-version install and signature verification, with both inline runner-setup steps declared; `dev.ci_contract` passes. Type: audit trail and CI contract drift.
## Recommendations

- Rule on the managed-policy tier and correct the claim (`managed-policy-env-reaches-the-child`), done by the ADR amendment and P06.S20.
- Re-run the Claude lane's completed-turn test with working child authentication against the resolved binary (`claude-lane-proof-predates-the-binary`, `claude-current-binary-auth-refused`).

- Keep the typed Claude CLI unavailable reason in the shared resolver when later admission work adds version checks.
### version-proof-could-drift-before-child-spawn | medium | constructed model retained an old version verdict

Fixed in P02.S09. Factory construction and provider-catalog selection now return typed `binary_out_of_proof_range` or `binary_version_unavailable` blockers. Review found that a constructed model could outlive its launcher file, so both Codex and Claude-backed model paths recheck the resolved binary immediately before child spawn. A real launcher replacement test confirms refusal before a child starts. Type: runtime admission and time-of-check drift.

### preset-list-is-not-provider-selection | medium | D2 named the wrong read surface

Fixed in P02.S09 by correcting the factual wording in the accepted ADR and plan. The `/v1/presets` response lists static team configurations without provider/model eligibility; `/v1/provider-catalog` supplies selectable lanes, and run-start checks that selection. The binary verdict is therefore enforced in provider-catalog selection, factory construction, and child spawn. Type: decision and contract wording drift.

### malformed-p02-s21-plan-row | low | reenrollment Step was invisible to plan parsing

Fixed in P02.S09. A prior manual conflict resolution dropped the Markdown code spans around P02.S21, making the row noncanonical and omitting it from Core's Step census. The row is restored through Core and remains open pending Claude and Z.ai live turns. Type: plan state integrity.

### launcher-replacement-between-final-probe-and-spawn | low | filesystem race remains at process creation

Open for later runtime hardening. P02.S09 verifies the launcher's identity immediately before child spawn, but the filesystem can replace that path in the interval between the probe and the operating system's process creation. No exploit or observed production incident is established; a descriptor-bound process launch would be needed to eliminate the race completely. Type: residual runtime identity race.
### runtime-identity-compile-scope-gap | low | the approved Step omitted compiler forwarding sites

Fixed in P03.S12. The public compiler delegates worker construction to `_compiler_topologies.py` and `_compiler_research.py`, and `create_worker_node` binds a fixed set of options. A port added only to the four originally named S12 files would not reach compiled workers. Core expanded S12's scope to the two topology modules and the worker binder before implementation. Type: plan scope and dependency injection coverage.

### research-branch-identity-seam | medium | research fan-out bypasses the worker node binder

Fixed in P03.S13. Research branch models are invoked by `_make_research_producer` through `create_researcher_node`, so the producer now binds the per-run identity port after model composition, as the worker does. A real Codex worker turn followed by a research producer turn wrote one durable row and retained the first native session ID. Type: topology coverage and runtime evidence.
### failed-acp-turn-usage-unrecorded | medium | failed prompts can spend tokens without a returned usage message

Fixed in P06.S27. ACP parses provider-reported terminal usage for every supported stop reason, retains it on the typed failure, and the worker writes the measured counts through the existing durable cost port before propagating the failure. Failed prompts remain failures and produce no successful response or checkpoint token_usage delta; the cost table is the durable accounting record for those attempts. Type: cost-accounting gap.
### proof-range-typing-was-not-narrowed | low | strict CI could not verify version comparisons

Fixed in P02.S22. The P02.S08 proof predicate rejected missing parse results in a compound condition that basedpyright could not narrow, leaving three strict diagnostics at the host PATH comparison. It now checks all four parsed versions for `None` before comparing them. Behavior is unchanged; focused lane admission tests and strict type checks pass. Type: CI type correctness and proof gate readability.
### managed-policy-presence-not-observable-from-acp | medium | runtime identity cannot yet assert host policy presence

Open for a later adapter/host-tier evidence Step. The adapter applies managed policy before sessions but ACP initialize and session/new do not report whether that tier existed or loaded. P06.S20 logs the resolution path only, and `managedSettings: true` advertises capability rather than actual presence. P03.S13 persists `managed_policy_present = null` for ACP and Codex; the ADR now states this explicitly. A separate host SDK probe cannot prove that the adapter child successfully loaded that tier. Type: runtime evidence gap.
### claude-auth-example-stale | medium | the operator example describes the old ambient-only Claude auth contract

Fixed in P04.S15. The example now documents the two canonical Claude auth settings, the alternate CLI token name, and the distinction between a token held only in project .env and an operator export under the default channel. It also covers SUCCESSOR_TRANSCRIPT_DEPTH. The env-example drift and coverage suite passes. Type: operator documentation and settings coverage drift.
### acp-per-model-usage-strict-type | low | S18 read optional nested TypedDict fields as required

Fixed in P06.S19. The S18 per-model usage aggregation built the nested cache details in every row but read them through LangChain's optional `UsageMetadata.input_token_details` type, producing four `reportTypedDictNotRequiredAccess` diagnostics in the strict type gate. The parser now accumulates its already validated cache counts directly while constructing each row, preserving the turn totals and eliminating those four diagnostics. The remaining lane-admission and checkpoint diagnostics are owned by P02.S22 and continuation P06.S17. Type: static type safety and CI integration.
### lock-vendored-cli-storage-anchor-flag | low | the new asset resolver use failed the storage-anchor guard

Fixed in P02.S23. P01.S04's lock-vendored Claude CLI fallback reads the declared install root to locate a shipped binary, which is an asset resolver use. The guard only allowed the existing factory-command resolver module and flagged this call. The line now carries the guard's documented `storage-anchor-ok` annotation beside an explanation; no storage location or runtime behavior changed. Type: CI guard classification.

### release-history-test-assumed-no-new-release | medium | 0.4.0 changelog entry broke the dev CI gate

Fixed in P02.S23. The release-please contract test required exactly the three bootstrapped headings even after 0.4.0 was released. It now requires those exact historical headings as the preserved suffix while allowing newer releases to prepend. The focused release and storage-anchor suites pass together (25 tests). Type: stale test contract and CI integration.
P04.S15 review (2026-10-02): PASS for the declared-channel credential prerequisite and operator example. The prerequisite calls the production auth selector, so a configured token under subscription_login alone is insufficient and an ambient token under oauth_token cannot mask a missing configured token. The example gives editable channel and token settings, explains dotenv-only behavior, and documents successor transcript depth. The stale env-example guard is removed. Twenty-nine focused tests and changed-file checks pass. No new finding was surfaced; shared integrated CI remains pending.
### claude-auth-prerequisite-used-private-factory-helper | low | strict CI rejected the cross-module seam

Fixed in P04.S24. S15 correctly shared production credential resolution with the Claude test prerequisite but imported a private factory helper, producing one `reportPrivateUsage` diagnostic in the integrated strict type gate. The factory now names that shared interface `claude_auth_env`; served construction, catalog probing and the prerequisite call it. Focused real-child auth and binary admission tests pass, and changed-file strict typing is clean. Type: API visibility and CI integration.
P03.S13 review (2026-10-02): PASS on the isolated branch. A real catalog-selected Codex 0.159.2 app-server turn completed and wrote a SQLite identity row; a graph worker/research pair retained the first native session ID while checking stable evidence on a later call. A real ACP simulator subprocess covered initialize, session creation, and write-before-prompt. Focused provider/worker tests, database-admin tests, two service proofs, and changed-file checks pass. Integrated CI remains with the branch supervisor.

### first-native-session-id-is-not-a-session-history | medium | D3's one row was ambiguous under D5 per-call sessions

Fixed in P03.S13. D3's write-once row now retains the first observed native session ID; each later initialized call may have a different native ID but must match every stable binary, adapter, authority, and auth field in the same atomic transaction. The ADR states that the row does not enumerate later ephemeral sessions. SQLite concurrent-session and changed-version tests cover the rule. Type: runtime evidence semantics and storage contract.

### acp-private-identity-bypassed-by-custom-getattr | high | ACP could fail after session creation before recording evidence

Fixed in P03.S13. `AcpChatModel` overrides Pydantic's private-attribute getter to expose its session state. The new runtime binding was a private attribute, so the first real ACP subprocess test reached `session/new` and then raised `AttributeError` before writing. The getter now explicitly reads that private binding; the subprocess test completes its turn and finds the row. Type: runtime state integration.

### runtime-identity-step-scope-omitted-producer-and-codex | low | the original S13 row named only ACP and worker files

Fixed in P03.S13. Codex records its app-server initialize and native thread, while the research producer invokes models outside the worker node. Core expanded S13's file scope to those providers, graph paths, SQL port/repository, tests, and ADR/audit evidence before closure. Type: plan scope and topology coverage.

### admin-clear-omitted-runtime-identity-table | high | clear could report success while keeping runtime identity rows

Fixed in P03.S13 after the integrated CI gate exposed the defect. The S11 migration added `provider_runtime_identities`, but the database admin clear order was not updated. The completeness and foreign-key order tests failed; `_CLEAR_ORDER` now includes the child table before `threads`, and all seven admin tests pass on a real SQLite database. Type: destructive administrative operation and migration integration.
### desktop-component-fixture-pinned-prior-wheel | medium | desktop contract failed after 0.4.0 release

Fixed in P02.S25. The dashboard release-manifest fixture still pinned vaultspec-a2a 0.3.0 while the clean wheel built from this branch reports 0.4.0. The fixture now names 0.4.0; it remains explicitly fixture-only and does not claim release binding. The three desktop component contract tests pass. Type: release fixture and CI contract drift.
## Integrated review after P02.S25, 2026-10-02

`just ci` on 1be5a0cd passed lint, vault integrity and 153 development tests, then finished its 5,252 selected unit tests with 5,217 passed, 19 skipped and 16 failed. The failures were reproduced in isolation. P02.S26 repairs the following roots; 292 focused tests passed together, the repaired worker test passed separately, and changed-file lint, format and type checks passed. The full gates are to be rerun after the commit.

### withdrawn-web-proof-left-tests-with-no-live-subject | medium | three tests assumed a Claude web declaration still existed

Fixed in P02.S26. With Claude's completed-turn proof withdrawn, Codex is the only turn-proven external lane and its web reach is configured with no allowlist names. The three graph tests no longer assert a nonexistent turn-only or allowlist-lit lane; the real ACP simulator still proves supplied built-in composition, while shipped Claude darkness and Codex's empty built-in declaration are asserted separately. Type: test evidence drift after proof withdrawal.

### vault-index-paths-varied-by-host | medium | checkpointed vault paths used host separators

Fixed in P02.S26. `build_initial_vault_index` and mounted document headers used `str(Path.relative_to(...))`, producing backslashes in Windows checkpoint state while the graph contract and other tests used `.vault/...`. Both now serialize relative paths with `as_posix()`, which remains readable by `Path` on Windows. The two original graph failures and neighboring mount tests pass. Type: cross-platform state serialization.

### core-mcp-launch-test-missed-interpreter-pin | low | the registry test expected an obsolete launch argument list

Fixed in P02.S26. The production `vaultspec-core` MCP launch includes `uvx --python 3.13`; the test now expects the same interpreter pin its sibling already reads from the production seam. Type: test contract drift.

### acp-stderr-fixture-broke-under-windows-shell | low | three subprocess tests exited before initialize

Fixed in P02.S26. The fixture passed a multiline Python program through `python -c` to the Windows `cmd.exe` ACP spawn path; the child closed before handshake, so no stderr-tail behavior was exercised. It now writes and executes a real script file, and all three redaction, warning and retention tests pass. Type: test subprocess portability.

### claude-native-rule-test-overclaimed-path-grammar | medium | two CLI assertions assumed POSIX handling on Windows

Fixed in P02.S26 with a correction in `2026-09-24-architecture-review-audit`. The current Windows CLI accepted a drive-absolute grant and applied the matching deny, while the old tests expected both to miss. The production explicit `//` grant and deny still pass unchanged. The tests now state and assert the host-specific native-path observation. Type: platform-dependent CLI rule grammar and audit evidence precision.

### cli-resolution-tests-assumed-posix-launchers | low | two resolver assertions used POSIX executable names on Windows

Fixed in P02.S26. Windows correctly admits a `.cmd` shim and does not resolve an extensionless test file as an executable. The tests now check the platform's real candidate rules and use an executable filename it can launch. Type: test portability.

### rag-compat-test-split-on-posix-newlines | low | a real unreported verdict was parsed as empty on Windows

Fixed in P02.S26. The external client's own mismatch and unreported responses were both produced, but the test partitioned byte-decoded Windows CRLF output on an LF-only separator. It normalizes CRLF before partitioning; the production classifier is unchanged. Type: test output portability.

### duplicate-export-homes-blocked-unit-gate | medium | 11 ordinary-module names were declared from other modules

Fixed in P02.S26. Eight compiler names, two worker permission names and the moved provider-runtime error remained in facade `__all__` declarations, violating the repository's one-declaring-module guard. The exports were removed, and compiler/worker consumers were directed to the declaring modules while retaining used imports. The export-home guard and focused graph tests pass. Type: public API ownership and CI contract drift.

### worker-dispatch-test-inspected-an-in-flight-buffer | low | one replay test missed a terminal while the bridge flushed it

Fixed in P02.S26. The test captured the event batch at one instant even though `flush_events` clears it during retries; the terminal appeared only after the failed batch was requeued. It now reads after the bridge's flush lock, waiting for the real retained terminal, and still asserts one accepted dispatch and one terminal. Type: asynchronous test observation race.

### provider-plan-live-identity-status-was-stale | low | verification prose still described P03.S13 as pending

Fixed in P02.S26. The plan now records the completed real Codex turn and durable SQLite identity-row assertion, while leaving P02.S21 open for Claude and Z.ai credentialed live turns. Type: plan evidence drift.

### explicit-cli-setting-can-escape-an-armed-capsule | high | D1 order conflicts with the capsule-owned runtime constraint

Open pending a decision. `pin_claude_executable` checks `claude_cli_executable` before `capsule_assets_root`, and `test_explicit_setting_outranks_capsule` asserts that an external file wins even when a capsule is armed. D1 states that order, but the same accepted ADR's binding constraint says an armed desktop capsule runs a capsule-owned CLI and must fail loudly when that asset is absent. Type: accepted-decision conflict and runtime authority. The integrated review requested the intended rule before changing it.

### withdrawn-proof-can-restart-a-frozen-provider | high | a previously frozen lane can reach the factory after its proof is withdrawn

Open pending a decision. `resolve_model_for_worker` and `resolve_supervisor_model` accept exact frozen values, while `binary_proof_reason` returns no blocker when `PROVEN_TURN_LANES` has no entry. Thus a recovered Claude or Z.ai run frozen before P02.S07 can construct its lane despite current served admission being withheld. The provider catalog ADR requires restart from frozen values after catalog drift; the newer proof rule requires current version-bound completed-turn evidence at launch. Type: served-proof enforcement and accepted-decision conflict. The review requested whether withdrawal refuses restart or honors the accepted frozen run.

### moved-runtime-error-left-four-private-imports | low | strict typing rejected old factory import sites

Fixed in P02.S26. Removing the duplicate `ProviderRuntimeUnavailableError` factory export left four consumers importing it from the facade: the provider test prerequisite and three test modules. They now import the class from `cli_resolution`, its declaring module. Type: module API ownership and strict CI integration.

## P02.S26 verification and integrated review, 2026-10-02

The repaired working tree passed `just ci-merge`: strict types, repository guards, vault checks, 153 development tests, and 2,129 unit tests with five Windows platform skips. It also passed `just ci`: lint, types, dependency and vault checks, 153 development tests, 5,233 selected tests with 19 skips and 281 service deselections, package build, six documentation tests, and warning-free Sphinx build. Both gates ran on Windows with Python 3.13.11 and pinned Node 26.8.1. The code diff and affected graph, provider, and worker interfaces were reviewed after these repairs; no further defect was found in P02.S26. Review verdict: REVISION REQUIRED for the two open high policy conflicts above. P02.S21 remains open because Claude and Z.ai lack completed credentialed live turns on the resolved binaries. No merge readiness is claimed.

The high findings reopen P01.S04 for the capsule authority order and P02.S09 for withdrawn-proof enforcement at provider construction and spawn. Those steps remain open pending the requested policy choices. P02.S26 stays closed because its integrated gate repairs and review are complete.

## P01.S04 capsule authority resolution, 2026-10-02

### explicit-cli-setting-can-escape-an-armed-capsule | high | resolved by capsule-first CLI authority

Fixed in reopened P01.S04 under the user's instruction to continue with the recommended rule. The single resolver now chooses the capsule CLI before an explicit setting when a capsule root is armed. A present capsule asset reaches the real child environment despite a conflicting explicit path, and a missing capsule asset refuses with the typed CLI-unavailable reason rather than borrowing that path. Outside a capsule, the explicit setting still selects the CLI. The accepted provider-binary-policy ADR's D1 order is amended and cross-referenced against relevant accepted decisions. Six focused capsule/explicit tests passed after the change; the full 16-test binary-identity file passed before the final real-child test expansion. Ruff lint and format, strict types, and vault checks pass. Integrated review of the resolver, catalog probe, factory, and child-environment seam found no new issue in this step. Review verdict for P01.S04: PASS. P02.S09 and P02.S21 remain open.
## Reopened P02.S09 review, 2026-10-02

### withdrawn-proof-can-restart-a-frozen-provider | high | resolved by current proof at every frozen launch boundary

Fixed in reopened P02.S09 under the user's instruction to apply the recommended fail-closed rule. A missing Claude or Z.ai binary proof now produces typed `binary_proof_missing` at catalog health, factory construction and the pre-spawn model recheck. A frozen Claude worker assignment was exercised through the real compiler and factory path and refused before model construction. The provider-binary-policy and provider-model-catalog ADRs now distinguish frozen selection identity from current execution eligibility. Type: served-proof enforcement and decision reconciliation.

### other-frozen-lanes-could-bypass-current-turn-proof | high | compiler admitted unproven external frozen lanes

Fixed in P02.S09. Review found the same frozen-path gap for Kimi, OpenAI, Zhipu and Antigravity even though none has a current exact-lane completed-turn proof. Worker and supervisor resolution now check the existing exact-mode admission declaration before asking any factory for a model, with typed `turn_proof_missing`; an explicitly frozen fallback is evaluated under its own proof. Six external lane cases and the supervisor case pass, while Codex and in-process frozen paths remain covered by neighboring graph tests. Type: served admission and frozen restart authority.

### withheld-factory-tests-expected-unproven-models | medium | five factory assertions assumed Claude or Z.ai could construct now

Fixed in P02.S09. With both lanes intentionally withheld, those assertions could no longer reach a model. Their command and environment builders retain independent coverage; the factory tests now assert typed proof refusal, and model/configuration assertions are deferred until credentialed reenrollment can make the lane reachable. Type: test contract drift after proof withdrawal.

### auth-channel-tests-constructed-a-withheld-lane | low | credential tests failed before reaching child auth selection

Fixed in P02.S09. The three child-environment assertions now use the production `claude_auth_env` selector to construct a real ACP model directly and inspect its real child environment. The empty-token assertion calls the same selector. This retains the credential precedence proof without claiming the withdrawn lane is served. Type: test seam and admission separation.

### graph-test-used-provider-only-fixture | low | the new frozen-run test named a fixture unavailable to graph tests

Fixed in P02.S09. The frozen-run test needs no ACP adapter fixture because the current-proof guard refuses before adapter construction. The fixture dependency was removed, and the real compiler/factory path passed. Type: test fixture scope.

### constrained-merge-run-exposed-lifecycle-timing | low | two unrelated lifecycle tests failed under one-worker resource admission

Verification follow-up. The first `just ci-merge` run admitted one worker under host resource pressure and failed the desktop discovery racing-reader and parked-SSE shutdown clock tests; both passed in the immediate isolated `--lf` rerun without code changes. They are classified as timing-sensitive verification failures, with no provider-policy defect evidenced. The full merge profile must pass on the final tree before this Step closes. Type: CI environment and timing.

The current focused provider, auth and graph set passes 141 tests; strict types, changed-file Ruff lint and formatting pass. The integrated merge profile is pending rerun after the general frozen-lane guard.

## P02.S09 integrated verification and review, 2026-10-02

The final working tree passed `just ci-merge` on Windows with Python 3.13.11 and pinned Node 26.8.1: lint, format, strict types, dependency and vault guards, 153 development tests, and 2,130 unit tests with five Linux-only skips. The focused provider/auth/graph set passed 141 tests. The two timing-sensitive lifecycle tests from the earlier constrained run passed in the immediate isolated rerun and again in this complete merge profile without source changes, closing that verification follow-up. Review traced frozen worker and supervisor resolution, catalog admission, factory construction, and ACP/Codex pre-spawn checks against both amended ADRs; no further finding was surfaced in this step. Review verdict for P02.S09: PASS. P02.S21 remains open pending credentialed Claude and Z.ai live turns.

### P06.S27 implementation review | low | no new finding surfaced

Provider stop-reason parsing, typed error propagation, worker failure handling, and SQL cost persistence were reviewed together. The cost write remains observational and best-effort, as for successful turns; a database outage can still leave usage unrecorded and is logged. Four failure stop reasons retain usage while still raising. Focused provider and database tests pass (55), strict types, Ruff, and diff checks pass. The first merge-profile run had a single host disk-full failure while copying Node; that test passed in isolation after test artifacts were moved to free space. The full clean rerun passed 153 development tests and 2,134 unit tests with five Windows platform skips. Review verdict: PASS for P06.S27; no new defect surfaced. Type: review outcome.
