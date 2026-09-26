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
import threading
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import UnionType
from typing import Any, Final, Union, cast, final, get_args, get_origin, override

from pydantic import AliasChoices, ValidationError
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    InitSettingsSource,
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
    "build_now",
    "built_at_first_use",
    "env_name",
    "field_env_names",
    "is_absolute_path",
    "read_configuration",
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


@final
class _OperatorEnvFileMarker:
    """Stands in for "the operator's file, if this process names one".

    It sits in ``model_config['env_file']`` so that
    :meth:`ProjectSettings.settings_customise_sources` can tell the class
    default apart from a caller's explicit ``_env_file`` - including
    ``_env_file=None``, which takes no file at all.

    Deliberately NOT a path. A path-shaped marker is a filename, and a
    filename is something a workspace can create: whoever writes a file of
    that name next to the process has written a settings source nobody named.
    This object is compared by identity, so there is no name to collide with.

    It reads as an empty sequence of files, because pydantic-settings builds
    its own dotenv source - and opens whatever that source names - before
    :meth:`ProjectSettings.settings_customise_sources` is given the chance to
    replace it. Naming no file at all is what makes that eager pass a no-op.
    """

    __slots__ = ()

    def __iter__(self) -> Iterator[Path]:
        return iter(())

    def __repr__(self) -> str:
        return "<the operator's environment file, if one is named>"


_OPERATOR_ENV_FILE: Final = _OperatorEnvFileMarker()


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

    def __init__(self, settings_cls: type[BaseSettings], root: Path) -> None:
        super().__init__(settings_cls)
        self._root = root
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
        root = self._root
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


def _construction_project_root(
    init_settings: PydanticBaseSettingsSource,
) -> Path | None:
    """Return the project root the construction call named, if it named one.

    An invocation outranks the session environment for every other field, and
    the root is no exception: a caller that passes ``project_root=`` is naming
    the project this object serves, so the files resolved against that root
    must be that project's, not the launch directory's.
    """
    if not isinstance(init_settings, InitSettingsSource):
        return None
    named = init_settings.init_kwargs.get("project_root")
    if named is None:
        return None
    # Routed through the resolver so a relative value is joined to the working
    # directory exactly as the environment variable's would be.
    return resolve_project_root({PROJECT_ROOT_ENV: os.fspath(named)})


def _operator_env_file(
    settings_cls: type[BaseSettings], declared: DotEnvSettingsSource, root: Path
) -> PydanticBaseSettingsSource | None:
    """Return the source for the operator's settings file, or ``None``.

    Args:
        settings_cls: The settings class being built.
        declared: The dotenv source pydantic-settings built from the class's
            own ``model_config``, carrying either the marker that means "the
            operator's file, if this process names one" or a file the
            construction call named outright.
        root: The project root a relative path is resolved against.

    Returns:
        A source reading the named file, or ``None`` when no file is named.

    Raises:
        ConfigurationError: If a named file does not exist.
    """
    declared_file: object = declared.env_file
    if declared_file is None:
        return None
    if declared_file is _OPERATOR_ENV_FILE:
        from_environment = env_value(ENV_FILE_VARIABLE)
        if from_environment is None:
            return None
        named: DotenvType = Path(from_environment)
        source = ENV_FILE_ENV
    else:
        named = declared_file
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

    Subclasses set ``env_file`` from :meth:`operator_env_file` to take the
    operator's environment file when the process names one, and the project's
    gated credentials either way.
    """

    @classmethod
    def operator_env_file(cls) -> DotenvType:
        """Return the marker a subclass's ``model_config`` names as its env file."""
        return cast("DotenvType", _OPERATOR_ENV_FILE)

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
        root = _construction_project_root(init_settings) or resolve_project_root()
        operator = (
            _operator_env_file(settings_cls, dotenv_settings, root)
            if isinstance(dotenv_settings, DotEnvSettingsSource)
            else None
        )
        ranked: tuple[PydanticBaseSettingsSource, ...] = (init_settings, env_settings)
        if operator is not None:
            ranked = (*ranked, operator)
        return (
            *ranked,
            _WorkspaceCredentials(settings_cls, root),
            file_secret_settings,
        )


def _shape_of(annotation: object) -> str:
    """Render a field's declared type the way an operator would say it.

    The reader of the message is setting an environment variable, so the
    useful half of a refusal is what the variable is FOR: an integer, a path,
    one of a handful of words. Pydantic's own message describes the parse that
    failed, which answers a different question.
    """
    if annotation is None or annotation is type(None):
        return "unset"
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        alternatives = [
            _shape_of(argument)
            for argument in get_args(annotation)
            if argument is not type(None)
        ]
        return " or ".join(dict.fromkeys(alternatives)) or "unset"
    if origin is not None:
        return _shape_of(origin)
    name = getattr(annotation, "__name__", None)
    return str(name or annotation)


