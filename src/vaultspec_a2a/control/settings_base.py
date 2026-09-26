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
* **Where a value may come from** - in one order, highest first: the
  construction call, the process environment, the operator's own settings file
  when this process names one, a registered credential from the project's
  ``.env`` under vaultspec-core's gate, then a file secret, then the field's
  default.

The project a2a serves is a workspace it did not write: its ``.env`` arrives
with a clone. Nothing in it configures the service. Only a credential declared
in :mod:`.env_registry` is read from it, one name at a time, and only when
vaultspec-core's gate opens - the running interpreter belongs to that workspace
and the workspace runs this package as a project dependency. Settings come from
the process environment, or from a file the operator names on this process with
``VAULTSPEC_A2A_ENV_FILE`` or in the construction call. That file is never
discovered: an operator who names it has decided to trust it, which is why it
ranks with the session environment, and a named file that is not there is an
error rather than a silent fall-through to defaults.

The project root is taken from the process environment only. An environment
file is resolved relative to the project root, so letting one name a different
root would make the answer depend on which file was read first.
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
from pydantic_settings.sources import DotenvType
from vaultspec_core.config import (
    ConfigurationError,
    CredentialSource,
    env_value,
    resolve_credential,
)

from .env_prefix import ENV_PREFIX
from .env_registry import CREDENTIAL_VARIABLES, ENV_FILE_VARIABLE

