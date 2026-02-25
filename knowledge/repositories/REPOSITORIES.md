---
name: "Repository Index"
date: 2026-25-02
type: index
summary: "Catalog of cloned repositories and their reference notes covering A2A, ACP, MCP, and orchestration frameworks."
maturity: 60
---

# A2A Universe Repositories

This directory contains references and local clones of the core repositories
that define and implement the Agent-to-Agent (A2A) ecosystem, the Agent Client
Protocol (ACP), and related SDKs.

## Core A2A Repositories

- **[A2A Protocol Specification](https://github.com/a2aproject/A2A)**
  - The formal specification for the A2A protocol.
  - Key concepts: Agent Cards, Task lifecycle, streaming, and discovery.

- **[A2A Python SDK](https://github.com/a2aproject/a2a-python)**
  - Reference implementation of the A2A protocol in Python.
  - Provides base classes for A2A servers, executors, and clients.

- **[A2A Samples](https://github.com/a2aproject/a2a-samples)**
  - Example implementations demonstrating various A2A patterns.
  - Includes "hello world" agents and complex task management scenarios.

- **[A2A Walkthrough](https://github.com/holtskinner/A2AWalkthrough)**
  - A step-by-step educational walkthrough of A2A and MCP concepts.
  - Includes Jupyter notebooks and specialized agent examples.

## Client & IDE Protocols

- **[Agent Client Protocol (ACP) Python SDK](https://github.com/agentclientprotocol/python-sdk)**
  - SDK for connecting AI coding agents with editors and IDEs (e.g., Zed).
  - Based on JSON-RPC over stdio/HTTP.

- **[Model Context Protocol (MCP) Python SDK](https://github.com/modelcontextprotocol/python-sdk)**
  - Protocol for connecting AI models to local data and tools.

- **[Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python)**
  - Anthropic's SDK for building agents with Claude, including MCP
    integration.

## Orchestration Frameworks

- **[LangChain](https://github.com/langchain-ai/langchain)**
  - Fundamental library for LLM abstractions and tool-calling primitives.

- **[LangGraph](https://github.com/langchain-ai/langgraph)**
  - Engine for building stateful, multi-agent collaborative workflows.

- **[DeepAgents](https://github.com/langchain-ai/deepagents)**
  - Blueprints for advanced autonomous reasoning and planning agents.

## Companion Repositories

- **[vaultspec](Y:\code\vaultspec-worktrees\main)**
  - The companion repository for this project, providing the governed
    development framework.
