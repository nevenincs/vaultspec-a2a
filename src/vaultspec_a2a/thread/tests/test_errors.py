"""Tests for the error taxonomy and exception hierarchy."""

import pytest

from .. import (
    AgentConfigNotFoundError,
    AgentProcessError,
    ConfigError,
    ContextOverflowError,
    DatabaseError,
    ErrorSeverity,
    EventAggregatorError,
    NicknameConflictError,
    PermissionDeniedError,
    ProtocolError,
    ProviderSessionError,
    RecoveryAction,
    TeamConfigNotFoundError,
    TokenBudgetExceededError,
    VaultspecError,
    WorkerExecutionError,
)

# Module object used for __all__ introspection
from .. import errors as _errors_module

# GitWorkspaceError and describe_exception live in errors but are NOT
# re-exported by the thread facade
from ..errors import GitWorkspaceError, describe_exception

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
            AgentProcessError,
            ProtocolError,
            EventAggregatorError,
            DatabaseError,
            PermissionDeniedError,
            TokenBudgetExceededError,
            ContextOverflowError,
            ProviderSessionError,
        ],
    )
    def test_direct_subclasses_of_vaultspec_error(
        self, exc_cls: type[VaultspecError]
    ) -> None:
        """Each listed exception class is a direct subclass of VaultspecError."""
        assert issubclass(exc_cls, VaultspecError)


# ---------------------------------------------------------------------------
# Default severity and recovery classifications
# ---------------------------------------------------------------------------


