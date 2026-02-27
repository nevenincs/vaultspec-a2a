"""Tests for the error taxonomy and exception hierarchy."""

import pytest

# All other exception types are imported from the core facade to test re-exports
from .. import (
    AgentProcessError,
    ConfigError,
    ContextOverflowError,
    DatabaseError,
    ErrorSeverity,
    EventAggregatorError,
    MergeConflictError,
    PermissionDeniedError,
    ProtocolError,
    RecoveryAction,
    TokenBudgetExceededError,
    VaultspecError,
    WorkspaceError,
)

# Module object used for __all__ introspection
from .. import exceptions as _exceptions_module

# GitWorkspaceError lives in exceptions but is NOT re-exported by the core facade
from ..exceptions import GitWorkspaceError


# ---------------------------------------------------------------------------
# ErrorSeverity enum
# ---------------------------------------------------------------------------


class TestErrorSeverity:
    """Tests for the ErrorSeverity enumeration."""

    def test_members(self) -> None:
        """All expected severity levels are present."""
        assert set(ErrorSeverity) == {
            ErrorSeverity.TRANSIENT,
            ErrorSeverity.PERMANENT,
            ErrorSeverity.UNKNOWN,
        }

    def test_values_are_strings(self) -> None:
        """Each member value is a lowercase string matching its name."""
        for member in ErrorSeverity:
            assert isinstance(member.value, str)
            assert member.value == member.name.lower()


# ---------------------------------------------------------------------------
# RecoveryAction enum
# ---------------------------------------------------------------------------


class TestRecoveryAction:
    """Tests for the RecoveryAction enumeration."""

    def test_members(self) -> None:
        """All expected recovery actions are present."""
        assert set(RecoveryAction) == {
            RecoveryAction.RETRY,
            RecoveryAction.RETRY_WITH_BACKOFF,
            RecoveryAction.REASSIGN,
            RecoveryAction.ESCALATE_TO_USER,
            RecoveryAction.ABORT,
        }

    def test_values_are_strings(self) -> None:
        """Each member value is a string."""
        for member in RecoveryAction:
            assert isinstance(member.value, str)


# ---------------------------------------------------------------------------
# Inheritance hierarchy
# ---------------------------------------------------------------------------


class TestInheritanceHierarchy:
    """Verify the exception class tree matches the design."""

    def test_vaultspec_error_is_exception(self) -> None:
        """VaultspecError is a subclass of Exception."""
        assert issubclass(VaultspecError, Exception)

    def test_git_workspace_error_is_exception(self) -> None:
        """GitWorkspaceError is a subclass of Exception."""
        assert issubclass(GitWorkspaceError, Exception)

    def test_git_workspace_error_not_vaultspec(self) -> None:
        """GitWorkspaceError is a separate tree from VaultspecError."""
        assert not issubclass(GitWorkspaceError, VaultspecError)

    @pytest.mark.parametrize(
        "exc_cls",
        [
            ConfigError,
            WorkspaceError,
            AgentProcessError,
            ProtocolError,
            EventAggregatorError,
            DatabaseError,
            PermissionDeniedError,
            TokenBudgetExceededError,
            ContextOverflowError,
        ],
    )
    def test_direct_subclasses_of_vaultspec_error(
        self, exc_cls: type[VaultspecError]
    ) -> None:
        """Each listed exception class is a direct subclass of VaultspecError."""
        assert issubclass(exc_cls, VaultspecError)

    def test_merge_conflict_is_workspace_error(self) -> None:
        """MergeConflictError is a subclass of WorkspaceError."""
        assert issubclass(MergeConflictError, WorkspaceError)

    def test_merge_conflict_is_also_vaultspec_error(self) -> None:
        """MergeConflictError is also a subclass of VaultspecError."""
        assert issubclass(MergeConflictError, VaultspecError)


# ---------------------------------------------------------------------------
# Default severity and recovery classifications
# ---------------------------------------------------------------------------


