---
tags:
  - '#audit'
  - '#production-boundary'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:8c3df65f0f6492b7046323a69a7d989aebfde30bfe284558991e3d8e26133896'
related:
  - '[[2026-08-03-production-boundary-adr]]'
---

# `production-boundary` audit: `development conditions reaching production code`

## Scope

Where production code hardcodes conditions that only hold in a source checkout,
and how logs, files, databases, and canonical data storage are defined. The
audit covers the settings module that owns path resolution, the database and
migration paths, the logging lanes, the packaging boundary, the shipped
container topology, and the chain that decides which directory agent
subprocesses execute against.

Every finding below was verified by execution or by reading shipped build
configuration, not inferred. Findings are recorded with severity, type, and
status; those already closed name the change that closed them.

## Findings

### ambient-agent-siting | critical | agent execution and its sandbox roots resolved to the serving process directory

Type: security boundary. Status: CLOSED.

A run whose metadata envelope was absent reached the provider layer with no
workspace, and ten fallbacks resolved it to the worker's own working directory.
The consequence was sharper than misplaced execution: the filesystem and
terminal sandbox roots in `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`
derive from the same value, so an unsited run confined its agent to - and
therefore permitted it within - this service's own tree. A sandbox boundary
computed from ambient process state is not a boundary. The start path was
protected only incidentally, by a provider-selection gate that refused a null
workspace under an unrelated error message, and the follow-up message path had
no protection at all: it degraded an unreadable stored workspace to null through
a bare exception handler and dispatched anyway.

### repo-anchored-default-store | high | the repository checkout was the default canonical data store

Type: data placement. Status: CLOSED.

The default database anchored to the repository root derived from the settings
module's own file location. Verified live: the store resolved inside the source
tree. In a non-editable install the same expression resolves into the Python
library directory - confirmed by computing both a Windows virtual-environment
layout and a POSIX site-packages layout - where a reinstall destroys it. The
schema already assumed the opposite shape: threads carry a hashed workspace
identity with dedicated partial indexes, so one machine-global store keyed by
project is the designed form, and anchoring per checkout fragmented it.

### duplicate-migration-authority | high | a second migration authority was broken in the shipped container

Type: correctness. Status: CLOSED.

The database administration module re-derived the repository root from its own
file location and read a repository-root Alembic configuration, honouring no
override. The production image installs non-editable, so that path resolved
inside the virtual environment's library directory while the configuration file
was copied to the application root. The module was therefore broken in every
shipped deployment, and it sits behind the destructive clear and restore verbs.
A correct authority already existed and was what the runtime startup path used:
it resolves migration scripts from installed package resources and assembles the
configuration programmatically with no file attached.

### launch-directory-configuration | high | a served process read configuration and credentials from its launch directory

Type: security. Status: CLOSED.

The settings model declared a bare relative dotenv filename, which resolves
against the process working directory, and the settings singleton is constructed
at module import. Verified by launching from an unrelated directory containing a
dotenv file: it supplied both a port override and an API key to the process. Any
directory a production service happened to start in could configure it.

### dev-harness-in-wheel | medium | development-only modules shipped inside the production package

Type: packaging boundary. Status: CLOSED.

The wheel excluded tests and mock presets but still shipped the git hook
installer - whose own docstring stated it was invoked by the task runner and not
exposed on the production command line - alongside a build-artifact cleaner that
deletes directories under the process working directory, and a repository
enrolment driver. They now live outside the package root, so they cannot reach
the wheel at all rather than depending on a denylist entry to keep them out.

### global-pytest-plugin | medium | the test-execution plugin auto-loaded into consumer environments

Type: outward-facing side effect. Status: CLOSED.

The resource-aware execution plugin was registered through a packaging entry
point, which is global: any environment installing this package inherited the
plugin into its own test sessions, where its refusal of non-grouped distribution
breaks a consumer's parallel run and its session registration writes lease state
under the consumer's home directory. A library does not get to reconfigure its
consumer's test runner. A repository-root test configuration module now loads
it - equally unreachable from a command-line option override, but scoped to this
checkout.

