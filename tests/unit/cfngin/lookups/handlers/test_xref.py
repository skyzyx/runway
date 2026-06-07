"""Tests for runway.cfngin.lookups.handlers.xref.

Validates the cross-reference lookup that fetches outputs from
fully-qualified external stack names without applying namespace prefixing,
enabling references to stacks managed outside the current CFNgin namespace.
"""

# pyright: reportUnknownArgumentType=none, reportUnknownVariableType=none
import unittest
from unittest.mock import MagicMock

from runway.cfngin.lookups.handlers.xref import XrefLookup


class TestXrefHandler(unittest.TestCase):
    """Tests for runway.cfngin.lookups.handlers.xref.XrefHandler.

    Unlike output/rxref lookups, xref uses fully-qualified stack names and
    bypasses namespace prefixing. This is needed when referencing stacks from
    other deployments or shared infrastructure stacks.
    """

    def setUp(self) -> None:
        """Run before tests."""
        self.provider = MagicMock()
        self.context = MagicMock()

    def test_xref_handler(self) -> None:
        """Test xref handler.

        Confirms that the stack name is passed directly to the provider without
        get_fqn being called, verifying the intentional bypass of namespace
        prefixing.
        """
        self.provider.get_output.return_value = "Test Output"
        value = XrefLookup.handle(
            "fully-qualified-stack-name::SomeOutput",
            provider=self.provider,
            context=self.context,
        )
        assert value == "Test Output"
        assert self.context.get_fqn.call_count == 0
        args = self.provider.get_output.call_args
        assert args[0][0] == "fully-qualified-stack-name"
        assert args[0][1] == "SomeOutput"
