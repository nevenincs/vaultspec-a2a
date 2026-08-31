---
tags:
  - '#research'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:e0422d11cae98b6824d07f7f0eb9da149fe9bbd9dae3a6ad995a077e23483d29'
related: []
---

# `served-capability-contract` research: `what a2a actually serves against the owner's natural-language asks`

The owner named four natural-language asks a frontend must be able to relay here
- scaffold a new feature, summarize this feature, report this project's status,
and author ADR and plan documents that are semantically checked against the
corpus they join. The question is which of those the served contract can carry
today, and the answer is not uniform: one is served and correctly declared, one
is served and MISDECLARED, and two have no capability of their shape anywhere in
the system. Separately, a live capture shows the served preset list mixes
certification scaffolding into the product surface in a way a frontend cannot
filter. This document is the evidence picture behind those verdicts; the
accompanying ADR decides what to do about them.

Evidence was taken three ways: a live authenticated capture of the running
gateway on 2026-08-05, a read of the code that produces those fields, and a
sweep of the ADR corpora in this repository and in the dashboard repository for
decisions that already govern any part of it.

## Findings

### The capability declaration is keyed to the topology, and the key cannot express the preset set

`supported_capabilities()` and `authoring_capability()` both take a single
argument - the topology type - and branch on `is_document_authoring_topology()`
(`src/vaultspec_a2a/team/team_config.py:158-189`). That predicate reads a
frozenset containing exactly one member, `research_adr`
(`src/vaultspec_a2a/authoring/contract.py:65`). Four topology types therefore
partition twenty served presets into two capability answers.

The partition is already wrong on a shipped preset. `vaultspec-doc-editor`
declares `type = "pipeline"`
(`src/vaultspec_a2a/team/presets/teams/vaultspec-doc-editor.toml:12`), and its
single worker holds the `doc-editor` role, which the same contract module lists
as a document-authoring role (`src/vaultspec_a2a/authoring/contract.py:57`). The
preset arms `authoring_bridge = true` with empty `required_surfaces`, so the
document moves through the ledgered authoring API or it does not move at all.
Every property that makes it a document-authoring lane is present except the
topology name, and the topology name is the only thing the declaration reads.

The live capture shows the consequence on the wire:

```
vaultspec-doc-editor     pipeline      coding              []
vaultspec-adr-research   research_adr  document_authoring  [research_document, architecture_decision, plan_document]
```

The function's own docstring anticipates a divergence between the topology name
and the authoring predicate and calls asking the predicate the fix
(`src/vaultspec_a2a/team/team_config.py:180-185`). The divergence that actually
occurred is a step further out: a document-authoring ROLE on a non-authoring
TOPOLOGY, which neither the name comparison nor the predicate can see, because
both are still keyed to the topology.

This is a live violation of a binding constraint from the consuming repository:
"Preset capability declarations (`supported_capabilities()`) are the served
truth the dashboard renders; extending a topology extends that declaration in
the same change"
(`Y:/code/vaultspec-dashboard-worktrees/main/.vault/adr/2026-08-01-a2a-agent-flow-adr.md`,
Constraints). The same record's D2 mandates the doc-editor preset and D7 turns
its `filesystem_write` off precisely so documents move only through the
authoring bridge - the dashboard designed a document lane, and this repository
serves it to the dashboard as `coding`.

The role set is the discriminator the topology is not. Roles map to document
kinds one-to-one across the whole served set: `researcher` and `synthesist`
produce the research document, `adr-author` the decision, `plan-author` the
plan, `doc-editor` a whole-document revision. A capability derived from the
preset's declared worker roles distinguishes all five and needs no new
vocabulary. The competing shape - a free-text capability list in each preset
TOML - buys the same expressiveness but lets a workspace-local preset assert a
capability nothing backs, which is the mutability
`2026-07-16-authoring-contract-adr` refused for policy constants.

### There is no capability whose output is an answer rather than a document

Every capability a2a serves terminates in a proposal on the ledgered authoring
path. The research_adr chain parks on phase gates whose payload is a proposal id
awaiting a human verdict; the doc-editor lane submits one whole-document
proposal and waits on the same three-verdict review lane
(`src/vaultspec_a2a/team/presets/teams/vaultspec-doc-editor.toml:6-11`). No
served route returns synthesized prose to the caller as the run's product. The
full route inventory from `GET /v1/service` carries run lifecycle, streaming,
clarification and permission responses, presets, provider catalog and service
readiness - and no capability or graph endpoint of any kind.

