"""Load example profiles through the service's own settings loader.

Run as a child process with an environment that sets no setting, so the only
values the loader sees are the ones under test: a dotenv profile written from
the example's lines, read exactly as an operator's ``.env`` is read by each of
the service's settings classes, including every decoder and cross-field
validator they carry. Each line is then compared with what the class that
declares it yields when nothing is set at all.

Reads ``{"profiles": [[[name, value], ...], ...]}`` on standard input and writes
one result per profile: the load error, or for each line whether the loaded
value is the code's default. Values are never echoed, so a credential in a
profile cannot reach the report.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ...testing import load_settings
from ._env_example import SERVICE_SETTINGS, declaring_class, setting_field_by_name

if TYPE_CHECKING:
    from pydantic_settings import BaseSettings


def _load_all(dotenv: Path | None) -> dict[type[BaseSettings], BaseSettings]:
    """Load every service settings class from one dotenv file, or from none."""
    return {
        settings_cls: load_settings(settings_cls, env_file=dotenv)
        for settings_cls in SERVICE_SETTINGS
    }


def _profile_result(
    profile: list[list[str]],
    baseline: dict[type[BaseSettings], BaseSettings],
    directory: Path,
    index: int,
) -> dict[str, object]:
    fields = setting_field_by_name()
    dotenv = directory / f"profile-{index}.env"
    dotenv.write_text(
        "".join(f"{name}={value}\n" for name, value in profile if value),
        encoding="utf-8",
    )
    try:
        loaded = _load_all(dotenv)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False)
        return {"error": "; ".join(error["msg"] for error in errors), "lines": []}
    return {
        "error": None,
        "lines": [
            {
                "name": name,
                "matches_default": getattr(loaded[owner], fields[name])
                == getattr(baseline[owner], fields[name]),
            }
            for name, _value in profile
            for owner in (declaring_class(fields[name]),)
        ],
    }


def main() -> None:
    request = json.load(sys.stdin)
    baseline = _load_all(None)
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
