"""Thin CLI over the capsule preparation orchestration.

Preparation is the phase that mints the pinned capsule input descriptor the
build stage later opens read-only.  This entrypoint wires the committed pinned
inputs, the two dependency locks, and a source-HEAD wheel build into one
per-target descriptor by delegating to
:func:`vaultspec_a2a.desktop.capsule_preparation.prepare_capsule_inputs`; it owns
no preparation logic of its own.

Usage:
  uv run --no-sync python scripts/prepare_desktop_capsule.py \\
      --target x86_64-pc-windows-msvc \\
      --out-dir dist/capsule-inputs
"""

from __future__ import annotations

from pathlib import Path

import click

from vaultspec_a2a.desktop.capsule_input_authoring import CapsuleInputAuthoringError
from vaultspec_a2a.desktop.capsule_preparation import prepare_capsule_inputs
from vaultspec_a2a.desktop.contract import TargetTriple

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_INPUTS = _REPO_ROOT / "scripts" / "desktop_capsule_inputs.toml"
_DEFAULT_UV_LOCK = _REPO_ROOT / "uv.lock"
_DEFAULT_PACKAGE_LOCK = _REPO_ROOT / "package-lock.json"
_DEFAULT_SOURCE_DATE_EPOCH = 1_700_000_000


@click.command()
@click.option(
    "--target",
    required=True,
    type=click.Choice([triple.value for triple in TargetTriple]),
    help="Target triple to prepare capsule inputs for.",
)
@click.option(
    "--out-dir",
    required=True,
    type=click.Path(),
    help="Directory to write the pinned capsule input descriptor.",
)
@click.option(
    "--cache-dir",
    default=None,
    type=click.Path(),
    help="Content-addressed acquisition cache.  Defaults to <out-dir>/.cache.",
)
@click.option(
    "--inputs",
    default=str(_DEFAULT_INPUTS),
    type=click.Path(),
    help="Pinned inputs document (committed by default).",
)
@click.option(
    "--uv-lock",
    default=str(_DEFAULT_UV_LOCK),
    type=click.Path(),
    help="Python dependency lock (committed by default).",
)
@click.option(
    "--package-lock",
    default=str(_DEFAULT_PACKAGE_LOCK),
    type=click.Path(),
    help="ACP dependency lock (committed by default).",
)
@click.option(
    "--source-date-epoch",
    default=_DEFAULT_SOURCE_DATE_EPOCH,
    type=int,
    help="Deterministic build epoch for the source-HEAD wheel.",
)
def prepare(
    target: str,
    out_dir: str,
    cache_dir: str | None,
    inputs: str,
    uv_lock: str,
    package_lock: str,
    source_date_epoch: int,
) -> None:
    """Emit the pinned capsule input descriptor for TARGET.

    Prints the written descriptor path and its sha256; the descriptor is proven
    against the production verified-input session before it is returned.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir) if cache_dir else out / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    try:
        descriptor_path, digest = prepare_capsule_inputs(
            TargetTriple(target),
            inputs_toml=Path(inputs),
            uv_lock=Path(uv_lock),
            package_lock=Path(package_lock),
            repo_root=_REPO_ROOT,
            cache_root=cache,
            output_dir=out,
            source_date_epoch=source_date_epoch,
        )
    except CapsuleInputAuthoringError as error:
        raise click.ClickException(str(error)) from None
    click.echo(str(descriptor_path))
    click.echo(f"sha256:{digest}")


if __name__ == "__main__":
    prepare()
