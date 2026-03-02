"""Probe 1 - OpenAI provider via ProviderFactory.

Verifies that:
  1. ProviderFactory.create() produces a working ChatOpenAI instance
  2. A single ainvoke() call completes and returns an AIMessage
  3. The LangChain call is wrapped in an OTel span visible in Jaeger

Every step is printed to stdout for visual inspection.
Failures raise and print a traceback — no silent swallowing.

Usage::

    python probes/probe_provider_openai.py

Jaeger UI: http://localhost:16686  (service: vaultspec-a2a, op: probe.provider.openai)

Requirements:
    VAULTSPEC_OPENAI_API_KEY env var (or set in .env)
"""

from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, ".")

from opentelemetry import trace as otel_trace

from langchain_core.messages import HumanMessage

from lib.telemetry import configure_telemetry, get_tracer
from lib.providers.factory import ProviderFactory
from lib.utils.enums import Model, Provider


async def run_probe() -> None:
    tracer = get_tracer("probe.provider.openai")

    with tracer.start_as_current_span("probe.provider.openai") as root:
        root.set_attribute("probe.provider", "openai")
        root.set_attribute("probe.model_level", "low")

        print("[step 1] Creating provider via ProviderFactory ...")
        with tracer.start_as_current_span("provider.factory.create"):
            model = ProviderFactory.create(provider=Provider.OPENAI, model=Model.LOW)
        print(f"[ok]     model type  : {type(model).__name__}")
        print(f"[ok]     model name  : {getattr(model, 'model_name', getattr(model, 'model', '?'))}")

        print()
        print("[step 2] Invoking model with a simple prompt ...")
        prompt = [HumanMessage(content="Reply with exactly: PROBE_OK")]

        t0 = time.perf_counter()
        with tracer.start_as_current_span("provider.ainvoke") as span:
            response = await model.ainvoke(prompt)
            span.set_attribute("response.type", type(response).__name__)
            span.set_attribute("response.content_len", len(str(response.content)))

        elapsed = time.perf_counter() - t0
        print(f"[ok]     response    : {response.content!r}")
        print(f"[ok]     latency     : {elapsed:.2f} s")

        root.set_attribute("probe.success", True)

    # Force-flush before exit
    provider = otel_trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush(timeout_millis=5000)

    print()
    print("Jaeger UI  : http://localhost:16686")
    print("Service    : vaultspec-a2a")
    print("Operation  : probe.provider.openai")
    print()
    print("[PASS] Probe 1 complete")


def main() -> None:
    print("=" * 60)
    print("PROBE 1 - OpenAI provider (ProviderFactory)")
    print("=" * 60)
    print()

    cfg = configure_telemetry()
    print(f"[telemetry] {cfg!r}")
    print()

    asyncio.run(run_probe())


if __name__ == "__main__":
    main()
