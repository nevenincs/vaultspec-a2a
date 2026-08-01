---
tags:
  - '#plan'
  - '#tool-cores'
date: '2026-08-01'
modified: '2026-08-01'
tier: L2
related:
  - '[[2026-08-01-tool-cores-web-grounding-adr]]'
  - '[[2026-08-01-tool-cores-web-grounding-research]]'
  - '[[2026-07-17-tool-cores-adr]]'
  - '[[2026-07-17-tool-cores-plan]]'
---
# `tool-cores` plan

Executes the accepted web-grounding decision record
(`2026-08-01-tool-cores-web-grounding-adr`): the two-layer citation channel,
the structural refusal, provider-native web tools with a declared egress axis,
and per-lane proof before any persona claims online research. The Stage-1
external tool-choice proposal this campaign once expected never arrived (the
producing agent was reassigned); the decision record's own grounding
(`2026-08-01-tool-cores-web-grounding-research`) is the sole and sufficient
basis of this plan.

Two disciplines bind every Step, learned from the dead-capability findings of
the agent-flow campaign:

- **Wiring proof is the acceptance condition.** A Step that adds a producer,
  emitter, tool binding, or config knob does not close on unit coverage; it
  closes on evidence that the production path exercises it - the real
  composition seam, the real generated config, the real refusal firing. Each
  Step row names its evidence.
- **The tree never carries a capability that cannot fire, nor a claim the
  tools cannot back.** Activation is gated behind a declared proven-web-lanes
  set, empty at first landing: no web tool joins any allowlist and every
  persona keeps its no-online-access disclaimer until a lane's live proof
  lands, and the proof Step flips tools and persona text together, atomically
  per lane.

Phase P01 and Phase P02 are independently landable in order; every Step in
Phase P03 is independently landable per lane (spend- and credential-gated),
except the bounds proof, which requires the first proven lane.

### Phase `P01` - Contract seams

Land the three contract changes everything else depends on: the registry egress axis, the typed web locator, and the structural refusal. The capability stays dark throughout; each Step is independently landable and leaves the tree green.

- [ ] `P01.S01` - Split the registry trust-root marker so network egress is its own declared axis: an entry or native tool set with no egress declaration is REFUSED fail-loud at the real composition seam, never defaulted, migrating the sole existing registry entry to declare no-egress in the same change so the tree stays green. Closes on a test that drives the production config-home and spawn composition path and proves the refusal fires for an undeclared entry (executor-core); `src/vaultspec_a2a/providers/_acp_mcp.py`.
- [ ] `P01.S02` - Admit the typed web locator into the research-finding contract - kind web, url, retrieved-at ISO-8601, optional title and capped excerpt - enforced in the branch-side finding validation with caps. Closes on a graph-level test through the real dispatch, reducer, and checkpoint seam proving the locator survives into checkpointed state and reaches synthesis, never a direct field-set (executor-core); `src/vaultspec_a2a/graph/nodes/diverge.py`.
- [ ] `P01.S03` - Extend the submit refusal structurally: when accumulated findings carry web locators, every distinct locator URL must appear in the proposed document body, else the document-conformance error routes the run into the existing revision loop. Closes on a test through the real submit path proving the refusal FIRES on an undisclosed URL, plus a mutation run demonstrating the test fails when the check is absent (executor-core); `src/vaultspec_a2a/authoring/submitter.py`.

### Phase `P02` - Gated delivery and bounds

Compose the provider-native web tools, their bounds, and the lane-conditional persona text behind the proven-web-lanes set, which is empty at landing: everything is wired and asserted on the real spawn surfaces, and nothing fires until a Phase P03 proof admits a lane.

- [ ] `P02.S04` - Introduce the declared proven-web-lanes set as the single activation gate consumed by both tool composition and persona-text composition, empty at landing. Closes on a composition test through the real spawn payload proving an unproven lane surfaces no web tool name and keeps the no-online-access disclaimer (executor-core); `src/vaultspec_a2a/graph/nodes/worker.py`.
- [ ] `P02.S05` - Compose the Claude and Z.ai web built-ins WebSearch and WebFetch into the autonomous allowlist by exact name for the researcher and analyst roles only, gated on the proven set, carrying the decided bounds through the first-party controls - eight search and sixteen fetch uses per researcher branch, fetch content-token caps, blocklist posture. Closes on a graph-boundary test asserting the real spawn payload carries the names, caps, and role scoping for a proven lane and omits them for every other role and for unproven lanes (executor-core); `src/vaultspec_a2a/graph/nodes/worker.py`.
- [ ] `P02.S06` - Enable Codex web search through the per-run config home in cached mode only, gated on the proven set, with live mode unwritable under any configuration. Closes on a test reading the real generated per-run config from the production writer and proving cached mode, the gate, and the absence of any live-mode escape (executor-core); `src/vaultspec_a2a/providers/codex_chat_model.py`.
- [ ] `P02.S07` - Compose the persona web-capability text lane-conditionally: the researcher and analyst web-grounding paragraph with its citation obligations is injected only for lanes in the proven set, the existing no-online-access disclaimer stays the default, and preset descriptions remain unchanged in this Phase. Closes on the real harness prompt assembly carrying or omitting the paragraph per set membership (executor-service); `src/vaultspec_a2a/team/presets/agents/`.

### Phase `P03` - Per-lane live proof and activation

Prove each lane live to the completed-retrieval standard and flip it into the proven set; prove the declared bounds bind; flip preset descriptions only once at least one lane is proven. Handshake or config coverage never closes a Step here.

- [ ] `P03.S08` - Prove the Claude lane live to the completed-retrieval standard: a real autonomous run performs a real web retrieval that lands as a typed web locator in checkpointed state and as a Sources disclosure in the proposed document body, no mocks and zero vault writes. Landing flips claude into the proven set so tools and persona text activate together, atomically for the lane (executor-service); `src/vaultspec_a2a/service_tests/`.
- [ ] `P03.S09` - Prove the declared bounds BIND on the proven Claude lane, not merely that they are declared: drive a live run past the per-branch search and fetch caps and observe further uses refused, and prove the content-token cap truncates a fetch result. A declared-but-unchecked bound is the unenforced-rule defect class this campaign is closing (executor-service); `src/vaultspec_a2a/service_tests/`.
- [ ] `P03.S10` - Prove the Z.ai lane live to the same completed-retrieval standard, credential-gated on the Z.ai auth token and independently landable. Landing flips zai into the proven set (executor-service); `src/vaultspec_a2a/service_tests/`.
- [ ] `P03.S11` - Prove the Codex cached-mode lane live to the same completed-retrieval standard, additionally verifying the undocumented axis the decision record constrains - cached web search actually surfacing and invoking under the read-only sandbox and never approval policy - independently landable. Landing flips codex into the proven set (executor-service); `src/vaultspec_a2a/service_tests/`.
- [ ] `P03.S12` - Flip served preset descriptions to claim online research only once at least one lane is in the proven set, verify the served description matches the proven state, and close the plan by appending outcomes and any new findings to the feature's rolling trail, amending the decision record in place if implementation changed the team's understanding (executor-service); `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml`.
