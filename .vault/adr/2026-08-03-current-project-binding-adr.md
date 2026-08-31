---
tags:
  - '#adr'
  - '#current-project-binding'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:2ff30d4abc3a3d96d01aa6fc052acb4c5c55ffd749639ce0510e734ea2878db0'
related:
  - "[[2026-08-03-current-project-binding-research]]"
---

# `current-project-binding` adr: `the active project is a run-bound scope, and the trust boundary is the call` | (**status:** `accepted`)

## Problem Statement

The dashboard's project selection is expected to be binding for all agent work a
run performs. It is not. As established by the research, the selection binds the
directory an agent starts in and nothing else: the tools the agent is handed take
a project as a per-call argument, resolved against any enrolled workspace on the
machine, so a run scoped to one project can read another's source and vault, and
under autonomy can mutate another's index.

A decision is needed because the registry's trust model cannot express this. It
declares two axes per server - whether the server writes locally, and whether it
reaches outward - and a server that is entirely read-only and entirely local
still hands an agent another project's content, because the project is chosen per
call. The escape is in the argument, and no per-server assertion reaches it.

## Considerations

There is no first-class run-scoped project identity to enforce against: the
orchestrator holds a path parameter, the engine holds a mutable pointer, and the
search service takes a per-call root. Enforcement needs something to enforce.

The default project binding today rides undeclared child-process
working-directory inheritance inside third-party binaries. It is correct as far
as anyone has checked and is verified for none of them.

A per-run pin cannot ride the current registry: it sets no environment, the agent
environment is scrubbed of the variable that would carry it, and registry
environment values are deliberately constrained to literals so that a placeholder
cannot be expanded from the serving process's environment.

The autonomous permission fallback approves any uncovered call on the non-Kimi
lanes. One lane already demonstrates the alternative: an exact-name read
allowlist enforced at the permission layer.

The terminal surface is a general escape. The vault write-deny exists only on the
filesystem remote-procedure path, and the framework command-line tool's target is
unconstrained, so confinement expressed only in the tool registry is incomplete
by construction.

The authoring write channel derives its target from engine-global mutable state
at command time rather than from the authoring run.

## Considered options

**Trust the server, keep declaring per-server axes.** The status quo. Cheap and
already built, but structurally incapable of expressing an argument-borne scope
escape. Rejected: it is the model that produced both high-severity findings.

**Trust the call: pin the project per run and refuse calls that name another.**
The agent's tools operate on the run's project or they fail. Requires a run-bound
identity to pin against and a seam to carry it. Chosen.

**Inspect and rewrite tool-call arguments orchestrator-side.** Would work without
changing the servers, but puts the orchestrator in the business of understanding
every tool's schema, and silently rewriting an agent's argument is a
different-answer-than-asked hazard. Rejected as the primary mechanism; retained
as a defensive check where a server cannot be pinned.

**Lock the server to its launch root for stdio sessions.** The cleanest
enforcement point, since the server already knows its launch root and uses it as
the default. Requires a change in a separately released component. Chosen as the
primary mechanism, with the orchestrator-side check as the backstop until it
lands.

**Drop the search tools from autonomous runs.** Would close both findings
immediately and remove the grounding capability the runs exist to use. Rejected
as a permanent posture; acceptable only as a temporary containment if the
primary mechanisms slip.

## Constraints

The wire contract to the dashboard must not change: the engine already supplies
the workspace on every stage.

Registry environment values remain literals. Any per-run pinning seam must be
explicit and separate from the frozen registry, not a relaxation of it.

The read-only composition boundary stays: declared, allowlisted tools remain the
advertised surface, and this decision does not widen it.

Grounding capability must survive. A run must still be able to search and read
its own project.

## Implementation

The active project becomes a first-class, run-bound scope. It is minted once, at
admission, from the workspace the engine supplied, in one canonical form, and
carried as an explicit value rather than re-derived at each boundary. The
existing durable discovery hash remains the storage selector; the canonical form
is what crosses boundaries and what enforcement compares against.

The trust boundary moves from the server to the call. Every registry server
gains a third declared property stating whether it is root-pinnable. A pinnable
server is launched pinned to the run's project through an explicit per-run
pinning seam, separate from the frozen registry so the literals-only rule stands.
A server that cannot be pinned may not be surfaced to a run at all until it can
be, which makes the absence of pinning a composition-time refusal rather than a
runtime hope.

Enforcement is layered rather than singular, because the primary mechanism lives
in a separately released component. The search service locks a stdio session to
its launch root, so an explicit root naming a different project is refused at the
server. Until that lands, the orchestrator refuses a tool call whose arguments
name a project other than the run's, at the permission layer where calls already
pass.

The autonomous permission fallback stops approving uncovered calls on every lane.
The exact-name read allowlist already proven on one lane becomes the rule for all
of them, so an uncovered call is refused rather than approved and a server's
unadvertised verbs are unreachable regardless of what it mounts.

The authoring session carries the run's project, and the engine validates each
authoring command against the session's pinned scope rather than the active
workspace at command time.

Crash recovery refuses an absent project early and typed, matching the follow-up
path, rather than dispatching and failing late at the provider seam.

Harness verification and the run's actual surface are reconciled: either the
project's declared server corpus becomes an input to composition, or the harness
stops verifying a surface the run does not consume. This decision does not choose
between those; it forbids the current state where the verdict implies a
relationship that does not exist.

## Rationale

Pinning at the call is the only boundary that matches where the escape lives.
Per-server assertions describe a server's nature; the project is chosen per
invocation, so only a per-invocation check can bind it.

Minting the identity once, at admission, gives enforcement something to compare
against and removes the re-derivation that let four authorities drift into
agreement-by-coincidence.

Layering server-side locking over an orchestrator-side refusal accepts that the
strongest enforcement point is in another release cycle without leaving the
findings open until it arrives.

Replacing blanket approval with the proven allowlist removes an entire class of
reachability: it stops mattering what a server mounts beyond what it declares.

## Consequences

Good: a run can no longer read or mutate a project other than its own through the
granted tool surface. The active project becomes something the system can name,
carry, and enforce rather than a path that happens to be passed. A server's
unadvertised verbs stop being reachable by approval fallback. The authoring
channel stops depending on the operator not switching projects mid-run.

Bad: a third declared registry property makes every existing entry incomplete
until declared, which is intended - omission must not read as permission - but is
migration work. Cross-project grounding, if any workflow relied on it, is
removed. The primary enforcement depends on a change in a separately released
component, so the orchestrator-side refusal must be built even though it is meant
to become redundant. An exact-name allowlist on every lane will refuse calls that
blanket approval previously let through, and some of those refusals will be
legitimate work that must be declared before it runs again.

Neutral: the terminal surface remains a broader escape than the tool registry can
close, and this decision does not address it. The unverified assumption about
child-process working-directory inheritance stops being load-bearing once pinning
is explicit, but is not itself resolved. Version authority for agent-facing
tooling, and whether post-start control-plane verbs should assert project
identity, are deferred as separate decisions.
