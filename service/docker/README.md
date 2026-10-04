# Development fixture image

`vidaimock.Dockerfile` builds the deterministic mock-provider fixture used by
native service integration tests. Jaeger uses its upstream image. Neither is
a production dependency; gateway and worker run as native processes.

## Build and start

Run commands from the repository root:

```console
just build-docker
just stack-integration-config
just stack-integration-up
just stack-integration-status
just stack-integration-down
```

`build-docker` builds VidaiMock without starting containers. The integration
Compose file defines only VidaiMock and Jaeger. For trace debugging without
the mock provider, use `just stack-infrastructure-up`, which starts only
Jaeger in a separate Compose project. Stop it with
`just stack-infrastructure-down`.

The fixture ports bind to loopback. See the [service overview](../README.md)
for endpoints and the [operator reference](../../docs/operations.rst) for
native process and fixture lifecycle commands.
