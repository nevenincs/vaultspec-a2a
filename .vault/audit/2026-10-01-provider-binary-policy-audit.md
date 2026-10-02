---
tags:
  - '#audit'
  - '#provider-binary-policy'
date: '2026-10-01'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:1ab24eb1aeec9f4ed3b7329c146503e13517bc8c78d5b8d340cb97d1c11f2f1a'
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

Open; owned by P03.S13. Research branch models are invoked by `_make_research_producer` through `create_researcher_node`, while S12's port reaches the six research document workers through `create_worker_node`. A provider used only by a fan-out branch would receive no identity row if S13 records solely in the worker node. S13 must capture that initialize path too. Type: topology coverage and runtime evidence.
### failed-acp-turn-usage-unrecorded | medium | failed prompts can spend tokens without a returned usage message

Open; follow-up scope is the graph's error-path accounting contract. The upgraded adapter reports usage on terminal prompt results even for refusal, cancellation and budget stops. This Step attaches usage to the final message only after a successful end_turn because those other outcomes raise a typed prompt error and return no message for the graph's _turn_token_usage reader. A failed turn can therefore incur provider usage without a token_usage entry. Type: cost-accounting gap. A later Step must decide how error-path usage reaches the durable turn record without treating a failed prompt as a successful response.
### proof-range-typing-was-not-narrowed | low | strict CI could not verify version comparisons

Fixed in P02.S22. The P02.S08 proof predicate rejected missing parse results in a compound condition that basedpyright could not narrow, leaving three strict diagnostics at the host PATH comparison. It now checks all four parsed versions for `None` before comparing them. Behavior is unchanged; focused lane admission tests and strict type checks pass. Type: CI type correctness and proof gate readability.
### managed-policy-presence-not-observable-from-acp | medium | runtime identity cannot yet assert host policy presence

Open; owned by P03.S13. The adapter applies managed policy before sessions but its ACP initialize and session/new results do not report whether that tier existed or its read succeeded. P06.S20 logs the resolution path only. `ProviderRuntimeIdentityModel.managed_policy_present` must remain unknown until S13 obtains a reliable presence signal, for example by probing the same SDK `resolveSettings({settingSources: []})` policy tier without exporting its values. Type: runtime evidence gap.
### claude-auth-example-stale | medium | the operator example describes the old ambient-only Claude auth contract

Fixed in P04.S15. The example now documents the two canonical Claude auth settings, the alternate CLI token name, and the distinction between a token held only in project .env and an operator export under the default channel. It also covers SUCCESSOR_TRANSCRIPT_DEPTH. The env-example drift and coverage suite passes. Type: operator documentation and settings coverage drift.
### acp-per-model-usage-strict-type | low | S18 read optional nested TypedDict fields as required

Fixed in P06.S19. The S18 per-model usage aggregation built the nested cache details in every row but read them through LangChain's optional `UsageMetadata.input_token_details` type, producing four `reportTypedDictNotRequiredAccess` diagnostics in the strict type gate. The parser now accumulates its already validated cache counts directly while constructing each row, preserving the turn totals and eliminating those four diagnostics. The remaining lane-admission and checkpoint diagnostics are owned by P02.S22 and continuation P06.S17. Type: static type safety and CI integration.
### lock-vendored-cli-storage-anchor-flag | low | the new asset resolver use failed the storage-anchor guard

Fixed in P02.S23. P01.S04's lock-vendored Claude CLI fallback reads the declared install root to locate a shipped binary, which is an asset resolver use. The guard only allowed the existing factory-command resolver module and flagged this call. The line now carries the guard's documented `storage-anchor-ok` annotation beside an explanation; no storage location or runtime behavior changed. Type: CI guard classification.

### release-history-test-assumed-no-new-release | medium | 0.4.0 changelog entry broke the dev CI gate

Fixed in P02.S23. The release-please contract test required exactly the three bootstrapped headings even after 0.4.0 was released. It now requires those exact historical headings as the preserved suffix while allowing newer releases to prepend. The focused release and storage-anchor suites pass together (25 tests). Type: stale test contract and CI integration.
P04.S15 review (2026-10-02): PASS for the declared-channel credential prerequisite and operator example. The prerequisite calls the production auth selector, so a configured token under subscription_login alone is insufficient and an ambient token under oauth_token cannot mask a missing configured token. The example gives editable channel and token settings, explains dotenv-only behavior, and documents successor transcript depth. The stale env-example guard is removed. Twenty-nine focused tests and changed-file checks pass. No new finding was surfaced; shared integrated CI remains pending.
