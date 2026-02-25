# Vaultspec's A2A AgeNt Orchestration Immplememtation

This reposity contains work-in-progress implementation to be used by vaultspec to support its custom agentic coding workflow. Vaultspects code can be found at `Y:/code/vaultspec-worktrees/main`

## Goal

To implement the library backends required to offload work to custom coding agents. We're aiming to implement two modes:

- Subagent mode: A client app will call on an agent to perform a task. The preferred way of handing off non-paralellized, non-concurrent tasks from a client, like gemini cli, claude code or antigravity.
- Team mode: A coding team that self-orchestrates between the members to perform a task. The preferred way of handling paralellized, concurrent tasks. For example, a team of coders, supervisros and orhcestrators working against a set list of ADRs, plans and research knowledge.
- Implement robust abstractions layers to support Claude, Gemini and Codex agents.

## Implementation

To be researched. We're aiming to implement local orchestration servers. The tech stack is not certain yet. Not certain how gemini, codex, claude integrate. Online, local, sdk based solutions are all possible.

## References

Code references and knowledgebase:
