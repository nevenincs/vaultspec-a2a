"""Tests for the error taxonomy and exception hierarchy."""

import pytest

from .. import (
    AgentConfigNotFoundError,
    AgentProcessError,
    ConfigError,
    ContextOverflowError,
    DatabaseError,
    EventAggregatorError,
    NicknameConflictError,
    PermissionDeniedError,
    ProtocolError,
    ProviderSessionError,
    TeamConfigNotFoundError,
    TokenBudgetExceededError,
    VaultspecError,
    WorkerExecutionError,
)

# Module object used for __all__ introspection
from .. import errors as _errors_module

# GitWorkspaceError and describe_exception live in errors but are NOT
# re-exported by the thread facade
from ..errors import (
    GitWorkspaceError,
    describe_exception,
    describe_exception_chain,
)

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

    def test_the_message_survives_raise_and_catch(self) -> None:
        """The message a caller raised with is the message a catcher reads.

        The base carries no state of its own and defines no ``__init__``, so a
        subclass that adds neither gets the interpreter's own message handling.
        Asserted through a real raise because that is the path a reporting site
        takes, and because a base-class ``__init__`` reintroduced here is exactly
        how a message comes to be swallowed before anyone renders it.
        """
        with pytest.raises(PermissionDeniedError) as exc_info:
            raise PermissionDeniedError("not allowed")

        assert str(exc_info.value) == "not allowed"

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


class TestDescribeExceptionChain:
    """Tests for the one renderer every failure-reporting site shares.

    Chains are built by raising and catching rather than by assigning
    ``__cause__``, because only a genuine ``raise ... from`` sets the link the
    way the interpreter does, and a hand-assembled chain would prove the walker
    reads a field production never fills the same way.
    """

    @staticmethod
    def _chain(depth: int) -> BaseException:
        """Raise and catch a real ``raise ... from`` chain *depth* links deep."""
        current: BaseException = RuntimeError("link-0")
        for index in range(1, depth):
            try:
                raise ValueError(f"link-{index}") from current
            except ValueError as raised:
                current = raised
        return current

    def test_each_link_of_a_real_chain_is_named_outermost_first(self) -> None:
        detail = describe_exception_chain(self._chain(3))

        assert detail == (
            "ValueError: link-2 <- ValueError: link-1 <- RuntimeError: link-0"
        )

    def test_a_lone_exception_renders_exactly_as_its_own_identity(self) -> None:
        exc = RuntimeError("boom")

        assert describe_exception_chain(exc) == describe_exception(exc)

    def test_a_deep_chain_stops_before_the_framework_plumbing(self) -> None:
        """The links that answer are the first few; the rest spend the budget."""
        detail = describe_exception_chain(self._chain(9))

        assert detail.count(" <- ") == 3
        assert "link-8" in detail
        assert "link-4" not in detail

    def test_implicit_context_is_never_followed(self) -> None:
        """A cleanup error that merely happened to be in flight is not a cause.

        Implicit context is what the interpreter records about whatever was in
        flight; only ``raise ... from`` states that one failure EXPLAINS another.
        Following context is how an unrelated cleanup error comes to be reported
        as the reason a run failed.
        """
        try:
            try:
                raise ValueError("unrelated cleanup")
            except ValueError:
                raise RuntimeError("the actual failure") from None
        except RuntimeError as exc:
            assert exc.__context__ is not None
            assert exc.__cause__ is None
            assert describe_exception_chain(exc) == "RuntimeError: the actual failure"

    def test_a_cyclic_chain_describes_each_link_once(self) -> None:
        first = RuntimeError("first")
        second = ValueError("second")
        first.__cause__ = second
        second.__cause__ = first

        assert describe_exception_chain(first) == (
            "RuntimeError: first <- ValueError: second"
        )

    def test_the_whole_chain_is_bounded_to_the_durable_reason_cap(self) -> None:
        """A long chain cannot outgrow the column that has to store it."""
        long_link: BaseException = RuntimeError("y" * 4000)
        for _ in range(3):
            try:
                raise ValueError("x" * 4000) from long_link
            except ValueError as raised:
                long_link = raised

        detail = describe_exception_chain(long_link)

        assert len(detail) == 500
        assert detail.endswith("…")


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
            "EventAggregatorError",
            "GitWorkspaceError",
            "HarnessToolContractError",
            "IsolationRequiredError",
            "NicknameConflictError",
            "PermissionDeniedError",
            "ProtocolError",
            "ProjectionRefusedError",
            "ProviderSessionError",
            "TeamConfigNotFoundError",
            "TokenBudgetExceededError",
            "VaultspecError",
            "WorkerExecutionError",
            "describe_exception",
            "describe_exception_chain",
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
        assert EventAggregatorError is _errors_module.EventAggregatorError
        assert PermissionDeniedError is _errors_module.PermissionDeniedError
        assert TokenBudgetExceededError is _errors_module.TokenBudgetExceededError
        assert ProviderSessionError is _errors_module.ProviderSessionError
