---
tags:
  - '#audit'
  - '#provider-binary-policy'
date: '2026-10-01'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:23ab0901625483c6457d35e5e0c8677e98034641da2d69a4666b1a851347c4fc'
related:
  - "[[2026-10-01-provider-binary-policy-plan]]"
---

# `provider-binary-policy` audit: `execution of the vendored adapter upgrade`

## Scope

Findings raised while executing P01.S17 of `2026-10-01-provider-binary-policy-plan`, the move of the vendored Claude ACP adapter from 0.59.0 to 0.84.0 (Agent SDK 0.3.207 to 0.3.284, CLI 2.1.207 to 2.1.284), read against `2026-10-01-provider-binary-policy-acp-adapter-upgrade-research`. Rolling: later Steps append here.

P01.S01 review (2026-10-02): PASS for the capsule CLI path authority and installed-binary version probe. The path stays under the capsule npm closure, uses the ACP adapter platform and libc preference order, and the focused real-binary test, lint, format, and targeted type check pass. No new review finding was queued.

P03.S11 review (2026-10-02): PASS for the additive identity table and write-once repository. The migration upgrades and downgrades on SQLite and PostgreSQL, model/schema parity passes, and an exact retry keeps one row while changed binary evidence is refused without poisoning the transaction. No new review finding was queued.

P01.S03 review (2026-10-02): PASS for the explicit absolute-path setting declaration and operator example. A real settings load accepts an absolute CLI path and refuses a relative one before project-root rebasing; the example-profile, lint, format, and targeted type checks pass. Launch consumption is scheduled by P01.S04. No new review finding was queued.

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

### capsule-cli-symlink-escaped-root | medium | desktop arming could accept an externally owned CLI

Fixed in P01.S02. The desktop profile previously validated runtime assets only with is_file(), which follows a symlink outside the capsule. Adding the Claude CLI as a third asset would have admitted a host-owned binary through that path. The profile now resolves each of the three assets against the resolved capsule root and refuses an escape; a real symlink test proves the refusal. Type: runtime authority and asset containment.

## Recommendations

- Rule on the managed-policy tier and correct the claim (`managed-policy-env-reaches-the-child`), done by the ADR amendment and P06.S20.
- Re-run the Claude lane's completed-turn test on a credentialed host against 2.1.284 (`claude-lane-proof-predates-the-binary`).
