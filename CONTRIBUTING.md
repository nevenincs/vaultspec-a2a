# Contributing

This guide explains how to prepare a focused change and submit a pull request
(PR). Report vulnerabilities through the [security policy](SECURITY.md), not a
public issue.

## Prepare a change

1. Open or select a scoped item in [GitHub Issues](https://github.com/nevenincs/vaultspec-a2a/issues).
2. Follow the [README](README.md) and [development guide](docs/development.rst).
3. Run `just help` to discover the native task surface.
4. Keep the change focused on the selected issue.
5. Update tests and documentation when behavior or user workflows change.

## Respect component ownership

The [architecture guide](docs/architecture.rst) is the canonical ownership
map. Don't move product logic into Just recipes, bypass the process registry
for a named host process, or manage a Docker Compose (Compose) stack through
registry commands.

## Write meaningful tests

Import the real code under test and verify observable behavior. Tests must not:

- Reimplement business logic
- Prove tautologies
- Use fakes, mocks, stubs, patches, or monkeypatching as shortcuts
- Use `skip` or `xfail` to manufacture a passing run

Add service tests when a change affects service or integration behavior.

## Complete the rolling audit

Every implementation pass continues the audit cycle. Code written doesn't
close the issue.

1. Implement the targeted change.
2. Run a formal review against the implementation.
3. Classify every finding by severity and type.
4. Append every finding to the relevant audit document or task queue.
5. Update the audit or research trail when implementation changes the system
   understanding.

Capture follow-up work even when the current PR does not address it.

## Validate the change

Run the required gates:

```console
just ci
just dev build docs
```

If the change affects services, also run:

```console
just dev test service
```

If you intend to apply Ruff fixes and formatting, use `just dev code repair`.
The PostgreSQL migration upgrade-and-downgrade round trip is a
separate hosted workflow. If a gate can't run, document why and state the
resulting uncertainty.

## Open the pull request

Include:

- A concise problem and solution summary
- Links to the issue and relevant audit records
- Tests and documentation for changed behavior
- Exact validation commands and results
- Excluded or not run gates with reasons
- Known limitations and queued follow-up findings

Don't include generated build output, runtime files, credentials, tokens, or
other secrets.
