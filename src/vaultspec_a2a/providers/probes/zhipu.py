"""Probe for Zhipu AI (GLM) — OpenAI-compatible Chinese LLM.

Runs a single-turn conversation through the Zhipu GLM API
(``https://open.bigmodel.cn/api/paas/v4/``) using the ``ZHIPU_API_KEY``
configured in VaultSpec settings and the default model resolved by
:class:`~vaultspec_a2a.providers.factory.ProviderFactory`.

Run directly::

    python -m vaultspec_a2a.providers.probes.zhipu

Exit code 0 on success, 1 on failure.
"""

import asyncio
import logging
import sys

from ...control.config import settings
from ...utils.enums import MODEL_MAP, PROVIDER_DEFAULT_MODELS, Provider
from ...utils.logging import setup_logging
from ..factory import ProviderFactory
from ._http import run_http_probe
from ._protocol import ProbeResult

__all__ = ["main"]

logger = logging.getLogger(__name__)

_PROMPT = "Reply with only the single word 'Hello'. No other text."


async def main() -> ProbeResult:
    """Run the Zhipu GLM HTTP API probe and return the result.

    Reads the API key from :attr:`~vaultspec_a2a.core.config.Settings.zhipu_api_key`.
    Returns a failing :class:`~._protocol.ProbeResult` when the key is not
    configured rather than raising.
    """
    if not settings.zhipu_api_key:
        logger.error(
            "ZHIPU_API_KEY is not configured — set VAULTSPEC_ZHIPU_API_KEY in .env"
        )
        return ProbeResult(success=False, error="ZHIPU_API_KEY not set")

    model_name = MODEL_MAP[Provider.ZHIPU][PROVIDER_DEFAULT_MODELS[Provider.ZHIPU]]
    logger.info("Starting Zhipu GLM probe (model=%s)...", model_name)

    model = ProviderFactory().create(Provider.ZHIPU)
    result = await run_http_probe(model, model_name, prompt=_PROMPT)

    if result.success:
        logger.info(
            "PROBE PASSED — text=%r elapsed=%.0fms",
            result.full_text,
            result.elapsed_ms,
        )
    else:
        logger.error("PROBE FAILED — error=%s", result.error)

    return result


if __name__ == "__main__":
    setup_logging("debug")
    outcome = asyncio.run(main())
    sys.exit(0 if outcome.success else 1)