Both remaining owner asks are answer-shaped. "Summarize this feature" wants
prose about a document set; "what is the status of this project" wants prose
about a repository. Neither wants a new document to exist, and neither can be
expressed as a proposal without inventing a persisted artifact for an ephemeral
question. This is a shape gap, not a missing preset: adding a preset that
produces a summary would still have nowhere to put the summary.

The doc-editor lane is the nearest existing thing and is explicitly narrower.
Its persona mandate forbids exactly the widening a feature summary needs -
"Authoring a second document, or widening the edit to the document's neighbours,
is out of scope - reject it rather than obliging"
(`src/vaultspec_a2a/team/presets/teams/vaultspec-doc-editor.toml`). A feature
summary spans a feature's whole document set by definition.

### Workspace binding is not the obstacle to a project-status ask; feature binding is not imposed on it either

The framing that a project-status ask does not fit because `workspace_root` is
mandatory does not survive the code. `RunStartRequest.metadata` is optional
(`src/vaultspec_a2a/api/schemas/gateway.py:240`), but `selection` is a required
field with no default (`:253`), and selection revalidation refuses with 422 when
no workspace root resolves - "explicit provider selection requires an existing
workspace_root" (`src/vaultspec_a2a/api/routes/gateway.py:1102-1106`). Workspace
binding is therefore effectively universal and arrives through the provider
catalog, not through metadata.

That binding is correct for this ask rather than obstructive: a project-status
question is a question ABOUT a project, so the run wants exactly the scope it is
already given. `2026-08-03-current-project-binding-adr` rules the active project
a run-bound scope on independent grounds, which this ask has no reason to
escape.

The binding the ask genuinely does not want is the FEATURE tag, and that
requirement is already narrow. `evaluate_run_start_eligibility` returns eligible
before reaching the feature-tag check for any preset that is not
document-authoring (`src/vaultspec_a2a/control/run_start_policy.py:148-170`); a
non-authoring preset that arms the authoring bridge needs per-role tokens and
still needs no feature tag (`:149-160`). The two scopes are independent, and the
framing that motivated the question collapsed them.

### The research-to-ADR chain is what the owner believes it is, with one vocabulary correction

The owner's belief that "scaffold a new feature" is the `research_adr` chain
checks out. Four presets run that topology; its five required roles are declared
in pipeline order as `RESEARCH_ADR_ROLES`
(`src/vaultspec_a2a/authoring/contract.py:42-48`), the compiler refuses to
compile a preset missing any of them, and the served description names the three
documents, the inner doc-review loop and the outer human verdict. The plan
document is a full third phase of the same chain rather than a separate preset,
which the dashboard's D4 rules deliberately so that the plan is grounded in the
research and ADR the same run produced.

One correction to the word "scaffold": no persona runs `vaultspec-core vault
add`, and none writes to the filesystem. Documents come into existence only when
a human accepts an engine proposal. The chain AUTHORS; the engine scaffolds.

The chain's reachability moved during this investigation and the premise that
opened it is now stale. A live `GET /v1/service` on 2026-08-05 reports
`authoring_backend_reachable: true`, `worker_connected: true`,
`run_admission: ready`, and `eligible_providers: [claude, codex, kimi]` - not
the single admitted provider and unreachable authoring backend recorded when
this triage was framed.

### Of the authoring obligations the owner named, two are already ruled and one is unowned

Structural conformance and agent-side self-validation are settled. The
2026-07-15 refinement to `2026-07-14-adr-authoring-orchestration-adr` binds every
document-authoring run to a fully provisioned workspace, gives agents the
vaultspec-core CLI for read-only self-validation against draft content staged
outside `.vault/`, and makes template conformance a doc-reviewer REVISION
criterion rather than a style suggestion. The write seam stays closed and the
engine remains the applier, so schema validity is enforced where the document
lands.

