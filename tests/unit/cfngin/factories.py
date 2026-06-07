"""Factories for tests.

Provides factory functions and lightweight stubs for constructing cfngin test
objects (contexts, providers, stacks, lookups) with sensible defaults. This
eliminates boilerplate setup across the test suite and ensures tests use
consistent, minimal configurations unless explicitly overridden.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple
from unittest.mock import MagicMock

from runway.cfngin.providers.aws.default import ProviderBuilder
from runway.config import CfnginConfig, CfnginStackDefinitionModel
from runway.context import CfnginContext

if TYPE_CHECKING:
    from runway.cfngin.providers.aws.default import Provider


class Lookup(NamedTuple):
    """Lookup named tuple.

    Models the three components of a resolved lookup reference so tests can
    assert on type, input, and raw-string form independently without parsing.
    """

    type: str
    input: str
    raw: str


class MockThreadingEvent:
    """Mock thread events.

    Simulates a threading event that never signals, allowing tests to exercise
    the cancel/timeout paths in cfngin's threaded walker without actual
    concurrency or timing dependencies.
    """

    def wait(self, timeout: int | None = None) -> bool:  # noqa: ARG002
        """Mock wait method."""
        return False


class MockProviderBuilder(ProviderBuilder):
    """Mock provider builder.

    Bypasses real AWS session/credential resolution so tests can inject a
    pre-configured provider directly, isolating cfngin orchestration logic
    from actual cloud API interactions.
    """

    def __init__(self, *, provider: Provider, region: str | None = None, **_: Any) -> None:
        """Instantiate class."""
        self.provider = provider
        self.region = region

    def build(
        self,
        *,
        profile: str | None = None,  # noqa: ARG002
        region: str | None = None,  # noqa: ARG002
    ) -> Provider:
        """Mock build method.

        Always returns the injected provider regardless of profile/region,
        ensuring tests verify orchestration behavior without AWS credentials.
        """
        return self.provider


def mock_provider(**kwargs: Any) -> MagicMock:
    """Mock provider.

    Creates a MagicMock that satisfies the Provider interface, allowing tests
    to set up specific return values or side effects for individual AWS
    operations without a full provider implementation.
    """
    return MagicMock(**kwargs)


def mock_context(
    namespace: str = "default",
    extra_config_args: dict[str, Any] | None = None,
    **kwargs: Any,
) -> CfnginContext:
    """Mock context.

    Constructs a CfnginContext with minimal valid configuration, defaulting
    to an empty environment. This isolates tests from real environment file
    resolution while still exercising real context initialization logic.
    """
    config_args = {"namespace": namespace}
    if extra_config_args:
        config_args.update(extra_config_args)
    config = CfnginConfig.parse_obj(config_args)
    if kwargs.get("environment"):
        return CfnginContext(config=config, **kwargs)
    return CfnginContext(config=config, environment={}, **kwargs)


def generate_definition(
    base_name: str, stack_id: Any = None, **overrides: Any
) -> CfnginStackDefinitionModel:
    """Generate definitions.

    Creates stack definitions with predictable naming conventions and default
    class paths pointing to mock blueprints, so tests can build multi-stack
    plans without specifying every field on each stack.
    """
    definition: dict[str, Any] = {
        "name": f"{base_name}-{stack_id}" if stack_id else base_name,
        "class_path": f"tests.unit.cfngin.fixtures.mock_blueprints.{base_name.upper()}",
        "requires": [],
    }
    definition.update(overrides)
    return CfnginStackDefinitionModel(**definition)


def mock_lookup(lookup_input: Any, lookup_type: str, raw: str | None = None) -> Lookup:
    """Mock lookup.

    Constructs a Lookup tuple with an auto-generated raw string when none
    is provided, matching cfngin's actual "type input" format so tests can
    verify lookup parsing and resolution without string formatting.
    """
    if raw is None:
        raw = f"{lookup_type} {lookup_input}"
    return Lookup(type=lookup_type, input=lookup_input, raw=raw)


class SessionStub:
    """Stubber class for boto3 sessions made with session_cache.get_session().

    Allows tests to inject a pre-built boto3 stubber client in place of real
    AWS sessions, enabling deterministic AWS API response testing without
    network calls or credentials.

    This is a helper class that should be used when trying to stub out
    get_session() calls using the boto3.stubber.

    Example Usage:

        @mock.patch('runway.cfngin.lookups.handlers.myfile.get_session',
                return_value=sessionStub(client))
        def myfile_test(self, client_stub):
            ...

    Attributes:
        client_stub (:class:`boto3.session.Session`:): boto3 session stub

    """

    def __init__(self, client_stub: Any) -> None:
        """Instantiate class."""
        self.client_stub = client_stub

    def client(self, region: str) -> Any:  # noqa: ARG002
        """Return the stubbed client object.

        Args:
            region: So boto3 won't complain

        Returns:
            The stubbed boto3 session

        """
        return self.client_stub
