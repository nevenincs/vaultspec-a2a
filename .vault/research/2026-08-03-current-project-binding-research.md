---
tags:
  - '#research'
  - '#current-project-binding'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:c63153ecb7521ed501a293df18f4fbc6b5d784d657d29c75b24db18083777b51'
related: []
---

# `current-project-binding` research: `how the dashboard project reaches agent execution and where it stops binding`

## Findings

### The expectation under test

The dashboard has a current project selection. The expectation is that this
selection is passed with the agent request and is then binding for all agent
work the run performs. This research traced that expectation from the dashboard
engine through admission, dispatch, graph compilation, subprocess spawn, and the
tool surface the agent is handed, and then back along the channels that return
data to the dashboard.

The expectation holds for the working directory and fails for the tool surface.
The selection binds where an agent STARTS; it does not bind what an agent can
REACH.

### There is no first-class current project

The orchestrator has no current-project concept. It has a mandatory per-run path
parameter and a derived discovery hash. The only stateful current project in the
system is the engine's active scope cell, a user-switchable pointer in engine
user state.

Five spellings exist across four authorities: the engine's active scope cell and
its wire form (an absolute path with POSIX separators and the extended-length
prefix stripped); the orchestrator's per-run workspace path; the orchestrator's
durable discovery hash, which is a case-folded, symlink-resolved digest and
therefore a SECOND canonical form; the semantic-search service's per-call project
root; and the framework command-line tool's per-invocation target. They agree on
the happy path only because the read seam re-normalises the engine's spelling.
No project-identity type crosses any boundary.

### The working-directory chain is sound

The engine selects its active cell, fences a browser-echoed scope, and injects
the workspace into the forwarded run body on every stage, accepting no
browser-supplied metadata. The orchestrator requires it at admission and
validates it as an existing directory, persists it, and threads it through
dispatch, the worker's graph cache key, graph compilation, and every provider
construction. At the subprocess it is required at the environment resolution
root, the spawn working directory, the session working directory, and the
filesystem and terminal sandbox roots. Follow-ups, clarification responses, and
verdict-driven resumes all re-read it from the durable row and refuse when it is
absent.

One path still tolerates absence: crash recovery degrades unreadable stored
metadata to nothing and constructs resume and message dispatches anyway, so the
refusal fires late at the provider seam rather than early and typed as the
follow-up path does.

### The tool surface is not bound to the project

The run's semantic-search tools accept a caller-supplied project root on every
call, resolved against any enrolled workspace on the machine and served by a
machine-global multi-root daemon. One of the auto-permitted read tools returns
full file content. Nothing on the orchestrator side inspects or pins tool-call
arguments, and nothing on the server side locks a stdio server to its launch
root once an explicit root is supplied - the launch-root binding is only the
default.

That default binding itself rides undeclared child-process working-directory
inheritance inside a third-party command-line tool. The registry entry sets no
environment, the agent environment is scrubbed of the variable that would pin the
root, and registry environment values are constrained to literals - so a per-run
pin cannot ride the current design at all.

The autonomous permission fallback compounds this. On the non-Kimi lanes,
autonomy leaves the permission callback unset and every uncovered tool call is
approved unconditionally. The search server mounts index-rebuild and index-clean
verbs beyond its three declared read tools; those are not allowlisted, so they
raise a permission request, which is then auto-approved. Combined with a
caller-selectable root, an autonomous run can mutate another project's index.

The framework command-line tool has the same shape by a different route: the
harness only checks that it resolves, its target is unconstrained, and the
terminal sandbox constrains the starting directory but never command arguments.
The vault write-deny exists only on the filesystem remote-procedure path, so
terminal commands bypass it.

### Verified is not the same as consumed

The harness verifies that the project carries rules, templates, skills, agent
definitions, and a server corpus. Rules, team configurations, and agent
configurations genuinely come from the project and shadow the orchestrator's
bundled defaults. Templates, skills, and the server corpus are verified only. The
server corpus in particular is read by nothing: the run's actual tool surface is
a closed, frozen registry inside the orchestrator package. The harness verdict
implies the project's declarations matter to the run, and they do not.

### The authoring write direction loses the run's identity

The orchestrator opens its authoring session with a literal scope constant and
carries no workspace identity in the session or proposal payloads. The engine
authorises mutating commands against its CURRENT active workspace at command
time, and resolves and applies against that same active worktree. While the
operator does not switch projects mid-run the two authorities coincide; a switch
makes a run's proposals fence against a different project than the one that
authored them. The start-time scope fence protects the start instant only, never
the run's authoring lifetime.

### The return channels carry no project identity

Only the catalog, active-runs, and run-start verbs are fenced to the active cell.
Every post-start verb is keyed by run identifier alone and is scope-blind, which
appears deliberate for reload correlation but is stated nowhere. Progress events
and authoring verdicts carry no project identity at all and correlate by
engine-unique identifiers. Artifact cleanup is the one place a returned thing is
re-anchored to its project, judging containment against the run's own recorded
workspace and refusing on a stale or missing root.

### What this means for the decision

The registry's trust model declares two axes per server: whether it writes
locally, and whether it reaches outward. Neither axis can express a scope
escape that arrives as a tool-call ARGUMENT. A server can be entirely read-only
and entirely local and still hand an agent another project's source, because the
project is chosen per call rather than per server. Deciding whether the trust
boundary is the server or the call is therefore the pivotal question, and it
bounds both of the high-severity findings.

## Sources

A read-only audit of the orchestrator repository at the commit that closed the
development/production boundary work, the dashboard engine repository at its
concurrent head, and the installed semantic-search package, conducted through
semantic search over both code and decision records, with every claim confirmed
against source by exact locator. Live lane behaviour was not exercised: no runs
were launched, so previously recorded live probes remain pending. The pinned
command-line binaries' child-process working-directory and skills discovery
behaviour were not verified, being binaries rather than source.
