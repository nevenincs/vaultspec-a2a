---
tags:
  - '#adr'
  - '#project-bound-state'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:318eb242f7408fa9135b0bc27777beb48d400465dffa1c810199e61acbc1af48'
related:
  - "[[2026-09-23-project-bound-state-reference]]"
  - "[[2026-08-04-canonical-homes-adr]]"
  - "[[2026-07-18-desktop-product-profile-adr]]"
  - "[[2026-07-15-dev-process-registry-adr]]"
---

# `project-bound-state` adr: `project-bound state and one settings authority` | (**status:** `accepted`)

Accepted 2026-09-23 on the user's direct instruction in session: a2a variables carry one
`VAULTSPEC_A2A_` prefix enrolled in one settings authority, default storage is bound to the
project rather than the user profile, storage variables accept relative or absolute paths, tests
keep every artifact inside an ignored worktree location, and the dashboard contract is patched in
the same campaign. The four open forks were answered explicitly: root `.vault/data/agents/`,
project root by override then marker search then working directory, dashboard patched with no
legacy names, a2a names first with the owning tool's name as fallback.

## Problem Statement

a2a writes its database, logs, discovery record, credentials handoff, process registry and
per-run provider homes into the user profile and the OS temp directory, and its tests do the same
under a plain `pytest`. Configuration is split between three settings classes, about twenty raw
environment reads, and literal names copied into child environments, under a prefix shared with
sibling tools. The measured surface is `2026-09-23-project-bound-state-reference`.

## Considerations

- vaultspec-core already sanctions `.vault/data/` as ignored, unwalked runtime state, and the
  engine publishes its own discovery record there per workspace
  (`2026-09-23-project-bound-state-reference`, framework and contract sections).
- a2a's "machine-global resident" posture rested on a home-directory rendezvous that the engine
  no longer uses for itself.
- `2026-08-04-canonical-homes-adr` forbids re-export shims; a legacy alias is a second name.
- The per-run execution root and its admission rules (`2026-09-21-workspace-root-authority-adr`,
  `2026-08-03-current-project-binding-adr`) are a security boundary and are not storage.
- The desktop profile (`2026-07-18-desktop-product-profile-adr`) seats state under an explicit
  application home chosen by the dashboard; that stays explicit.

## Considered options

- **Project-bound root under `.vault/data/agents/`, one settings authority, `VAULTSPEC_A2A_`
  prefix, no legacy names.** Chosen.
- **Keep a user-profile home, only rename it.** Rejected: still pollutes the workstation and
  diverges from the engine's per-workspace discovery.
- **Dedicated `.vaultspec-a2a/` in the project root.** Rejected: outside the framework-managed
  ignore policy; every project would need its own ignore entry.
- **Keep old `VAULTSPEC_*` names as deprecated fallbacks.** Rejected by the no-shim rule and by
  the user; the dashboard is patched instead.
- **Rename third-party names outright.** Rejected: breaks existing CLI logins; the owning tool's
  name stays as a fallback behind the a2a name.

## Constraints

- pydantic-settings applies `env_prefix` only to un-aliased fields, so every explicit alias must
  be rewritten, not just the prefix.
- `Settings()` is constructed at import, so project-root resolution must be pure filesystem work
  with no settings dependency.
- Sibling-owned names (`VAULTSPEC_RAG_*`, `VAULTSPEC_TARGET_DIR`) are not a2a's and are not
  renamed; they are written for sibling servers only.
- Concurrent test sessions are admitted, so any test root must be unique per session.

## Implementation

**D1: prefix.** Every a2a-owned variable is `VAULTSPEC_A2A_<NAME>` and is declared as a field of
the composed settings; there are no other `VAULTSPEC_*` spellings for a2a. A variable that names
another tool's configuration (`OPENAI_API_KEY`, `CODEX_HOME`, `CI`, `NO_COLOR`, the Kimi, Z.ai,
Claude and Antigravity names) is a field whose a2a name is tried first and whose owning tool's
name is the fallback. Variables a2a writes for its own children use the same names, taken from
one name registry rather than literals.

