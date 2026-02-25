# A2A Python SDK Reference

- **Source:** [https://github.com/a2aproject/a2a-python](https://github.com/a2aproject/a2a-python)
- **Relevance:** 10/10 - Reference implementation for the A2A protocol.

## Overview

The `a2a-sdk` Python package provides the core infrastructure for building and interacting with A2A agents.

## Key Modules

- `a2a_sdk.server`: Provides `A2AServer` for hosting agents via HTTP.
- `a2a_sdk.client`: Provides `A2AClient` for interacting with remote agents.
- `a2a_sdk.models`: Pydantic models for A2A protocol objects (AgentCard, Task, etc.).
- `a2a_sdk.executor`: Abstract base classes for implementing agent logic (`AgentExecutor`).
- `a2a_sdk.updater`: Interfaces for streaming task updates back to clients (`TaskUpdater`).

## Implementation Patterns

### Agent Execution

The `AgentExecutor` pattern is used to encapsulate the logic for processing a task. It receives a `Task` object and a `TaskUpdater` for reporting progress.

### Task Management

Tasks are tracked using UUIDs and follow a standard lifecycle (CREATED, RUNNING, COMPLETED, FAILED).

### Discovery

Agents expose their capabilities through the `.well-known/agent.json` endpoint, returning their `AgentCard`.
