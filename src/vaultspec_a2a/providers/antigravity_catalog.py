"""Enumerate the Antigravity lane's catalog from its own CLI.

``agy models`` is the lane's only enumeration surface: there is no JSON mode and
no listing API, so discovery runs the CLI and reads what it prints. That is the
same shape every other external lane takes here - the catalog is asked, never
declared - and it is why no Antigravity model id appears anywhere in this tree.

Two properties of the output are load-bearing and both are asserted rather than
assumed. The rows are TAB-separated ``id<TAB>display name``; a space-split would
tear "Gemini 3.8 Flash (High)" into fragments and mint ids that no ``--model``
flag accepts. And the progress notice ("Fetching available models...") goes to
STDERR while the rows go to STDOUT, so only stdout is parsed - reading the merged
streams would turn the notice into a model.

Authentication is INFERRED from the listing rather than probed separately: the
CLI has no status verb, and it cannot enumerate the account's models without a
session, so a successful listing is authentication evidence and a failure is not
distinguishable from a missing login. That inference is stated here rather than
hidden, because it is weaker than the direct evidence the claude and codex lanes
can produce.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ._catalog_fields import display_text, local_id, model_list_revision
from .antigravity_cli import resolve_antigravity_command
from .provider_catalog import (
    MAX_MODELS,
    AuthenticationState,
    CatalogState,
    CatalogStatus,
    ControlKind,
    ModelCatalogEntry,
    NativeControl,
    NativeControlOption,
    ProviderCatalog,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .provider_catalog import ProviderCatalogKey

__all__ = ["discover_antigravity_catalog"]

#: The CLI answers a bare listing quickly; a wedged one must not hold discovery.
_LISTING_TIMEOUT_SECONDS = 90.0

#: Bounded so a runaway CLI cannot stream an unbounded catalog into memory.
_OUTPUT_BUDGET_BYTES = 1 << 20

#: The reasoning-effort domain, declared by ``agy --effort`` as
#: ``(low|medium|high)``. Unlike the model ids this is NOT enumerable: the CLI
#: exposes no listing for it, so the values are carried here and will need
#: revisiting if the flag's domain changes. They are control options, not model
#: names - no model identity is hardcoded by this.
_EFFORT_VALUES = ("low", "medium", "high")
_EFFORT_CONTROL_ID = "effort"


def _unavailable(
    key: ProviderCatalogKey, *, reason: str, authentication: AuthenticationState
) -> tuple[ProviderCatalog, AuthenticationState]:
    return (
        ProviderCatalog(
            key=key,
            state=CatalogState(
                status=CatalogStatus.UNAVAILABLE,
                checked_at=datetime.now(UTC),
                reason=reason,
            ),
            models=(),
        ),
        authentication,
    )


def _effort_control(namespace: str) -> NativeControl:
    return NativeControl(
        control_id=_EFFORT_CONTROL_ID,
        kind=ControlKind.THOUGHT_LEVEL,
        display_name="Reasoning effort",
        options=tuple(
            NativeControlOption(
                option_id=local_id(f"{namespace}:{_EFFORT_CONTROL_ID}", value),
                provider_value=value,
                display_name=value.capitalize(),
            )
            for value in _EFFORT_VALUES
        ),
    )


def _models_from_listing(
    stdout: str, *, namespace: str
) -> tuple[ModelCatalogEntry, ...]:
    """Parse ``id<TAB>display name`` rows, skipping anything that is not one."""
    models: list[ModelCatalogEntry] = []
    seen: set[str] = set()
    for line in stdout.splitlines():
        row = line.strip()
        if not row or "\t" not in row:
            # Progress chatter or a blank; a row without a TAB carries no id.
            continue
        raw_id, _, raw_name = row.partition("\t")
        model_id = raw_id.strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        models.append(
            ModelCatalogEntry(
                entry_id=local_id(f"{namespace}:model", model_id),
                provider_value=model_id,
                display_name=display_text(raw_name.strip() or None, model_id),
            )
        )
        if len(models) >= MAX_MODELS:
            break
    return tuple(models)


async def discover_antigravity_catalog(
    key: ProviderCatalogKey,
    workspace_root: Path,
    *,
    cli_path: str | None = None,
    home: str | None = None,
) -> tuple[ProviderCatalog, AuthenticationState]:
    """Discover the Antigravity catalog by listing models with the real CLI."""
    executable = resolve_antigravity_command(cli_path=cli_path, home=home)
    if executable is None:
        return _unavailable(
            key,
            reason="Antigravity CLI is not installed",
            authentication=AuthenticationState.UNKNOWN,
        )

    try:
        process = await asyncio.create_subprocess_exec(
            str(executable),
            "models",
            cwd=str(workspace_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return _unavailable(
            key,
            reason=f"Antigravity CLI could not be launched: {exc.strerror or exc}",
            authentication=AuthenticationState.UNKNOWN,
        )

    try:
        stdout_bytes, _ = await asyncio.wait_for(
            process.communicate(), timeout=_LISTING_TIMEOUT_SECONDS
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        return _unavailable(
            key,
            reason=(
                f"Antigravity model listing exceeded {_LISTING_TIMEOUT_SECONDS:.0f}s"
            ),
            authentication=AuthenticationState.UNKNOWN,
        )

    if process.returncode != 0:
        # A listing needs the account, so a refusal is most likely a missing
        # login - but the CLI does not say so, and reporting UNAUTHENTICATED on
        # every failure would blame the operator for a crash. UNKNOWN is honest.
        return _unavailable(
            key,
            reason=f"Antigravity model listing exited {process.returncode}",
            authentication=AuthenticationState.UNKNOWN,
        )

    stdout = stdout_bytes[:_OUTPUT_BUDGET_BYTES].decode("utf-8", errors="replace")
    namespace = f"{key.provider_id}:{key.execution_mode}"
    models = _models_from_listing(stdout, namespace=namespace)
    if not models:
        return _unavailable(
            key,
            reason="Antigravity served no models",
            authentication=AuthenticationState.UNAUTHENTICATED,
        )

    controls = (_effort_control(namespace),)
    return (
        ProviderCatalog(
            key=key,
            state=CatalogState(
                status=CatalogStatus.AVAILABLE,
                checked_at=datetime.now(UTC),
                # The bare model list is the whole revision here. The RPC lanes
                # fold their native controls in because a provider can change
                # those between calls; this lane's one control is a static flag
                # domain that cannot move without a code change, so hashing it
                # would add a constant to every revision and signal nothing.
                revision=model_list_revision(key, models),
            ),
            models=models,
            native_controls=controls,
        ),
        AuthenticationState.AUTHENTICATED,
    )
