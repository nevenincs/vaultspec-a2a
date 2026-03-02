"""Probe 2 - Gemini provider via AcpChatModel (subprocess JSON-RPC).

Verifies the full ACP stdio protocol path:
  subprocess spawn -> initialize handshake -> session/new -> session/prompt
  -> streamed chunks -> AIMessage assembled -> checkpoint-ready output

Every ACP protocol stage is captured as an OTel child span.
Failures raise and print a traceback — no silent swallowing.

Usage::

    python probes/probe_provider_gemini.py

Jaeger UI: http://localhost:16686  (service: vaultspec-a2a, op: probe.provider.gemini)

Requirements:
    Active Gemini CLI session (~/.gemini/oauth_creds.json)
    `gemini` binary on PATH
"""

from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, ".")

from opentelemetry import trace as otel_trace

from langchain_core.messages import AIMessageChunk, HumanMessage

from lib.telemetry import configure_telemetry, get_tracer
from lib.providers.factory import ProviderFactory
from lib.utils.enums import Model, Provider


async def run_probe() -> None:
    tracer = get_tracer("probe.provider.gemini")

    with tracer.start_as_current_span("probe.provider.gemini") as root:
        root.set_attribute("probe.provider", "gemini")
        root.set_attribute("probe.model_level", "low")
        root.set_attribute("probe.protocol", "acp-stdio")

        print("[step 1] Creating Gemini AcpChatModel via ProviderFactory ...")
        with tracer.start_as_current_span("provider.factory.create"):
            model = ProviderFactory.create(provider=Provider.GEMINI, model=Model.LOW)
        print(f"[ok]     model type  : {type(model).__name__}")

        print()
        print("[step 2] Streaming from Gemini ACP subprocess ...")
        prompt = [HumanMessage(content="Reply with exactly: PROBE_OK")]

        chunks: list[str] = []
        t0 = time.perf_counter()

        with tracer.start_as_current_span("provider.astream") as span:
            async for chunk in model.astream(prompt):
                text = chunk.content if isinstance(chunk, AIMessageChunk) else str(chunk)
                chunks.append(text)
                sys.stdout.write(".")
                sys.stdout.flush()

            elapsed = time.perf_counter() - t0
            full_response = "".join(chunks)
            span.set_attribute("response.chunks", len(chunks))
            span.set_attribute("response.content_len", len(full_response))
            span.set_attribute("response.latency_s", round(elapsed, 2))

        print()
        print(f"[ok]     chunks      : {len(chunks)}")
        print(f"[ok]     response    : {full_response!r}")
        print(f"[ok]     latency     : {elapsed:.2f} s")

        root.set_attribute("probe.success", True)

    provider = otel_trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush(timeout_millis=5000)

    print()
    print("Jaeger UI  : http://localhost:16686")
    print("Service    : vaultspec-a2a")
    print("Operation  : probe.provider.gemini")
    print()
    print("[PASS] Probe 2 complete")


def main() -> None:
    print("=" * 60)
    print("PROBE 2 - Gemini provider (AcpChatModel / ACP stdio)")
    print("=" * 60)
    print()

    cfg = configure_telemetry()
    print(f"[telemetry] {cfg!r}")
    print()

    asyncio.run(run_probe())


if __name__ == "__main__":
    main()
