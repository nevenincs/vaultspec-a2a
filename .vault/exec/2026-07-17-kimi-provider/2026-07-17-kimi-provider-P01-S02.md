---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S02'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Add Provider.KIMI to the provider enum with its MODEL_MAP and PROVIDER_DEFAULT_MODELS entries, additive and never renaming existing members (executor-core)

## Scope

- `src/vaultspec_a2a/graph/enums.py`

## Description

- Add the `KIMI = "kimi"` member to `Provider` (alphabetical, additive; no existing member renamed).
- Add the `Provider.KIMI` `MODEL_MAP` entry mapping the four capability tiers to the `kimi-k2` family (`kimi-k2` for LOW/MID, `kimi-k2-thinking` for HIGH/MAX).
- Add the `Provider.KIMI: Model.MID` `PROVIDER_DEFAULT_MODELS` entry (mirroring the Z.ai document-lane default).
- Update the `TestProvider.test_members` completeness set to include `"kimi"`.

## Outcome

The Kimi lane has its enum identity and model mapping, purely additive. The model names are grounded in the installed `kimi-cli` 1.49.0 source, which recognizes the `kimi-k2` family (its welcome check guards on `model_name.startswith("kimi-k2")` and the source references `kimi-k2` and `kimi-k2-thinking`); the thinking variant is placed at the higher tiers. The account's exact available model ids are confirmed only on `KIMI_API_KEY` arrival (P05), noted in the code comment. The default tier is `MID`, mirroring the Z.ai lane (the other `AcpChatModel` variant). Gate: ruff clean, ty clean, 18 `test_enums` tests pass including the MODEL_MAP/PROVIDER_DEFAULT_MODELS completeness assertions (every provider has an entry, no extra keys) which now cover `KIMI`.

## Notes

- The `Provider.test_members` completeness set is a hardcoded enumeration; adding `KIMI` required updating it (additive, one entry). This is the only test that pins the exact member set - the MODEL_MAP/default tests iterate `Provider` dynamically and needed no change beyond the two new map entries.
- Model-name grounding is best-effort against the CLI source without a key: `kimi-k2`/`kimi-k2-thinking` are the recognized names, but whether the Moonshot account exposes those exact ids (vs `kimi-k2-0711-preview` etc.) is key-gated; `KIMI_MODEL_NAME` (S03) lets the operator override, so a wrong default is correctable without code.
