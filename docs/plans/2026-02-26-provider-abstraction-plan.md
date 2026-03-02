---
date: 2026-02-26
type: plan
feature: provider-abstraction
description: "Implementation plan for the LLM Context and Provider Abstraction layer per ADR-002, securely instantiating LangChain BaseChatModel connections to external LLM providers."
related_adrs:
  - docs/adrs/2026-02-25-002-llm-context-provider-abstraction-adr.md
  - docs/adrs/2026-02-26-009-module-hierarchy-adr.md
related_research:
  - docs/research/2026-02-25-protocols-distilled-research.md
  - docs/research/2026-02-25-process-distilled-research.md
---

# Implement Model Provider Abstraction Layer

This plan outlines the implementation of the LLM Context & Provider Abstraction
layer as mandated by **ADR-002**. This foundational layer will securely
instantiate connection objects to external LLM providers using standard
LangChain `BaseChatModel` interfaces.

## User Review Required

> [!CAUTION]
> **API Keys for Testing**
> Since this project strictly forbids mocks in tests (`GEMINI.md`: "Mocks are
FORBIDDEN. Every test must run live real code against real services."), the
integration tests will make real network calls to the LLM APIs.
> You must ensure that your local `.env`file or environment variables are
populated with valid keys for the providers you have access to
(e.g.,`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `ZHIPU_API_KEY`).

## Proposed Changes

### `pyproject.toml`

Verify or add the necessary LangChain provider packages (e.g.,
`langchain-google-genai`, `langchain-anthropic`, `langchain-openai`).

### `lib/core/config.py`

Update the `Settings`class to manage provider-specific parameters like global
timeouts and model defaults, ensuring keys are sourced from the environment.

### `lib/providers/factory.py`

Implement the core `ProviderFactory`class that returns a
configured`BaseChatModel`.

- **Gemini**: Instantiates `ChatGoogleGenerativeAI`.
- **Claude**: Instantiates `ChatAnthropic`.
- **GLM-5**: Instantiates `ChatOpenAI`populated with the
  custom`base_url="https://open.bigmodel.cn/api/paas/v4/"`, satisfying the
  OpenAI-compatibility mandate in ADR-002 without custom translation layers.
- **Codex/OpenAI**: Standard `ChatOpenAI`.

### `lib/providers/tests/test_factory.py`

#### [NEW] `lib/providers/tests/test_factory.py`

Implement live integration tests testing the `ProviderFactory`.
The tests will instantiate a model and use `invoke("Say hi")`to guarantee
end-to-end network connectivity. If a specific API key is absent from the
environment, we will use`pytest.mark.skipif`to bypass that specific provider
test to prevent hard failures for missing developer credentials, while strictly
avoiding mocks.

## Verification Plan

### Automated Tests

I will use the`uv` python package manager to run the newly created integration
tests.

```powershell
.\.venv\Scripts\Activate.ps1
uv run pytest lib/providers/tests/test_factory.py -v
```

### Manual Verification

No specific manual verification is needed beyond running the tests since the
integration tests will run live network protocols. You can verify that the
console output displays live responses from the language models.
