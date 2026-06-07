"""Tests for runway.cfngin.lookups.handlers.default.

Validates the default lookup handler that resolves context parameters with
fallback values, providing a safe way to reference optional configuration.
"""

import unittest
from unittest.mock import MagicMock

import pytest

from runway.cfngin.lookups.handlers.default import DefaultLookup
from runway.context import CfnginContext


class TestDefaultLookup(unittest.TestCase):
    """Tests for runway.cfngin.lookups.handlers.default.DefaultLookup.

    The default lookup resolves variables from context parameters with a
    fallback mechanism, which is essential for optional configuration that
    should degrade gracefully rather than fail the deployment.
    """

    def setUp(self) -> None:
        """Run before tests."""
        self.provider = MagicMock()
        self.context = CfnginContext(parameters={"namespace": "test", "env_var": "val_in_env"})

    def test_env_var_present(self) -> None:
        """Test env var present.

        Confirms that when the parameter exists, its value takes priority over
        the fallback, ensuring explicitly set config is never overridden.
        """
        lookup_val = "env_var::fallback"
        value = DefaultLookup.handle(lookup_val, provider=self.provider, context=self.context)
        assert value == "val_in_env"

    def test_env_var_missing(self) -> None:
        """Test env var missing.

        Verifies the fallback path is used when a parameter doesn't exist,
        which is the primary use case for optional deployment parameters.
        """
        lookup_val = "bad_env_var::fallback"
        value = DefaultLookup.handle(lookup_val, provider=self.provider, context=self.context)
        assert value == "fallback"

    def test_invalid_value(self) -> None:
        """Test invalid value.

        Ensures a ValueError is raised when the query uses a single colon
        instead of the required double-colon delimiter, catching user typos
        early with a clear error.
        """
        with pytest.raises(ValueError):  # noqa: PT011
            DefaultLookup.handle("env_var:fallback", provider=self.provider, context=self.context)
