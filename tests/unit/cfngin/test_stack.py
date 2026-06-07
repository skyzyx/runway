"""Tests for runway.cfngin.stack."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar
from unittest.mock import Mock

import pytest

from runway.cfngin.lookups.registry import (
    register_lookup_handler,
    unregister_lookup_handler,
)
from runway.cfngin.stack import Stack
from runway.config import CfnginStackDefinitionModel
from runway.lookups.handlers.base import LookupHandler

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest_mock import MockerFixture

    from ..factories import MockCfnginContext

MODULE = "runway.cfngin.stack"


@pytest.fixture(autouse=True, scope="module")
def fake_lookup() -> Iterator[None]:
    """Register a fake lookup handler for testing.

    Provides a no-op lookup so tests can use lookup syntax in variables
    without needing real AWS credentials or external state.
    """

    class FakeLookup(LookupHandler):
        """False Lookup."""

        TYPE_NAME: ClassVar[str] = "fake"

        @classmethod
        def handle(cls, value: str, *__args: Any, **__kwargs: Any) -> str:
            """Perform the lookup."""
            return "test"

    register_lookup_handler(FakeLookup.TYPE_NAME, FakeLookup)
    yield
    unregister_lookup_handler(FakeLookup.TYPE_NAME)


def generate_stack_definition(base_name: str, stack_id: Any = None, **overrides: Any) -> CfnginStackDefinitionModel:
    """Generate stack definition.

    Factory helper that produces minimal valid stack definitions, allowing
    tests to override only the fields relevant to each scenario.
    """
    definition: dict[str, Any] = {
        "name": f"{base_name}-{stack_id}" if stack_id else base_name,
        "class_path": f"tests.unit.cfngin.fixtures.mock_blueprints.{base_name.upper()}",
        "requires": [],
    }
    definition.update(overrides)
    return CfnginStackDefinitionModel(**definition)


class TestStack:
    """Test Stack.

    Validates the Stack abstraction's property resolution including
    dependency extraction from variable lookups, tag merging logic,
    and policy file loading. These behaviors are critical because
    incorrect dependency resolution causes execution ordering failures.
    """

    def test_required_by(self, cfngin_context: MockCfnginContext) -> None:
        """Test required_by.

        Verifies that explicit required_by declarations create reverse
        dependency edges, allowing stacks to declare "I must run before X"
        without X knowing about the dependency.
        """
        stack = Stack(
            definition=generate_stack_definition(
                base_name="vpc",
                required_by=["fakeStack0"],
                variables={"Param1": "${output fakeStack.FakeOutput}"},
            ),
            context=cfngin_context,
        )
        assert stack.required_by == {"fakeStack0"}

    def test_requires(self, cfngin_context: MockCfnginContext) -> None:
        """Test requires.

        Confirms that implicit dependencies are extracted from output
        lookups in variables, and that explicit requires are merged with
        implicit ones. De-duplication and non-output lookups (like fake)
        must not create spurious dependencies.
        """
        stack = Stack(
            definition=generate_stack_definition(
                base_name="vpc",
                variables={
                    "Var1": "${fake fakeStack2::FakeOutput}",
                    "Var2": ("some.template.value:${output fakeStack1.FakeOutput}:${output fakeStack0.FakeOutput}"),
                    "Var3": "${output fakeStack0.FakeOutput},${output fakeStack1.FakeOutput}",
                },
                requires=["fakeStack0"],
            ),
            context=cfngin_context,
        )
        assert len(stack.requires) == 2
        assert "fakeStack0" in stack.requires
        assert "fakeStack1" in stack.requires

    def test_requires_cyclic_dependency(self, cfngin_context: MockCfnginContext) -> None:
        """Test requires cyclic dependency.

        A stack referencing its own output creates a self-loop that would
        deadlock execution, so it must raise immediately during resolution.
        """
        stack = Stack(
            definition=generate_stack_definition(
                base_name="vpc",
                variables={"Var1": "${output vpc.FakeOutput}"},
            ),
            context=cfngin_context,
        )
        with pytest.raises(ValueError, match="has a circular reference"):
            assert stack.requires

    def test_resolve(self, cfngin_context: MockCfnginContext, mocker: MockerFixture) -> None:
        """Test resolve.

        Verifies the two-phase variable resolution: first resolving lookup
        values against live AWS state, then binding the resolved values
        into the blueprint. Both phases must execute in order.
        """
        mock_resolve_variables = mocker.patch(f"{MODULE}.resolve_variables")
        mock_provider = Mock()
        stack = Stack(
            definition=generate_stack_definition(base_name="vpc"),
            context=cfngin_context,
        )
        stack._blueprint = Mock()
        assert not stack.resolve(cfngin_context, mock_provider)
        mock_resolve_variables.assert_called_once_with(stack.variables, cfngin_context, mock_provider)
        stack._blueprint.resolve_variables.assert_called_once_with(stack.variables)

    def test_set_outputs(self, cfngin_context: MockCfnginContext) -> None:
        """Test set_outputs.

        Stack outputs are cached after deployment so that downstream stacks
        can resolve cross-stack references without additional API calls.
        """
        stack = Stack(
            definition=generate_stack_definition(base_name="vpc"),
            context=cfngin_context,
        )
        assert not stack.outputs
        outputs = {"foo": "bar"}
        assert not stack.set_outputs(outputs)
        assert stack.outputs == outputs

    def test_stack_policy(self, cfngin_context: MockCfnginContext, tmp_path: Path) -> None:
        """Test stack_policy.

        Verifies that a stack policy file is read and its content made
        available, which is passed to CloudFormation to protect resources
        from accidental updates or deletions.
        """
        stack_policy_path = tmp_path / "stack_policy.json"
        stack_policy_path.write_text("success")
        assert (
            Stack(
                definition=generate_stack_definition(base_name="vpc", stack_policy_path=stack_policy_path),
                context=cfngin_context,
            ).stack_policy
            == "success"
        )

    def test_stack_policy_not_provided(self, cfngin_context: MockCfnginContext) -> None:
        """Test stack_policy.

        Confirms that stacks without a policy path return a falsy value,
        so the provider knows not to send a stack policy to CloudFormation.
        """
        assert not Stack(
            definition=generate_stack_definition(base_name="vpc"),
            context=cfngin_context,
        ).stack_policy

    def test_tags(self, cfngin_context: MockCfnginContext) -> None:
        """Test tags.

        Stack-level tags must override context-level tags when the same key
        exists, allowing per-stack customization while inheriting defaults.
        """
        cfngin_context.config.tags = {"environment": "prod"}
        assert Stack(
            definition=generate_stack_definition(base_name="vpc", tags={"app": "graph", "environment": "stage"}),
            context=cfngin_context,
        ).tags == {"app": "graph", "environment": "stage"}

    def test_tags_default(self, cfngin_context: MockCfnginContext) -> None:
        """Test tags.

        When no stack-level tags are defined, the stack inherits all
        context-level tags unchanged.
        """
        cfngin_context.config.tags = {"environment": "prod"}
        assert Stack(
            definition=generate_stack_definition(base_name="vpc"),
            context=cfngin_context,
        ).tags == {"environment": "prod"}

    @pytest.mark.parametrize(
        "termination_protection, expected",
        [(False, False), (True, True)],
    )
    def test_termination_protection(
        self,
        cfngin_context: MockCfnginContext,
        expected: str,
        termination_protection: bool | str,
    ) -> None:
        """Test termination_protection.

        Validates that the boolean termination protection flag is passed
        through correctly, which controls whether CloudFormation allows
        stack deletion.
        """
        assert (
            Stack(
                definition=generate_stack_definition(base_name="vpc", termination_protection=termination_protection),
                context=cfngin_context,
            ).termination_protection
            is expected
        )
