---
name: "Protocols Gaps Research"
date: 2026-25-02
type: research
summary: "Rigorous analysis of protocol bridging, focusing on state translation logic, queueing mechanics for elicitations, and MCP compliance."
maturity: 70
---

# Protocols Gaps Research

**Date**: 2026-02-25
**Domain**: Protocols (A2A ↔ MCP Bridge)

## 1. Multi-Agent Status Aggregation (Gap G2)

**Architectural Problem**: The orchestrator must collapse a concurrent matrix of N A2A agents (each with 8 potential states) into a single, cohesive MCP task status (which only has 5 states) for the client CLI.

**Implementation Reference (Aggregator State Machine)**:
The orchestrator must implement a strictly ordered reduction function. Highest priority conditions evaluate first.

```python
from enum import Enum
from typing import List

class MCPState(str, Enum):
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class A2AState(str, Enum):
    SUBMITTED = "TASK_STATE_SUBMITTED"
    WORKING = "TASK_STATE_WORKING"
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"
    COMPLETED = "TASK_STATE_COMPLETED"
    FAILED = "TASK_STATE_FAILED"
    CANCELED = "TASK_STATE_CANCELED"
    REJECTED = "TASK_STATE_REJECTED"

def aggregate_team_status(agent_states: List[A2AState]) -> MCPState:
    # 1. Terminal Failures take absolute precedence (fail fast)
    if any(s in (A2AState.FAILED, A2AState.REJECTED) for s in agent_states):
        return MCPState.FAILED
        
    # 2. Blockers halt the entire team from the CLI's perspective
    if any(s in (A2AState.INPUT_REQUIRED, A2AState.AUTH_REQUIRED) for s in agent_states):
        return MCPState.INPUT_REQUIRED
        
    # 3. Success is only achieved when ALL agents are done
    if all(s == A2AState.COMPLETED for s in agent_states):
        return MCPState.COMPLETED
        
    # 4. If anyone is cancelled, the session is cancelled
    if any(s == A2AState.CANCELED for s in agent_states):
        return MCPState.CANCELLED

    # Default fallback: At least one agent is working or submitted
    return MCPState.WORKING
```

## 2. Concurrent Elicitation Handling (Gap G3)

**Architectural Problem**: MCP protocol strictly enforces a sequential `server -> client -> server` elicitation model. However, in a multi-agent A2A team, Agent A and Agent B might both enter `TASK_STATE_INPUT_REQUIRED` simultaneously.

**Inclusion/Exclusion Decision**:

- **Excluded**: Dropping concurrent requests. This causes unrecoverable agent hangs.
- **Excluded**: Merging prompts (e.g., "Agent A wants X and Agent B wants Y"). The A2A protocol requires distinct `contextId` and `taskId` correlations for responses; a merged response breaks trace integrity.
- **Included**: An explicit `asyncio.Queue` acting as an Elicitation Serializer within the Orchestrator.

**Implementation Rationalization**:
When Agent B emits an `INPUT_REQUIRED` event while an MCP elicitation for Agent A is already active, the orchestrator appends Agent B's request to an internal `pending_elicitations` queue. Once the client responds to Agent A, the orchestrator immediately pops the queue and triggers a new MCP `elicitation/create` for Agent B before returning the status as `working`.

## 3. AUTH_REQUIRED Through MCP (Gap G4)

**Architectural Problem**: A2A supports a discrete `AUTH_REQUIRED` state. MCP has no native "Authentication" task state or protocol concept.

**Inclusion/Exclusion Decision**:

- **Excluded**: Out-of-band OAuth flows (e.g., opening a browser). This breaks headless CI/CD execution and violates the strict `stdio` boundaries expected by the MCP host.
- **Included**: "Collapsed Elicitation". The orchestrator coerces the `AUTH_REQUIRED` A2A state into an MCP `input_required` state.

**Rationale**:
By coercing the state, we rely on the MCP host's native standard input mechanisms (CLI prompts) to ask the user for the missing credential (e.g., "Provide API Key for tool X"). This keeps the integration 100% compliant with the MCP specification, ensuring broad compatibility with any MCP-capable host (Claude CLI, Gemini CLI) without requiring custom extensions.