**D2: one authority.** A single settings module owns every field, its default, and the path
derivation; `domain_config` reads through it. Every raw read listed in the reference is enrolled
as a field. `.env.example` lists every field, and a test proves the example and the settings
agree.

**D3: project root.** `VAULTSPEC_A2A_PROJECT_ROOT` wins; otherwise the nearest ancestor of the
working directory holding `.vaultspec/` or `.vault/`, then one holding `.git`; otherwise the
working directory. The install location of the package is a separate, non-configurable concept
used only for shipped assets. `.env` is read from the resolved project root.

**D4: storage.** `VAULTSPEC_A2A_HOME` defaults to `<project_root>/.vault/data/agents`. Every
storage variable accepts an absolute path or a relative one resolved against the project root,
never against the working directory. One layout derivation, shared by the default and the
desktop profile, places the databases under `state/`, logs under `runtime/`, the discovery record
and handoff credential at the root, the process registry under `procs/`, and per-run provider
homes under `tmp/homes/`. Nothing a2a writes defaults to the user profile or the OS temp
directory. Reads of other tools' state keep their own defaults and gain an a2a override.

**D5: engine rendezvous.** a2a reads the engine record from
`<project_root>/.vault/data/engine-data/service.json` unless overridden. The engine resolves a2a
at `<workspace>/.vault/data/agents/service.json` unless `VAULTSPEC_A2A_HOME` is set, and the
product launcher passes the renamed desktop variables.

**D6: tests.** Every test session gets one unique root under `<worktree>/.pytest-tmp/sessions/`
that holds pytest's `basetemp`, the session state home, and the process registry; no test writes
to the user profile or the OS temp directory, and no module creates directories at import.

**Amendment 2026-09-23 (D4 and Consequences).** Authorized by the owner on 2026-09-23 after the
P03 review, with the direction that every known issue be addressed and that nothing a2a owns stay
in or be written to the user profile without an explicit override.

- *The seal.* a2a keeps its state out of version control by writing a self-ignoring ignore file
  into the state home before its first write. It does so only when a2a owns the home: it creates
  the home, or the existing home holds nothing but the state layout. An existing home holding
  anything else is the operator's choice; it gets no ignore file, and a2a warns once. A directory a2a creates elsewhere inside the project
  root for a relocated store is sealed the same way, at the outermost directory a2a itself
  creates. A directory that already existed is the operator's, and a2a writes no ignore file into
  it. Outside the project root, version control is not a2a's concern.
- *Refusal.* A state home that is the project root or one of its ancestors is refused at settings
  validation. A home that is itself a repository root is refused by the seal. Either one would
  hide a whole repository from version control.
- *Legacy profile state.* This reverses the consequence that legacy data stays in place. The
  state in `~/.vaultspec-a2a` and `~/.vaultspec/procs` is moved out of the user profile when this
  change lands. No a2a code path reads or writes the profile to do so; it is a one-time operator
  action recorded in the ledger.

## Rationale

The knockout is the engine: it already treats discovery as per-workspace state under `.vault/data`,
so a machine-global a2a home is the odd one out and the only reason a2a state leaks into the
profile. One name registry and one derivation are the canonical-homes rule applied to
configuration: the audit trail in the reference shows the database split and the stale engine
path are both symptoms of the same concept being resolved in several places.

## Consequences

- Breaking rename for every operator variable and every deployment file; `.env` files in this
  worktree carry no `VAULTSPEC_*` names, so local secrets are unaffected.
- One gateway per project rather than per machine. A second project on the same machine gets its
  own store, logs and discovery record; the singleton guard becomes per-project.
- Existing data in `~/.vaultspec-a2a` and `~/.vaultspec/procs` is not migrated automatically; it
  is left in place and the operator can remove it.
- The dashboard must ship the matching engine and launcher change; until it does, a new a2a is
  invisible to an old engine.
- Accepted decisions that named the home-directory locations are refined by this record:
  `2026-07-15-dev-process-registry-adr` (registry home) and the machine-global default described
  in `control/config.py`.
