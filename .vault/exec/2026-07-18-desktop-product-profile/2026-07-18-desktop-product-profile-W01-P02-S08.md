---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S08'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Load bundled agent and team presets through package-owned resource paths

## Scope

- `src/vaultspec_a2a/team/team_config.py`

## Description

- Replace the checkout-relative `__file__` preset root with an
  `importlib.resources`-resolved authority over the `vaultspec_a2a.team` package.
- Derive the bundled agent and team preset directories from that package-owned
  root, keeping them as `Path` objects so all discovery operations are unchanged.

## Outcome

The bundled preset directories now resolve from the installed
`vaultspec_a2a.team` package through `importlib.resources.files`, rather than a
`Path(__file__).parent` relative to the checkout. The two module constants stay
`Path` objects, so the globbing, membership, and candidate-path construction in
`discover_agent_preset_ids`, `discover_team_preset_ids`, `load_agent_config`, and
`load_team_config` are byte-for-byte unchanged; only the root authority moved.

The two-level workspace-then-bundled discovery order is preserved, and the
`mock-` preset marking through `is_mock_preset` is untouched. Source and Compose
discovery still see the repository's wider certification inventory. The desktop
product inventory is instead curated by the S06 wheel exclusions, so its clean
installation contains only the production resources that this package-owned
seam discovers.

## Tests

- `uv run --no-sync pytest src/vaultspec_a2a/team -q` reported 120 passed,
  including the preset-discovery, config-load, and validation suites.
- A discovery probe confirmed the resolved teams directory is a real directory,
  12 team and 16 agent presets are discovered, `mock-success-single` is present,
  and `load_team_config("vaultspec-solo-coder")` resolves.
- Independent review installed the clean S06 wheel into isolated CPython 3.13
  and confirmed the resource root is under `site-packages`, exactly nine agent
  and two team production presets are discovered, no mock or deterministic
  certification id is present, a real workspace override wins, and a missing
  preset raises `TeamConfigNotFoundError`.
- `uv run --no-sync pytest src/vaultspec_a2a/desktop_tests -q` reported 5 passed,
  keeping the S05 dependency-closure gate green.
- Ruff check and format, and scoped `ty check`, passed for the changed module.

## Notes

Wheels install unzipped, so the resource traversable is a real filesystem
directory that the existing `Path` operations read without change. No discovery
semantics, workspace-override precedence, or mock marking was altered. S12 owns
the persistent clean-installed artifact assertion for this inventory. No mock,
stub, patch, or skip was introduced.
