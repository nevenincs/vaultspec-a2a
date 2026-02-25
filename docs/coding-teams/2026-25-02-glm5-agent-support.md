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
- **Coding Plan (Subscription)**: Zhipu AI offers a specific "GLM Coding Plan" subscription designed for AI IDEs. **Unlike Western providers, this subscription does issue a specific API key.**
- **Highest Tier (Max Plan)**: The highest tier is the **Max Plan** (~$65/mo domestic, ~$200/mo international). This plan provides a massive high-frequency quota (e.g., ~1,600 complex coding prompts every 5 hours) and includes access to GLM-5, Vision models, and 1,000 monthly calls for MCP tools (like Web Search).
- **API Key Caveat**: The API key generated from the Max Plan **cannot be used for general API calls** (e.g., building a standalone web app). It is strictly whitelisted for "supported coding tools" (like Cursor, Cline, or an orchestrator explicitly mimicking a coding IDE).
- **Standard API (Pay-as-you-go)**: If you use GLM-5 outside of the Coding Plan via the Zhipu Open Platform, the cost is approximately $1.00 per 1M input tokens. The Max Plan quota cannot be used to offset these standard API costs.
- **Summary**: For high-volume agentic engineering workflows, a developer can subscribe to the Max Plan and use its dedicated, quota-based API key within an orchestrator. However, for general application development, the standard pay-as-you-go API key is required.