__all__ = [
    "ENV_FILE_ENV",
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


#: The one variable that names the project root. Read from the process
#: environment only; see the module docstring.
PROJECT_ROOT_ENV = f"{ENV_PREFIX}PROJECT_ROOT"

#: Directories whose presence marks a vaultspec project root, searched before
#: the version-control fallback.
PROJECT_MARKERS: tuple[str, ...] = (".vaultspec", ".vault")

#: The version-control marker: a directory in a clone, a file in a worktree.
_VCS_MARKER = ".git"

#: The project's own dotenv file. Repository content: it supplies registered
#: credentials under vaultspec-core's gate, and never a setting.
PROJECT_DOTENV = ".env"

#: The variable an operator names their own settings file with.
ENV_FILE_ENV = ENV_FILE_VARIABLE.env_name

# Stands in for "this class takes the operator's environment file, if one is
# named" in ``model_config`` so that ``settings_customise_sources`` can tell the
# class default apart from a caller's explicit ``_env_file`` (including
# ``_env_file=None``, which takes no file at all).
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


def settings_key(field: FieldInfo, field_name: str) -> str:
    """Return the key a settings source must file a value for *field* under.

    A field that declares an alias is validated by that alias and by nothing
    else, so a source keying its value to the field's own name would have it
    discarded as an extra. An un-aliased field is validated by its name.
    """
    alias = field.validation_alias or field.alias
    if isinstance(alias, str):
        return alias
    if isinstance(alias, AliasChoices):
        chosen = next(
            (choice for choice in alias.choices if isinstance(choice, str)), None
        )
        if chosen is not None:
            return chosen
    return field_name


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
    A rooted path without a drive (``\\app\\data``, which is how a ``Path`` built
    from ``/app/data`` prints on Windows) is absolute for the same reason.
    """
    windows = PureWindowsPath(raw)
    return (
        PurePosixPath(raw.replace("\\", "/")).is_absolute()
        or windows.is_absolute()
        or bool(windows.root)
    )


def resolve_against(root: Path, value: Path | str) -> Path:
    """Return ``value`` unchanged when absolute, else joined onto ``root``.

    The single rule for every relative storage setting: it is relative to the
    project root, never to the working directory, so two processes of one
    project resolve it identically wherever each was launched.
    """
    text = os.fspath(value)
    if is_absolute_path(text):
        return Path(text)
    windows = PureWindowsPath(text)
    if windows.drive and not windows.root:
        # "C:foo" is relative to drive C's per-process working directory, which
        # joining would silently keep; rebase what follows the drive instead.
        text = str(PureWindowsPath(*windows.parts[1:])) if windows.parts[1:] else "."
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
    """An environment-file source that can never supply the project root.

    The file was resolved against the project root; a value inside it naming
    another root would contradict the lookup that found it.
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


class _WorkspaceCredentials(PydanticBaseSettingsSource):
    """The credentials the project's own ``.env`` may supply, and nothing else.

    Every value comes through vaultspec-core's gate, which reads one declared
    name at a time and opens the file only for a workspace that runs this
    package from its own environment. A field this source does not know is left
    to the sources below it, so the file cannot reach a setting.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        self._resolved: dict[str, Any] | None = None

    def _gated(self, root: Path, field_name: str) -> str | None:
        """Return what the gate lets the workspace supply for one field."""
        for entry in CREDENTIAL_VARIABLES[field_name]:
            credential = resolve_credential(entry, root)
            if credential is None:
                continue
            # The process environment is a higher-ranked source in its own
            # right; only what the gated file supplied belongs to this one.
            if credential.source is CredentialSource.DOTENV:
                return credential.key
            return None
        return None

    def _from_the_workspace(self) -> dict[str, Any]:
        """Resolve each declared credential once per construction."""
        if self._resolved is not None:
            return self._resolved
        root = resolve_project_root()
        resolved: dict[str, Any] = {}
        if (root / PROJECT_DOTENV).is_file():
            for field_name in CREDENTIAL_VARIABLES:
                field = self.settings_cls.model_fields.get(field_name)
                if field is None:
                    continue
                key = self._gated(root, field_name)
                if key is not None:
                    # Keyed as the field is validated - by its alias where it
                    # declares one - so a credential reaches the field that
                    # declared it rather than being dropped as an extra.
                    resolved[settings_key(field, field_name)] = key
        self._resolved = resolved
        return resolved

    @override
    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        key = settings_key(field, field_name)
        return self._from_the_workspace().get(key), key, False

    @override
    def __call__(self) -> dict[str, Any]:
        return dict(self._from_the_workspace())


def _named_paths(named: DotenvType) -> tuple[Path, ...]:
    """Return every path an ``env_file`` names, as paths."""
    if isinstance(named, (str, os.PathLike)):
        return (Path(named),)
    return tuple(Path(entry) for entry in named)


def _operator_env_file(
    settings_cls: type[BaseSettings], declared: DotEnvSettingsSource
) -> PydanticBaseSettingsSource | None:
    """Return the source for the operator's settings file, or ``None``.

    Args:
        settings_cls: The settings class being built.
        declared: The dotenv source pydantic-settings built from the class's
            own ``model_config``, carrying either the marker that means "the
            operator's file, if this process names one" or a file the
            construction call named outright.

    Returns:
        A source reading the named file, or ``None`` when no file is named.

    Raises:
        ConfigurationError: If a named file does not exist.
    """
    named: DotenvType | None = declared.env_file
    if named is None:
        return None
    root = resolve_project_root()
    if _named_paths(named) == (_PROJECT_DOTENV_MARKER,):
        from_environment = env_value(ENV_FILE_VARIABLE)
        if from_environment is None:
            return None
        named = resolve_against(root, from_environment)
        source = ENV_FILE_ENV
    else:
        source = "the construction call"
    paths = tuple(resolve_against(root, path) for path in _named_paths(named))
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ConfigurationError(
            f"{source} names an environment file that does not exist: "
            f"{', '.join(missing)}"
        )
    return _DotEnvWithoutProjectRoot(
        settings_cls,
        DotEnvSettingsSource(
            settings_cls,
            env_file=list(paths),
            env_file_encoding=declared.env_file_encoding,
        ),
    )


class ProjectSettings(BaseSettings):
    """Base for every a2a settings class: the one resolution order.

    Subclasses set ``env_file=_PROJECT_DOTENV_MARKER`` through
    :meth:`project_dotenv` to take the operator's environment file when the
    process names one, and the project's gated credentials either way.
    """

    @classmethod
    def project_dotenv(cls) -> Path:
        """Return the marker a subclass's ``model_config`` names as its env file."""
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
        """Rank the sources: call, environment, operator file, credentials, secrets."""
        operator = (
            _operator_env_file(settings_cls, dotenv_settings)
            if isinstance(dotenv_settings, DotEnvSettingsSource)
            else None
        )
        ranked: tuple[PydanticBaseSettingsSource, ...] = (init_settings, env_settings)
        if operator is not None:
            ranked = (*ranked, operator)
        return (
            *ranked,
            _WorkspaceCredentials(settings_cls),
            file_secret_settings,
        )
