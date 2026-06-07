"""Tests for runway.cfngin.lookups.handlers.envvar.

Validates the environment variable lookup handler that reads OS-level
environment variables, providing a bridge between the system environment
and CFNgin configuration values.
"""

import os
import unittest

import pytest

from runway.cfngin.lookups.handlers.envvar import EnvvarLookup


class TestEnvVarHandler(unittest.TestCase):
    """Tests for runway.cfngin.lookups.handlers.envvar.EnvvarLookup.

    Environment variable lookups allow injecting deployment-time secrets and
    configuration without hardcoding values, which is essential for CI/CD
    pipelines and multi-environment deployments.
    """

    def setUp(self) -> None:
        """Run before tests."""
        self.testkey = "STACKER_ENVVAR_TESTCASE"
        self.invalidtestkey = "STACKER_INVALID_ENVVAR_TESTCASE"
        self.testval = "TestVal"
        os.environ[self.testkey] = self.testval

    def test_valid_envvar(self) -> None:
        """Test valid envvar.

        Confirms that a set environment variable is correctly read and returned,
        which is the primary use case for runtime configuration injection.
        """
        value = EnvvarLookup.handle(self.testkey)
        assert value == self.testval

    def test_invalid_envvar(self) -> None:
        """Test invalid envvar.

        Ensures a missing environment variable raises ValueError instead of
        returning None, because a missing required secret should fail loudly
        rather than produce a broken deployment.
        """
        with pytest.raises(ValueError):  # noqa: PT011
            EnvvarLookup.handle(self.invalidtestkey)
