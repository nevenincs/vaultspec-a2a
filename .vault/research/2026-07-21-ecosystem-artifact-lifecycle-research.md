---
tags:
  - '#research'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
related: []
---

# `ecosystem-artifact-lifecycle` research: `ecosystem artifact and output lifecycle sweep`

Where does every output this ecosystem produces go, who owns its lifetime, and do the
four projects agree? A seven-domain sweep covered a2a logging, persistent state,
orchestration traces, and test/build artifacts, then reconciled those against the output
contracts vaultspec-core, vaultspec-rag, and the dashboard declare.

The evidence picture is one-sided: creation contracts are strong and well-documented
across all four projects; lifecycle contracts are almost entirely absent. Every project
can state where an artifact lands, in what format, under what schema. Only vaultspec-rag
can state when it goes away — and its reclaim predicate cannot see the leak that
actually occurred. Two cross-repo contract breaks and one armed data-loss path were found
incidentally, because they live in the same seams.

## Findings

### Creation is specified; retention is not

No ADR in this repository governs transcript retention, run-artifact retention, or
workspace teardown. A survey of `.vault/adr/` found records governing worker process
architecture, harness provisioning, the authoring contract, and the desktop state layout,
but none establishing when any produced artifact is removed. The decision appears never
to have been made rather than made and violated.

The clearest expression of the gap is a contradiction inside one module.
`src/vaultspec_a2a/workspace/git_manager.py:196-202` documents the only retention
philosophy written anywhere in the codebase - worktrees are never removed automatically,
to preserve forensic state - and `create_worktree`, `remove_worktree`, and
`merge_worktree` have zero production callers; only the module-level `_git_mutex` at
`git_manager.py:45` is live. Meanwhile the richest real forensic record the system
produces, the pinned CLI's own session transcripts under the isolated `CLAUDE_CONFIG_DIR`,
is destroyed wholesale by `shutil.rmtree` at
`src/vaultspec_a2a/providers/_acp_config_home.py:200` on every `_astream` call, with
nothing reading, copying, or exporting it first. The stated policy attaches to code that
does not run; the shipped behavior is its opposite.

### The only workspace-creating verb has no location policy and no lifecycle owner

Exactly one production path creates a workspace directory:
`src/vaultspec_a2a/cli/provision.py:133`, reached from
`src/vaultspec_a2a/cli/main.py:523-545`. The path argument defaults to `"."`, accepts any
location, and is then populated with a full harness tree by
`vaultspec-core install --target`. There is no deprovision verb, no sweeper, and no TTL;
a failed provision raises after the `mkdir` at `cli/provision.py:137-140`, leaving the
tree behind permanently.

The runtime path does not create workspaces at all - `control/thread_service.py:323-327`
requires a caller-supplied `workspace_root` that already exists and rejects the request
otherwise, so agents execute directly in the user's real checkout with no filesystem
isolation boundary. `settings.workspace_root` at `control/config.py:116` is inert, read
only by a health payload at `api/app.py:467`.

Measured consequence: `C:\Users\hello\.vaultspec-rag` stands at 39 GB. Roughly 2.5 GB is
two repo-internal provisioned workspaces indexed as permanent first-class roots; about
0.47 GB is collections with no manifest entry, which are permanently exempt from
automated deletion by design; roughly 5 GB is dead worktrees still inside their
legitimate grace window and therefore not a defect.

### vaultspec-rag has the mature model, and a predicate one assumption too narrow

Of the four projects, only rag treats reclaim as a first-class concern: tiered grace
clocks, mandatory snapshot archive before any point-bearing drop, a per-cycle destructive
cap, path-containment guards, and an `unverifiable` class that is never auto-pruned on an
offline volume. Its module docstrings state the governing principle directly - managed
state lives in the per-host status directory and never the project tree.

Its ephemeral-reclaim tier was built for precisely the leak that occurred:
`storage_survey.py:44-49` describes a harness indexing a throwaway directory into the
shared backend and surviving pruning forever because the directory still exists. The
predicate `is_temp_rooted()` at `storage_survey.py:41-75` matches only OS temp locations,
so a throwaway workspace inside a repository tree never enters the candidate set filtered
at `storage_ops.py:657`. The mechanism is sound; its detection surface is too small.