def _field_behind(settings_cls: type[BaseSettings], location: object) -> str | None:
    """Return the field name behind one validation-error location, if any.

    A source files its value under the field's validation alias, so a location
    arrives as either spelling; an error a whole-model validator raised carries
    neither, and belongs to no single field.
    """
    key = str(location)
    if key in settings_cls.model_fields:
        return key
    return next(
        (
            field_name
            for field_name in settings_cls.model_fields
            if key in field_env_names(settings_cls, field_name)
        ),
        None,
    )


def _refusal(settings_cls: type[BaseSettings], invalid: ValidationError) -> str:
    """Render every rejected value as one line naming variable, shape and value."""
    lines: list[str] = []
    for problem in invalid.errors():
        field_name = _field_behind(
            settings_cls, problem["loc"][0] if problem["loc"] else ""
        )
        if field_name is None:
            # A whole-model validator, which already says what it refused.
            lines.append(str(problem["msg"]))
            continue
        field = settings_cls.model_fields[field_name]
        # A field the registry declares a credential, or one the schema keeps
        # out of a repr, holds a secret: name it, never quote it.
        secret = field_name in CREDENTIAL_VARIABLES or field.repr is False
        shown = "a redacted value" if secret else repr(problem.get("input"))
        lines.append(
            f"{field_env_names(settings_cls, field_name)[0]} must be "
            f"{_shape_of(field.annotation)}, got {shown}"
        )
    return "\n".join(dict.fromkeys(lines))


def read_configuration[T: BaseSettings](settings_cls: type[T], **values: Any) -> T:
    """Build a settings object, or refuse with one error naming every problem.

    Pydantic reports a rejected value by FIELD, with the parse that failed and
    the value inline - which tells an operator neither which variable to edit
    nor what to put in it, and puts a live credential in the traceback when the
    rejected field holds one. This states the variable, the shape and the
    value, once per problem and all of them together, so a misconfigured start
    is fixed in one pass rather than one restart per mistake.

    Args:
        settings_cls: The settings class to build.
        values: Values the construction call supplies, outranking every source.

    Returns:
        The settings object.

    Raises:
        ConfigurationError: If any value was rejected.
    """
    try:
        return settings_cls(**values)
    except ValidationError as invalid:
        raise ConfigurationError(_refusal(settings_cls, invalid)) from invalid


class _BuiltAtFirstUse[T: BaseSettings]:
    """A settings singleton built when it is first read, not when it is imported.

    A settings class refuses a configuration it cannot read: a named file that
    is not there, a value of the wrong shape. Building the singleton while its
    module is being imported hands that refusal to whoever imported the module
    - as a traceback several frames inside pydantic-settings, and to every
    importer rather than to the process that started the service. Deferring it
    to the first read puts the refusal at a startup site, which renders it as
    one named error.
    """

    __slots__ = ("_build", "_instance", "_lock")

    def __init__(self, build: Callable[[], T]) -> None:
        object.__setattr__(self, "_build", build)
        object.__setattr__(self, "_instance", None)
        object.__setattr__(self, "_lock", threading.Lock())

    def _settings(self) -> T:
        built: T | None = object.__getattribute__(self, "_instance")
        if built is not None:
            return built
        # Two threads racing the first read would otherwise each build one,
        # and every mutation of the loser's copy would be silently discarded.
        with object.__getattribute__(self, "_lock"):
            built = object.__getattribute__(self, "_instance")
            if built is None:
                built = object.__getattribute__(self, "_build")()
                object.__setattr__(self, "_instance", built)
        return built

    def __getattr__(self, name: str) -> Any:
        return getattr(self._settings(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._settings(), name, value)

    def __repr__(self) -> str:
        return repr(self._settings())

    def __dir__(self) -> list[str]:
        return dir(self._settings())


def built_at_first_use[T: BaseSettings](build: Callable[[], T]) -> T:
    """Return a stand-in for a settings singleton, built when it is first read."""
    return cast("T", _BuiltAtFirstUse(build))


def build_now(settings: object) -> None:
    """Build a deferred settings singleton now, so no later reader is the first.

    A service wants the deferral: it keeps a refused configuration out of an
    importer's traceback. A test session wants the opposite - the environment
    it declares before the first test must be the one the singletons read, not
    whatever the test that happened to touch one first had arranged around
    itself. Calling this after those declarations pins them.
    """
    if isinstance(settings, _BuiltAtFirstUse):
        settings._settings()
