---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S93'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Guard optional OTLP exporter detection so the desktop base initializes gateway and worker telemetry without server extras and prove it from a clean base installation

## Scope

- `src/vaultspec_a2a/telemetry`

## Description

- Trace the gateway and worker lifespan calls into the shared production telemetry initializer.
- Probe every OTLP namespace parent before probing the trace and metric exporter modules.
- Treat only a missing module specification as capability absence while allowing parent import failures to propagate.
- Add an executable clean-base probe that imports the gateway and worker entrypoint modules and initializes each profile in an independent Python process.

## Outcome

The desktop base now initializes its mandatory OpenTelemetry SDK when the
optional `opentelemetry.exporter` namespace is genuinely absent. Both service
profiles report `otlp_available=false`; the gateway retains service name
`vaultspec-a2a` and the worker retains `vaultspec-worker`.

A fresh CPython 3.13 environment was populated from the locked default export
without extras or dependency groups, then installed with the production
project. The environment confirmed that `opentelemetry.exporter` had no module
spec before the durable probe passed for both service entrypoints.

## Notes

Focused telemetry verification passed with 29 tests in the development
environment, exercising the installed-exporter branch. Ruff lint, Ruff
formatting, and ty checks passed for both changed Python files. The clean
environment exercised the absent-exporter branch and was removed with all of
its installed packages after the probe.

No exception is caught by the availability guard. This is deliberate: import
errors from an installed but broken exporter remain visible rather than being
misreported as an unavailable optional capability. The plan row remains open
for independent review.
