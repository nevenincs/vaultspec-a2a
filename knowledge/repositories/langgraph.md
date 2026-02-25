# LangGraph Reference

- **Source:** [https://github.com/langchain-ai/langgraph](https://github.com/langchain-ai/langgraph)
- **Relevance:** 10/10 - Engine for building self-orchestrating multi-agent
  teams.

## Overview

LangGraph is a library for building stateful, multi-actor applications with LLMs,
built on top of LangChain. It allows for creating cycles in agentic workflows,
making it ideal for complex, multi-turn collaboration.

## Key Concepts

- **State:** A shared object that agents read from and write to.
- **Nodes:** Individual agents or functions that perform work and update the
  state.
- **Edges:** Define the control flow between nodes (conditional or direct).
- **Checkpointers:** Enable "time travel" and persistence by saving state
  at every step.

## Value for Vaultspec

LangGraph is the primary reference for implementing Vaultspec's "Team Mode." It
enables the definition of specialized roles (Supervisor, Coder, Reviewer) and
their collaborative loop, which can then be exposed as an A2A-compliant service.
The built-in persistence maps directly to A2A's `context_id` requirements.
