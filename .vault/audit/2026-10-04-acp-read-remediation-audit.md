---
tags:
  - '#audit'
  - '#acp-read-remediation'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:4aac655fbebe6c2cff184b786b1275af64b5c80b4bb5adde9cc672f1c3dcc388'
related:
  - "[[2026-10-04-acp-read-remediation-plan]]"
---
# `acp-read-remediation` audit: `Sequential validation and ACP read review`

## Scope

Review of the sequential work authorized by the user on 2026-10-04.
S01 verifies hook removal and current validation recovery; S02 and S03
cover the ACP filesystem read contract and its integrated checks.

## Findings

### commit-hook-removal | low | the commit hook was removed through its owning harness

Status: resolved; type: development workflow configuration. The user
explicitly requested removal. `python -m dev.repo.hooks remove` returned
`removed`, and the resolved `pre-commit` path was verified absent.
The hook configuration remains available for manual verification.

### transient-validation-failures | low | concurrent engine-peer and worker test typing failures are resolved

Status: resolved; type: static typing and integration concurrency. Seven
Ty diagnostics initially pointed at broad `self.server.server_address`
types in three real HTTP peers and a string action passed to a Literal
worker contract. Concurrent owners corrected the HTTP server narrowing and
`server_port` access and narrowed the test action to its supported
Literal values. This executor made no overlapping source edits.
Review of the resulting code found no newly introduced issue.

Verification: full locked `ruff check src dev docs scripts packaging`,
`ruff format --check src dev docs scripts packaging` (1122 files), and
`ty check src dev docs scripts packaging` passed. The real
`test_client_reresolve.py`, `test_discovery_unit.py`, and
`worker/tests/test_desktop_workspace_boundary.py` suites passed all
16 tests. The initial commit-hook blocker is resolved by explicit hook
removal; required checks continue to run manually.

## Recommendations

S02 closes the filesystem read byte, line, and session findings. Keep the
sibling request ownership and native-tool enforcement findings open under
the earlier ACP migration plan. Continue to preserve concurrent source changes.

## S02 implementation and review, 2026-10-04

### negative-and-malformed-read-ranges | low | strict request domains prevent unbounded reads

Status: resolved; type: security/input validation. `AcpFileReadRequest` and
`AcpFileReadRange` require actual non-boolean integers: a one-based uint32
line and a non-negative uint32 line limit, with omitted/null values accepted.
Legacy top-level offset is refused rather than silently reinterpreted. Negative
numbers/strings, fractions, booleans, containers, oversized integers, and line
zero fail before filesystem access. The reported `limit=-1` cannot reach an
unbounded stream read. The configured byte maximum is constrained by `ge=0`
and revalidated before I/O, including when a runtime override sets it negative.
Existing error envelopes remain `-32603`.

### utf8-read-budget | low | the surfaced text obeys an independent byte budget

Status: resolved; type: security/resource limits and contract correctness.
Both ordinary and anchored descriptor readers use the same bounded line-chunk
reader. It counts lines separately from chunks, counts surfaced UTF-8 bytes,
and returns a complete-character prefix. Limit zero or byte cap zero returns
empty content; omitted ranges read from the first line up to the byte cap.
Long skipped and selected lines, multibyte boundaries, and universal newline
normalization are exercised with real files. Skipping to a late line may scan
the preceding content, but each allocated chunk is bounded.

### read-session-and-line-contract | medium | reads now implement accepted ACP v1 semantics

Status: resolved for filesystem reads; type: protocol/authority contract.
`setup_session` binds the negotiated session identifier to the process context.
The handler requires that exact identifier before dispatching threaded I/O.
One-based line selection and line-count limits replace legacy offset and
character-count limits as required by the accepted ACP v1 client-wire ADR.
Legitimate vault reads and workspace confinement remain covered. This resolves
the read-specific residuals in the older architecture audit; it does not close
the larger migration plan or its sibling request families.

### provider-node-dependency-skew | low | installed adapter did not match the lockfile

Status: resolved; type: verification/environment. The extended Windows suite
initially had six adapter-source failures: installed adapter 0.59.0 lacked
modules supplied by locked 0.84.0. Restored dependencies with official,
SHA256-verified portable Node 26.8.1 and npm 11.19.0, then `npm ci`; 106 packages
installed, audit reported zero vulnerabilities. Package manifests and lockfiles
were unchanged. The affected 156-test suite subsequently passed.

### linux-race-proof-filesystem | low | descriptor-race tests require native Linux rename semantics

Status: resolved; type: verification/environment. A first WSL confinement run
on Windows-mounted DrvFs failed two parent-rename probes with ENXIO, including
an unchanged write probe. Rerunning on native Linux `/tmp` with secure callbacks
enabled passed all 113 read and confinement tests without skips. This is the
secure-backend evidence; the Windows run retains three existing Linux-only skips.

### callback-race-probe-refusal | medium | a direct reader refusal escaped the updated test

Status: resolved; type: introduced verification regression. Candidate review
identified that moving the root-component race probe from the JSON handler to
the direct reader exposed NotADirectoryError, an OSError. The probe now accepts
ValueError or OSError as a refusal and still fails if the read succeeds. The
three Docker boundary tests pass, including the replaced-root and parent races.

### stale-launcher-probe-import | low | the Docker probe used a renamed private helper

Status: resolved; type: pre-existing verification drift. The initial Docker
run failed importing `_provider_execution_command`; production exposes
`provider_execution_command`. Updated the proof's import and invocation to the
actual production helper. The partial identity configuration still fails closed.

