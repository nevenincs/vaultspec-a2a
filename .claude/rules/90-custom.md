---
name: 90-custom
trigger: always_on
---

# Repository rolling audit contract

Every implementation pass continues the repository's audit, research, and hardening cycle:

- Implement the approved target and verify the real behavior.
- Review the actual implementation for safety, intent, architecture, quality, portability, and operational risk.
- Classify every finding by severity, type, and status.
- Append every finding to the feature's rolling audit or task queue, including findings deferred beyond the current Step.
- Update the relevant research, reference, or decision trail when implementation changes the team's understanding of the system.
- Treat a Step as complete only after implementation, review, finding classification, queue updates, execution record, and owning plan-state update are complete.

Code written is not equivalent to an issue closed. Newly discovered debt remains visible until it is fixed or explicitly owned by a later Step or upstream project.
