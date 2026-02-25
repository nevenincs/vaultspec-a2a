---
title: A2A Walkthrough Deep Dive
source: knowledge/repositories/A2AWalkthrough
relevance: 9
---

# A2A Walkthrough: Multi-Framework Orchestration Guide

This walkthrough is a critical reference for integrating A2A with various agent frameworks (LangGraph, BeeAI, ADK) and the Model Context Protocol (MCP).

## 1. Tech Stack Overview

The project uses a modern, high-interoperability stack:
- **Language**: Python >= 3.12 (managed via `uv`).
- **A2A Core**: `a2a-sdk[http-server]` (0.3.16).
- **Frameworks**:
  - **Google ADK**: `google-adk[a2a]` (1.19.0) for exposing/consuming agents.
  - **LangChain/LangGraph**: `langgraph` (1.0.2) and `langgraph-a2a-server` (0.1.6).
  - **BeeAI**: `beeai-framework[a2a]` (0.1.70) for "Concierge" orchestration.
  - **Microsoft**: `agent-framework-a2a` (1.0.0b).
- **Protocol Interop**:
  - **MCP**: `mcp` (1.19.0) and `langchain-mcp-adapters`.
- **Model Layer**: `litellm` (for provider-agnostic LLM calls) and `google-generativeai`.

## 2. Implementation Patterns

### Pattern A: Vanilla A2A SDK (`a2a_policy_agent.py`)
Used for lightweight agents without a heavy framework.
1. **Executor**: Subclass `AgentExecutor` to wrap your logic.
2. **Event Queue**: Call `event_queue.enqueue_event(new_agent_text_message(text))` to send output.
3. **Card**: Define `AgentCard` with `AgentSkill` list.
4. **App**: Use `A2AStarletteApplication` to build the app and `uvicorn` to serve it.

### Pattern B: Google ADK (`a2a_research_agent.py`)
Used for seamless Google Search integration and simpler A2A exposure.
1. Define a `Tool` (e.g., `GoogleSearchRetrieval`).
2. Create an `Agent` using the tool.
3. Use ADK's `A2AServer` to wrap the agent.

### Pattern C: LangGraph + MCP (`a2a_provider_agent.py`)
Used for stateful, tool-heavy agents.
1. **MCP Server**: FastMCP server (`mcpserver.py`) exposing local tools (e.g., DB queries).
2. **LangGraph**: Orchestrates the reasoning loop using MCP tools via adapters.
3. **A2A Wrapper**: Exposes the graph as an A2A agent.

### Pattern D: BeeAI Concierge (`a2a_healthcare_client.py`)
The "Master Agent" pattern.
1. Uses `BeeAI` to route user requests to other A2A agents.
2. Acts as a client to `PolicyAgent`, `ResearchAgent`, and `ProviderAgent`.

## 3. Deployment & Execution
The walkthrough uses a consistent port-mapping strategy for local orchestration:
- `9999`: Policy Agent (A2A SDK)
- `9998`: Research Agent (Google ADK)
- `9997`: Provider Agent (LangGraph + MCP)
- `9996`: Healthcare Concierge (BeeAI Orchestrator)

## 4. Key References
- **`helpers.py`**: Contains `setup_env()` for centralized API key management.
- **`mcpserver.py`**: Reference for implementing tool servers using `FastMCP`.
- **`6_A2AxMCPLangGraph.ipynb`**: Best example for full-stack integration (A2A -> LangGraph -> MCP).
