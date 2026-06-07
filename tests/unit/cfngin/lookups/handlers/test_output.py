"""Tests for runway.cfngin.lookups.handlers.output.

Validates the output lookup that resolves CloudFormation stack outputs by
name, enabling cross-stack references within a CFNgin deployment. Tests
cover dependency detection, both query syntaxes, default values, and error
cases for missing stacks or outputs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from runway._logging import LogLevels
from runway.cfngin.exceptions import StackDoesNotExist
from runway.cfngin.lookups.handlers.output import OutputLookup
from runway.cfngin.stack import Stack
from runway.exceptions import OutputDoesNotExist
from runway.variables import VariableValueLiteral

from ...factories import generate_definition

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from ....factories import MockCfnginContext

MODULE = "runway.cfngin.lookups.handlers.output"


class TestOutputLookup:
    """Test OutputLookup.

    Output lookups are the primary cross-stack wiring mechanism in CFNgin,
    allowing one stack to consume another stack's exports. Correct dependency
    detection ensures stacks deploy in the right order.
    """

    @pytest.mark.parametrize("provided", ["stack-name.Output", "stack-name::Output"])
    def test_dependencies(self, provided: str) -> None:
        """Test dependencies.

        Validates that the lookup correctly extracts the stack name as a
        dependency, which the DAG uses to order stack operations.
        """
        data_item = VariableValueLiteral(provided)
        var_val = MagicMock()
        var_val.__iter__.return_value = iter([data_item])
        assert OutputLookup.dependencies(var_val) == {"stack-name"}

    @pytest.mark.parametrize("provided", ["stack-name:Output", "foobar"])
    def test_dependencies_none(self, provided: str) -> None:
        """Test dependencies none found.

        Ensures malformed lookup strings (single colon, no separator) don't
        produce phantom dependencies, which would create incorrect ordering.
        """
        data_item = VariableValueLiteral(provided)
        var_val = MagicMock()
        var_val.__iter__.return_value = iter([data_item])
        assert OutputLookup.dependencies(var_val) == set()

    def test_dependencies_not_resolved(self) -> None:
        """Test dependencies.

        Unresolved variables can't be parsed for dependency extraction, so
        they must return an empty set to avoid blocking the resolution pass.
        """
        data_item = MagicMock(resolved=False)
        var_val = MagicMock()
        var_val.__iter__.return_value = iter([data_item])
        assert OutputLookup.dependencies(var_val) == set()

    @pytest.mark.parametrize(
        "provided, expected",
        [
            ("stack-name::Output", "output-val"),
            ("stack-name.Output", "output-val"),
            ("stack-name.Output::default=bar", "output-val"),
            ("foo.Output::default=bar", "bar"),
            ("stack-name.foo::default=bar", "bar"),
        ],
    )
    def test_handle(self, cfngin_context: MockCfnginContext, expected: str, provided: str) -> None:
        """Test handle."""
        stack = Stack(definition=generate_definition("stack-name"), context=cfngin_context)
        stack.set_outputs({"Output": "output-val"})
        cfngin_context.stacks_dict[cfngin_context.get_fqn(stack.name)] = stack
        assert OutputLookup.handle(provided, context=cfngin_context) == expected

    @pytest.mark.parametrize("provided", ["stack-name.MissingOutput", "stack-name::MissingOutput"])
    def test_handle_raise_output_does_not_exist(
        self, cfngin_context: MockCfnginContext, provided: str
    ) -> None:
        """Test handle raise OutputDoesNotExist."""
        stack = Stack(definition=generate_definition("stack-name"), context=cfngin_context)
        stack.set_outputs({"Output": "output-val"})
        cfngin_context.stacks_dict[cfngin_context.get_fqn(stack.name)] = stack
        with pytest.raises(
            OutputDoesNotExist,
            match="Output MissingOutput does not exist on stack "
            + cfngin_context.get_fqn(stack.name),
        ):
            OutputLookup.handle(provided, context=cfngin_context)

    @pytest.mark.parametrize("provided", ["stack-name.Output", "stack-name::Output"])
    def test_handle_raise_stack_does_not_exist(
        self, cfngin_context: MockCfnginContext, provided: str
    ) -> None:
        """Test handle raise StackDoesNotExist."""
        with pytest.raises(
            StackDoesNotExist,
            match=rf'Stack: "{cfngin_context.get_fqn("stack-name")}" does not exist .*',
        ):
            OutputLookup.handle(provided, context=cfngin_context)

    def test_legacy_parse(self, caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
        """Test legacy_parse.

        Validates that the deprecated dot-syntax is still accepted with a
        deprecation warning, maintaining backward compatibility for existing
        configurations while encouraging migration to the new syntax.
        """
        query = "foo"
        caplog.set_level(LogLevels.WARNING, MODULE)
        deconstruct = mocker.patch(f"{MODULE}.deconstruct", return_value="success")
        assert OutputLookup.legacy_parse(query) == (deconstruct.return_value, {})
        deconstruct.assert_called_once_with(query)
        assert f"${{output {query}}}: {OutputLookup.DEPRECATION_MSG}" in caplog.messages
