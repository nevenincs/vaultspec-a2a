---
date: 2026-02-26
type: research
feature: console-printer
description: 'Research into dual-mode terminal output strategy using rich for the CLI.'
---

# Console & Terminal Printing Strategy

## Objective

Establish best practices for a dual-mode terminal output system that provides
rich, interactive feedback to users in TTY environments while seamlessly
degrading to structured JSON logging for headless, CI, or production
deployments.

## Core Best Practices

### 1. Separation of Concerns (UI vs. Diagnostics)

- **User Interface (`stdout`)**: Communicates intentional progress, user
  prompts, formatted tables, and semantic updates directly to the human
  operator.
- **Diagnostics/Logging (`stderr`)**: Emits structured data, stack traces, and
  system lifecycle events meant for machine parsing, debugging, or log
  aggregation (e.g. Datadog, ELK).

### 2. Contextual Awareness (TTY Detection)

The system must dynamically interrogate its execution environment at startup:

- `is_interactive = sys.stdout.isatty() and sys.stderr.isatty()`
- The system should also respect standard bypass environment variables, such as
  `NO_COLOR=1`or`CI=true`.

### 3. Dual-Mode Architecture (Leveraging `rich`)

Since the project already includes `rich`in`pyproject.toml`, we should
orchestrate outputs as follows:

- **Interactive Mode**:
  - Use `rich.console.Console`for styling standard output.
  - Implement dynamic UI elements (like`rich.progress`or`rich.status`) for
    long-running workflows to avoid terminal spam.
  - Route the standard python `logging`module
    through`rich.logging.RichHandler`to prevent raw text logs from disrupting
    the rendered UI blocks.
- **Headless Mode**:
  - Disable all ANSI styling and dynamic UI features.
  - Use the`JSONFormatter`(previously implemented) across the root logger so
    machine-readable diagnostics are emitted sequentially without visual noise.

## Proposed Component:`lib/utils/printer.py`

A centralized `Printer`singleton acting as a facade for the`rich.Console`will
ensure uniform output styling across the entire`lib/` tree without duplicating
format configurations:

```python
# Pseudo-implementation
class Printer:
    def success(self, msg: str): ...  # Green styling
    def error(self, msg: str): ...    # Red styling
    def warn(self, msg: str): ...     # Yellow styling
    def step(self, msg: str): ...     # Highlighting workflow progression
```

## Conclusion

To integrate this properly, `lib/utils/logging.py`should be retrofitted to
detect`sys.stdout.isatty()`. It would instantiate either the structured
`JSONFormatter`or the`RichHandler`dynamically based on the execution context.
Concurrently, a new`printer.py` should be introduced to handle semantic,
user-facing output.
