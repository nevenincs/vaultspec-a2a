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

## Steps

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

- [x] `P01.S01` - Split the registry trust-root marker so network egress is its own declared axis: an entry or native tool set with no egress declaration is REFUSED fail-loud at the real composition seam, never defaulted, migrating the sole existing registry entry to declare no-egress in the same change so the tree stays green. Closes on a test that drives the production config-home and spawn composition path and proves the refusal fires for an undeclared entry (executor-core); `src/vaultspec_a2a/providers/_acp_mcp.py`.
- [x] `P01.S02` - Admit the typed web locator into the research-finding contract - kind web, url, retrieved-at ISO-8601, optional title and capped excerpt - enforced in the branch-side finding validation with caps. Closes on a graph-level test through the real dispatch, reducer, and checkpoint seam proving the locator survives into checkpointed state and reaches synthesis, never a direct field-set (executor-core); `src/vaultspec_a2a/graph/nodes/diverge.py`.
- [x] `P01.S03` - Extend the submit refusal structurally: when accumulated findings carry web locators, every distinct locator URL must appear in the proposed document body, else the document-conformance error routes the run into the existing revision loop. Closes on a test through the real submit path proving the refusal FIRES on an undisclosed URL, plus a mutation run demonstrating the test fails when the check is absent (executor-core); `src/vaultspec_a2a/authoring/submitter.py`.

### Phase `P02` - Gated delivery and bounds

Compose the provider-native web tools, their bounds, and the lane-conditional persona text behind the proven-web-lanes set, which is empty at landing: everything is wired and asserted on the real spawn surfaces, and nothing fires until a Phase P03 proof admits a lane.

- [ ] `P02.S04` - Introduce the proven-web-lanes activation gate consumed by both tool composition and persona-text composition, empty at landing, by EXTENDING the existing lane-admission module rather than declaring a second mechanism. That module already implements this exact pattern for completed-turn proof: a hand-edited, deny-by-default frozen mapping whose every entry cites the live test that earned the lane, explicitly not derived by scanning for test files because a derived set would silently re-admit a lane the moment an unrelated test appeared. Web proof is the same rule for a different capability, so it belongs beside completed-turn proof - either as a sibling mapping or as a second proof field - and must not become a parallel registry that can disagree with it. BLOCKED until the lane-admission module and its test are committed: both are currently untracked while a sibling module already imports them, so the seam this Step builds on exists on disk but not in history and could still change shape. Closes on a composition test through the real spawn payload proving an unproven lane surfaces no web tool name and keeps the no-online-access disclaimer (executor-core); `src/vaultspec_a2a/graph/nodes/worker.py`.
- [ ] `P02.S05` - Compose the Claude and Z.ai web built-ins WebSearch and WebFetch into the autonomous allowlist by exact name for every document-authoring role, using the same role predicate that governs the native read floor, gated on the proven set, carrying the decided bounds through the first-party controls - eight search and sixteen fetch uses per branch, fetch content-token caps, blocklist posture. Closes on a graph-boundary test asserting the real spawn payload carries the names, caps, and role predicate for a proven lane, and omits them for non-document roles and for unproven lanes (executor-core); `src/vaultspec_a2a/graph/nodes/worker.py`.
- [ ] `P02.S06` - Enable Codex web search through the per-run config home in live mode as the served posture, gated on the proven set, with cached mode reachable by configuration for a deployment that prefers zero egress. Semantic grounding corrected this Step's target: the chat model only calls the builder, while the actual config.toml renderer is the config-home module, so the feature and mode keys belong beside the existing declared-server blocks rather than in the model. No web-search or feature key exists there today, so nothing is being duplicated. Closes on a test reading the real generated per-run config from the production renderer and proving the served live mode, the gate, and that the cached posture remains selectable (executor-core); `src/vaultspec_a2a/providers/_codex_config_home.py`.
- [ ] `P02.S07` - Compose the persona web-capability text lane-conditionally: the web-grounding paragraph with its citation obligations is injected for every document-authoring role only on lanes in the proven set, the existing no-online-access disclaimer stays the default, and preset descriptions remain unchanged in this Phase. Semantic grounding corrected this Step's target: persona directives are assembled at graph-compile time from the preset text, so the lane-conditional composition belongs at that assembly seam rather than in the preset files, which carry the static text only. Closes on the real harness prompt assembly carrying or omitting the paragraph per set membership (executor-service); `src/vaultspec_a2a/graph/compiler.py`.
- [ ] `P02.S13` - Land the web-locator extractor in the research producer so a real retrieval becomes a typed locator, and decide in the same change whether the producer normalises a malformed locator or the branch refuses it. The typed channel currently has no production emitter - the producer returns an empty locator list unconditionally - so the contract admits a shape nothing produces and the submit refusal cannot fire in a real run. The decision is load-bearing rather than cosmetic: branch-side validation raises out of the researcher node, which is wired with no retry policy unlike every sibling in the topology, so a malformed locator aborts the whole run rather than routing into the revision loop, and a retry could not help because the failure is deterministic. A decision of normalise must say WHICH malformation it covers, because the two likely ones need different fixes: a scheme-less host such as a bare domain-and-path fails the scheme check exactly as hard as an over-cap excerpt does and is the likelier of the two in practice, but prefixing a scheme is a different operation from truncating an excerpt. Closes on a live-shaped test proving a retrieval reaches checkpointed state as a typed locator through the real producer, plus a test per malformation class proving the chosen path - normalised at the producer, or refused with a route the run can actually recover through (executor-core); `src/vaultspec_a2a/graph/compiler.py`.
- [ ] `P02.S14` - Close the two trust-structure findings the P01 review raised, as one change because they share a root. Make both declaration structures immutable rather than public mutable dicts - the native egress catalog is exported in the module's public names as a plain dict while membership IS the declaration, so any importer can declare a web tool at runtime with a single assignment, and the registry itself is mutable for the same reason. Then resolve the unreachable guards honestly: with both structures frozen, the composition-seam assertions become PROVABLY redundant rather than merely unreachable, because no code path can introduce an undeclared entry after construction. Decide and record whether they are removed as dead code or kept with a comment stating they are redundancy behind the construction seam, never enforcement - the P01 review established that neither the egress assertion nor the pre-existing read-only assertion can be reached by legitimate production input, and a fail-loud guard nothing can trigger is documentation. Closes on a test proving a runtime declaration attempt is refused by the frozen structure, plus whichever the decision requires: the guards deleted with the suite still green, or their redundancy comment present and accurate (executor-core); `src/vaultspec_a2a/providers/_acp_mcp.py`.

