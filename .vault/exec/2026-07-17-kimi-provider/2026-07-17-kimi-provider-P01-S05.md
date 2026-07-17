---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S05'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Record the kimi-cli 1.49.0 pin as a named constant co-located with the factory binary-resolution code and surface it in the install hint mirroring the _classify_acp_command pattern, verifying the Git-Bash prerequisite and honoring KIMI_SHELL_PATH (executor-core)

## Scope

- `src/vaultspec_a2a/providers/factory.py`

## Description

- Add the `_KIMI_CLI_PIN = "1.49.0"` named constant co-located with the factory binary-resolution code, plus `_KIMI_INSTALL_HINT` (`uv tool install kimi-cli==1.49.0`).
- Add `_kimi_git_bash_resolvable`, mirroring the CLI's own Git-Bash resolution order (`KIMI_CLI_GIT_BASH_PATH` override → `git`/`bash` on PATH → standard install path).
- Enrich the `classify_provider_command` KIMI branch: the unresolvable-binary error now surfaces the pinned install hint, and a missing-Git-Bash prerequisite raises with the correct env-var name.
- Add tests: the pin/hint co-location, the classify resolution/hint path, and the Git-Bash prerequisite helper (asserting the corrected env-var name).

## Outcome

The Kimi provisioning axis has one recorded home: `_KIMI_CLI_PIN`, surfaced in the `uv tool install kimi-cli==1.49.0` hint on the unresolvable path, mirroring the `_classify_acp_command` "Run 'npm install' ..." pattern but on the NEW Python `uv tool` axis (distinct from the Node `package.json` adapter pin). The Git-Bash prerequisite is verified: `classify_provider_command(Provider.KIMI)` now raises if the CLI's required shell cannot be resolved, matching the reason the CLI itself exits at startup. Verified: pin `1.49.0`, install hint correct, `_kimi_git_bash_resolvable()` True (Git 2.54.0 present), classify returns `kimi_cli`/`system_path_executable`. Gate: ruff clean, ty clean, 26 factory tests pass.

## Notes

- GROUNDING CORRECTION (installed-source re-grounding superseded the ADR): the ADR/research named the shell override `KIMI_SHELL_PATH`, but the installed `kimi-cli` 1.49.0 source (`utils/environment.py:100`, `os.environ.get("KIMI_CLI_GIT_BASH_PATH")`, and the CHANGELOG shell-backend entry) reads `KIMI_CLI_GIT_BASH_PATH`. The code and the prerequisite hint use the CORRECT name; `_KIMI_GIT_BASH_ENV` centralizes it and a test pins it, so a future ADR reader is not misled. The resolution order also matches the CLI's: env override (validated to exist) → `git`/`bash` on PATH → `C:\Program Files\Git\bin\bash.exe`.
- "Honoring KIMI_SHELL_PATH" from the Step text is satisfied by honoring the ACTUAL override `KIMI_CLI_GIT_BASH_PATH`: if the operator sets it, `_kimi_git_bash_resolvable` accepts it, and the CLI subprocess (which reads the same var from its inherited environment) uses it - the factory does not need to re-inject it because it is a non-secret passthrough that survives the env scrub.
- Prerequisite placement: the Git-Bash check lives in `classify_provider_command` (the no-instantiation seam the readiness probe consumes in S06), so both readiness and any pre-dispatch check share one gate; `_classify_kimi_command` itself stays a pure command-resolver (no prerequisite side effects), matching the Codex/Gemini classifier convention.
