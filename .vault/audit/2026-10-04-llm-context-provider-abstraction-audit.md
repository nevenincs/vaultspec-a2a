---
tags:
  - '#audit'
  - '#llm-context-provider-abstraction'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:57bb18e9bffe3762b6a855806d79d5dabd409eae16ce1c041f90496d8654c55c'
related:
  - "[[2026-08-02-llm-context-provider-abstraction-plan]]"
---
# `llm-context-provider-abstraction` audit: `Remaining ACP issue validation`

## Scope

Requested verification of all remaining ACP issues after read/session repairs:
P01.S02 terminal retained output, P02.S05 native adapter callbacks, and P03.S06
strict verification. Validation spans 2026-10-04 to 2026-10-05. No functional
source changes or plan closures are claimed. Initial HEAD b8a6e6d5, later native
production retirement at f09f44a6 and current checkpoint 29aa92d9. Production
terminal handler blob: 1a97a3b99e6617ee8111c854308dbfa009e2407c.
Governing accepted ACP v1 ADR remains unchanged. Managed validation reports,
receipts and exact PoCs are retained in the target-bound Codex Security
collection under artifacts/05_findings. This bounded verification needs no new
implementation plan; the existing migration plan owns the confirmed repairs.

## Findings

### terminal-byte-limit-ignored | low | zero and small caps do not bound output

Status: confirmed open; type: protocol/resource. Production terminal/create
validates only session fields and retains only process identity, ignoring
outputByteLimit at `_acp_rpc_terminal_handlers.py:201` and `:221`. A real child
returned six UTF-8 bytes for caps 0 and 4, always truncated=false. Negative -1,
a numeric string and true also reached real process creation. The installed SDK
1.6.0 describes a retained tail truncated from the beginning at character
boundaries. Owner: P01.S02. All shipped vaultspec personas declare terminal=false,
and actual dispatch refuses terminal RPCs without that capability; this is
latent under shipped personas, not a demonstrated unconditional served DoS.

### terminal-output-consumed | low | repeated output calls lose the retained snapshot

Status: confirmed open; type: protocol/lifecycle. Two output calls after each
real child completed returned the full string then an empty string, because
`_acp_rpc_terminal_handlers.py:358` reads directly from pipes. The v1 retained
output model is absent. Owner: P01.S02; correction must keep killed terminals
addressable until explicit release and make output observations non-consuming.

### terminal-utf8-split | low | the fixed read size corrupts a complete character

Status: confirmed open; type: protocol/data integrity. A valid euro character
crossing byte 65536 became replacement characters in successive output responses.
The first string re-encoded to 65538 bytes, with truncated=false. Independent
per-chunk replacement decoding at `_acp_rpc_terminal_handlers.py:369` is not
UTF-8-safe retention. Owner: P01.S02; use continuous decoding and character-safe
tail truncation rather than modifying expected values to accept corruption.

### terminal-output-backpressure | low | large output can block command completion

Status: confirmed open; type: resource/lifecycle. A 32 MiB actual stdout producer
requesting outputByteLimit=4 timed out after a 15-second wait, remained alive with
21102592 bytes buffered and paused read transport, and never wrote its completion
marker. A 1 MiB control completed. Production spawn uses a 10 MiB StreamReader
limit at `_subprocess.py:319`; no owned continuous drain exists. No unbounded
capture claim is needed: the observed buffer/backpressure already violates the
requested cap and completion contract. Cleanup reaped all children and emptied
the registry. Owner: P01.S02; drain both pipes continuously into bounded retained
state with cleanup-owned tasks. Severity remains conditional on enabled terminal
authority, as explained above.

### native-callback-route-confirmed | high | actual native tools complete without filesystem or terminal ACP requests

Status: confirmed open route gap; type: enforcement reachability. The historical
acp-client-enforcement-unreached finding now has real Claude evidence instead of
only source inference. Installed adapter 0.85.1 exposes forwarding methods at
`node_modules/@agentclientprotocol/claude-agent-acp/dist/acp-agent.js:934`, `:977`,
and `:5854`, but its SDK query starts native tools at `:6985`. An authenticated
Haiku turn used native Read, Write and a Python command in a synthetic temporary
workspace. The unknown nonce was copied exactly, the command created its exact
marker file, and the turn ended normally while ZERO filesystem and ZERO terminal
ACP RPCs were observed. Incoming bytes were observed then passed to actual
production `_dispatch_stdout_line`; no handler was replaced. Optional console
marker observation was false, so the real command-created file is the terminal
completion evidence. Owner: P02.S05 and existing native enforcement workstreams.

