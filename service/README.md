# Development service fixtures

Production uses native binaries and has no Docker dependency. This directory
contains Docker support only for Jaeger trace debugging. Gateway and worker run
as native processes.

## Native development services

Run commands from the repository root. The named host-process registry owns
the gateway and worker:

```console
just service-gateway-up
just service-worker-up
just service-list
```

Use the endpoints and registrations reported by the registry; stop a process
with `just service-kill NAME`. Every engine-facing `/v1` request requires the
gateway bearer. Its owner-restricted `service.token` handoff is beside
`service.json` in the configured state home. The separate
`VAULTSPEC_A2A_INTERNAL_TOKEN` is for gateway-to-worker traffic.

See [`.env.example`](../.env.example) for supported settings and the
[operator reference](../docs/operations.rst) for authentication, state paths,
and native lifecycle ownership.

## Integration fixtures

`docker-compose.integration.yml` defines only Jaeger. The integration harness
starts gateway and worker natively and uses this container as a development/test
dependency.

Run `just test-native-integration` to exercise native lifecycle, cancellation,
health, trace, and worker attachment checks with the development fixture.

```console
just stack-integration-config
just stack-integration-up
just stack-integration-status
just stack-integration-down
```

The Jaeger user interface is available at <http://127.0.0.1:16686>. Native
processes export OTLP gRPC traces to `http://127.0.0.1:4317`. `JAEGER_UI_PORT`
and `JAEGER_OTLP_PORT` change the host ports while retaining loopback binding.
OTLP HTTP and Jaeger's health endpoint remain inside the Compose network.

## Trace debugging

Configure native trace exporters through the settings in `.env.example`, and
start the Jaeger fixture above to receive them.

HTTP trace URL attributes omit query strings, fragments, and URL user
information. Trace paths, server addresses, and run/thread identifiers remain
sensitive diagnostic data.

## Native releases

Changes go through the PR merge gate. Maintainers start a release through the
existing cut workflow:

```console
gh workflow run release-please.yml --ref main
```

Release qualification builds native archives, proves that each frozen runtime
starts, serves, and stops, and verifies archive provenance before publishing
the complete release. There are no gateway or worker images to publish or
deploy. The consumer owns installation and process lifecycle; the accepted
Dashboard contract uses a native binary.