_EXPECTED_DEFAULTS: list[tuple[type[VaultspecError], ErrorSeverity, RecoveryAction]] = [
    (VaultspecError, ErrorSeverity.UNKNOWN, RecoveryAction.ESCALATE_TO_USER),
    (ConfigError, ErrorSeverity.PERMANENT, RecoveryAction.ABORT),
    (
        AgentProcessError,
        ErrorSeverity.TRANSIENT,
        RecoveryAction.RETRY_WITH_BACKOFF,
    ),
    (ProtocolError, ErrorSeverity.PERMANENT, RecoveryAction.ABORT),
    (
        ProviderSessionError,
        ErrorSeverity.TRANSIENT,
        RecoveryAction.RETRY_WITH_BACKOFF,
    ),
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

    def test_provider_session_error_catchable(self) -> None:
        """ProviderSessionError is catchable as VaultspecError."""
        with pytest.raises(VaultspecError):
            raise ProviderSessionError("session died")


# ---------------------------------------------------------------------------
# Custom __init__ exception classes
# ---------------------------------------------------------------------------


class TestCustomInitExceptions:
    """Tests for exception classes with custom __init__ signatures."""

    def test_agent_config_not_found_contains_agent_id(self) -> None:
        """AgentConfigNotFoundError message contains the agent_id."""
        err = AgentConfigNotFoundError("coder")
        assert "coder" in str(err)
        assert err.agent_id == "coder"

    def test_team_config_not_found_contains_team_id(self) -> None:
        """TeamConfigNotFoundError message contains the preset name."""
        err = TeamConfigNotFoundError("my-team")
        assert "my-team" in str(err)
        assert err.team_id == "my-team"

    def test_nickname_conflict_contains_nickname(self) -> None:
        """NicknameConflictError message contains the nickname."""
        err = NicknameConflictError("nick")
        assert "nick" in str(err)
        assert err.nickname == "nick"


# ---------------------------------------------------------------------------
# Cause retention on the worker wrapper
# ---------------------------------------------------------------------------


class TestDescribeException:
    """Tests for the bounded, single-line exception identity renderer."""

    def test_a_real_provider_error_renders_its_type_code_and_message(self) -> None:
        """The renderer reads the convention the ACP errors actually publish.

        Exercised against the real provider exception rather than a stand-in with
        the attributes this renderer hopes for: the renderer's whole value is that
        it recovers a provider's own numeric code, and only the shipped class can
        prove that ``code`` and ``message`` still mean what it assumes.
        """
        from ...providers.acp_exceptions import AcpErrorCode, AcpPromptError

        detail = describe_exception(
            AcpPromptError(
                "ACP prompt failed: credit balance too low",
                code=AcpErrorCode.UNAUTHENTICATED,
                data={"errorKind": "billing_error"},
            )
        )

        assert detail == (
            "AcpPromptError[-32000]: ACP prompt failed: credit balance too low"
        )

    def test_an_exception_without_a_code_renders_type_and_message_alone(self) -> None:
        """A plain exception carries no code, and none is invented for it."""
        assert describe_exception(RuntimeError("boom")) == "RuntimeError: boom"

    def test_the_rendering_is_single_line_and_bounded(self) -> None:
        """A pathological message can never consume a whole failure reason."""
        detail = describe_exception(RuntimeError("a\nb\n" + "x" * 4000))

        assert "\n" not in detail
        assert detail.startswith("RuntimeError: a b ")
        assert detail.endswith("…")
        assert len(detail) <= len("RuntimeError: ") + 240

    def test_the_rendering_does_not_follow_the_cause_chain(self) -> None:
        """Each link is described alone so a walker never reports one twice."""
        cause = RuntimeError("root")
        wrapper = ValueError("wrapper")
        wrapper.__cause__ = cause

        assert describe_exception(wrapper) == "ValueError: wrapper"


class TestWorkerExecutionErrorRetainsItsCause:
    """Tests that the worker wrapper stops discarding the provider's identity."""

    def test_the_wrapper_message_names_the_provider_failure(self) -> None:
        """``str`` carries attribution AND the wrapped provider fault.

        This is the loss point the whole failure surface depended on: the
        wrapper used to report only which worker and model died, so a client
        received the same sentence for an expired credential, an overloaded
        provider, and an empty credit balance.
        """
        from ...providers.acp_exceptions import AcpErrorCode, AcpPromptError

        cause = AcpPromptError(
            "ACP prompt failed: credit balance too low",
            code=AcpErrorCode.UNAUTHENTICATED,
        )
        err = WorkerExecutionError(
            worker="coder",
            model="claude/claude-sonnet-4-5",
            message_count=3,
            cause=cause,
        )

        rendered = str(err)
        assert "worker='coder' model=claude/claude-sonnet-4-5 messages=3" in rendered
        assert "AcpPromptError" in rendered
        assert "-32000" in rendered
        assert "credit balance too low" in rendered

    def test_the_attribution_stays_available_free_of_the_cause(self) -> None:
        """``message`` keeps the cause-free half for cause-chain walkers.

        A walker rendering this wrapper and then its ``__cause__`` would print
        the provider fault twice if the wrapper's own identity folded it in.
        """
        cause = RuntimeError("provider exploded")
        err = WorkerExecutionError(
            worker="coder", model="claude/opus", message_count=1, cause=cause
        )

        assert err.message == "worker='coder' model=claude/opus messages=1"
        assert describe_exception(err) == (
            "WorkerExecutionError: worker='coder' model=claude/opus messages=1"
        )

    def test_a_wrapper_with_no_cause_reports_attribution_only(self) -> None:
        """Nothing is appended when there is no failure to attribute."""
        err = WorkerExecutionError(worker="coder", model="mock", message_count=2)

        assert str(err) == "worker='coder' model=mock messages=2"
        assert err.message == str(err)


# ---------------------------------------------------------------------------
# __all__ exports
# ---------------------------------------------------------------------------


class TestAllExports:
    """Tests for the public API surface of the errors module."""

    def test_all_defined(self) -> None:
        """The errors module exposes __all__."""
        assert hasattr(_errors_module, "__all__")

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
            "HarnessToolContractError",
            "IsolationRequiredError",
            "NicknameConflictError",
            "PermissionDeniedError",
            "ProtocolError",
            "ProjectionRefusedError",
            "ProviderSessionError",
            "RecoveryAction",
            "TeamConfigNotFoundError",
            "TokenBudgetExceededError",
            "VaultspecError",
            "WorkerExecutionError",
            "describe_exception",
        }
        assert set(_errors_module.__all__) == expected

    def test_facade_reexports_are_same_objects(self) -> None:
        """Facade re-exports are identity-equal to errors module objects.

        The module-level imports from ``..`` (the thread facade) must refer to
        the exact same class objects as ``..errors``.  ``is`` proves
        they are not accidental copies or shadowed names.
        """
        assert ContextOverflowError is _errors_module.ContextOverflowError
        assert DatabaseError is _errors_module.DatabaseError
        assert ErrorSeverity is _errors_module.ErrorSeverity
        assert EventAggregatorError is _errors_module.EventAggregatorError
        assert PermissionDeniedError is _errors_module.PermissionDeniedError
        assert RecoveryAction is _errors_module.RecoveryAction
        assert TokenBudgetExceededError is _errors_module.TokenBudgetExceededError
        assert ProviderSessionError is _errors_module.ProviderSessionError