The existing High classification describes the historical authority risk; this
probe does not demonstrate an active native-production private-state exploit.
Armed desktop native execution remains refused before acquisition, verified by
seven real desktop controls; permission posture, exact binary admission, and
persona denies remain independent protections. Unarmed development execution is
available. The newly accepted native-production retirement makes old application
Compose/setuid proofs historical, not native isolation certification. Claude
findings do not certify Kimi or other provider families. Callback correctness and
SDK request proofs cannot close the demonstrated native route gap.

### live-catalog-prerequisite-resolved | info | current IDs were discovered and supplied for the real turn

Status: resolved; type: verification setup. Initial completed-turn execution
skipped because no catalog entry was selected. The user then explicitly authorized
finding and filling the identifiers. Actual ProviderFactory discovery reported
the Claude lane authenticated and advertised Haiku; the five current identifiers
were passed to the child test and restored afterwards. The real candidate turn
passed with --require-prerequisite provider-catalog-live-selection, superseding
the earlier skip. The repository's `dev.providers` reporter generates these
opaque IDs. No model IDs or environment selection exports are committed.

### native-command-description-advertisement | low | real adapter command advertisements are blocked

Status: observed open follow-up; type: interoperability. Both native probes
logged two available command description is invalid refusals. Production
`_acp_protocol.py:127` validates a complete command snapshot and `:522` records
its refusal. Native tool work still completed. Exact offending entries and the
intended optional/empty-description contract need a separate focused assessment;
no security impact is inferred from this warning. Owner: provider command
advertisement validation follow-up, outside the retained-output repair.

### validation-format-and-discovery-environment | info | index and line-ending drift required explicit treatment

Status: resolved/recorded; type: tooling environment. Semantic discovery returned
index_unverifiable, so targeted source reads and Core feature/decision records
supplied grounding. No index mutation occurred. Full format initially detected
one mixed-line-ending docstring in service_tests/conftest.py; bounded Ruff
format normalized it with no tracked Git content diff. Final full formatting
passes. Concurrent native deployment and engine work remains outside this commit.

### terminal-output-remediation | low | All four retained-output defects remediated

2026-10-05 implementation and integrated review of P01.S02, based on verification checkpoint 2465a34e. Type: resource bounds and ACP interoperability; status: fixed. Strict `AcpTerminalCreateRequest` rejects negative, boolean, floating, string and out-of-uint64 caps before subprocess acquisition. The final retained-output budget is bounded to 0..1 MiB. Both real pipes drain continuously under terminal ownership, independently from cancellable RPC tasks. Separate incremental decoders preserve UTF-8 across reads; the combined bounded tail removes oldest complete characters and reports sticky truncation. Snapshots do not consume output, kill preserves it, and release joins the drain owners. Source: `src/vaultspec_a2a/providers/_acp_client_requests.py`, `src/vaultspec_a2a/providers/_acp_terminal_output.py`, `src/vaultspec_a2a/providers/_acp_rpc_terminal_handlers.py`, `src/vaultspec_a2a/providers/_acp_types.py`.

Original trigger substitution through the same real handlers: zero returns zero bytes; cap four returns only Z from A-emoji-Z; negative/string/bool are refused; absent/null retain the complete legitimate marker. The 65,536-byte boundary returns a valid 65,536-byte tail without replacements, and repeated snapshots are equal. The same real 32 MiB stdout producer now exits normally within the wait deadline, writes its completion marker, has zero unread buffered bytes and no paused read transport. Dedicated tests additionally complete 32 MiB on each pipe without output polling, clamp uint64 maximum to the server budget, preserve live and post-kill markers, flush malformed/incomplete input within the byte budget, and bound settlement when an exited root has a live descendant retaining pipes. All owned children and output records are reaped.

