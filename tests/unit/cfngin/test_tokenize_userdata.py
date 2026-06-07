"""Tests for runway.cfngin.tokenize_userdata.

Validates that CloudFormation intrinsic function references embedded in
EC2 userdata strings are correctly parsed from YAML into their native
CFN dict representation, enabling cfngin to produce valid Join/Sub
expressions in generated templates.
"""

import unittest

import yaml

from runway.cfngin.tokenize_userdata import cf_tokenize


class TestCfTokenize(unittest.TestCase):
    """Tests for runway.cfngin.tokenize_userdata.

    Tokenization must correctly identify and convert Ref() and Fn::GetAtt()
    string patterns into CloudFormation-native dict structures so that
    userdata scripts can reference stack resources at deploy time.
    """

    def test_tokenize(self) -> None:
        """Test tokenize.

        Verifies that Ref and Fn::GetAtt patterns within YAML-serialized
        userdata are converted to their CloudFormation dict equivalents while
        leaving plain string fields untouched.
        """
        user_data = ["field0", 'Ref("SshKey")', "field1", 'Fn::GetAtt("Blah", "Woot")']
        user_data_dump = yaml.dump(user_data)
        parts = cf_tokenize(user_data_dump)
        assert isinstance(parts[1], dict)
        assert isinstance(parts[3], dict)
        assert parts[1]["Ref"] == "SshKey"
        assert parts[3]["Fn::GetAtt"] == ["Blah", "Woot"]
        assert len(parts) == 5