_EXPECTED_DEFAULTS: list[tuple[type[VaultspecError], ErrorSeverity, RecoveryAction]] = [
    (VaultspecError, ErrorSeverity.UNKNOWN, RecoveryAction.ESCALATE_TO_USER),
    (ConfigError, ErrorSeverity.PERMANENT, RecoveryAction.ABORT),
    (WorkspaceError, ErrorSeverity.PERMANENT, RecoveryAction.ESCALATE_TO_USER),
    (
        AgentProcessError,
        ErrorSeverity.TRANSIENT,
        RecoveryAction.RETRY_WITH_BACKOFF,
    ),
    (ProtocolError, ErrorSeverity.PERMANENT, RecoveryAction.ABORT),
    (EventAggregatorError, ErrorSeverity.TRANSIENT, RecoveryAction.RETRY),
    (
        DatabaseError,
        ErrorSeverity.TRANSIENT,
        RecoveryAction.RETRY_WITH_BACKOFF,
    ),
    (
        PermissionDeniedError,
        ErrorSeverity.PERMANENT,
        RecoveryAction.ESCALATE_TO_USER,
    ),
    (TokenBudgetExceededError, ErrorSeverity.PERMANENT, RecoveryAction.REASSIGN),
    (ContextOverflowError, ErrorSeverity.PERMANENT, RecoveryAction.REASSIGN),
    (
        MergeConflictError,
        ErrorSeverity.PERMANENT,
        RecoveryAction.ESCALATE_TO_USER,
    ),
]


class TestDefaultClassification:
    """Tests for class-level severity and recovery action defaults."""

    @pytest.mark.parametrize(
        ("exc_cls", "expected_severity", "expected_action"),
        _EXPECTED_DEFAULTS,
        ids=[cls.__name__ for cls, _, _ in _EXPECTED_DEFAULTS],
    )
    def test_class_level_defaults(
        self,
        exc_cls: type[VaultspecError],
        expected_severity: ErrorSeverity,
        expected_action: RecoveryAction,
    ) -> None:
        """Each exception class carries the expected default severity and action."""
        err = exc_cls("test")
        assert err.severity == expected_severity
        assert err.recovery_action == expected_action

    @pytest.mark.parametrize(
        ("exc_cls", "expected_severity", "expected_action"),
        _EXPECTED_DEFAULTS,
        ids=[cls.__name__ for cls, _, _ in _EXPECTED_DEFAULTS],
    )
    def test_instance_str(
        self,
        exc_cls: type[VaultspecError],
        expected_severity: ErrorSeverity,
        expected_action: RecoveryAction,
    ) -> None:
        """str(exception) returns the message passed to the constructor."""
        err = exc_cls("something went wrong")
        assert str(err) == "something went wrong"


# ---------------------------------------------------------------------------
# Override severity / recovery at instantiation
# ---------------------------------------------------------------------------


class TestOverrides:
    """Tests for per-instance severity and recovery_action overrides."""

    def test_override_severity(self) -> None:
        """Severity can be overridden at instantiation; action keeps the default."""
        err = ConfigError(
            "retry this config",
            severity=ErrorSeverity.TRANSIENT,
        )
        assert err.severity is ErrorSeverity.TRANSIENT
        # recovery_action keeps class default
        assert err.recovery_action is RecoveryAction.ABORT

    def test_override_recovery_action(self) -> None:
        """Recovery action can be overridden; severity keeps the default."""
        err = AgentProcessError(
            "escalate instead",
            recovery_action=RecoveryAction.ESCALATE_TO_USER,
        )
        assert err.recovery_action is RecoveryAction.ESCALATE_TO_USER
        # severity keeps class default
        assert err.severity is ErrorSeverity.TRANSIENT

    def test_override_both(self) -> None:
        """Both severity and recovery_action can be overridden together."""
        err = DatabaseError(
            "permanent failure",
            severity=ErrorSeverity.PERMANENT,
            recovery_action=RecoveryAction.ABORT,
        )
        assert err.severity is ErrorSeverity.PERMANENT
        assert err.recovery_action is RecoveryAction.ABORT

    def test_override_does_not_mutate_class(self) -> None:
        """Instance overrides must not change the class-level defaults."""
        _ = DatabaseError(
            "override",
            severity=ErrorSeverity.PERMANENT,
            recovery_action=RecoveryAction.ABORT,
        )
        fresh = DatabaseError("fresh")
        assert fresh.severity is ErrorSeverity.TRANSIENT
        assert fresh.recovery_action is RecoveryAction.RETRY_WITH_BACKOFF


