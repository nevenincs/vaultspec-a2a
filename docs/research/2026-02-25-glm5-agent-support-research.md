---
date: 2026-02-25
type: research
feature: glm5-agent
description: 'Provider analysis for Zhipu AI GLM-5 covering API-only access, OpenAI-compatible REST interface, and Coding Plan subscription pricing.'
name: 'GLM-5 Agent Support'
maturity: 20
summary: 'Provider analysis for Zhipu AI GLM-5 covering API-only access, OpenAI-compatible REST interface, and Coding Plan subscription pricing.'
---

# Phase 4 Research: GLM-5 Agent Support and Specificities

**Date**: 2026-02-25
**Provider**: Zhipu AI (GLM-5 Models)
**Status**: Research Complete

---

## 1. Authentication Process

**Local CLI vs. Direct Online APIs**
Zhipu AI officially promotes integration with CLI tools by leveraging a
customized fork of the open-source Gemini CLI (specifically the
`feature/openrouter-support`branch on`heartyguy/gemini-cli`). This allows users
to run GLM models locally within a terminal interface.

### Authentication Methods

- **API Keys**: Regardless of whether you use the CLI fork or direct online
  APIs, authentication is handled purely via API keys. In the context of the
  Gemini CLI fork, users export an `OPENROUTER_API_KEY`and point
  the`OPENROUTER_BASE_URL`to Zhipu's endpoint
  (e.g.,`https://api.z.ai/api/coding/paas/v4`).
- **OpenAI Compatibility**: Zhipu AI provides an OpenAI-compatible REST API
  structure. Standard libraries (like the `openai`Python package) can easily be
  pointed to Zhipu's base URL using Zhipu API keys.

**Emerging Consensus & Architectural Assessment:**
While there is "CLI support" via a community fork of the Gemini CLI, the
architectural assessment strongly favors **Direct Online APIs**.

- Unlike Gemini or Claude, where wrapping the first-party CLI is necessary to
  "hijack" the consumer subscription and avoid per-token API billing, Zhipu AI's
  subscription model operates fundamentally differently.
- Zhipu AI's "Coding Plan" subscription natively issues an API key that draws
  from a monthly subscription quota.
- Because the subscription natively supports API quotas, there is absolutely no
  architectural or financial benefit to wrapping a brittle, third-party CLI fork
  just to get a local agent experience. **Direct online API calls using a custom
  A2A server wrapper are significantly more robust, stable, and
  cost-effective.**

## 2. Agent Client Protocol (ACP) Support

- **No Native Support**: The customized Gemini CLI fork does not natively
  support ACP for Zhipu out of the box.
- **Custom Wrapper Requirement**: Integration into an ACP host requires a custom
  ACP server. Given the OpenAI API compatibility, an ACP wrapper built for
  OpenAI can be easily adapted for GLM-5 by simply changing the base URL and
  injecting the Coding Plan API key.

## 3. Agent-to-Agent (A2A) Support

- **Custom A2A Server**: Integrating GLM-5 into the A2A ecosystem requires
  deploying a custom A2A server (e.g., using`a2a-python`), rather than relying
  on a CLI wrapper.
- **Implementation**: The custom server defines the `AgentCard`and uses the
  direct GLM-5 REST API for its`AgentExecutor`. The A2A server translates the
  protocol's SSE streams and task state management into stateless API calls.

## 4. Technical Requirements for Integration

To successfully integrate Z.ai's GLM-5 into the proposed coding-teams framework:

- **Auth**: The orchestrator must provide the Zhipu `API_KEY` to the custom
  Python A2A server.
- **A2A Server Implementation**: A lightweight Python A2A server must be
  deployed to wrap the GLM-5 API directly. Avoid using the Gemini CLI fork.
- **Tool-Calling Compatibility**: Ensure that the tool-calling format supported
  by GLM-5 aligns with the expectations of the A2A or MCP tools provided by the
  orchestrator. The A2A server wrapper must handle any necessary translation
  layers.
- **Endpoint Routing**: Ensure the A2A wrapper points specifically to the Coding
  Plan endpoint (`https://api.z.ai/api/coding/paas/v4`) rather than the standard
  Open Platform endpoint, ensuring billing correctly hits the subscription
  quota.

## 5. Pricing & API Usage

**Subscriptions vs. API Billing**
Zhipu AI's GLM-5 utilizes a unique hybrid approach to billing that is highly
advantageous for developers building orchestrators.

- **Coding Plan (Subscription)**: Zhipu AI offers a specific "GLM Coding Plan"
  subscription designed for AI IDEs. **Unlike Western providers, this
  subscription does issue a specific API key.**
- **Highest Tier (Max Plan)**: The highest tier is the **Max Plan** (~$65/mo
  domestic, ~$200/mo international). This plan provides a massive high-frequency
  quota (e.g., ~1,600 complex coding prompts every 5 hours) and includes access
  to GLM-5, Vision models, and 1,000 monthly calls for MCP tools (like Web
  Search).
- **API Key Caveat**: The API key generated from the Max Plan **cannot be used
  for general API calls** (e.g., building a standalone web app). It is strictly
  whitelisted for "supported coding tools" (like Cursor, Cline, or an
  orchestrator explicitly mimicking a coding IDE).
- **Standard API (Pay-as-you-go)**: If you use GLM-5 outside of the Coding Plan
  via the Zhipu Open Platform, the cost is approximately $1.00 per 1M input
  tokens. The Max Plan quota cannot be used to offset these standard API costs.
- **Summary**: For the proposed A2A framework, a developer can subscribe to the
  Max Plan, take the generated API key, and use it directly within a Python A2A
  wrapper. Because the subscription provides an API key natively tied to the
  flat-rate quota, there is no need to employ complex "OAuth bypass" tricks or
  CLI wrappers like we must do for Gemini and Claude.
