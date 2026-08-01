---
name: no-unproven-providers-in-served-profiles
trigger: always_on
---

# Served profiles admit only proven providers

- **Admission rule.** A served model profile may name a provider lane only after a
  live-service test has COMPLETED A REAL TURN on that lane: a real prompt through the
  real transport producing real model output. Construction-only coverage, config-parse
  coverage, and live pre-auth HANDSHAKE coverage do not qualify — a handshake proves
  spawn, not work.
- **Enforcement is served, not conventional.** The proven/unproven status of a lane is
  encoded where profiles are served (the eligibility service consumed by `presets-list`
  and launch), never left as a comment or a review habit. Credential readiness is
  NECESSARY but NOT SUFFICIENT: a profile whose lane lacks completed-turn proof is
  ineligible even with a valid credential present.
- **The same completed-work standard extends to capability claims.** A preset or
  persona may advertise a capability (e.g. online research) only on a lane with a live
  test proving the capability completed real work end to end on that lane.
- **Provenance:** codifies `2026-08-01-a2a-agent-flow-adr` D3/D8 (dashboard repo,
  agent-panel campaign), per the mutual-reference discipline of
  `2026-07-14-a2a-orchestration-edge-adr`. The rule exists because a served kimi
  profile once violated D3 when handshake-only coverage was mistaken for proof.
