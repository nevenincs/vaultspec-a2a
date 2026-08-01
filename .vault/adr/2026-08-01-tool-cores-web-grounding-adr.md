---
tags:
  - '#adr'
  - '#tool-cores'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
related:
  - '[[2026-08-01-tool-cores-web-grounding-research]]'
  - '[[2026-07-17-tool-cores-adr]]'
  - '[[2026-07-17-tool-cores-research]]'
  - '[[2026-07-15-agent-harness-provisioning-adr]]'
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
