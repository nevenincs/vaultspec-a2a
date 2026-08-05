---
tags:
  - '#adr'
  - '#tool-cores'
date: '2026-08-01'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:4204699b283838c7ddf90b55fda25eb067e6bdc476cfae2c57843e1ee0136d97'
related:
  - '[[2026-08-01-tool-cores-web-grounding-research]]'
  - '[[2026-07-17-tool-cores-adr]]'
  - '[[2026-07-17-tool-cores-research]]'
  - '[[2026-07-15-agent-harness-provisioning-adr]]'
  - '[[2026-08-04-canonical-homes-audit]]'
---
# `tool-cores` adr: `web grounding` | (**status:** `accepted`)

## Problem Statement

The cross-repo agent-flow decision (dashboard repo, agent-panel campaign,
`2026-08-01-a2a-agent-flow-adr` D6) commits a2a to a real web capability in the
researcher/analyst harness with a hard discipline - "results enter the run as
cited evidence in the context package, never as silent prose" - and defers tool
choice and rate bounds to a2a. `2026-08-01-tool-cores-web-grounding-research`
establishes feasibility (first-party web tools on every provider lane, no
vendor, no credential) and leaves three questions for this record: how the
registry expresses network egress, which roles get the capability, and the
Codex mode posture. A fourth question is the crux: external sources are not
vault documents and must never be `related:` wiki-links, yet the pipeline's
grounding machinery currently speaks only applied vault stems, so the citation
channel for web evidence must be decided before any implementation.
Implementation is deliberately blocked on this record.

## Considerations

- Vault grounding is machine-owned and vault-only: the submitter resolves
  applied proposals into `related:` wiki-link stems deterministically and
  refuses a phase whose required upstream document has not materialized
  (`src/vaultspec_a2a/authoring/submitter.py`). URLs in that channel would
  corrupt the vault link graph and break replay-exact resolution.
- A typed in-run evidence channel already exists: research findings
  `{claim, locators, source_thread}` are validated at the researcher branch
  (`src/vaultspec_a2a/graph/nodes/diverge.py`) and accumulate through an
  append-only reducer into checkpointed state
  (`src/vaultspec_a2a/thread/state.py`); `locators` is an untyped list today.
- The context preamble is built once at thread creation, before any retrieval
  exists (`src/vaultspec_a2a/context/preamble.py`); mid-run evidence can only
  live in graph state, which is the context package the synthesis stage
  actually consumes.
- The research template already mandates a Sources section citing external
  sources as bare URLs; document bodies are agent-authored prose and survive
  the whole-document authoring path verbatim.
- Per `2026-08-01-tool-cores-web-grounding-research`: every lane ships
  first-party web tools under the already-authenticating subscription
  (Claude/Z.ai `WebSearch`/`WebFetch` built-ins; Codex config-level web search
  with cached/indexed/live/disabled modes, cached the default since the
  January 2026 build); the fetch tool retrieves only user-supplied or
  search-derived URLs; first-party caps exist (per-request use caps, content
  token caps, domain allow/block lists).
- Same research, exposure: indirect prompt injection cannot be prompted away;
  fetch alongside sensitive context is a named exfiltration risk; local write
  and network egress are independent axes and the registry's `read_only`
  marker expresses only the first.
- House rule, ecosystem-wide: no version constraint of any kind; the
  compatibility boundary is the declared contract asserted against served
  behaviour (the `_KNOWN_MCP_SERVERS` pattern: declared tools verified at the
  spawn seam, `src/vaultspec_a2a/providers/_acp_mcp.py`).
- The researcher and analyst personas currently disclaim online access,
  truthfully; parent D6 forbids served preset descriptions claiming online
  research until the capability is real.
- Autonomous permissioning is an exact-name allowlist union; human-in-the-loop
  runs already gate any new tool behind the existing permission interrupt.

## Considered options

