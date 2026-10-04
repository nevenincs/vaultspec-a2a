---
tags:
  - '#audit'
  - '#acp-callback-ownership'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:1e4fe35d8b08dad1ed5ef6bdf67a9f961a16bb53dc22f2b1029d126fa4b8a873'
related:
  - "[[2026-10-04-acp-callback-ownership-plan]]"
  - "[[2026-10-04-acp-read-remediation-audit]]"
---
# `acp-callback-ownership` audit: `ACP callback ownership review`

## Scope

Sequential continuation of the Medium sibling session authority finding from
`2026-10-04-acp-read-remediation-audit`. Governing accepted decision:
`2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr`.

## Findings

### callback-session-authority | medium | filesystem writes and terminals accept unowned session requests

Status: open; type: protocol/authority validation. The write handler ignores its
context and terminal creation/addressing resolve commands or terminal ids without
session validation. The production context already carries the negotiated session.
S01 owns write enforcement and a shared validated session guard; S02 owns every
terminal callback and teardown integration. Native callback reachability remains
separate and open under the older provider migration plan.

### semantic-discovery-unverifiable | info | semantic index cannot supply authoritative code results

Status: recorded; type: discovery environment. Locked RAG search returned
index_unverifiable; service status confirms failed indexing. Targeted source
inspection and Core ADR listing supplied grounding. No index mutation performed.

## Recommendations

Finish the two ownership repairs and verify their cleanup and real-wire paths.
Keep output-retention and native-tool enforcement in their existing audit queue.

## S01 write boundary and review

### filesystem-write-session-ownership | medium | writes require the negotiated session before any path work

Status: resolved; type: protocol/authority validation. Before repair, the real-file
suite failed ten invalid-session controls while the owner write passed. Strict
AcpSessionRequest rejects missing/null/non-string/empty/oversized identifiers;
its shared guard compares exact context identity. The write handler guards before
path resolution and again after acquiring the actual workspace mutex. Reads reuse
that same guard without weakening their range schema. Existing owner writes,
vault forbidden_actor denials, workspace confinement, and capability dispatch
remain covered. Terminal ownership remains S02's open responsibility.

### write-admission-after-session-close | medium | a waiting write could submit I/O during teardown

Status: resolved; type: lifecycle authority. Candidate review reproduced the gap
using a real process, production stdout loop, and production session teardown:
a queued write landed after ctx.closing became true, even though cleanup cancelled
its task. The guard now refuses closing contexts. The reviewer reran the same
reproduction: no file landed and -32603 reported ACP session is closing. A real
mutex regression test also covers session replacement and closure after waiting.
The two parametrizations share their loop so the actual production global mutex
retains its native loop ownership; no replacement lock is introduced.

### compose-proof-without-protocol-authority | medium | a missed probe passed None as a session context

Status: resolved; type: introduced verification regression. Candidate review
found the initial callback-created.txt probe still using an omitted sessionId
and None context after sibling probes migrated. All intended low-level filesystem
containment probes now call the actual confined I/O helpers, while negotiated SDK
traffic separately proves callback authorization. Docker's three real boundary
proofs pass without protocol bypasses or manufactured session contexts.

### root-component-race-hook-drift | low | the confinement refactor changed the native open target

Status: resolved; type: pre-existing verification drift. The concurrent filesystem
authority refactor walks absolute-root components with directory descriptors,
while the old proof hooked an entire managed-root Path. Adapted the existing race
hook to its actual managed directory component and assert it really swapped the
component. The read remains refused. The Docker helper now reports captured stderr
on any nonzero exit instead of hiding the underlying proof failure in a long
subprocess command representation.

### linux-proof-group-selection | low | an outdated test GID prevented legitimate secure writes

Status: resolved; type: verification/environment. Initial WSL execution used GID
1000 and failed three legitimate writes with EPERM; `id` established that this
Ubuntu user belongs to GID 1002. Rerunning with that actual group and native /tmp
files passed 64 tests with secure callbacks enabled and no skips. No production
permission policy was relaxed.

### concurrent-quality-drift | low | unrelated work introduced temporary full-scope lint errors

Status: resolved; type: integration/formatting. Full lint/format initially found
import ordering and long lines in concurrent authoring and telemetry proof files.
The owner corrected import order. Only mechanical string/argument wrapping was
applied to the remaining long lines; functional changes in those files remain
outside the callback ownership commit. Full locked Ruff lint/format (1139 files)
and Ty now pass. No runtime test expectation was changed to satisfy a failure.

Verification: Windows callback/read/vault/authoring/confinement/desktop suites:
192 passed, three existing Linux-only skips, one SDK service deselected. Native
Linux callback/confinement/vault: 64 passed, no skips; agent launcher /bin/true,
actual GID 1002, cap 32, native --basetemp under /tmp. Installed ACP SDK negotiated
read/write traffic: one passed, owner file lands and foreign write is refused.
Docker Compose identity/filesystem boundary: three passed. Full Ruff lint/format
and Ty passed; scoped Basedpyright reported zero errors/warnings/notes. Independent
candidate review found no surviving S01 bypass after the two confirmed repairs.

## S02 terminal authority and review

### terminal-session-ownership | medium | every terminal callback requires the receiving session

