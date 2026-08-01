---
name: clarifications-are-typed-interrupts
---

# Clarifications are typed interrupts

- **One pause mechanism.** A question to the user mid-run pauses the run ONLY via
  checkpointed LangGraph `interrupt()` raised by the clarification node, with the
  bounded typed payload (at most 4 questions per request, at most 4 options per
  choice question, capped strings). No side channel, no free-form prose question.
- **Disclosure is authoritative on `run-status`.** The pending clarification
  (request id + question payload) is projected from the live checkpoint into the
  `run-status` response so a reload re-renders the questionnaire from authoritative
  state. Relay frames (`clarification_pending`) carry the request id ONLY and are
  non-authoritative nudges to re-read `run-status` — never the source of questions.
- **Resume is the typed verb only.** Answers re-enter exclusively through the
  clarification respond verb mapped to `Command(resume=...)` of the parked node,
  validated against the live checkpoint (option existence, per-question
  satisfaction, required-question completeness). The follow-up messages route is
  NEVER an answer path: it starts a new turn and silently orphans the parked
  interrupt.
- **Wiring is proven, not assumed.** A surface that can raise a clarification must
  have a producer actually injected and a test driving the full
  interrupt → disclosure → respond → resume loop; an emitter with zero callers is a
  defect, not a feature.
- **Provenance:** codifies `2026-08-01-a2a-agent-flow-adr` D5 (dashboard repo,
  agent-panel campaign) and its 2026-08-01 amendment to
  `2026-07-14-a2a-orchestration-edge-adr`, per the edge's mutual-reference
  discipline. The wiring clause exists because D5 first shipped as dead capability:
  every part built, no producer injected.
