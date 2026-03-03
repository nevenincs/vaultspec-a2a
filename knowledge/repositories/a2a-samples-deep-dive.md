---
name: 'A2A Samples Deep Dive'
date: 2026-25-02
type: reference
summary: 'Analysis of a2a-samples repository patterns including local tool integration, host orchestration, coding agents, and self-orchestrating teams.'
maturity: 60
---

# A2A Samples Deep Dive: Orchestration & Local Tools

- **Scope:** analysis of `a2a_mcp`, `a2a_multiagent_host`, `github-agent`, and `langgraph` samples.
- **Objective:** Extract implementation patterns for Vaultspec's local coding orchestration.

---

## 1. Local Tool Integration (`a2a_mcp`)

The `a2a_mcp` sample demonstrates how to bridge A2A agents with local capabilities using the Model Context Protocol (MCP).

### Key Patterns

- **MCP as a Registry:** The MCP server hosts `AgentCards` as resources. Orchestrators query the MCP server to find the right agent for a task.
- **Orchestration via Graph:** Uses a `WorkflowGraph` to manage dependencies. Nodes represent specialized tasks (Air, Hotel, Car Rental).
- **Tool-Augmented Agents:** A2A agents can be given "hands" by connecting them to an MCP server that provides filesystem or database access.

### Takeaways for Vaultspec

- We should use an MCP server to expose our local workspace tools (e.g., `read_file`, `write_file`, `run_tests`) to the A2A agents.
- The "Planner" pattern is essential for breaking down complex coding tasks into granular A2A-executable steps.

---

## 2. Host Orchestration (`a2a_multiagent_host`)

This sample provides a blueprint for a central "Host" that coordinates multiple remote agents.

### Key Patterns

- **Routing Agent:** An agent whose primary "tool" is `send_message`. It acts as a dispatcher, selecting specialized agents based on their `AgentCard` descriptions.
- **Conversion Layer:** `HostAgentExecutor` manages the mapping between the A2A task lifecycle and internal agent runners (like ADK).
- **Traceability Extension:** Demonstrates how to track multi-agent interactions across different services using a custom protocol extension.

### Takeaways for Vaultspec

- Our "Team Mode" supervisor should follow the `RoutingAgent` pattern, using A2A calls as tools.
- Implementing a `Traceability` extension is critical for debugging complex agentic workflows in Vaultspec.

---

## 3. Coding Agent Implementation (`github-agent`)

A focused example of an agent designed for coding-related workflows.

### Key Patterns

- **Toolset Encapsulation:** Logic for interacting with external APIs (GitHub) is encapsulated in a dedicated `Toolset` class.
- **Dynamic Schema Extraction:** Automatically generates JSON schemas for LLM tool-calling from Python methods using `inspect`.
- **OpenAI/A2A Bridge:** Shows how to run a typical LLM tool-calling loop (ReAct) within the context of an A2A `AgentExecutor`.

### Takeaways for Vaultspec

- Our local coding agents should encapsulate toolsets for Git, LSP, and build systems.
- Dynamic tool schema extraction will simplify adding new local tools to our agents.

---

## 4. Self-Orchestrating Teams (`langgraph`)

Demonstrates wrapping a sophisticated multi-agent graph (LangGraph) as a single A2A-compliant agent.

### Key Patterns

- **Checkpointers:** Uses LangGraph's `MemorySaver` to maintain state across interactions, mapping `context_id` to `thread_id`.
- **Structured Output:** Enforces specific response formats (`ResponseFormat`) to handle state transitions like `input_required` or `completed`.
- **A2A Streaming Wrapper:** Bridges LangGraph's internal streaming events to A2A `TaskStatusUpdateEvents`.

### Takeaways for Vaultspec

- "Team Mode" can be implemented as a single A2A agent that internally runs a LangGraph or CrewAI workflow.
- Mapping `context_id` to the internal thread/session storage is the standard way to handle long-running collaborative coding tasks.
