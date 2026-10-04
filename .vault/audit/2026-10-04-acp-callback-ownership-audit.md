---
tags:
  - '#audit'
  - '#acp-callback-ownership'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:d73ab1b63b56f6b63750a8a6114e080cc26243056d99c603d1a5978226e2bc55'
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