- **Third-party web-search MCP server joined via `mcp_servers`** (the parent
  record's literal mechanism wording). Rejected: adds a vendor, a credential,
  a billing/rate contract, and an unpinnable dependency for capability the
  provider lanes already ship first-party at parity.
- **Provider-native first-party web tools over the two existing seams
  (CHOSEN).** No new registry entry, no secret, no new machinery; per-lane
  delivery shapes already exist (allowlist union; Codex config home).
- **Force external sources into `related:` wiki-links or per-source vault
  mirror documents.** Rejected: corrupts the vault link graph; `related:` is
  machine-resolved from applied proposals only; a mirror document per URL is
  ledger noise with no reviewer and no lifecycle.
- **Free-prose citations only, no typed channel.** Rejected: the parent's
  cited-evidence discipline becomes unenforceable; nothing machine-checkable
  survives into the revision loop.
- **Typed web locators in the findings contract plus the template's Sources
  section (CHOSEN).** Extends the two channels that already exist instead of
  inventing a third.
- **Machine-refuse any claim lacking a backing retrieval.** Rejected:
  claim-level provenance need is not machine-decidable; refusal must stay
  structural or it becomes arbitrary.

## Constraints

- Parent seams are stable and shipped: the finding contract and reducer, the
  submitter refusal seam, the exact-name allowlist union, and the per-run
  Codex config home are all tested code; native built-ins surface without the
  MCP surfacing gate (`2026-08-01-tool-cores-web-grounding-research`).
- No version constraint anywhere (house rule): upstream tool names and
  behaviour may drift under us; the per-lane live proof is the detection
  mechanism and the admission gate.
- Frontier risk: Codex web-search interaction with the read-only sandbox and
  headless approval policy is inferred, not documented; it must be live-proven
  per lane before the capability is served or claimed.
- Prompt injection is not fully mitigable by any prompt strategy; the human
  review gate on every document apply is the backstop and stays mandatory for
  web-grounded documents.

## Implementation

**D1 - The citation channel is two-layered; neither layer touches vault
links.** Layer 1, in-run (machine-checkable): the finding contract's
`locators` list admits a typed web locator dict carrying `kind` (`web`),
`url`, `retrieved_at` (ISO-8601), and optional `title` and capped `excerpt`,
alongside the existing internal locator entries; the branch-side finding
validation extends to enforce the shape and caps. Web evidence thereby enters
checkpointed state through the existing append-only reducer - replay-exact,
attributable to its source thread, and consumed by synthesis exactly where
internal evidence already is. This channel satisfies the parent's "context
package" obligation: the preamble predates any retrieval, so run state is the
package. Layer 2, in-document (reader-checkable): every distinct web-locator
URL the synthesized document relies on lands in the document body's Sources
section as a bare URL plus its retrieval date, with body claims citing their
sources inline. External sources never appear in `related:`, never as
wiki-links, never in frontmatter; the submitter's vault-stem grounding
resolution is untouched.

**D2 - The refusal discipline extends structurally, not semantically.**
Mechanical rule, refused on violation: when the run's accumulated findings
carry one or more web locators, the proposed document must disclose every
distinct web-locator URL in its body; a document that consumed retrievals but
shows none (or a strict subset) raises the same conformance error and routes
into the same revision loop as the existing ungrounded-phase refusal. This is
deterministic over checkpointed state and needs no tool telemetry. Claim-level
judgment - whether a given claim needed a retrieval, and whether it cites the
right one - is deliberately NOT machine-refused: it is not decidable. It is
flagged instead: the doc-reviewer persona mandate extends to verify that
claims cite the sources they claim (the mitigation the security guidance
names), and the human phase gate remains the final authority. A claim with no
backing retrieval is permitted only under the existing honesty mandate:
presented as recall or a gap, never as retrieved fact.

**D3 - Tools are provider-native; bounds are first-party controls; egress
becomes a declared axis.** Claude and Z.ai: `WebSearch` and `WebFetch` join
the autonomous allowlist by exact name for the researcher and analyst roles
only - never the coder lanes, never write-capable roles. Default bounds, set
via the first-party controls and revisable by amendment: 8 search uses and 16
fetch uses per researcher branch, content-token caps on fetch results, and a
domain blocklist posture (the stricter allowlist stays available per-feature).
Codex: web search is enabled through the per-run config home with cached mode
as the served default - genuine search with zero outbound requests from the
agent host; live mode is not served and requires its own amendment. Registry
impact: the trust-root marker splits - network egress becomes its own declared
axis alongside the local-write axis, so a tool set that reaches outward is
expressed as such and can never ride a read-only-only assertion. No version
constraint appears anywhere; native built-ins expose no tool listing to
assert, so the served-contract assertion for this capability is the exact-name
allowlist plus the per-lane live proof of D4.

**D4 - Personas reclaim online research per lane, on proof.** A lane's
capability claim flips only in the change that both enables the tools on that
lane and lands a live test proving a completed real retrieval that produced a
web-locator-cited finding end to end on that lane. Config-parse, handshake, or
construction coverage does not qualify - the same completed-work standard as
the served-profile admission rule. The harness composes the web-capability
persona text lane-conditionally; the no-online-access disclaimer remains the
default for unproven lanes. Served preset descriptions may claim online
research only once at least one served profile's lane carries the proof,
closing the parent's interim prohibition.

This record also refines the parent D6 delivery-mechanism wording a2a-side:
first-party tools over the existing declaration seams rather than a literal
MCP server. The parent's contract content - no wire change, cited evidence
never silent prose, the capability claim becoming backed - is preserved
unchanged; tool choice was explicitly deferred to a2a, so this is an in-place
refinement, not a supersession.

## Rationale

The knockout is the research finding that every lane already ships the
capability first-party under the subscription that already authenticates the
run: any vendor server adds a credential, a cost, and an unpinnable dependency
for zero capability gain, and the no-pinning house rule makes a third-party
contract strictly worse than asserting first-party behaviour we live-prove
anyway. The citation design falls out of what exists: the run already has
exactly one typed evidence channel (the findings contract) and documents have
exactly one reader-facing citation surface (the template's Sources section);
extending both is smaller and more enforceable than any new channel and leaves
the vault-stem grounding machinery - deterministic, replay-exact, vault-only -
completely untouched. The refusal split keeps refusal semantics honest: refuse
exactly what is mechanically decidable over checkpointed state (the same
pattern as the existing ungrounded-phase refusal), and route judgment to the
reviewer loop and the human gate, which double as the authoritative backstop
against the injection exposure the research says cannot be prompted away.

## Consequences

- Web grounding reaches all three lanes with zero new dependencies, zero new
  secrets, and no wire change; cited-evidence discipline becomes
  machine-enforced at the structural level and reviewer-enforced at the claim
  level; the vault link graph stays clean by construction.
- The prompt-injection surface genuinely opens on researcher/analyst lanes.
  Accepted with named bounds: role scoping, the fetch tool's URL-origin bound,
  use and token caps, provenance-marked evidence, reviewer citation
  validation, and the mandatory human gate before any document applies.
- Upstream tool drift (names, behaviour) is detected only by the live-proof
  gate - the accepted cost of the no-pinning rule.
- Codex cached mode trades freshness for zero egress; the disclosed retrieval
  date makes the staleness visible to readers. Live-mode admission, per-source
  excerpt retention policy, and per-feature domain allowlists remain open
  follow-ups.
- The registry's split egress axis is new auditable surface: future entries
  must declare it, and a missing declaration fails loud, inheriting the
  unsafe-by-omission default.

## Amendment - scope and Codex posture widened (2026-08-01, owner decision)

Two of D3's bounds are widened by owner decision. The rest of this record - the
citation channel, the refusal discipline, the per-lane proof gate, the first-party
bounds, and the split egress axis - stands unchanged, and the reasoning D3
recorded for the narrower posture is preserved above rather than rewritten,
because it remains the argument against what follows.

**Scope widens to every document-authoring role.** D3 admitted the web tools for
the researcher and analyst roles only. They are now admitted for the same role
predicate that already governs the native read floor, so any role receiving
`Read`, `Grep`, and `Glob` in an autonomous run also receives `WebSearch` and
`WebFetch`. The exclusions D3 named are unchanged in substance: the predicate
does not cover coder lanes, and human-in-the-loop runs keep their permission
prompts regardless of role, so the interrupt still gates outbound reach there.

What is genuinely given up is the containment argument D3 made - that confining
outbound reach to the two discovery roles limits what an injected instruction can
reach. Synthesis and review ground on the same external material discovery
surfaces, and a boundary the roles do not observe in practice buys narrower
exposure at the cost of agents that cannot verify what they are asked to
synthesize. The residual risk is accepted on the bounds already named, and the
mandatory human gate before any document applies remains the load-bearing one.

**Codex serves live retrieval.** D3 served the cached mode - a provider-maintained
index with no outbound request from the agent host - and deferred live mode to a
further amendment. This is that amendment: live mode is now the served default.

The cached posture is the safer one and D3 was right that it delivers genuine
search with zero egress. It is set aside because divergent freshness across lanes
is itself a correctness hazard in a multi-provider graph: a lane answering from a
provider-maintained index while its siblings read the live web produces
findings that differ by provider rather than by evidence, and a graph whose
conclusions depend on which lane happened to run is not reproducible. Parity of
reach is the property this capability exists to establish. The mode remains
configuration, so a deployment preferring zero egress can still take cached
without a further record.

Two consequences of this record are restated accordingly: the prompt-injection
surface opens on every autonomous document-authoring lane rather than the
discovery roles alone, and role scoping is no longer among the bounds carrying
that risk - the remaining bounds are the fetch tool's URL-origin restriction, the
use and token caps, provenance-marked evidence, reviewer citation validation, and
the human gate. The staleness-visibility note attached to cached mode no longer
applies to the served posture.

## Amendment - disclosure scoped to research documents (2026-08-01, P01 review)

D2 states the disclosure obligation unconditionally: a proposed document must
disclose every distinct web-locator URL its run retrieved. As implemented the
refusal fires for research documents only, and the record is amended to say so
rather than leaving code and decision in disagreement.

The reason is the vault's own document boundary. Each fact has one home: the
research document grounds, and every later document cites it by stem without
restating its evidence. A URL is evidence, so its home is the research document,
and a later document discharges the obligation by citing the stem that holds it.
The research template is correspondingly the only one in the tree carrying a
sources section.

One reason originally offered for this scoping is withdrawn as false, and is
recorded here rather than quietly dropped. It was argued that a later document
had nowhere sanctioned to put a URL and therefore could not comply. Review
disproved that: a bare URL in prose is refused by nothing, because the
markdown-link conformance check deliberately exempts web targets. A non-research
document could have complied. The scoping is a convention about where evidence
lives, not a necessity, and it should be defended on that ground alone.

The narrowing is currently without practical effect, because the only topology
using the researcher fan-out accumulates every finding before its research gate,
so a URL in state has already been forced into the research document or the run
was refused. That will stop being true if a later topology grounds a
non-research phase on the web, at which point this scoping is the thing to
revisit first.

Where enforcement now ends is stated plainly so it is not rediscovered as a gap:
non-research documents are machine-unchecked for web evidence. D2's reviewer
obligation and the mandatory human gate before any document applies are the only
backstops there, and they are unchanged.

## Amendment - web search is universal, and there is no first-party search server (2026-08-01, owner directive)

Two corrections by owner directive, and the first overrides any narrowing this
record or its earlier amendments carry.

**Every provider lane must be able to search the web. This is not negotiable and
is not conditional on lane, role, preset, or proof.** Where earlier text scoped
the capability - to document-authoring roles, to proven lanes, to autonomous
runs - that scoping governs what a persona may CLAIM and when a tool activates,
never whether a lane is capable at all. A lane that cannot search is not an
acceptable resting state. Grounding on material that postdates the model is a
baseline faculty of an authoring agent, not a feature some lanes earn.

**There is no vaultspec-owned web-search MCP server, and there will not be one.**
A registry entry naming one arrived on a feature branch and is removed. It was a
fiction: it declared a first-party server that does not exist, wrapping a
third-party package under a first-party name. The closed registry stays closed,
exactly as this record already decided, and the reasoning that decided it stands
unchanged - a server would buy a capability the lanes already have while adding a
dependency nobody owns.

Delivery therefore splits by what a lane already is, not by what it has earned:

- **Command-line lanes** - Claude, Codex, Gemini, Kimi, and the Z.ai lane that
  shares Claude's transport - carry first-party web tools already, licensed under
  the subscription that authenticates the run. They are enabled through the
  allowlist and configuration seams this record already describes.
- **Hosted-API lanes** - those reached as model endpoints rather than as
  subprocesses - have no built-in equivalent, so the framework must bind a web
  search tool to the model directly. That is the framework's job and its
  established mechanism; it is not a reason to introduce a server.

The persona consequence is immediate and is the live defect this amendment also
closes: a persona currently instructs agents to call the fictional server's tools
by exact name, five times over, on a server no preset declares and none ever
could. That text is replaced, not gated, because gating a claim about something
that does not exist would preserve the falsehood behind a condition.

The proven-lane declaration keeps its purpose and loses its veto over
capability. It records which lanes have DEMONSTRATED a completed retrieval, and
it governs what a served preset and a persona may assert. It does not decide
which lanes are built to search - after this amendment, all of them are.

## Amendment - the rejection reasons corrected, and the owed removal recorded (2026-08-01, reconciliation review)

The Considered options rejection and the tree it governs disagreed for most of
a day, and the reasons the rejection gave do not all survive contact with the
artifact that shipped. This amendment records the history, corrects the
reasons, and keeps the decision - which now rests on the grounds that actually
hold.

**The history is concurrency, not stale reading.** The rejected mechanism
shipped as the `vaultspec-web-search` registry entry on a concurrent line
(`60d6ff0f`, 10:01) two and a half hours before this record was committed, but
that commit was not an ancestor of this record's line, so the Considerations
statement that the personas "currently disclaim online access, truthfully" was
true where it was written. It became false when the lines merged later that
day, badly; the entry was lost in that merge, restored (`d88c8b79`) under a
lost-work reading a later review found wrong on the merits, and the third
amendment's "is removed" was written sixteen minutes after that restore - a
directive, not yet a description. As of this amendment the tree still carries
the entry. The removal is owed work, deliberately sequenced behind the harness
egress admission gate, which uses the entry as its only egressing exemplar
while in flight; withdrawal retargets that mechanism's coverage onto an
injected exemplar rather than deleting it, and the persona-claims guard fails
loudly on a registry with no egressing entry precisely so the withdrawal is
said out loud rather than slipping past as another merge accident.

**Three of the four rejection reasons are corrected, per this record's own
convention of recording withdrawn reasons rather than quietly dropping them.**
"Adds a credential" is withdrawn as false of the artifact that shipped:
`duckduckgo-mcp-server` (PyPI, MIT, nickclyde) requires no API key and no
runtime env (verified 2026-08-01). "A billing/rate contract" is corrected:
there is no billing and no contract of any kind - the package self-throttles
(30 searches/min, 20 fetches/min) against a scraped public endpoint whose
operator may block it without notice, and the absence of any contract is a
sharper objection than the presence of one. "An unpinnable dependency" is
withdrawn as non-discriminating: the accepted rag entry launches through the
same seam, equally unpinned, under the same house rule, so pinnability
distinguishes nothing in this registry - the discriminating property is
ownership, and the third amendment's restatement ("a dependency nobody owns")
is the form that survives. "Adds a vendor" stands, and doubled: the search
operator and the package maintainer are both parties nobody here owns.

**The decision is unchanged, which is why this is an amendment.** The
rejection now rests on ownership and on the first-party-name fiction the third
amendment named - sufficient grounds, correctly stated. This record's own
practice is that sub-decision reversals and reason corrections amend in place
with the original reasoning preserved; a superseding record is reserved for
reversing the central choice. Re-admitting a web-search server as the delivery
mechanism would be that reversal, and it is foreclosed by the third amendment
regardless. One clarification against a foreseeable misreading: the harness
egress admission gate proof-vetoes egressing registry entries, and that does
not collide with the third amendment stripping proof's veto over web
capability, because after the withdrawal web capability never rides the
registry - it is first-party on command-line lanes and framework-bound on
hosted-API lanes - and the gate guards only whatever future reviewed entry
declares egress.

### Cross-repo consequence of the universal-search directive

The removed registry entry did not arrive by accident. It was built to satisfy
the consuming project's own decision record, whose D6 calls for a web-search and
fetch MCP server joining the researcher harness through the declaration
mechanism. Its tests cite that record by name. So the owner directive does not
merely delete a local mistake - it declines a cross-repo ask, and that is worth
stating plainly rather than leaving the other side to discover a server they
specified is never coming.

The substance of D6 is satisfied and its mechanism is not. The researcher does
get real web reach, on every lane rather than only where a server could be
mounted, which is more than D6 asked for. What it does not get is a server: the
command-line lanes carry first-party search already, and the hosted-API lanes
take a framework-bound tool. D6's own wording anticipated using the existing
declaration mechanism with no wire change, and no wire change is what happened -
the delivery seam is simply the allowlist and the model binding rather than the
registry.

The record on this side is now the authority for how a2a delivers web reach. The
consuming project's D6 should be amended to match, and until it is, a reader of
that record will expect a server this repository will not provide. That
divergence is recorded here rather than silently tolerated, because a
specification nobody intends to honour is the same defect class as a docstring
asserting an invariant the code does not hold.

### Reconciling the two amendments about the removal, and closing it

Two amendments above address the same withdrawal, written hours apart by
different hands, and a reader deserves to be told which governs what rather than
left to infer it.

The universal-search amendment is authoritative for the DECISION: every provider
lane must be able to search the web, no first-party search server exists or is
planned, and delivery splits between the command-line lanes' own tools and a
framework-bound tool for hosted-API lanes. That is an owner directive and it is
not subject to the reconciliation below.

The reconciliation amendment is authoritative for the HISTORY and for the
rejection reasons. Its account is better than the universal-search amendment's:
the entry shipped on a concurrent line before this record was committed, so the
disagreement was concurrency rather than anyone reading a stale tree, and three
of the four reasons originally given for rejecting a server do not survive
contact with what actually shipped - the package needs no credential and carries
no billing relationship. Those corrections stand. The decision does not rest on
them; it rests on the lanes already having the capability, which is the one
reason that held throughout.

**The removal is no longer owed. It is done.** The registry entry and its
desktop-capability action were withdrawn once the owner directive made the
sequencing moot, and the registry now carries a single no-egress member with a
comment recording why no web entry belongs there.

The sequencing concern that amendment raised was correct and was met, though not
in the order it anticipated. It warned that the entry was the egress mechanism's
only egressing exemplar and that withdrawal must RETARGET that coverage rather
than delete it. The removal did land first and did redden that coverage. The
retarget is the native tool path: the command-line web tools are declared
egressing in the native map and enforced by the native counterpart of the same
guard, so every lane-scoping assertion has a real subject again - and a better
one, because it is the path actually shipped rather than an exemplar kept alive
to be tested. No injected exemplar is needed, and no test-only registry member
should be introduced to substitute for one.

### The gate ruling and the mechanism residue (2026-08-01, reconciliation review)

The paragraph above sequenced the withdrawal behind the harness egress
admission gate and promised that gate's coverage retargeted onto an injected
exemplar. That clause is superseded here rather than rewritten: the owner
directive removes the gate's only possible subject, and a proof-gated
admission seam over a permanently empty subject set is precisely the
dead-capability class this campaign exists to close. The dynamic gate is
withdrawn with the entry - the admission seam, the proof record's
harness-server half, and the served eligibility term all go; none of it ever
landed on the main line as more than a committed test adapted to an
uncommitted API, which is recorded as its own defect.

The residue that survives is static. The registry's declared-egress set is
asserted empty by a guard whose deliberate edit is the act of admitting a
future egressing entry - the tripwire form that would have caught the fiction
arriving on this week's merge - and the persona-claims guard keeps failing
loudly on the same state, rewritten to attest the withdrawal rather than
deleted. The egress axis itself, unconstructible when undeclared, stands
unchanged: a future reviewed entry still declares its reach, and admitting an
egressing one now requires a decision record before the guard edit that lets
it in.

What delivers the capability stands unchanged. The proven-lanes declaration
remains the claim-and-activation governor the third amendment left it - never
a capability veto - and the per-lane live-proof Steps remain the only path to
lighting native tools and flipping persona text and preset claims, atomically
per lane. Its harness-server half leaves with the gate; its native half is
the whole story. The served-profile admission rule needs no amendment: it
governs which lanes may be served and what presets and personas may assert,
and has never governed what a lane is built to do, so the capability
universality above changes nothing the rule speaks to.

The delivery split needs no separate record: delivery is this record's
decision, and the third amendment records the split with its rationale. The
one decision it leaves open - which binding the hosted-API lanes take - is
owed as an amendment here when that work is planned, together with the plan
Step that does not exist today.

## Amendment - the dynamic gate re-landed, smaller (2026-08-05, curator reconciliation)

The preceding section ("The gate ruling and the mechanism residue") states
that the dynamic gate was withdrawn with the entry and that "the residue that
survives is static." That sentence is behind the tree: a dynamic gate has
since re-landed. This amendment records the mechanism, its narrower shape, and
why it does not reverse the withdrawal - and where the reconciliation rests on
reasoning rather than a proved reading, it says which.

**What landed.** Commit `7f4e1ea3` (2026-08-04) re-landed a dynamic lane
gate, centralized in the resolution stage every harness composition already
passes through: `resolve_harness_mcp_capabilities`
(`src/vaultspec_a2a/providers/_acp_mcp.py:658-740`). A declared name whose
registry entry states `network_egress` resolves only on a lane carrying
recorded completed-retrieval proof; otherwise it lands in the resolution's
unavailable set with code `lane_unproven_egress` (`_acp_mcp.py:717-729`). The
gate keys on the DECLARED axis through `harness_server_egresses`
(`_acp_mcp.py:634-647`) and on the existing lane predicate
`is_web_lane_proven` (`src/vaultspec_a2a/providers/lane_admission.py:411-420`),
and it fails closed on an omitted lane: `None` - a caller that stated no lane,
a model that declared none - is refused, because absence of a lane is not
permission. Two follow-ups completed the wiring: the research producer now
states its lane (`75a6aeae`, 2026-08-04), and the desktop attached-server
re-resolution asks its inner question under the same lane as the outer call
(`9e0ef0ef`, 2026-08-05, `_acp_mcp.py:1281-1285`).

**Why this is not the withdrawn gate returning.** The withdrawal named three
surfaces, and all three remain absent - each PROVED against the tree,
2026-08-05:

- **No separate admission seam.** The gate is a conditional inside the one
  resolution stage every composition already routes through, not a dedicated
  seam a caller could forget to consult. `_acp_mcp.py:717` is the only egress
  gating in the module (whole-file reading).
- **No harness-server proof half.** The lane declaration carries native
  evidence only: `WebLaneProof` records the native built-ins the proven
  retrieval exercised (`lane_admission.py:129-152`). No per-server proof
  record exists anywhere in the tree.
- **No served eligibility term.** `is_web_lane_proven` has exactly three
  production consumers: this resolver (`_acp_mcp.py:717`), the compiler's
  persona-capability seam (`src/vaultspec_a2a/graph/compiler.py:864-866`),
  and the codex web-mode resolution
  (`src/vaultspec_a2a/providers/codex_chat_model.py:753`). Served-profile
  eligibility consults completed-turn admission only; web proof enters no
  eligibility verdict.

The re-landed mechanism is therefore strictly smaller than what was
withdrawn: it introduces no proof record, no admission seam, and no served
term, and it reuses the one lane declaration that already exists for native
tool activation. It is also exactly what the reconciliation amendment above
affirmed in prospect - "the gate guards only whatever future reviewed entry
declares egress" - keyed on the declared axis, never on entry identity. So
the disagreement between text and tree is stale TEXT, not a reversed
decision, and this amendment is the correction.

**The honest caveat, stated so it is not rediscovered as a gap.** The refusal
branch is production-unreachable today: the frozen registry holds no egressing
entry, and the `lane_unproven_egress` code has no producer outside
`_acp_mcp.py` and no test that reaches it (PROVED: the literal appears
nowhere else in the tree). The withdrawal's own reasoning condemned a
proof-gated seam over a permanently empty subject set as dead capability, and
for one day - the gate re-landed 2026-08-04, the admission ruling below is
dated 2026-08-05 - the branch stood on nothing but the tripwire docstring's
expectation of a future admission. What resolves the tension is that ruling:
the subject set is empty today but no longer PERMANENTLY empty, and the
coverage that would exercise the branch is deliberately owed at admission
time rather than faked now against a test-built registry the frozen
construction seam would never admit. One judgment here is REASONED rather
than proved: that the re-landing was a deliberate arming of the axis rather
than an accidental contradiction of this record. The commit message and the
mechanism's shape both say arming, but no decision record said so before this
one - which is precisely the defect this amendment closes.

The residue sentence is restated to match the tree. The residue is static AND
dynamic. Static: the declared-egress set is asserted empty by the tripwire
whose deliberate edit is the admission act
(`src/vaultspec_a2a/team/tests/test_persona_web_claims.py:142-146`). Dynamic:
the lane gate above, dormant over that same empty set, is the
composition-time half that arms the moment a reviewed entry declares egress.
Everything else in the superseded sentence's section stands unchanged.

## Amendment - egress admission ruled: admissible in principle, no candidate qualifies, web delivery foreclosed (2026-08-05, owner ruling)

The ruling recorded here was made 2026-08-05 and until now lived only in a
task card and one campaign audit entry
(`2026-08-04-canonical-homes-audit`, finding
`the-admission-decision-conditional-yes-nothing-admitted`). A decision with no
decision record is the defect class this vault exists to prevent, so this
amendment is the ruling's home; the audit entry and the task card are
pointers from here on. Nothing in this amendment admits anything.

**Placement, decided and recorded.** This ruling lands as an in-place
amendment rather than as its own ADR, for three reasons. First, condition (d)
below - taken verbatim from the ruling - names THIS record as the target of
any future admission amendment, so the policy governing those amendments
belongs in the record they will amend. Second, a sibling accepted ADR on the
same scope (this registry's egress axis and what may join it) would fragment
one governing decision across two records. Third, this record's own
convention reserves a superseding record for reversing the central choice,
and this ruling reverses nothing: it confirms the closed registry and arms
the axis this record created. The rejected alternative - a standalone
admission-policy ADR - was schema-viable (`vault check schema` requires an
ADR to reference research, which the same
`2026-08-01-tool-cores-web-grounding-research` would satisfy) but was
rejected on the fragmentation ground alone, because it is a policy about this
mechanism, not a new subject.

**The ruling.** An egressing harness MCP server MAY be admitted in
principle. A categorical "never" would recreate the dead-capability class
this record's own campaign condemns, and the registry's tripwire names the
admission act as an expected future event - its failure message ends "or a
real capability that owes this guard an update"
(`test_persona_web_claims.py:142-146`); the mechanism was built expressive,
not prohibitive. But no candidate qualifies today, and one whole category is
permanently out of reach.

**Admission requires ALL of the following.** Ownership (a) and the entry's
own per-lane completed-work proof (e) are the load-bearing conditions.

- **(a) Ownership.** The discriminating property that survived this record's
  own reason-corrections (the reconciliation amendment above) is ownership -
  not credentials, billing, or pinnability. A third-party-operated,
  contract-less endpoint fails permanently.
- **(b) Not web-search/fetch delivery.** Foreclosed, not conditional. Web
  reach is first-party on the CLI lanes and framework-bound on hosted-API
  lanes, "never by a server this registry mounts" (the registry's own
  standing comment, `_acp_mcp.py:354-360`). Re-admitting a web-delivery
  server would reverse this record's central delivery choice and is therefore
  a SUPERSESSION, never an amendment - this ruling cannot reopen it, and does
  not. What stays admissible is a non-web-delivery capability that happens to
  egress: a first-party documentation or index service is the standing
  example.
- **(c) Full trust-root declaration through the construction seam.**
  `_declare_registry` (`_acp_mcp.py:197-286`): `network_egress` true,
  `read_only` stated (a write-capable egressing entry is constructible but
  unsurfaceable - the surfacing policy lives at `_require_read_only`,
  `_acp_mcp.py:928-948`), `root_pin` stated or explicitly null,
  `exact_surface` stated, and no `env` (the field is refused at construction,
  `bd5b6b2d`, `_acp_mcp.py:272-282`).
- **(d) The decision record before the guard edit.** An in-place amendment to
  this record naming the entry, its owner, its capability, its bounds, and
  its per-lane proofs - landed before or with the tripwire edit, never after.
- **(e) The entry's own completed-work proof per served lane.** Lane
  web-proof does NOT discharge this; see the floor paragraph below.

**The lanes are exactly the members of `PROVEN_WEB_LANES` at admission
time.** Verified 2026-08-05 as `{claude, codex}`
(`lane_admission.py:262-293`). kimi (handshake-only), gemini
(construction-only), openai, zhipu, any garbage lane, and an unstated lane
are all refused.

**Two different emptinesses, two different remedies - do not read one as the
other.** `PROVEN_WEB_LANES` is NOT empty: the gate's PREDICATE has two live
members. What is empty is the gate's SUBJECT set - the registry entries that
declare egress, asserted empty by the tripwire. An empty predicate would be
cured by a lane's live retrieval proof; the empty subject set is cured only
by the full admission path above. A recent working note asserted "nothing
egresses" of the predicate and had to be corrected: it is true of the
registry's entries only. Any future reader finding one emptiness must check
which one they are holding before acting on it.

**The lane predicate is a FLOOR, not the admission.** Two questions exist,
and the gate answers only the first: (1) may outward reach compose on this
lane at all - `is_web_lane_proven`; (2) has THIS server completed real work
on this lane - a separate, stronger claim. Claude's recorded proof is
native-`WebFetch`-only (`lane_admission.py:277-291`); codex's is a
config-posture retrieval with no allowlistable tool name at all
(`lane_admission.py:263-276`). NEITHER ever exercised MCP-server-mediated
egress, and the lane catalog's own principle forbids evidence inheritance
across mechanisms (`lane_admission.py:200-205`,
`catalog_lane_admission_reason`). So every (server, lane) pair needs its own
proof on the transport actually served - which is condition (e), and why
credential readiness, lane web-proof, and every other floor property are
necessary but never sufficient.

**Evidence that suffices, per (server, lane).** A shipped registry entry
(never a hand-built or test-only member) -> resolution with the lane stated
-> production composition (`compose_harness_mcp_servers` +
`harness_allowed_tool_names` on claude; `codex_mcp_server_specs` ->
`build_codex_config_home` on codex) -> a real spawned session -> the agent
invokes the server's tool -> a real retrieval completes -> the content lands
in checkpointed state, asserted on A VALUE ONLY THE LIVE SOURCE COULD
SUPPLY. Plus the negative half in the same file: `lane=None` and a
handshake-only lane yield `lane_unproven_egress`, the server absent from the
launch specs, its tools absent from the allowlist.

**What does not count as proof** - written down before any candidate exists,
because every item on this list has been mistaken for proof in this
repository: `tools/list` contract verification passing; the server process
spawning; rendering into `.claude.json` or `config.toml`; resolution
returning the name available; the model SAYING it used the tool without the
live-only-value assertion; any mocked, patched, or replayed transport;
credential or readiness checks.

**Precondition the admitting change must close: an egressing registry entry
has NO BOUNDS AXIS.** Verified:
`_require_bounds_match_the_egress_axis(NATIVE_TOOL_EGRESS,
NATIVE_WEB_TOOL_BOUNDS)` (`_acp_mcp.py:1594-1632`) binds usage bounds to
NATIVE tool names only, and `NATIVE_WEB_TOOL_BOUNDS` (`_acp_mcp.py:1553-1568`)
declares bounds for `WebSearch` and `WebFetch` alone. An admitted egressing
MCP tool would pass a real gate and then reach outward uncapped while its
native siblings are capped per branch. The admitting change must either
extend a bounds declaration to egressing registry entries or record
explicitly why the server's own throttling suffices. Recorded here as a
precondition, deliberately NOT fixed now: a bounds surface for entries that
cannot exist would be the dead-capability class again.

**Owed at admission, not before.** The two tests that would exercise the
gate become writable when a candidate exists, and must assert DIRECTION and
reason-truthfulness: the research producer's stated lane observably changes
composition - a proven lane admits, an absent or unproven lane strips
(`75a6aeae`); and the desktop attached-server re-resolution answers under
the same lane as the outer call (`9e0ef0ef`). Also recommended then: split
the served refusal so "no lane was stated" is distinguishable from "this
lane carries no recorded proof" - today's single reason
(`_UNPROVEN_EGRESS_REASON`, `_acp_mcp.py:369-372`) blames the lane for a
caller's omission, as the resolver's own desktop commentary already notes
(`_acp_mcp.py:1274-1280`).

**This ruling does NOT authorize:** admitting any server; any
web-search/fetch delivery server under any framing; widening
`PROVEN_WEB_LANES` or `PROVEN_TURN_LANES`; `WebSearch` on claude; serving
kimi, gemini, openai, or zhipu; evidence inheritance of any kind; editing
the tripwire ahead of the entry's own proof; test-only registry members.
Nothing is admitted by this amendment, and nothing remains open under it
until a candidate entry exists.