### split-store-durability | medium | the shipped container persisted the database but not the rest of the canonical state

Type: operational. Status: CLOSED.

The production compose profile mounted one named volume and pointed the database
at it, but set neither the workspace root nor the application home. The home
therefore resolved under the container user's directory on the ephemeral
writable layer, so the rotating service logs and the service discovery file were
destroyed on every container recreate while the database survived. Durability
was split across the canonical stores with no stated reason.

### divergent-project-identity | medium | one project has three canonical string forms across three repositories

Type: cross-repository contract. Status: OPEN.

The engine mints a scope token as an absolute path with forward separators and
no extended-length prefix, and its own comment calls this the one canonical form
everywhere. This service normalises to a case-folded, symlink-resolved form and
its own docstring likewise calls itself the single formula. The semantic search
service reports a third form again. Two modules in two repositories each
documented as authoritative, producing different strings for the same directory.
This is not currently a live defect, because this service normalises both the
stored value and the incoming query through its own formula, so its internal
hashes agree. The defect is that project identity has no shared definition
across the boundary: nothing can correlate a run with an indexed project without
re-deriving, and symlink or junction divergence stays invisible until it is not.

### fail-open-auth-default | medium | internal transport authentication is disabled by a development default

Type: security posture. Status: OPEN, mitigated in the shipped topology.

The environment setting defaults to development, and the internal bearer rule
disables authentication entirely when the token is unset and the environment is
development. Token minting happens only on the armed desktop branch. A
deployment that runs outside the shipped compose profile and does not set the
environment therefore serves the internal surface unauthenticated. The shipped
production profile does set it and marks the token as a required variable, so
this is a fail-open default rather than a hole in the shipped deployment - but
the loud failure only occurs for an operator who already remembered to configure
the thing the failure is meant to enforce.

### managed-process-registry-anchoring | low | the development process registry anchors to the repository root

Type: boundary. Status: OPEN, recorded as debt.

The managed-process manager seats a serve command at the repository root when a
record carries no explicit repository, and the process table is read from the
same root. Both modules describe themselves as development and test process
management, yet they ship inside the production package and are load-bearing at
runtime through service self-registration. This is the same class as the modules
relocated out of the wheel, but larger and not separable without deciding where
the registry belongs.

### stale-catalog-selection-tests | medium | seventy-seven interface tests were already failing before this work began

Type: pre-existing debt. Status: OPEN, owned elsewhere.

A change making explicit catalog selections mandatory added two required request
fields and forbade unknown ones, without updating the tests that post the older
body shape. Those tests receive an unprocessable-entity response instead of a
created run. Attribution was established three ways: the commit introducing the
requirement is an ancestor of the commit this audit started from, both the
failing test module and the request schema are byte-identical to that starting
point, and no commit in this campaign touched the interface schema or routes.
The breakage was invisible until the packaging work repaired collection, because
a stale installed entry point was aborting the whole session.

## Recommendations

The closed findings above need no further action beyond the changes already
made. Four items remain open.

Define one shared project identity across the three repositories, so that the
normalisation formula is declared once and consumed rather than restated. This
is architecturally significant and cross-repository: a follow-on decision record
must choose which repository owns the canonical form and how the other two
consume it, including whether existing stored identities are migrated or
re-derived.

Decide where the managed-process registry belongs. It is development harness by
its own description but is wired into production service startup, so it cannot
simply be relocated the way the other development modules were. The decision is
whether service self-registration is a production capability that should be
named as such, or a development affordance that production startup should not
call.

Make the environment setting fail closed rather than open. The safe posture
should not depend on an operator having set the variable whose absence is the
hazard; either the default should be the strict one, or an unset environment
should refuse to serve the internal surface at all.

Repair the stale catalog-selection tests. They belong to the lane that made the
selection fields mandatory, not to this one, and they mask any genuine
regression in that interface for as long as they stay red.
