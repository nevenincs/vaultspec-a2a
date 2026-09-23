"""The settings base every a2a configuration class derives from.

Two facts are resolved here, before any settings field is read, because every
other default depends on them:

* **The project root** - the directory a2a serves and keeps its state under. An
  explicit ``VAULTSPEC_A2A_PROJECT_ROOT`` wins; otherwise the nearest ancestor of
  the working directory that holds a vaultspec marker (``.vaultspec/`` or
  ``.vault/``), then the nearest one holding ``.git``; otherwise the working
  directory itself. The marker search is what makes the answer stable: a gateway
  and a CLI started from different folders of one project agree on one root,
  where a bare working directory would found a second store per launch folder.
* **The dotenv file** - ``<project root>/.env``. It is located per construction,
  not at import, so a process that relocates its project root reads that
  project's file rather than the one beside the first import.

The project root is taken from the process environment only. A dotenv file is
found BY the project root, so letting that file name a different root would make
the answer depend on which file was read first.
"""

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, override

from pydantic import AliasChoices
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource,
)

__all__ = [
    "ENV_PREFIX",
    "PROJECT_DOTENV",
    "PROJECT_MARKERS",
    "PROJECT_ROOT_ENV",
    "ProjectSettings",
    "env_name",
    "field_env_names",
    "is_absolute_path",
    "resolve_against",
    "resolve_project_root",
]

#: The prefix every a2a-owned environment variable carries.
ENV_PREFIX = "VAULTSPEC_A2A_"

#: The one variable that names the project root. Read from the process
#: environment only; see the module docstring.
PROJECT_ROOT_ENV = f"{ENV_PREFIX}PROJECT_ROOT"

#: Directories whose presence marks a vaultspec project root, searched before
#: the version-control fallback.
PROJECT_MARKERS: tuple[str, ...] = (".vaultspec", ".vault")

#: The version-control marker: a directory in a clone, a file in a worktree.
_VCS_MARKER = ".git"

#: The dotenv file's name inside the project root.
PROJECT_DOTENV = ".env"

# Stands in for "the project root's dotenv file" in ``model_config`` so that
# ``settings_customise_sources`` can tell the class default apart from a caller's
# explicit ``_env_file`` (including ``_env_file=None``, which disables the file).
_PROJECT_DOTENV_MARKER = Path("<vaultspec-a2a project dotenv>")


def field_env_names(
    settings_cls: type[BaseSettings], field_name: str
) -> tuple[str, ...]:
    """Return every environment name a settings field is read from, canonical first.

    An explicit alias or validation alias names the field outright; an
    un-aliased field is read as the class's ``env_prefix`` plus its name. The
    first entry is the canonical a2a name; any later ones are another tool's own
    spelling kept as a fallback.
    """
    field = settings_cls.model_fields[field_name]
    names: list[str] = []
    if field.alias:
        names.append(field.alias)
    validation_alias = field.validation_alias
    if isinstance(validation_alias, str):
        names.append(validation_alias)
    elif isinstance(validation_alias, AliasChoices):
        names.extend(
            choice for choice in validation_alias.choices if isinstance(choice, str)
        )
    if not names:
        prefix = settings_cls.model_config.get("env_prefix") or ""
        names.append(f"{prefix}{field_name}".upper())
    return tuple(dict.fromkeys(names))


def env_name(settings_cls: type[BaseSettings], field_name: str) -> str:
    """Return the canonical environment name of a settings field.

    Every place that WRITES a setting into a child environment takes the name
    from here, so the schema is the only declaration of it.
    """
    return field_env_names(settings_cls, field_name)[0]


def is_absolute_path(raw: str) -> bool:
    """Return whether ``raw`` is absolute under either path convention.

    Storage settings name paths on the DEPLOYMENT host, which is not always the
    host validating them: a Windows workstation legitimately reads a container
    configuration naming ``/app/data``, and ``pathlib`` there calls that relative.
    """
    return PurePosixPath(raw).is_absolute() or PureWindowsPath(raw).is_absolute()


def resolve_against(root: Path, value: Path | str) -> Path:
    """Return ``value`` unchanged when absolute, else joined onto ``root``.

    The single rule for every relative storage setting: it is relative to the
    project root, never to the working directory, so two processes of one
    project resolve it identically wherever each was launched.
    """
    text = os.fspath(value)
    if is_absolute_path(text):
        return Path(text)
    return Path(os.path.normpath(root / text))


def nearest_ancestor_with(start: Path, markers: tuple[str, ...]) -> Path | None:
    for candidate in (start, *start.parents):
        if any((candidate / marker).exists() for marker in markers):
            return candidate
    return None


def resolve_project_root(
    environ: dict[str, str] | None = None, cwd: Path | None = None
) -> Path:
    """Resolve the project root from the environment and the working directory.

    ``environ`` and ``cwd`` default to the live process values; they are
    parameters so the resolution is a pure function of its inputs.
    """
    environment = os.environ if environ is None else environ
    start = (cwd if cwd is not None else Path.cwd()).resolve()  # storage-anchor-ok
    explicit = environment.get(PROJECT_ROOT_ENV, "").strip()
    if explicit:
        return resolve_against(start, explicit)
    return (
        nearest_ancestor_with(start, PROJECT_MARKERS)
        or nearest_ancestor_with(start, (_VCS_MARKER,))
        or start
    )


class _DotEnvWithoutProjectRoot(PydanticBaseSettingsSource):
    """A dotenv source that can never supply the project root.

    The file was located BY the project root; a value inside it naming another
    root would contradict the lookup that found it.
    """

    def __init__(
        self, settings_cls: type[BaseSettings], inner: PydanticBaseSettingsSource
    ) -> None:
        super().__init__(settings_cls)
        self._inner = inner

    @override
    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        return self._inner.get_field_value(field, field_name)

    @override
    def __call__(self) -> dict[str, Any]:
        values = self._inner()
        for key in ("project_root", PROJECT_ROOT_ENV):
            values.pop(key, None)
        return values


class ProjectSettings(BaseSettings):
    """Base for every a2a settings class: reads ``<project root>/.env``.

    Subclasses set ``env_file=_PROJECT_DOTENV_MARKER`` through
    :meth:`project_dotenv` so the file is located at construction time.
    """

    @classmethod
    def project_dotenv(cls) -> Path:
        """Return the marker a subclass's ``model_config`` names as its dotenv."""
        return _PROJECT_DOTENV_MARKER

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Swap the dotenv marker for the resolved project root's file."""
        if (
            isinstance(dotenv_settings, DotEnvSettingsSource)
            and dotenv_settings.env_file == _PROJECT_DOTENV_MARKER
        ):
            dotenv_settings = DotEnvSettingsSource(
                settings_cls,
                env_file=resolve_project_root() / PROJECT_DOTENV,
                env_file_encoding=dotenv_settings.env_file_encoding,
            )
        return (
            init_settings,
            env_settings,
            _DotEnvWithoutProjectRoot(settings_cls, dotenv_settings),
            file_secret_settings,
        )
