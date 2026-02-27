"""HTTP LLM probe engine.

Exercises an HTTP-based provider by issuing a single-turn conversation
via the standard LangChain ``BaseChatModel.ainvoke`` interface.

Used for manual verification that API credentials, base URLs, and
model identifiers are correctly configured end-to-end.
"""

import logging
import time

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from ._protocol import ProbeResult


__all__ = ["run_http_probe"]

logger = logging.getLogger(__name__)


async def run_http_probe(
    model: BaseChatModel,
    model_name: str,
    prompt: str = "Reply with only the single word 'Hello'.",
) -> ProbeResult:
    """Run an HTTP API probe against the given LangChain model.

    Sends a single ``HumanMessage`` via ``ainvoke`` and records the response.
    Any exception from the SDK is captured as a failing :class:`~._protocol.ProbeResult`
    rather than propagated, so callers always receive a structured result.

    Args:
        model:      A fully configured
            :class:`~langchain_core.language_models.BaseChatModel`.
        model_name: Human-readable model identifier used in log messages.
        prompt:     Text prompt to send as the single human turn.

    Returns:
        :class:`~._protocol.ProbeResult` describing whether the probe succeeded.
    """
    t0 = time.monotonic()
    result = ProbeResult(success=False)

    logger.info("Sending prompt to %s...", model_name)
    try:
        response = await model.ainvoke([HumanMessage(content=prompt)])
        content = response.content
        # OpenAI Responses API returns a list of typed content blocks.
        # Extract plain text; fall back to str() for other representations.
        if isinstance(content, list):
            text = " ".join(
                block["text"]
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
        else:
            text = str(content).strip()
        result.success = True
        result.text_chunks = [text]
        result.elapsed_ms = (time.monotonic() - t0) * 1000
        logger.debug("HTTP response: %r", text)
    except Exception as exc:
        result.error = str(exc)
        result.elapsed_ms = (time.monotonic() - t0) * 1000
        logger.error("HTTP probe failed: %s", exc)

    return result
