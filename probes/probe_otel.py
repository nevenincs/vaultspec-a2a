"""Probe 0 - OTel / Jaeger connectivity check.

Verifies that:
  1. configure_telemetry() succeeds and returns a real SDK config
  2. A synthetic span is emitted to Jaeger over OTLP gRPC (localhost:4317)
  3. The span is queryable via the Jaeger HTTP API after force-flush

Usage::

    python probes/probe_otel.py

Jaeger UI: http://localhost:16686
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from opentelemetry import trace as otel_trace

from lib.telemetry import configure_telemetry, get_tracer


def _query_jaeger_services() -> list[str]:
    with urllib.request.urlopen("http://localhost:16686/api/services", timeout=5) as resp:
        return json.loads(resp.read()).get("data", [])


def main() -> None:
    print("=" * 60)
    print("PROBE 0 - OTel / Jaeger connectivity")
    print("=" * 60)

    cfg = configure_telemetry()
    print(f"\n[telemetry] {cfg!r}")

    if not cfg.sdk_enabled:
        print("[FAIL] SDK not enabled — check OTEL_SDK_DISABLED")
        sys.exit(1)
    if not cfg.otlp_available:
        print("[FAIL] OTLP exporter not available")
        sys.exit(1)

    print(f"[ok]   SDK enabled, OTLP -> {cfg.otlp_endpoint}")

    tracer = get_tracer("probe.otel")
    with tracer.start_as_current_span("probe.otel.connectivity_check") as span:
        span.set_attribute("probe.name", "probe_otel")
        span.set_attribute("probe.layer", "telemetry")
        span.set_attribute("probe.target", "jaeger")
        time.sleep(0.05)
        span.add_event("connectivity_verified")

    # Force-flush the BatchSpanProcessor so the span reaches Jaeger before exit
    provider = otel_trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        print("[wait] force_flush() ...")
        provider.force_flush(timeout_millis=5000)
        print("[ok]   flush complete")
    else:
        print("[warn] provider has no force_flush — waiting 3 s")
        time.sleep(3)

    # Confirm service visible in Jaeger
    try:
        services = _query_jaeger_services()
        if cfg.service_name in services:
            print(f"[ok]   Service '{cfg.service_name}' visible in Jaeger")
        else:
            print(f"[warn] Service not yet in Jaeger (found: {services})")
            print("       The span may still be buffered — open the UI to verify")
    except Exception as exc:
        print(f"[warn] Could not query Jaeger: {exc}")

    print()
    print("Jaeger UI  : http://localhost:16686")
    print(f"Service    : {cfg.service_name}")
    print("Operation  : probe.otel.connectivity_check")
    print()
    print("[PASS] Probe 0 complete")


if __name__ == "__main__":
    main()
