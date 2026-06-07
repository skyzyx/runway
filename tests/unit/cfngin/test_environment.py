"""Tests for runway.cfngin.environment.

Validates that cfngin's environment file parser correctly handles the
key:value format used for stack configuration, including edge cases like
colons in values, special characters, blank values, and comment lines.
"""

# pyright: reportUnnecessaryIsInstance=none
import pytest

from runway.cfngin.environment import parse_environment

TEST_ENV = """key1: value1
# some: comment

 # here: about

# key2
key2: value2

# another comment here
key3: some:complex::value


# one more here as well
key4: :otherValue:
key5: <another>@value
"""

TEST_ERROR_ENV = """key1: value1
error
"""


class TestEnvironment:
    """Tests for runway.cfngin.environment.

    Environment files are the primary mechanism for injecting per-environment
    values (dev vs prod) into cfngin configs, so parsing correctness is
    critical for reliable deployments.
    """

    def test_simple_key_value_parsing(self) -> None:
        """Test simple key value parsing.

        Verifies the parser handles realistic environment files containing
        comments, blank lines, colons within values, and special characters
        — all patterns that occur in real deployment configurations.
        """
        parsed_env = parse_environment(TEST_ENV)
        assert isinstance(parsed_env, dict)
        assert parsed_env["key1"] == "value1"
        assert parsed_env["key2"] == "value2"
        assert parsed_env["key3"] == "some:complex::value"
        assert parsed_env["key4"] == ":otherValue:"
        assert parsed_env["key5"] == "<another>@value"
        assert len(parsed_env) == 5

    def test_simple_key_value_parsing_exception(self) -> None:
        """Test simple key value parsing exception.

        Lines without a colon separator are invalid; the parser must reject
        them early so users get clear errors instead of silent misconfiguration.
        """
        with pytest.raises(ValueError):  # noqa: PT011
            parse_environment(TEST_ERROR_ENV)

    def test_blank_value(self) -> None:
        """Test blank value.

        Keys with empty values are valid and represent intentional overrides
        (e.g., clearing a default), so the parser must accept them without error.
        """
        env = """key1:"""
        parsed = parse_environment(env)
        assert not parsed["key1"]
