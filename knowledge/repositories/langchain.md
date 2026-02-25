# LangChain Reference

- **Source:** [https://github.com/langchain-ai/langchain](https://github.com/langchain-ai/langchain)
- **Relevance:** 9/10 - Core library for model abstraction and tool integration.

## Overview

LangChain is a framework for developing applications powered by large language
models (LLMs). It provides a standard interface for chains, many integrations
with other tools, and end-to-end chains for common applications.

## Key Components

- **Models:** Abstractions for chat models, completions, and embeddings.
- **Prompts:** Template management and optimization.
- **Tools:** Interface for agents to interact with the world (e.g., search,
  math, custom Python functions).
- **Agents:** Chains that use an LLM to decide which actions to take.
- **Memory:** State persistence between turns of a chain.

## Value for Vaultspec

LangChain provides the model-agnostic layer that allows Vaultspec to easily
switch between Gemini, Claude, and other providers while maintaining a
consistent API for tool-calling and prompt management.