Two secondary observations: `last_indexed` is empty for every manifest root despite
`store.py:494-518` stamping it from both indexers under a suppressed exception, and an
empty stamp resolves to a non-destructive `pending` decision at `storage_ops.py:662-674`,
so the tier fails safe but inert. Separately, the `is_temp_rooted` docstring claims the
flag is report-only and never feeds a destructive path, while `storage_ops.py:657` uses it
to select reclaim candidates; this was not resolved and needs a read of the lifecycle
caller before either side is treated as correct.

### Four state-home conventions, no shared resolver

a2a resolves `~/.vaultspec-a2a` from `VAULTSPEC_A2A_HOME` at `control/config.py:34,126`;
its process registry uses a separate `~/.vaultspec/procs` from `VAULTSPEC_PROCS_HOME` at
`lifecycle/registry.py:135-149`; rag uses `~/.vaultspec-rag` from
`VAULTSPEC_RAG_STATUS_DIR`, with an independently overridable Qdrant storage root; the
dashboard uses `~/.vaultspec` from `VAULTSPEC_APP_HOME`. vaultspec-core has no user-level
config home at all, keeping state project-relative except for MCP user-scope ownership.
None of these resolve through a shared implementation, and the dashboard's own decision
record flags that its uninstall story must name the sibling homes - an uninstall glob over
`~/.vaultspec*` would destroy both siblings.

a2a's database default compounds this: `control/config.py:82` resolves
`sqlite+aiosqlite:///vaultspec.db` relative to the current working directory, so the
database lands wherever the process was launched.

### The desktop edge is both broken and unauthenticated

Three independent defects sit in the a2a/dashboard seam, and all three are masked by the
same design choice.

`lifecycle/discovery.py:373-392` publishes `handoff_reference` only when a service token is
supplied, and otherwise unlinks the credential file. The live discovery record carries
four keys and no reference. The dashboard's reader requires only `port`, so this parses
cleanly and yields a null bearer, and its transport emits an `Authorization` header only
when a bearer is present - so brokered calls currently go out unauthenticated. The token
is passed at `api/app.py:436`, and `app.py:620` assigns it in the serve entrypoint while
`app.py:186` assigns it in the desktop branch, which indicates a launch path that bypasses
the former; this inference needs a live run to confirm rather than a further code read.

The dashboard's spawn path invokes a console script named `vaultspec-a2a-gateway`;
`pyproject.toml:46-48` declares only `vaultspec-a2a` and `vaultspec-a2a-mcp`. The
dashboard's own manifest and contract tests use the correct name, so it disagrees with
itself and the incorrect name is the one on the spawn path.

Under the armed desktop profile, `desktop/profile.py:108-117` places the discovery record
at `<app_home>/service.json`, while the dashboard searches for a differently-named product
record in that directory and for `service.json` in the other home entirely - both the
directory and the filename diverge.

All three degrade to HTTP 200 with a degraded tier by design, so a home mismatch, a schema
fork, a renamed handoff, and a genuinely absent service are indistinguishable to the
caller. Any reconciliation must key on the reason string, never the status code.

### An armed data-loss path

`control/thread_service.py:578` deletes files from the user's real workspace on hard
thread delete, driven by rows in the `artifacts` table. That table has no production
writer - `database/artifact_repository.py:45` is reachable only from a package re-export
and tests - so the path is inert today. It becomes destructive to the user's repository
the moment artifact persistence is implemented, which is itself a natural remedy for the
trace-loss finding below. The two must not be sequenced in that order.

### Traces are emitted and discarded

There is no message, transcript, or tool-call table in the model set at
`database/models.py:27`. Conversation content survives only inside LangGraph checkpoint
blobs, which have no pruning, depth cap, or vacuum, and are removed only on hard thread
delete. `artifacts`, `permission_logs`, and `cost_tracking` are dead tables, so the cost
read surface is guaranteed to return zero permanently. `streaming/transformer.py:200-218`
emits an artifact event for every file an agent writes, edits, or deletes, and it is never
persisted - the system knows exactly which files each agent touched and discards it. There
is no replay buffer; recovery is checkpoint re-projection.

### Smaller structural defects found in the same seams

The atomic write-and-rename pattern is implemented three times independently, at
`lifecycle/discovery.py:393-395`, `lifecycle/discovery.py:694-701` with its retry helper at
`705-721`, and `lifecycle/registry.py:264-268`. None unlinks its temporary file on a
failure path; the first produced an observed six-day-old orphan.