# ---------------------------------------------------------------------------
# Catchability & raise/except round-trips
# ---------------------------------------------------------------------------


class TestCatchability:
    """Tests that exceptions are catchable via the correct base types."""

    def test_catch_vaultspec_error_catches_subclass(self) -> None:
        """VaultspecError catches any subclass."""
        with pytest.raises(VaultspecError):
            raise ConfigError("bad config")

    def test_catch_workspace_error_catches_merge_conflict(self) -> None:
        """WorkspaceError catches MergeConflictError."""
        with pytest.raises(WorkspaceError):
            raise MergeConflictError("conflict in file.py")

    def test_catch_exception_catches_vaultspec_error(self) -> None:
        """TokenBudgetExceededError is catchable as its own type (and as Exception)."""
        with pytest.raises(TokenBudgetExceededError):
            raise TokenBudgetExceededError("over budget")

    def test_catch_specific_does_not_catch_sibling(self) -> None:
        """ConfigError is not caught by DatabaseError (sibling types)."""
        with pytest.raises(ConfigError):
            try:
                raise ConfigError("config issue")
            except DatabaseError:
                pytest.fail("DatabaseError should not catch ConfigError")

    def test_attributes_survive_raise(self) -> None:
        """Severity and recovery_action are preserved after raise/catch."""
        with pytest.raises(PermissionDeniedError) as exc_info:
            raise PermissionDeniedError("not allowed")
        err = exc_info.value
        assert err.severity is ErrorSeverity.PERMANENT
        assert err.recovery_action is RecoveryAction.ESCALATE_TO_USER
        assert str(err) == "not allowed"


# ---------------------------------------------------------------------------
# __all__ exports
# ---------------------------------------------------------------------------


class TestAllExports:
    """Tests for the public API surface of the exceptions module."""

    def test_all_defined(self) -> None:
        """The exceptions module exposes __all__."""
        assert hasattr(_exceptions_module, "__all__")

    def test_all_contains_every_public_name(self) -> None:
        """__all__ matches the expected set of public names."""
        expected = {
            "AgentConfigNotFoundError",
            "AgentProcessError",
            "ConfigError",
            "ContextOverflowError",
            "DatabaseError",
            "ErrorSeverity",
            "EventAggregatorError",
            "GitWorkspaceError",
            "MergeConflictError",
            "PermissionDeniedError",
            "ProtocolError",
            "RecoveryAction",
            "TeamConfigNotFoundError",
            "TokenBudgetExceededError",
            "VaultspecError",
            "WorkspaceError",
        }
        assert set(_exceptions_module.__all__) == expected

    def test_facade_reexports_new_exceptions(self) -> None:
        """The core facade (__init__.py) must re-export the new types.

        Verified by the module-level imports from ``..`` above; any missing
        re-export would cause an ImportError at collection time.
        """
        assert ContextOverflowError is not None
        assert DatabaseError is not None
        assert ErrorSeverity is not None
        assert EventAggregatorError is not None
        assert MergeConflictError is not None
        assert PermissionDeniedError is not None
        assert RecoveryAction is not None
        assert TokenBudgetExceededError is not None
