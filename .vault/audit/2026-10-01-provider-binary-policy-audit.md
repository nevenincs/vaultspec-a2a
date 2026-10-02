---
tags:
  - '#audit'
  - '#provider-binary-policy'
date: '2026-10-01'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:84f1de8efe3e0d5ecfbdbc6662b44bbfae6b6cba64b35207926b188ab2707c36'
related:
  - "[[2026-10-01-provider-binary-policy-plan]]"
---

# `provider-binary-policy` audit: `execution of the vendored adapter upgrade`

## Scope

Findings raised while executing P01.S17 of `2026-10-01-provider-binary-policy-plan`, the move of the vendored Claude ACP adapter from 0.59.0 to 0.84.0 (Agent SDK 0.3.207 to 0.3.284, CLI 2.1.207 to 2.1.284), read against `2026-10-01-provider-binary-policy-acp-adapter-upgrade-research`. Rolling: later Steps append here.

## Findings

### root-session-armed-skip-permissions | critical | a root host with IS_SANDBOX set could open no Claude session

Fixed in P01.S17. The adapter computes bypass availability as not-root or `IS_SANDBOX`, and when available passes the CLI's skip-permissions flag, which the CLI refuses for root regardless of `IS_SANDBOX`; on this host (root, `IS_SANDBOX=yes`) every served session and the catalog probe failed at `session/new`. The defect existed at 0.59.0, which offered no way to decline; 0.84.0 reads the client's `allowDangerouslySkipPermissions: false`, which `claude_session_options` and the catalog probe now send (`src/vaultspec_a2a/providers/_claude_tool_policy.py`, `claude_bypass_declined_meta`). Declining also keeps `bypassPermissions` out of the advertised catalog on any host.

### new-error-kinds-resolved-to-unknown | high | three new provider error kinds reached clients as unknown

Fixed in P01.S17. The Agent SDK added `account_on_hold`, `verification_required` and `cloud_credential_error`; they are mapped as the adapter's own classifier files them, the first as exhausted credits and the other two as unauthenticated (`src/vaultspec_a2a/providers/conditions.py`).

### powershell-not-denied-to-terminal-less-persona | high | a persona with no terminal could still run commands through PowerShell

Fixed in P01.S17. The adapter treats `PowerShell` as a shell tool beside `Bash`, and on Windows without Git Bash the CLI requires it; it is now in `CLAUDE_TERMINAL_TOOLS`.

### managed-policy-env-reaches-the-child | high | the adapter injects managed-policy environment into the CLI child before any session

Open, owned by P06.S20; ruled by the 2026-10-01 amendment to `2026-10-01-provider-binary-policy-adr`. At module load the adapter reads the managed-policy settings tier, which includes macOS MDM and the Windows policy registry hives, and writes its `env` entries into its own process environment, which the CLI child inherits. Passing no setting sources does not suppress it, so the docstring claim that no setting sources drops enterprise managed configuration is wrong.

### permission-request-carries-tool-identity | medium | the permission request now names its tool and MCP server, which the rung does not read

Open, owned by P03.S23 of `2026-10-01-tool-permission-model-plan`. Since SDK 0.3.274 a permission request carries `_meta.claudeCode.toolName` and `mcpServer{name,source}`, a more reliable identity than the prose title the rung parses today.

### session-updates-dropped-silently | medium | three session update kinds that reach this lane are dropped with no log

Open, owned by P06.S19. The adapter emits eighteen update kinds; `usage_update`, `config_option_update` and `session_info_update` reach this lane ungated and fall through a dispatcher with no default branch.

### terminal-handlers-unreachable-on-claude | low | the client terminal handlers are never called by this adapter

Open. 0.84.0 calls no `terminal/*` client method; shell output rides the tool call's metadata. The five terminal handlers stay for other ACP lanes but are dead on the Claude lane, and the lane still handles `tool_call_chunk`, which this adapter never emits.

### ambient-is-sandbox-forwarded | low | the child environment forwards an ambient IS_SANDBOX

Open. `resolve_env_vars` passes `IS_SANDBOX` through; inert now that bypass is declined, but it is uncurated ambient state reaching the CLI.

### vendored-cli-behind-latest | low | the vendored CLI is two patches behind the latest SDK

Recorded. The adapter pins SDK 0.3.284 (CLI 2.1.284) while 0.3.286 exists; forcing it would override an exact pin upstream has not tested.

### claude-lane-proof-predates-the-binary | medium | the Claude lane's completed-turn proof was earned on an older binary

Open; needs a credentialed host. No model turn is possible here, so the bump is proven to the handshake and binary boundary only. Under the served-profile rule's binary-identity clause the Claude lane must re-earn its completed-turn proof on CLI 2.1.284 before that identity is admitted; P02.S07 of this plan records proved versions.

### workspace-scope-test-posix-only | low | workspace read grant test assumed POSIX temporary paths

Fixed in P05.S16. The workspace read grant assertion expected a POSIX spelling of tmp_path. On Windows the production rule correctly anchors the drive, so the assertion failed despite correct behavior. It now composes the separately tested production path renderer with the workspace rule. Type: test portability.

### desktop-test-still-passed-resume-option | low | desktop process test used the removed model option

Fixed in P05.S16. After removing AcpChatModel.session_id, the owned-process-tree test still passed session_id=None. The typed gate found the stale constructor call at src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py:158. Type: test compatibility. The argument is removed and the targeted type check passes.

### ownership-test-used-absolute-import | low | new test violated the relative-import guard

Fixed in P05.S16. The new model-field assertion initially imported the provider with an absolute intra-package path. The repository guard found it; the test now imports the production model relatively. Type: test convention.

## Recommendations

- Rule on the managed-policy tier and correct the claim (`managed-policy-env-reaches-the-child`), done by the ADR amendment and P06.S20.
- Re-run the Claude lane's completed-turn test on a credentialed host against 2.1.284 (`claude-lane-proof-predates-the-binary`).

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