### sdk-transport-evidence | low | echo pipes alone did not prove installed schema integration

Status: resolved for callback contract evidence; type: verification coverage.
The fresh reviewer found no surviving read bypass but requested the installed
transport path. A real Node process uses locked ACP SDK 1.5.1, negotiates through
production initialize/setup_session, and emits SDK filesystem requests through
production stdout dispatch. It verifies selected-line UTF-8 truncation, zero
limit, and foreign-session refusal. The pinned Claude adapter separately passes
its real initialize/session-new surface test. The SDK peer is not a Claude
model turn and does not prove native tools invoke ACP callbacks.

### sibling-session-authority-debt | medium | write and terminal callbacks remain unmigrated

Status: open, pre-existing; type: protocol/authority debt. The reviewer traced
`on_fs_write_text_file` ignoring its context, terminal creation lacking session
validation, and terminal addressing using only terminalId. These are owned by
`2026-08-02-llm-context-provider-abstraction-plan`, P02.S05 and terminal Steps,
and remain outside the authorized read-remediation plan.

### native-callback-reachability | high | native tools do not establish this client enforcement boundary

Status: open, pre-existing; type: enforcement reachability. Preserve the existing
`acp-client-enforcement-unreached` audit finding under the earlier migration plan.
Review of installed Claude adapter code found forwarding readTextFile methods
but no native-tool caller. No fresh Kimi source proof is available here. This
patch establishes callback correctness and does not close native-tool enforcement.

## Verification and final review

All commands use the locked tooling profile:
`uv run --no-sync --frozen --no-default-groups --group tooling`.

- `ruff check src dev docs scripts packaging`: pass.
- `ruff format --check src dev docs scripts packaging`: pass, 1123 files.
- `ty check src dev docs scripts packaging`: pass.
- `basedpyright` on `_acp_fs_read.py`, `_acp_rpc_handlers.py`, `_acp_types.py`,
  `_acp_session.py`, and `test_acp_fs_read_limits.py`: zero errors/warnings/notes.
- Windows pytest read-limits, vault-deny, project-confinement, Claude permission
  posture, and desktop workspace boundary: 156 passed, three existing Linux skips.
- Linux secure pytest read-limits and project-confinement: 113 passed, zero skips.
  WSL Ubuntu used frozen uv.lock dependencies in a separate temporary environment,
  `VAULTSPEC_A2A_PROVIDER_IDENTITY_LAUNCHER=/bin/true`, agent GID 1000, byte cap 32,
  and native `--basetemp=/tmp/vaultspec-acp-native-tests-20261004`.
- `pytest .../test_acp_fs_read_limits.py::test_installed_sdk_reads_over_a_negotiated_session -m service -q`:
  one passed using pinned Node 26.8.1, installed locked SDK 1.5.1.
- `pytest .../test_acp_migration_surface.py -m service -q`: one passed using
  the real locked Claude ACP adapter 0.84.0 and pinned Node.
- `pytest src/vaultspec_a2a/service_tests/test_compose_provider_service_state_isolation.py -m service -q`:
  three passed in isolated Docker image and test-owned volumes.

The independent read-only review found no surviving read-cap, pagination, or
session-ownership bypass. Its confirmed probe regression was repaired and
checked; every surfaced item above has severity, type, status, and ownership.
Semantic discovery returned `index_unverifiable`, so targeted code searches
and Core ADR queries supplied grounding. Concurrent source and vault changes
remain outside the authored commit.

## S03 integrated checkpoint

Final review verdict: PASS. The follow-up review accepted the confirmed race
probe repair and installed-SDK transport evidence; no new defect remained in
the authored read changes. Full quality checks and focused Windows, Linux,
installed SDK, real adapter, and Docker evidence above are the final results.
The feature-scoped vault checks also passed without diagnostics.

S02 committed as `e39c2ff9`, containing only authored source/test changes and
its plan, ledger, and audit checkpoint. Shared source files were committed at
hunk granularity using an isolated index, preserving concurrent workspace
boundary and discovery work. The hook remains absent after committing.

The architecture-review audit now appends the later read-specific resolution
without rewriting its historical intermediate findings. Every surfaced review
item is recorded above; sibling protocol authority and native callback
reachability remain explicitly open with their existing owners. S03 completes
this read-remediation plan, not the larger provider migration.

### older-architecture-step-in-flight | info | existing ledger rows refer to an open Step

Status: in flight, pre-existing; type: execution checkpoint advisory.
The architecture-review feature vault check passed with one informational
exec-mapping item: its ledger already records S50 while that plan Step remains
open. The owning architecture-review plan continues that work; no metadata was
changed by this read-remediation pass. The acp-read-remediation feature has no
vault health diagnostics.

### audit-markdown-hygiene | info | an appended body left an extra trailing blank line

Status: resolved; type: introduced documentation formatting. Feature-scoped
vault checks surfaced one extra blank line after the S03 body append. The
owning `vault check markdown --feature acp-read-remediation --fix` removed it;
subsequent feature health checks returned no diagnostics.

### concurrent-adapter-upgrade-reverification | info | final transport evidence includes the newer installed dependencies

Status: verified; type: integration checkpoint. Another workstream changed
package.json and package-lock.json to Claude ACP adapter 0.85.1 and ACP SDK
1.6.0 after the earlier 0.84.0/1.5.1 evidence. Those dependency changes were
preserved and excluded from this pass's commits. With pinned Node 26.8.1,
reran the installed-SDK callback test, real adapter migration-surface handshake,
and complete permission-posture file with `-m 'service or not service' -q`:
34 passed. No additional source fix was needed.
