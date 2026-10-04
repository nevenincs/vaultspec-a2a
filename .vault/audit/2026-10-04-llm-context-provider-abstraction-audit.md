---
tags:
  - '#audit'
  - '#llm-context-provider-abstraction'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:be34b757b0e77275ad16659a8e5f5af2c2de87c9fba9915ef335d03f4447ba1c'
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

Validation is complete for the supplied remaining ACP candidates. The migration
is not complete: P01.S02, P02.S05 and integrated P03.S06 remain open. No new source
fix or closure of the historical High boundary is claimed by this audit.
