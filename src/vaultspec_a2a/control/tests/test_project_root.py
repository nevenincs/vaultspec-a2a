"""The project root: the one anchor every default and relative path hangs from.

Resolution is exercised against real directory trees. The settings cases build
real ``Settings`` objects against a real ``.env`` so the dotenv lookup is proven
end to end rather than inferred from the resolver alone.
"""

from pathlib import Path
from typing import Protocol, cast

from ...domain_config import DomainSettingsConfig
from ...testing import armed_environment
from ..config import Settings
from ..settings_base import (
    PROJECT_ROOT_ENV,
    nearest_ancestor_with,
    resolve_against,
    resolve_project_root,
)


class _SettingsEnvFileFactory(Protocol):
    """``Settings`` called with pydantic-settings' private ``_env_file`` argument."""

    def __call__(self, *, _env_file: Path) -> Settings: ...


def _tree(root: Path, *markers: str) -> Path:
    for marker in markers:
        (root / marker).mkdir(parents=True, exist_ok=True)
    nested = root / "a" / "b"
    nested.mkdir(parents=True, exist_ok=True)
    return nested


def test_a_vaultspec_marker_anywhere_above_wins(tmp_path: Path) -> None:
    nested = _tree(tmp_path, ".vault")
    assert resolve_project_root({}, nested) == tmp_path.resolve()


def test_a_vaultspec_marker_beats_a_nearer_repository(tmp_path: Path) -> None:
    """A nested clone inside a vaultspec project still serves the outer project."""
    nested = _tree(tmp_path, ".vaultspec")
    (tmp_path / "a" / ".git").mkdir()
    assert resolve_project_root({}, nested) == tmp_path.resolve()


def test_a_worktree_git_file_counts_as_the_repository_marker(tmp_path: Path) -> None:
    """A linked worktree carries ``.git`` as a file, and it still marks the root."""
    nested = _tree(tmp_path)
    (tmp_path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    assert nearest_ancestor_with(nested, (".git",)) == tmp_path


def test_no_marker_falls_back_to_the_working_directory(tmp_path: Path) -> None:
    nested = _tree(tmp_path)
    resolved = resolve_project_root({}, nested)
    # The temporary tree may itself sit inside a marked checkout; either way the
    # answer is the start or one of its ancestors, never somewhere unrelated.
    assert resolved == nested.resolve() or resolved in nested.resolve().parents


def test_an_explicit_absolute_root_is_taken_verbatim(tmp_path: Path) -> None:
    nested = _tree(tmp_path, ".vault")
    elsewhere = tmp_path / "elsewhere"
    assert resolve_project_root({PROJECT_ROOT_ENV: str(elsewhere)}, nested) == elsewhere


def test_an_explicit_relative_root_resolves_against_the_working_directory(
    tmp_path: Path,
) -> None:
    nested = _tree(tmp_path, ".vault")
    resolved = resolve_project_root({PROJECT_ROOT_ENV: "../sibling"}, nested)
    assert resolved == (tmp_path / "a" / "sibling").resolve()


def test_relative_storage_values_join_the_root_and_absolute_ones_do_not(
    tmp_path: Path,
) -> None:
    assert resolve_against(tmp_path, "state/x.db") == tmp_path / "state" / "x.db"
    assert resolve_against(tmp_path, "../up") == tmp_path.parent / "up"
    # A container path named on a Windows host is still absolute.
    assert resolve_against(tmp_path, "/app/state") == Path("/app/state")


def test_settings_read_the_project_roots_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("VAULTSPEC_PORT=12345\n", encoding="utf-8")
    with armed_environment(**{PROJECT_ROOT_ENV: str(tmp_path), "VAULTSPEC_PORT": None}):
        configured = Settings()
    assert configured.project_root == tmp_path
    assert configured.port == 12345


def test_domain_settings_read_the_same_dotenv(tmp_path: Path) -> None:
    """The domain singleton no longer reads a .env beside the launch directory."""
    (tmp_path / ".env").write_text("VAULTSPEC_MAX_CACHED_GRAPHS=7\n", encoding="utf-8")
    with armed_environment(
        **{PROJECT_ROOT_ENV: str(tmp_path), "VAULTSPEC_MAX_CACHED_GRAPHS": None}
    ):
        assert DomainSettingsConfig().max_cached_graphs == 7


def test_a_dotenv_cannot_name_a_different_project_root(tmp_path: Path) -> None:
    """With no override in the environment, a dotenv's own root value is dropped."""
    hijacked = tmp_path / "hijacked"
    env_file = tmp_path / ".env"
    env_file.write_text(f"{PROJECT_ROOT_ENV}={hijacked}\n", encoding="utf-8")
    with armed_environment(**{PROJECT_ROOT_ENV: None}):
        configured = cast("_SettingsEnvFileFactory", Settings)(_env_file=env_file)
        expected = resolve_project_root()
    assert configured.project_root == expected
    assert configured.project_root != hijacked
