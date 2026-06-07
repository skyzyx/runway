"""Tests for runway.cfngin.lookups.handlers.split.

Validates the split lookup that divides a string into a list using a
user-specified delimiter, enabling multi-value parameters to be expressed
as a single string in configuration files.
"""

import unittest

import pytest

from runway.cfngin.lookups.handlers.split import SplitLookup


class TestSplitLookup(unittest.TestCase):
    """Tests for runway.cfngin.lookups.handlers.split.SplitLookup.

    The split lookup converts a delimited string into a list, which is needed
    because CFNgin config values are always strings but some CloudFormation
    parameters require lists.
    """

    def test_single_character_split(self) -> None:
        """Test single character split."""
        value = ",::a,b,c"
        expected = ["a", "b", "c"]
        assert SplitLookup.handle(value) == expected

    def test_multi_character_split(self) -> None:
        """Test multi character split.

        Validates that multi-character delimiters work correctly, which is
        needed when the delimiter character also appears in the data values.
        """
        value = ",,::a,,b,c"
        expected = ["a", "b,c"]
        assert SplitLookup.handle(value) == expected

    def test_invalid_value_split(self) -> None:
        """Test invalid value split.

        Ensures that a query without the required :: separator between
        delimiter and data raises ValueError, preventing silent misparse.
        """
        value = ",:a,b,c"
        with pytest.raises(ValueError):  # noqa: PT011
            SplitLookup.handle(value)
