"""Load example profiles through the service's own settings loader.

Run as a child process with an environment that sets no setting, so the only
values the loader sees are the ones under test: a dotenv profile written from
the example's lines, read exactly as an operator's ``.env`` is read, including
every decoder and cross-field validator the settings class carries. Each line is
then compared with what the same loader yields when nothing is set at all.

Reads ``{"profiles": [[[name, value], ...], ...]}`` on standard input and writes
one result per profile: the load error, or for each line whether the loaded
value is the code's default. Values are never echoed, so a credential in a
profile cannot reach the report.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Protocol, cast

from pydantic import ValidationError

from ...control.config import Settings
from ._env_example import setting_field_by_name


class _SettingsFromDotenv(Protocol):
    """``Settings`` called with pydantic-settings' private ``_env_file`` argument."""

    def __call__(self, *, _env_file: Path | None) -> Settings: ...


#: The one call the loader makes, typed once rather than at each use.
_load = cast("_SettingsFromDotenv", Settings)


def _profile_result(
    profile: list[list[str]], baseline: Settings, directory: Path, index: int
) -> dict[str, object]:
    fields = setting_field_by_name()
    dotenv = directory / f"profile-{index}.env"
    dotenv.write_text(
        "".join(f"{name}={value}\n" for name, value in profile if value),
        encoding="utf-8",
    )
    try:
        loaded = _load(_env_file=dotenv)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False)
        return {"error": "; ".join(error["msg"] for error in errors), "lines": []}
    return {
        "error": None,
        "lines": [
            {
                "name": name,
                "matches_default": getattr(loaded, fields[name])
                == getattr(baseline, fields[name]),
            }
            for name, _value in profile
        ],
    }


def main() -> None:
    request = json.load(sys.stdin)
    baseline = _load(_env_file=None)
    # The parent starts this process in a directory of the test's own, so the
    # profiles are written there rather than anywhere the session does not own.
    directory = Path.cwd()
    results = [
        _profile_result(profile, baseline, directory, index)
        for index, profile in enumerate(request["profiles"])
    ]
    json.dump(results, sys.stdout)


if __name__ == "__main__":
    main()
