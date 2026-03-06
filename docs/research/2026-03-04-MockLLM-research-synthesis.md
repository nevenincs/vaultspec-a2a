# MockLLM Research Synthesis and Architecture Strategy
**Date:** 2026-03-04
**Context:** Vaultspec-A2A UI testing decoupling

## Objective
To determine the best approach for implementing a `MockLLM` that can simulate full LangGraph team behaviors, error states, tool calls, and permission handling natively.

## 1. Native SDK Framework Support
LangChain explicitly provides mocking facilities through:
1. `GenericFakeChatModel`: Streams predefined messages deterministically.
2. Custom `BaseChatModel` subclasses: Recommended in LangChain docs for fine-grained control over prompt handling and complex simulated workflows.

## 2. Architecture Comparison: Native SDK vs. ACP-Based Agent
### ACP-Based Agent (External Process)
**Pros:** Uses the exact same `acp_chat_model.py` transport layer as real LLMs.
**Cons:** 
- Requires spawning an external Node/Python process.
- Hard to programmatically trigger core deep LangGraph exceptions (`GraphBubbleUp`, `InvalidUpdateError`) via JSON-RPC.
- Slower test execution due to subprocess overhead and pipe serialization.

### Native Python SDK (BaseChatModel subclass)
**Pros:** 
- Runs natively IN the LangGraph state machine.
- 100% trace compatibility: LangSmith perfectly traces Native SDK nodes exactly as it does for real LLMs.
- Capable of injecting native errors directly.
- Zero extra infra overhead.
- Total deterministic control over token generation speeds and outputs.

**Recommendation:** Go with the Native SDK Implementation. Implement `MockChatModel` in `src/vaultspec_a2a/providers/mock_chat_model.py`.

## 3. LangGraph Failure States & Error Mapping
Our mock implementation must simulate real failures observed in the LangGraph application. Here is the mapping of LangGraph exceptions to our mock scenarios:

| Failure Type | LangGraph / Native Exception | Mock Simulation Strategy |
|--------------|------------------------------|--------------------------|
| **Tool Execution Error** | `ToolExecutionError` / Validation Error | Model provides a malformed tool call payload; graph catches and feeds back. Let the graph handle the cycle, or simulate a hard break. |
| **State Corruption / Invalid Update** | `InvalidUpdateError` | `MockChatModel` returns a dict simulating an illegal channel update, crashing the node to simulate internal corruption. |
| **Max Iterations Exhausted** | `GraphRecursionError` | `MockChatModel` infinitely loops on dummy actions until LangGraph hits the configured recursion limit. |
| **Permission Halts** | `GraphBubbleUp` / `NodeInterrupt` | `MockChatModel` emits a mock `session/request_permission` tool call, forcing the `permission_callback` to bubble up an interrupt. |
| **Provider Auth Error** | `AuthenticationError` | Model explicitly raises an HTTP-like auth error or `AcpAuthError` on the first tick. |

## 4. Derived Mock Team Presets
Based on the required UI states, we will structure the `.vaultspec/teams/mock-*.toml` files to use `provider = "mock"` and bind `capability` to these precise scenarios:

1. **`mock-success-single.toml`**: Simulates a single model completing a task cleanly.
2. **`mock-success-multi.toml`**: Simulates a supervisor routing to a coder, then reviewer, and finishing.
3. **`mock-failure-tool.toml`**: Model emits garbage JSON; worker crashes or reaches recursion limit.
4. **`mock-invalid.toml`**: Model explicitly raises `InvalidUpdateError` or `AuthenticationError`.
5. **`mock-autonomous.toml`**: Model streams a long thought process and makes transparent tool calls without yielding.
6. **`mock-human-in-loop.toml`**: Model invokes `session/request_permission`, raising a `GraphBubbleUp` interrupt to the UI.

## Conclusion
The Native SDK implementation allows robust testing of the front-end stream without additional mock server infrastructure.

By combining `MockChatModel` with custom TOML definitions, developers can launch the primary VaultSpec server with `LANGSMITH_PROJECT=mock-tests` and saturate the UI via the standard WebSocket stream.
