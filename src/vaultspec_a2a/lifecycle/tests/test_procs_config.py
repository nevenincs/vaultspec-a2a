"""procs.toml parsing + band-invariant validation.

Real file I/O against the committed procs.toml and against tmp fixtures - no
mocks. The committed file is the source of truth, so its bands and
resident ports are asserted verbatim; the malformed fixtures prove the parser
refuses to silently accept a broken band definition.
"""

from __future__ import annotations

import pytest

from ..procs_config import ProcsConfigError, load_procs_config


def test_committed_procs_toml_matches_the_adr_bands() -> None:
    """The committed procs.toml declares exactly the pinned bands and residents."""
    config = load_procs_config()

    assert config.resident == {"engine": 8767, "gateway": 8000}

    bands = {name: (rc.band.start, rc.band.end) for name, rc in config.roles.items()}
    assert bands["engine-dev"] == (18760, 18769)
    assert bands["gateway-dev"] == (18100, 18109)
    assert bands["worker-dev"] == (18110, 18119)
    assert bands["scratch"] == (18900, 18999)

    # Heartbeating roles carry a staleness window; the serve template is declared.
    engine = config.roles["engine-dev"]
    assert engine.heartbeat is True
    assert engine.staleness_ms == 120000
    assert engine.serve and "{port}" in engine.serve
    # The engine seats its data store relative to cwd, so the serve template must
    # thread {workspace} through to the wrapper's explicit, validated data seat, and
    # the role must require an explicit repo so it never serves from the project root.
    assert "{workspace}" in engine.serve
    assert engine.require_repo is True
    # Roles that do not seat data from cwd stay opt-out.
    assert config.roles["gateway-dev"].require_repo is False

    # Serve templates resolve the interpreter via {python}, never a bare `python`.
    for role in ("engine-dev", "gateway-dev", "worker-dev"):
        assert config.roles[role].serve[0] == "{python}"

    # Roles whose serve reads its port from the environment declare it via `env`
    # (the CLI `serve` has no --port; the worker main ignores argv), so the serve
    # templates carry NO --port flag.
    assert config.roles["gateway-dev"].env == {"VAULTSPEC_PORT": "{port}"}
    assert config.roles["worker-dev"].env == {"VAULTSPEC_WORKER_PORT": "{port}"}
    assert "--port" not in config.roles["gateway-dev"].serve
    assert "--port" not in config.roles["worker-dev"].serve


def test_role_lookup_names_known_roles_on_miss() -> None:
    config = load_procs_config()
    with pytest.raises(ProcsConfigError, match="unknown role 'nope'"):
        config.role("nope")


def _write(tmp_path, body: str):
    path = tmp_path / "procs.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_overlapping_bands_are_rejected(tmp_path) -> None:
    path = _write(
        tmp_path,
        "\n".join(
            [
                "[roles.a]",
                "band = [100, 200]",
                "[roles.b]",
                "band = [150, 250]",
            ]
        ),
    )
    with pytest.raises(ProcsConfigError, match="bands overlap"):
        load_procs_config(path)


def test_resident_port_inside_a_band_is_rejected(tmp_path) -> None:
    path = _write(
        tmp_path,
        "\n".join(
            [
                "[resident]",
                "engine = 150",
                "[roles.a]",
                "band = [100, 200]",
            ]
        ),
    )
    with pytest.raises(ProcsConfigError, match="falls inside role"):
        load_procs_config(path)


def test_malformed_band_is_rejected(tmp_path) -> None:
    path = _write(tmp_path, "[roles.a]\nband = [200, 100]\n")
    with pytest.raises(ProcsConfigError, match="ascending range"):
        load_procs_config(path)


def test_missing_roles_table_is_rejected(tmp_path) -> None:
    path = _write(tmp_path, "[resident]\nengine = 8767\n")
    with pytest.raises(ProcsConfigError, match="at least one role"):
        load_procs_config(path)


def test_role_env_table_is_parsed(tmp_path) -> None:
    path = _write(
        tmp_path,
        "\n".join(
            [
                "[roles.a]",
                "band = [100, 200]",
                "env = { VAULTSPEC_PORT = '{port}', FOO = 'bar' }",
            ]
        ),
    )
    config = load_procs_config(path)
    assert config.roles["a"].env == {"VAULTSPEC_PORT": "{port}", "FOO": "bar"}


def test_role_without_env_defaults_to_empty(tmp_path) -> None:
    path = _write(tmp_path, "[roles.a]\nband = [100, 200]\n")
    assert load_procs_config(path).roles["a"].env == {}


def test_non_string_env_value_is_rejected(tmp_path) -> None:
    path = _write(
        tmp_path,
        "[roles.a]\nband = [100, 200]\nenv = { VAULTSPEC_PORT = 8000 }\n",
    )
    with pytest.raises(ProcsConfigError, match="env must be a table of string"):
        load_procs_config(path)


def test_require_repo_is_parsed_and_defaults_false(tmp_path) -> None:
    path = _write(
        tmp_path,
        "\n".join(
            [
                "[roles.seated]",
                "band = [100, 200]",
                "require_repo = true",
                "[roles.plain]",
                "band = [300, 400]",
            ]
        ),
    )
    config = load_procs_config(path)
    assert config.roles["seated"].require_repo is True
    assert config.roles["plain"].require_repo is False


def test_non_bool_require_repo_is_rejected(tmp_path) -> None:
    path = _write(
        tmp_path,
        "[roles.a]\nband = [100, 200]\nrequire_repo = 'yes'\n",
    )
    with pytest.raises(ProcsConfigError, match="require_repo must be a bool"):
        load_procs_config(path)