### Phase `P03` - Per-lane live proof and activation

Prove each lane live to the completed-retrieval standard and flip it into the proven set; prove the declared bounds bind; flip preset descriptions only once at least one lane is proven. Handshake or config coverage never closes a Step here.

- [ ] `P03.S08` - Prove the Claude lane live to the completed-retrieval standard: a real autonomous run performs a real web retrieval that lands as a typed web locator in checkpointed state and as a Sources disclosure in the proposed document body, no mocks and zero vault writes. Landing flips claude into the proven set so tools and persona text activate together, atomically for the lane (executor-service); `src/vaultspec_a2a/service_tests/`.
- [ ] `P03.S09` - Prove the declared bounds BIND on the proven Claude lane, not merely that they are declared: drive a live run past the per-branch search and fetch caps and observe further uses refused, and prove the content-token cap truncates a fetch result. A declared-but-unchecked bound is the unenforced-rule defect class this campaign is closing (executor-service); `src/vaultspec_a2a/service_tests/`.
- [ ] `P03.S10` - Prove the Z.ai lane live to the same completed-retrieval standard, credential-gated on the Z.ai auth token and independently landable. Landing flips zai into the proven set (executor-service); `src/vaultspec_a2a/service_tests/`.
- [ ] `P03.S11` - Prove the Codex live-mode lane live to the completed-retrieval standard, additionally verifying the undocumented axis the decision record constrains - live web search actually surfacing and invoking under the read-only sandbox and never approval policy - independently landable. Landing flips codex into the proven set. One cheap probe is ruled out by evidence gathered during delivery and must not be attempted: the tool's debug prompt-input output is byte-identical across all four web-search modes, because search is a server-side tool that never reaches the model-visible prompt input, so no prompt-input assertion can prove surfacing or invocation. This Step therefore requires a real turn that completes a real retrieval; configuration, handshake, and prompt-inspection coverage are all insufficient by construction rather than merely by the plan's standard (executor-service); `src/vaultspec_a2a/service_tests/`.
- [ ] `P03.S12` - Flip served preset descriptions to claim online research only once at least one lane is in the proven set, verify the served description matches the proven state, and close the plan by appending outcomes and any new findings to the feature's rolling trail, amending the decision record in place if implementation changed the team's understanding (executor-service); `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml`.
