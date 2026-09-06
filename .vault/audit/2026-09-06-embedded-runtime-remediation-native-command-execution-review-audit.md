---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:0be0c91a2548a6ab733d920f8c5630c6a1b9a06c1cc3e1205fd608fbf78277cd'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Native command execution implementation review

## Scope

Reviewed W03.P08.S38 against exact session negotiation, input validation, concurrent ownership, observable outcomes, effect uncertainty, command transport, and the explicit prohibition on claiming native compaction without independent effect proof.

## Findings

### native-command-session-authority | high | A command could execute without exact session advertisement

Resolved. Execution waits a bounded five seconds for the newly created ACP session's replacement command catalog, resolves the exact command name, and refuses blocked or unsupported commands before `session/prompt`. No alias, translation, default support, cached cross-session claim, or compatibility path exists.

### native-command-transport-boundary | high | A generic execution escape could bypass the negotiated command contract

Resolved. The adapter constructs one ACP prompt from the exact advertised name and validated arguments. It does not expose arbitrary JSON-RPC methods, subprocess arguments, or shell execution.

### native-command-concurrency | high | Concurrent command and chat operations could corrupt one model's active session state

Resolved. The model elects one in-flight provider session before any await and returns an explicit `busy` outcome to a concurrent native command. The ownership flag is released in `finally` after success, refusal, cancellation, or failure.

### native-command-outcome | high | Accepted commands could fail without exposing effect uncertainty

Resolved. Outcomes distinguish completed, busy, blocked, unsupported, cancelled, and failed. Once an advertised command is issued through `session/prompt`, completion and unknown failures conservatively report that effects may have occurred. Provider cancellation and ACP failures preserve their existing effect evidence.

### native-command-input | medium | Unbounded or ambiguous text could escape the command identity

Resolved. Names must be exact printable non-whitespace identities without a leading slash and within the protocol length bound. Arguments are printable and bounded to 8192 characters. Invalid input is rejected before provider spawn.

### native-command-compaction-claim | high | Command completion alone could be reported as context compaction

Blocked by design and remains assigned to the plan's independent effect qualification. S38 exposes only the negotiated command outcome. It does not claim that `compact` changed provider context, freed tokens, or produced a durable compaction effect. Those claims remain unavailable until W04.P09 and qualification steps prove them.

### native-command-consumer-exposure | medium | Provider execution does not itself make the command available through the Dashboard binary contract

Open under the existing W04.P09.S42 and W04.P09.S45 integration steps. This provider implementation is callable and verified at its API boundary; broker/CRUD exposure remains separate planned work.

## Verification

- Canonical owned runner: eight native-command cases passed in 8.83 seconds and exited naturally.
- Ruff and Ty passed for the provider implementation before the final focused run.
- Real subprocess fixtures proved exact prompt text, unsupported refusal without prompt, concurrent busy disposition, and invalid input refusal before spawn.

## Recommendations

- Keep command support bound to the executing session's exact replacement catalog.
- Preserve explicit busy and effect-uncertainty outcomes at every consumer boundary.
- Do not advertise compaction until independent state and token effects pass qualification.
- Complete the existing broker integration steps before treating the provider method as a shipped Dashboard operation.

## Disposition

The S38 provider boundary passes review. Native compaction effects and Dashboard consumer exposure remain explicitly unavailable and owned by their existing plan steps.