Four log-naming regimes coexist, two disjoint cleanup regimes share one runtime directory
and are unaware of each other, and the base service logs are covered by neither - they
rotate but are never deleted. The stock `RotatingFileHandler` configured at
`utils/logging.py:261-266` shifts generations in a loop with no per-iteration exception
handling, so a transient Windows lock during rollover permanently gaps the sequence; an
observed sibling-project log directory shows exactly that gap.

`providers/_acp_project_mcp.py:224` writes into a git-tracked file in the user's repository
on every armed run, and skips cleanup by design on a fingerprint mismatch. The test harness
at `service_tests/harness.py:30,158-160` creates directories in the real state home from a
dataclass constructor, with no teardown anywhere in the package. Several generated
artifacts are unmatched by ignore rules.

### What the option space looks like

The evidence favors treating retention as a declared property of every output rather than
as per-subsystem cleanup code, because the recurring failure is not absent cleanup but
cleanup that cannot see its targets - rag's predicate, the two disjoint log regimes, and
the manifest-blind reaper are the same shape three times. vaultspec-core has already
established the precedent worth extending: its CLI output standardization record reasons
that the primary reader is a language model rather than a human, and fixes shapes and a
machine contract accordingly. The open question the ADR must settle is whether that
discipline extends from command output to produced artifacts, and if so what a declaration
must contain and where it is enforced.

Not investigated: whether the dashboard's uninstall implementation actually globs the
sibling homes; the precise writer of two observed rag artifacts; the `ty` cache location;
and whether the dashboard tree currently compiles, since its console-script disagreement
may be refactor-in-flight rather than settled contract.

## Sources

`src/vaultspec_a2a/workspace/git_manager.py:45`,
`src/vaultspec_a2a/workspace/git_manager.py:196-202`,
`src/vaultspec_a2a/providers/_acp_config_home.py:200`,
`src/vaultspec_a2a/providers/_acp_project_mcp.py:224`,
`src/vaultspec_a2a/cli/provision.py:133`, `src/vaultspec_a2a/cli/provision.py:137-140`,
`src/vaultspec_a2a/cli/main.py:523-545`,
`src/vaultspec_a2a/control/thread_service.py:323-327`,
`src/vaultspec_a2a/control/thread_service.py:578`,
`src/vaultspec_a2a/control/config.py:34`, `src/vaultspec_a2a/control/config.py:82`,
`src/vaultspec_a2a/control/config.py:116`, `src/vaultspec_a2a/control/config.py:126`,
`src/vaultspec_a2a/api/app.py:186`, `src/vaultspec_a2a/api/app.py:436`,
`src/vaultspec_a2a/api/app.py:467`, `src/vaultspec_a2a/api/app.py:620`,
`src/vaultspec_a2a/lifecycle/discovery.py:373-392`,
`src/vaultspec_a2a/lifecycle/discovery.py:393-395`,
`src/vaultspec_a2a/lifecycle/discovery.py:694-701`,
`src/vaultspec_a2a/lifecycle/discovery.py:705-721`,
`src/vaultspec_a2a/lifecycle/registry.py:135-149`,
`src/vaultspec_a2a/lifecycle/registry.py:264-268`,
`src/vaultspec_a2a/desktop/profile.py:108-117`,
`src/vaultspec_a2a/database/models.py:27`,
`src/vaultspec_a2a/database/artifact_repository.py:45`,
`src/vaultspec_a2a/streaming/transformer.py:200-218`,
`src/vaultspec_a2a/utils/logging.py:261-266`,
`src/vaultspec_a2a/service_tests/harness.py:30`,
`src/vaultspec_a2a/service_tests/harness.py:158-160`, `pyproject.toml:46-48`,
`Y:/code/vaultspec-rag-worktrees/main/src/vaultspec_rag/storage_survey.py:41-75`,
`Y:/code/vaultspec-rag-worktrees/main/src/vaultspec_rag/storage_ops.py:657`,
`Y:/code/vaultspec-rag-worktrees/main/src/vaultspec_rag/storage_ops.py:662-674`,
`Y:/code/vaultspec-rag-worktrees/main/src/vaultspec_rag/store.py:494-518`,
`Y:/code/vaultspec-core-worktrees/main/src/vaultspec_core/core/gitignore.py:22-80`.

Disk measurements were taken on this host on 2026-07-21 and are point-in-time. The
launch-path explanation for the absent service token is an inference from two assignment
sites and is not verified by a live run.
