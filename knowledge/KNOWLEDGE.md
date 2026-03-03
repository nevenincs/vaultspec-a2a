---
name: 'Knowledge Base Index'
date: 2026-25-02
type: index
summary: 'Index of A2A protocol documentation and repository reference notes that inform the vaultspec agent orchestration implementation.'
maturity: 70
---

# Knowledge Base

Reference material for the A2A agent orchestration system. These documents
capture external protocol specifications and repository analysis — they are
**not** project decisions but the factual foundation that decisions are built on.

## A2A Protocol Documentation

Distilled from the official [A2A protocol site](https://a2a-protocol.org) and
specification repository. Read in this order for a coherent walkthrough.

| #   | File                                                                       | Maturity | Summary                                         |
| --- | -------------------------------------------------------------------------- | :------: | ----------------------------------------------- |
| 1   | [a2a-protocol-what-is-a2a.md](a2a-protocol-what-is-a2a.md)                 |    80    | Why A2A exists, design principles, agent stack  |
| 2   | [a2a-protocol-key-concepts.md](a2a-protocol-key-concepts.md)               |    80    | Agent Card, Task, Message, Part, Artifact       |
| 3   | [a2a-protocol-definitions.md](a2a-protocol-definitions.md)                 |    85    | V1 operations, data structures, enums, schema   |
| 4   | [a2a-protocol-agent-discovery.md](a2a-protocol-agent-discovery.md)         |    80    | Well-known URI, registries, secure discovery    |
| 5   | [a2a-protocol-life-of-a-task.md](a2a-protocol-life-of-a-task.md)           |    80    | Task lifecycle, contextId, artifact mutations   |
| 6   | [a2a-protocol-streaming-and-async.md](a2a-protocol-streaming-and-async.md) |    80    | SSE streaming, push notifications, JWT security |
| 7   | [a2a-protocol-mcp-integration.md](a2a-protocol-mcp-integration.md)         |    75    | A2A vs MCP comparison, complementary roles      |
| 8   | [a2a-protocol-extensions.md](a2a-protocol-extensions.md)                   |    75    | Extension system, declaration, activation       |
| 9   | [a2a-protocol-enterprise-ready.md](a2a-protocol-enterprise-ready.md)       |    75    | TLS, OAuth2, authorization, compliance, tracing |
| 10  | [a2a-protocol-specification.md](a2a-protocol-specification.md)             |    85    | RC v1.0 three-layer spec, bindings, errors      |

## Repository References

Notes and analysis of cloned repositories in `repositories/`. The actual
clones live alongside these files but are gitignored.

| File                                                              | Maturity | Summary                                                   |
| ----------------------------------------------------------------- | :------: | --------------------------------------------------------- |
| [a2a-protocol-spec.md](repositories/a2a-protocol-spec.md)         |    60    | Spec repo: Agent Cards, task lifecycle, comms             |
| [a2a-python-sdk.md](repositories/a2a-python-sdk.md)               |    55    | SDK modules: server, client, executor, updater            |
| [a2a-python-sdk-guide.md](repositories/a2a-python-sdk-guide.md)   |    65    | Architecture, directory map, data flows, extension points |
| [a2a-samples-deep-dive.md](repositories/a2a-samples-deep-dive.md) |    60    | MCP registry, routing agents, checkpointers               |
| [a2a-walkthrough.md](repositories/a2a-walkthrough.md)             |    55    | Vanilla A2A, Google ADK, LangGraph+MCP, BeeAI             |
| [acp-python-sdk.md](repositories/acp-python-sdk.md)               |    55    | ACP transports, agent base class, protocol flow           |
| [toad-acp-audit.md](repositories/toad-acp-audit.md)               |    65    | Zed's ACP host: agents, auth, streaming, safety           |
| [langchain.md](repositories/langchain.md)                         |    50    | Model abstraction, tools, agents, memory                  |
| [langgraph.md](repositories/langgraph.md)                         |    55    | State graphs, nodes, edges, checkpointers                 |
| [deepagents.md](repositories/deepagents.md)                       |    50    | Planning, reasoning loops, evaluation blueprints          |

## Maturity Scale

| Range  | Meaning                           |
| ------ | --------------------------------- |
| 0–20   | Raw notes, unorganized            |
| 20–40  | Structured research, no decisions |
| 40–60  | Analyzed with recommendations     |
| 60–80  | Verified reference material       |
| 80–100 | Approved, canonical               |