Status: resolved; type: protocol/authority validation. The original production
handlers admitted terminal creation and addressing without session validation.
Strict AcpSessionRequest guards creation before command/path/environment work and
again after awaited spawn, before registration. AcpTerminalRequest validates the
session and a nonempty string terminalId before output, wait, kill, or release
can look up the receiving context's registry. Invalid, absent, foreign, unbound,
and closing sessions return error envelopes without spawning, consuming pipes,
killing processes, or removing registrations. Two genuine contexts sharing one
terminal id prove a foreign request cannot select the sibling registry. Owner
calls preserve unknown-id refusal, release idempotence, exit-status objects,
post-kill addressability, and subtree reaping. No compatibility alias was added.
The independent read-only candidate review found no surviving authority bypass
or introduced lifecycle regression across dispatch, facade, and teardown paths.

### teardown-protocol-admission-conflict | medium | internal cleanup needs no live RPC admission

Status: resolved; type: lifecycle compatibility risk identified before repair.
Production teardown marks the context closing and previously synthesized a
release request without sessionId. Enforcing the public guard there would leak
children. The existing cancellation-joined cleanup body now lives in
release_owned_terminal; public release validates first, while teardown calls the
local helper directly. A real partial-setup context with no session id proves
both provider and terminal processes are reaped and the registry emptied.
Existing cancellation, exited-root descendants, foreign-process preservation,
and process-tree proofs remain applicable and pass.

### terminal-proof-session-fixtures | low | existing direct terminal proofs lacked required protocol identity

Status: resolved; type: verification/contract drift. Existing containment and
security callers now send the actual context's negotiated id. The desktop tree
proof uses a real AcpSessionContext backed by a production-spawned process instead
of a cast substitute context. Initial verification caught four keyword-form
security calls missed by the first migration and an async fixture declared with
the synchronous decorator; both were repaired. Missing terminalId now asserts
invalid params, while a valid unknown terminal keeps its established refusal.

### terminal-proof-newline-portability | low | Windows text output changed the expected marker bytes

Status: resolved; type: introduced verification portability. Eight initial proof
failures came from text-mode CRLF translation. The actual child now writes the
specified LF marker through sys.stdout.buffer. Exact byte assertions remain;
no output expectation or runtime policy was weakened.

### terminal-output-retention-and-native-reachability | low | broader v1 evidence remains with the migration plan

Status: open, pre-existing; type: protocol/resource and verification debt.
S02 does not change outputByteLimit handling or consuming output reads. The
accepted v1 output-retention repair remains owned by
2026-08-02-llm-context-provider-abstraction-plan P01.S02. Exact native supported
adapter callbacks remain P02.S05, and the earlier High reachability finding stays
open unless its independent owner supplies native execution evidence. The real
SDK peer below proves protocol transport and callback behavior, not a model's
native-tool routing. No new authority defect was discovered in this candidate.

Verification uses uv run --no-sync --frozen --no-default-groups --group tooling.
Windows pytest callback-ownership, terminal-containment, resource-lifetimes,
ACP-security, desktop-native-execution, and the owned terminal tree proof:
112 passed, one existing service test deselected. WSL Ubuntu callback-ownership,
terminal-containment, resource-lifetimes, and ACP-security with native /tmp
basetemp, no artificial identity launcher: 104 passed, one service deselected.
Pinned Node 26.8.1, installed ACP SDK 1.6.0, production initialize/setup_session
and stdio dispatch: SDK read/write/create/wait/output/kill/release traffic and
real terminal-grandchild service proof: two passed, 81 ordinary tests deselected.
SDK traffic refuses foreign read/write and all four terminal-addressing methods;
owner terminal output and exit status succeed, kill retains addressability, and
repeated release succeeds. Full ruff check ., ruff format --check . (1982 files),
and ty check passed. Scoped basedpyright on the three implementation files,
ownership/read-wire tests, and desktop tree proof: zero errors/warnings/notes.
Docker filesystem proofs from S01 are reused because S02 changes no filesystem
containment code. Hook presence remains false after the S01 commit.

## S03 integrated audit checkpoint

Final integrated verdict: PASS. Independent source review found no surviving
callback session-authority bypass or introduced terminal lifecycle regression;
parent-owned Windows, Linux, SDK, process-tree, and strict quality evidence above
satisfies required verification. The original Medium callback-session-authority
finding is resolved in both S01 (14747a0d) and S02 (9532ab35). The read guard from
the earlier remediation, write admission after the real workspace mutex, and all
terminal entrypoints now share the negotiated-session boundary. Every surfaced
issue in this pass has severity, type, status, and an owner in this rolling audit.
S03 reconciles the earlier read and architecture records by appending later
resolutions without rewriting their historical findings. The older ACP v1 plan
P01.S01 now has complete read-pagination and session-identity evidence; remaining
output retention and native supported-adapter callback evidence retain P01.S02
and P02.S05 ownership. Neither the SDK peer nor a handshake closes that native
model-tool routing gap. Concurrent desktop fail-closed execution work remains
its independent owner's evidence and commit. This plan closes callback ownership.

### callback-vault-scaffold-hygiene | info | initial annotations and whitespace needed Core repair

Status: resolved; type: documentation/tooling hygiene. Initial scaffold annotation
removal left transient body-hash/blank-line diagnostics. The feature-scoped owning
Core checks repaired them before S01. Final callback feature health and explicit
commit-gate checks have no blocking diagnostics. No vault metadata or progress
checkboxes were hand-edited. The user's hook removal remains in effect after
both implementation commits. Concurrent source and vault changes remain outside
these scoped commits.