Semantic conflict and duplication against the EXISTING corpus is the one the
owner named that nothing owns. The material exists: both document-authoring
lanes mount the read-only `vaultspec-rag` grounding server
(`src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml:108-124`),
giving semantic recall over the vault. Nothing requires an agent to use it
before authoring a decision, and nothing checks that it did. The submitter's
only structural refusal is intra-run - it refuses a phase whose required
upstream document has not materialized
(`src/vaultspec_a2a/authoring/submitter.py`, per
`2026-08-01-tool-cores-web-grounding-adr`) - which says nothing about the corpus
the new document joins. A sweep of both ADR corpora for a prior ruling on
corpus-conflict detection returned nothing on point.

The engine cannot discharge this obligation: it validates schema and ledger
state, not whether a decision restates one already ruled. The frontend cannot:
it has no corpus recall. a2a owns the phase machine and holds the grounding
server, which leaves it as the only layer positioned to.

What remains genuinely open is not WHO but HOW STRONG. Requiring that recall
happen and be disclosed into the gate is mechanically checkable, and matches the
existing typed in-run evidence channel: research findings already carry
`{claim, locators, source_thread}` validated at the researcher branch and
accumulated through an append-only reducer into checkpointed state. Requiring a
machine VERDICT on whether a conflict exists is a semantic judgement with no
demonstrated accuracy on this corpus, and treating a model's opinion as a
blocking gate would be an unproven capability claim of the kind the served-
profile admission rule was written against.

### Routing by natural language is already ruled, and ruled away from this repository

D1 of `2026-08-01-a2a-agent-flow-adr` (dashboard repository) rules that routing
is explicit preset selection and the composer is the router: "Solo vs team is
never inferred from prompt text." Its codification candidate
`served-presets-are-the-router` states it as a rule. The frontend's routing
problem is therefore not solved by a2a classifying intent; it is solved by a2a
serving a preset list rich enough to choose from, which returns the question to
the capability declaration above.

That codification candidate is the only one of the record's three not present in
this repository's rule directory - `no-unproven-providers-in-served-profiles.md`
and `clarifications-are-typed-interrupts.md` were both codified,
`served-presets-are-the-router` was not.

### Certification presets are served to product frontends and cannot be filtered out

The live capture returns twenty presets, of which fourteen are scaffolding: five
`deterministic-*`, eight `mock-*`, and `provider-condition-probe`. Only the
`mock-*` eight carry `is_mock: true`, because the predicate is a name prefix -
`return preset_id.startswith("mock-")`
(`src/vaultspec_a2a/team/team_config.py:155`). The other six are served as
`origin: bundled`, `is_mock: false`, indistinguishable on the wire from the four
product presets.

Precedent exists on both sides of a fix. The desktop product wheel already
excludes mock presets at packaging time, so filtering the product surface is
established practice rather than a new idea. And the 2026-08-03 amendment to
`2026-08-02-provider-model-catalog-adr` rules that a retired field is REMOVED
from a response rather than served empty, on the grounds that a client cannot
distinguish a confident emptiness from a real one - the same argument applies to
a certification preset that reports itself as bundled product.

### What was not investigated

No run was started, so nothing here is proof that a served capability COMPLETES;
every verdict is about what the contract declares and what the code can express.
Whether a project-status capability could source repository evidence was not
resolved: no git or repository-status entry appears in any preset's harness
registry, and whether such a tool is admissible under the current-project
binding pin was not traced. The engine-side authoring API was read only through
this repository's client and the dashboard's decision records, never directly.

## Sources

- `src/vaultspec_a2a/team/team_config.py:155`, `:158-189`
- `src/vaultspec_a2a/authoring/contract.py:42-48`, `:57`, `:65`
- `src/vaultspec_a2a/control/run_start_policy.py:148-170`
- `src/vaultspec_a2a/api/schemas/gateway.py:240`, `:253`
- `src/vaultspec_a2a/api/routes/gateway.py:1102-1106`, `:2372-2432`
- `src/vaultspec_a2a/team/presets/teams/vaultspec-doc-editor.toml`
- `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml:108-124`
- `src/vaultspec_a2a/authoring/submitter.py`
- Live capture 2026-08-05: `GET /v1/presets` and `GET /v1/service` against the
  loopback gateway on port 18100, bearer-authenticated.
- `Y:/code/vaultspec-dashboard-worktrees/main/.vault/adr/2026-08-01-a2a-agent-flow-adr.md`
  (D1, D2, D4, D7, Constraints, Codification candidates)