### terminal-output-review-fixture | low | Shared-ID ownership test now moves both owned registries

2026-10-05 independent candidate review finding. Type: test/lifecycle correctness; status: confirmed, corrected and verified in this pass. The existing same-ID test moved real process entries while abandoning the new output entries under old IDs, so release skipped its output-owner join. Both entries now move together; assertions prove receiving-context output removal, sibling preservation and completed drain tasks after both releases. Source: `src/vaultspec_a2a/providers/tests/test_acp_callback_ownership.py`. Desktop terminal fixture cleanup now calls the same complete owner release, and session cleanup checks both registries. The reviewer inspected the concrete corrections and found no further issue. No production bypass or regression was reported.

Integrated review verdict: PASS for P01.S02 and completed P01 behavior, with parent-owned final verification below. P02.S05 supported-adapter native callback routing and the command-description interoperability follow-up remain queued; their earlier validation is unchanged. Semantic code discovery was attempted again, found a stopped RAG service, and used targeted module/analogue reads with the accepted linked decisions. No shared index/service changes were made.
## Recommendations

Repair the four retained-output manifestations together within P01.S02's existing
accepted contract. Preserve the proven owner lifecycle and session guard. Keep
P02.S05 open: the real supported adapter completed native work but never invoked
the affected callbacks. Native execution authority must be proved independently,
including the active desktop isolation work. Record command advertisement drift
as an interoperability follow-up without weakening strict validation blindly.

## Verification

All Python checks use uv run --no-sync --frozen --no-default-groups --group tooling.
Pinned Node 26.8.1 was prepended only for child SDK/adapter tests.

- Real adapter handshake and desktop native execution controls: eight passed;
  the initial one live-turn skip was later superseded as recorded above.
- Permission posture and complete read/installed-SDK file: 107 passed, no skips.
- Current catalog-selected real Claude candidate turn with required prerequisite:
  one passed, producing a real answer; no handshake-only completion claim.
- Managed terminal observation script: executed successfully while demonstrating
  the four contract failures, including malformed range representations and the
  smaller-volume countercontrol. All owned processes reaped.
- Managed real native read/write/command proof: executed successfully; nonce and
  command file exact, end_turn, zero fs/terminal RPCs. No unsafe host file read.
- Full Ruff lint and Ty passed. Scoped Basedpyright on shared session, terminal,
  teardown and file-read schema: zero errors/warnings/notes.
- Final full Ruff formatting: 1987 files formatted, no diagnostics.

At checkpoint 2465a34e, validation was complete for the supplied remaining ACP candidates. The migration
is not complete: P01.S02, P02.S05 and integrated P03.S06 remain open. No new source
fix or closure of the historical High boundary is claimed by this audit.

### P01.S02 implementation verification, 2026-10-05

All commands retain the frozen uv tooling profile above. Final Windows focused terminal/output/ownership/resource-lifetime suite plus desktop terminal containment: 82 passed. Complete filesystem and installed SDK wire suite: 75 passed (the earlier combined run reported 76 including the same desktop test). Ubuntu frozen Python 3.13 environment, actual POSIX process groups, same four focused files: 81 passed. Total current applicable evidence: 157 distinct Windows tests and 81 Linux tests; no skip or mock introduced. SDK 1.6.0 over pinned Node 26.8.1 proves repeated output snapshots and explicit zero cap through negotiated production stdio dispatch. Current catalog-selected Claude native turn proof remains the earlier independently recorded evidence and does not stand in for callback traffic.

Final Basedpyright on all eleven changed source/test files: zero errors, warnings or notes. Full Ty, full Ruff lint, full Ruff formatting (1993 files) and git diff whitespace checks pass. Initial test import typo and formatting diagnostics were corrected before these final results. Managed original-trigger substitute and retained observed-fixed.json confirm remediation; historical failing reproduction remains preserved. The independent reviewer found one Low fixture issue, confirmed its correction, and no production bypass/regression. The retained artifact collection includes verify-fixed.py and observed-fixed.json under artifacts/05_findings/terminal-output-retention/validation_artifacts. P01.S02 closes only after these findings, checks and ledger are recorded; P02.S05 and P03.S06 remain open.
