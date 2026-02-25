# Phase 3 Research: Codex Agent Support and Specificities

**Date**: 2026-02-25
**Provider**: OpenAI (Codex / GPT-4o Models)
**Status**: Research Complete

---

## 1. Authentication Process
**Local CLI vs. Direct Online APIs**
Unlike Gemini and Claude, OpenAI does not provide an official, monolithic "Codex CLI" agent. "Codex" models (and their modern successors like `gpt-4o`) are exposed purely as direct online APIs.

**Authentication Methods:**
- **API Keys**: Authentication is handled exclusively via the `OPENAI_API_KEY` environment variable.
- **Organization/Project IDs**: For enterprise usage, `OPENAI_ORG_ID` and `OPENAI_PROJECT_ID` headers are used to scope billing and access.

**Emerging Consensus:** Because there is no official local CLI, the consensus is to run these agents against direct online APIs. Orchestrators must build or utilize open-source agent wrappers (such as those built with LangChain, LangGraph, or the `a2a-python` SDK) that call the OpenAI API directly.

## 2. Agent Client Protocol (ACP) Support
- **No Native Support**: Since there is no official CLI, there is no native ACP support.
- **Custom Wrapper Requirement**: To integrate an OpenAI model into an ACP-compliant IDE or orchestrator, a custom ACP server must be written. This server would accept ACP JSON-RPC commands via stdio or WebSocket and translate them into OpenAI API calls (using functions/tool-calling to emulate local actions).

## 3. Agent-to-Agent (A2A) Support
- **Custom A2A Server**: Integrating OpenAI models into an A2A ecosystem requires building an A2A server using a framework like the `a2a-python` SDK.
- **Implementation**: The A2A server would define an `AgentCard`, expose skills, and run an `AgentExecutor` that manages the conversational state and forwards requests to the OpenAI API.
- **Tool Usage**: The custom A2A server must also implement its own tool execution environment (e.g., executing code in a Docker container) since the OpenAI API only returns tool-call requests, not their actual execution.

## 4. Technical Requirements for Integration
To successfully integrate Codex/OpenAI into the proposed coding-teams framework:
- **Auth**: The orchestrator must provide the `OPENAI_API_KEY` to the custom agent wrapper.
- **A2A Server Implementation**: A lightweight Python A2A server must be deployed to wrap the OpenAI API. This server will handle the `Task` lifecycle, stream chunks via SSE, and translate OpenAI's tool-calling format into A2A artifacts or MCP tool executions.
- **State Management**: The A2A server wrapper must manage the conversation context and task history, as the OpenAI API is fundamentally stateless.

## 5. Pricing & API Usage
**Subscriptions vs. API Billing**
OpenAI enforces a strict separation between consumer subscriptions and developer APIs.
- **Interactive/Subscription Model**: The **ChatGPT Plus** ($20/month) subscription provides access to models like GPT-4o exclusively through the ChatGPT web and mobile interfaces.
- **API Model**: To build automated agents and orchestrators, developers must use the **OpenAI API**.
- **API Keys Do Not Use Subscriptions**: API keys generated via the OpenAI Platform require a separate, prepaid cash balance. They do not draw from or benefit from a ChatGPT Plus subscription. API usage is billed strictly on a pay-as-you-go basis per million tokens.
- **Summary**: A ChatGPT Plus subscription provides no utility for an A2A orchestrator. A developer must establish an OpenAI Platform account, add funds, and use a dedicated API key for agent integration.
