"""Root conftest — runs at collection time, before any test module imports."""

from __future__ import annotations

import os

# Suppress OTel metric exporter noise during tests.  The trace SDK stays
# active so span-creation tests work.  The metric reader's periodic export
# would otherwise hit localhost:4317 and log UNAVAILABLE errors.
# OTEL_METRICS_EXPORTER=none disables the metric export pipeline entirely.
os.environ.setdefault("OTEL_METRICS_EXPORTER", "none")
# Point the trace exporter at a non-routable address so BatchSpanProcessor
# silently drops spans instead of retrying against localhost:4317.
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://198.51.100.1:4317")
