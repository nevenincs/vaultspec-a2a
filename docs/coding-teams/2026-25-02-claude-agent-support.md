# Phase 2 Research: Claude Agent Support and Specificities

**Date**: 2026-02-25
**Provider**: Anthropic (Claude Code CLI)
**Status**: Research Complete

---

## 1. Authentication Process
**Local CLI vs. Direct Online APIs**
Claude Code CLI is heavily optimized for local terminal workflows. It acts as an interactive agent that reads the local file system and invokes Claude's cloud APIs for reasoning.

**Authentication Methods:**
- **Interactive Local CLI**: Users authenticate via `claude login`, which initiates a browser-based OAuth flow for Claude Pro, Team, or Enterprise accounts.
- **Direct Online APIs (Token-based)**:
  - **Environment Variables**: For automated and CI/CD environments, Claude supports the `CLAUDE_TOKEN` environment variable.
  - **Cloud Providers**: It also supports cloud-specific authentication when using models hosted on Amazon Bedrock or Google Cloud Vertex AI (e.g., using AWS credentials or Google ADC).

**Emerging Consensus:** For orchestration, relying on `CLAUDE_TOKEN` or cloud-provider credentials is the consensus. Browser-based authentication is unsuitable for automated, multi-agent frameworks as it requires human intervention upon token expiry.

## 2. Agent Client Protocol (ACP) Support
- **Adapter-based Integration**: Claude Code CLI does not natively expose an ACP server out of the box, but the ecosystem relies on robust adapters. 
- **Community & Official Bridges**: Tools like `@zed-industries/claude-code-acp` and the Python `claude-code-acp` package serve as bridges. These wrap the Claude CLI and handle the JSON-RPC communication required by ACP, allowing IDEs (like Zed, Neovim) or external orchestrators to run Claude as a background agent.

## 3. Agent-to-Agent (A2A) Support
- **MCP as the Gateway**: Claude Code has first-class support for the Model Context Protocol (MCP). Support for the A2A protocol is typically achieved by bridging A2A through an MCP server.
- **A2A-MCP Bridge**: To interact with A2A agents, an A2A-MCP bridge server (e.g., `a2a-mcp`) is configured in the `.claude/settings.json` or `CLAUDE.md`. This server translates MCP tool calls into A2A network requests.
- **Workflow**: Claude Code (Client) -> MCP Protocol -> A2A Bridge Server -> A2A Protocol -> Target Agent. This allows Claude to discover, message, and delegate tasks to other A2A-compliant agents seamlessly.

## 4. Technical Requirements for Integration
To successfully integrate Claude into the proposed coding-teams framework:
- **Auth**: The orchestrator must securely pass the `CLAUDE_TOKEN` or equivalent cloud credentials to the Claude Code CLI process.
- **ACP Wrapper**: Since Claude needs an adapter for ACP, the orchestrator should spawn the `claude-code-acp` process rather than the raw `claude` binary to gain rich streaming and permission flows.
- **Tool Exposure**: Configure the orchestrator to provide Claude with access to isolated workspaces (e.g., Git worktrees) via its native tools or an MCP filesystem server.
- **A2A Delegation**: If Claude needs to act as a supervisor, the orchestrator must inject an A2A-MCP bridge into Claude's configuration to allow it to delegate tasks to other agents.

## 5. Pricing & API Usage
**Subscriptions vs. API Billing**
The **Claude Pro** consumer subscription and the **Anthropic API** are entirely separate platforms.
- **Interactive/Subscription Model**: The $20/month Claude Pro subscription covers usage on Claude.ai and allows interactive use of the **Claude Code CLI** tool at no additional cost (it operates under Claude Pro's rate limits).
- **API Model**: If developers wish to use Anthropic's models inside third-party orchestrators, custom agents, or IDEs (like Cursor or the proposed A2A framework), they must use the **Anthropic API**.
- **API Keys Do Not Use Subscriptions**: API keys generated from the Anthropic Developer Console operate on a pre-paid, pay-as-you-go token model ($3.00/1M input tokens for Sonnet 3.7, for instance). An existing Claude Pro subscription does not provide free or discounted API keys.
- **Summary**: While human developers can use the Claude Code CLI wrapped in their Pro subscription, a multi-agent framework relying on API calls will require an Anthropic API key with a separate, usage-based billing balance.
