"""Report the provider lanes, models, and controls THIS host serves right now.

Model names move. A catalog that named them in source would be wrong by the next
provider release, so nothing in this repository hardcodes an external model
value: a lane is discovered by spawning the provider's own CLI and reading what
it advertises. This report is that discovery, printed.

Its second job is the live tier's opt-in. A billable proof turn runs only when an
operator names one exact lane through ``VAULTSPEC_LIVE_*``, because the suite
deliberately ranks nothing and will not spend money on a model it chose for
itself. Those identifiers are content-derived, so they change whenever the served
catalog does - which makes a pasted-and-forgotten block the obvious failure mode.
Printing them from live discovery is the fix; do not commit the values.

Run through the harness::

    just dev test lanes
    just dev test lanes --exports claude=haiku --option effort=low

``--exports`` renders the environment block for one chosen lane, in the syntax of
the shell that asked for it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vaultspec_a2a.providers.provider_catalog import ProviderCatalog

#: The five identifiers one live proof lane is declared with. Imported from the
#: suite that consumes them rather than restated, so a rename cannot leave this
#: reporter emitting a block nothing reads.
_SELECTION_NAMES = (
    "VAULTSPEC_LIVE_PROVIDER_ID",
    "VAULTSPEC_LIVE_EXECUTION_MODE",
    "VAULTSPEC_LIVE_ENTRY_ID",
    "VAULTSPEC_LIVE_CONTROL_ID",
    "VAULTSPEC_LIVE_OPTION_ID",
)

#: Discovery spawns real provider subprocesses; a wedged CLI must not hang a
#: report someone is running to find out why their lane is quiet.
_DISCOVERY_TIMEOUT_SECONDS = 180.0


async def _discover(
    workspace_root: Path,
) -> list[tuple[str, ProviderCatalog | None, str]]:
    """Discover every registered lane, keeping a failure beside its lane."""
    from vaultspec_a2a.providers.factory import ProviderFactory

    results: list[tuple[str, ProviderCatalog | None, str]] = []
    for registration in ProviderFactory().catalog_registrations(workspace_root):
        label = f"{registration.key.provider_id} [{registration.key.execution_mode}]"
        try:
            discovery = await asyncio.wait_for(
                registration.discover(), timeout=_DISCOVERY_TIMEOUT_SECONDS
            )
        # Broad on purpose: one unreachable CLI must not hide the lanes that did
        # answer, which is the whole point of running this report.
        except Exception as exc:
            results.append((label, None, f"{type(exc).__name__}: {exc}"))
            continue
        results.append((label, discovery.catalog, str(discovery.authentication)))
    return results


def _as_payload(
    discovered: list[tuple[str, ProviderCatalog | None, str]],
) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    for label, catalog, note in discovered:
        if catalog is None:
            lanes.append({"lane": label, "error": note})
            continue
        lanes.append(
            {
                "lane": label,
                "provider_id": catalog.key.provider_id,
                "execution_mode": catalog.key.execution_mode,
                "status": str(catalog.state.status),
                "authentication": note,
                "models": [
                    {"entry_id": m.entry_id, "provider_value": m.provider_value}
                    for m in catalog.models
                ],
                "controls": [
                    {
                        "control_id": c.control_id,
                        "options": [
                            {
                                "option_id": o.option_id,
                                "provider_value": o.provider_value,
                            }
                            for o in c.options
                        ],
                    }
                    for c in catalog.native_controls
                ],
            }
        )
    return lanes


def _print_report(lanes: list[dict[str, Any]]) -> None:
    for lane in lanes:
        if "error" in lane:
            print(f"{lane['lane']}: DISCOVERY FAILED - {lane['error']}")
            continue
        print(f"{lane['lane']}  status={lane['status']} auth={lane['authentication']}")
        for model in lane["models"]:
            print(
                f"    model  {model['provider_value']:<24} entry_id={model['entry_id']}"
            )
        for control in lane["controls"]:
            print(f"    control {control['control_id']}")
            for option in control["options"]:
                print(
                    f"        option {option['provider_value']:<12} "
                    f"option_id={option['option_id']}"
                )


def _render_exports(
    lanes: list[dict[str, Any]], selection: str, option: str | None, shell: str
) -> int:
    """Print the env block for ``provider=model``, or say exactly what is missing."""
    provider_id, _, model_value = selection.partition("=")
    if not provider_id or not model_value:
        print("--exports expects PROVIDER=MODEL, e.g. claude=haiku", file=sys.stderr)
        return 2

    lane = next(
        (
            candidate
            for candidate in lanes
            if candidate.get("provider_id") == provider_id and "error" not in candidate
        ),
        None,
    )
    if lane is None:
        print(f"no lane discovered for provider {provider_id!r}", file=sys.stderr)
        return 1

    model = next(
        (m for m in lane["models"] if m["provider_value"] == model_value), None
    )
    if model is None:
        served = ", ".join(m["provider_value"] for m in lane["models"]) or "(none)"
        print(
            f"{provider_id} does not serve model {model_value!r}; it serves: {served}",
            file=sys.stderr,
        )
        return 1

    control_id, option_id = _resolve_option(lane, option)
    if control_id is None:
        print(f"{provider_id} serves no control matching {option!r}", file=sys.stderr)
        return 1

    values = (
        provider_id,
        lane["execution_mode"],
        model["entry_id"],
        control_id,
        option_id,
    )
    print(
        "# Regenerate whenever the served catalog changes; these ids are derived\n"
        "# from it and a stale block selects a model the lane no longer serves."
    )
    for name, value in zip(_SELECTION_NAMES, values, strict=True):
        if shell == "bash":
            print(f'export {name}="{value}"')
        else:
            print(f'$env:{name} = "{value}"')
    return 0


def _resolve_option(
    lane: dict[str, Any], option: str | None
) -> tuple[str | None, str | None]:
    """Resolve ``control=value``, or fall back to the lane's first option."""
    controls = lane["controls"]
    if not controls:
        return None, None
    if option is None:
        first = controls[0]
        if not first["options"]:
            return None, None
        return first["control_id"], first["options"][0]["option_id"]
    wanted_control, _, wanted_value = option.partition("=")
    for control in controls:
        if control["control_id"] != wanted_control:
            continue
        for candidate in control["options"]:
            if candidate["provider_value"] == wanted_value:
                return control["control_id"], candidate["option_id"]
    return None, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m dev.providers", description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the discovery as machine-readable JSON.",
    )
    parser.add_argument(
        "--exports",
        metavar="PROVIDER=MODEL",
        help="Print the VAULTSPEC_LIVE_* block selecting one served lane.",
    )
    parser.add_argument(
        "--option",
        metavar="CONTROL=VALUE",
        help="The native control option to select (default: the lane's first).",
    )
    parser.add_argument(
        "--shell",
        choices=("pwsh", "bash"),
        default="pwsh",
        help="Shell syntax for --exports (default: pwsh).",
    )
    args = parser.parse_args(argv)

    # The suite declares a development environment for itself; discovery reads
    # the same settings, so this reporter must not describe a different posture.
    os.environ.setdefault("VAULTSPEC_ENVIRONMENT", "development")

    lanes = _as_payload(asyncio.run(_discover(Path.cwd())))

    if args.exports:
        return _render_exports(lanes, args.exports, args.option, args.shell)
    if args.json:
        print(json.dumps(lanes, indent=2))
        return 0
    _print_report(lanes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
