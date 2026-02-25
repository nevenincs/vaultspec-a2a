# Phase 4 Research: GLM-5 Agent Support and Specificities

**Date**: 2026-02-25
**Provider**: Zhipu AI (GLM-5 Models)
**Status**: Research Complete

---

## 1. Authentication Process
**Local CLI vs. Direct Online APIs**
Similar to OpenAI, Zhipu AI does not provide an official, dedicated local CLI agent for its GLM-5 models. The models are accessed via direct online REST APIs.

**Authentication Methods:**
- **API Keys**: Authentication is handled via the `ZHIPUAI_API_KEY` (often passed as a Bearer token or custom header, depending on the endpoint).
- **OpenAI Compatibility**: Zhipu AI provides an OpenAI-compatible API endpoint structure. This means standard libraries (like the `openai` Python package) can often be pointed to Zhipu's base URL using Zhipu API keys.

**Emerging Consensus:** The consensus for integrating Chinese LLM providers like Zhipu AI into standard frameworks is to use API wrappers that rely on direct online APIs. Due to the lack of an official CLI, orchestration must be managed server-side.

## 2. Agent Client Protocol (ACP) Support
- **No Native Support**: Without an official CLI, GLM-5 has no native ACP support.
- **Custom Wrapper Requirement**: Integration into an ACP host requires a custom ACP server. Given the OpenAI API compatibility, an ACP wrapper built for OpenAI can often be adapted for GLM-5 by simply changing the base URL and API key.

## 3. Agent-to-Agent (A2A) Support
- **Custom A2A Server**: As with Codex/OpenAI, integrating GLM-5 into the A2A ecosystem requires deploying a custom A2A server (e.g., using `a2a-python`).
- **Implementation**: The custom server defines the `AgentCard` and uses the GLM-5 API for its `AgentExecutor`. The A2A server is responsible for translating the protocol's SSE streams and task state management into stateless API calls.

## 4. Technical Requirements for Integration
To successfully integrate Z.ai's GLM-5 into the proposed coding-teams framework:
- **Auth**: The orchestrator must provide the `ZHIPUAI_API_KEY` to the custom agent wrapper.
- **A2A Server Implementation**: A Python A2A server must be deployed to wrap the GLM-5 API. 
- **Tool-Calling Compatibility**: Ensure that the tool-calling format supported by GLM-5 aligns with the expectations of the A2A or MCP tools provided by the orchestrator. If GLM-5's tool-calling syntax differs slightly from standard OpenAI, the A2A server wrapper must handle the translation layer.
- **Localization/Encoding**: Depending on the specific GLM-5 variant, ensure that the A2A server correctly handles character encoding and any potential latency issues when routing requests to regional data centers.

## 5. Pricing & API Usage
**Subscriptions vs. API Billing**
Zhipu AI's GLM-5 utilizes a unique hybrid approach to billing, distinguishing between standard API usage and specific "Agentic Engineering" tools.
- **Coding Plan (Subscription)**: Zhipu AI offers a specific "GLM Coding Plan" subscription (e.g., ¥469/mo for the Max tier). Unlike Western providers, **this subscription does issue a specific API key** optimized for coding tools (like Cursor, Cline, etc.). This key consumes the subscription's monthly usage quotas rather than a cash balance.
- **Standard API (Pay-as-you-go)**: Standard API keys generated from the Zhipu Open Platform are billed on a traditional per-token, pay-as-you-go basis (drawing from a prepaid cash balance).
- **Summary**: For high-volume agentic engineering workflows, an individual developer can subscribe to the "Coding Plan" and use its dedicated API key within an orchestrator. However, for a multi-user or production SaaS orchestrator, the standard pay-as-you-go API key is the necessary approach.
