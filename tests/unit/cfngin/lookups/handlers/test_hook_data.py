"""Tests for runway.cfngin.lookups.handlers.hook_data.

Validates the hook_data lookup that resolves values from data stored by
previously executed hooks, enabling inter-hook data passing and supporting
nested key traversal, defaults, and troposphere object extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from troposphere.awslambda import Code

from runway.exceptions import FailedVariableLookup
from runway.variables import Variable

if TYPE_CHECKING:
    from ....factories import MockCfnginContext


class TestHookDataLookup:
    """Tests for runway.cfngin.lookups.handlers.hook_data.HookDataLookup.

    Hook data lookups are the primary mechanism for passing data between hooks
    and stack templates. These tests ensure correct nested key resolution,
    default fallback behavior, and troposphere object deserialization.
    """

    def test_handle(self, cfngin_context: MockCfnginContext) -> None:
        """Test handle with simple usage.

        Validates both top-level and dot-notation nested key access, which is
        how hooks expose structured data to downstream stacks.
        """
        cfngin_context.set_hook_data("fake_hook", {"nested": {"result": "good"}})
        var_top = Variable("test", "${hook_data fake_hook}", variable_type="cfngin")
        var_nested = Variable(
            "test", "${hook_data fake_hook.nested.result}", variable_type="cfngin"
        )
        var_top.resolve(cfngin_context)
        var_nested.resolve(cfngin_context)

        assert var_top.value == {"nested": {"result": "good"}}
        assert var_nested.value == "good"

    def test_default(self, cfngin_context: MockCfnginContext) -> None:
        """Test handle with a default value.

        Ensures the default fallback works for both missing hooks and missing
        nested keys, which prevents deployment failures when optional hooks
        haven't run or data shape varies between environments.
        """
        cfngin_context.set_hook_data("fake_hook", {"nested": {"result": "good"}})
        var_top = Variable(
            "test", "${hook_data bad_hook::default=something}", variable_type="cfngin"
        )
        var_nested = Variable(
            "test",
            "${hook_data fake_hook.bad." + "result::default=something,load=json,get=key}",
            variable_type="cfngin",
        )
        var_top.resolve(cfngin_context)
        var_nested.resolve(cfngin_context)

        assert var_top.value == "something"
        assert var_nested.value == "something"

    def test_not_found(self, cfngin_context: MockCfnginContext) -> None:
        """Test value not found and no default.

        Confirms that a missing key without a default raises
        FailedVariableLookup with a clear message, so users know exactly
        which lookup path failed during template resolution.
        """
        variable = Variable("test", "${hook_data fake_hook.bad.result}", variable_type="cfngin")
        with pytest.raises(FailedVariableLookup) as err:
            variable.resolve(cfngin_context)

        assert str(err.value) == (
            f'Could not resolve lookup "{variable._raw_value}" for variable "{variable.name}"'
        )
        assert "Could not find a value for" in str(err.value.__cause__)

    def test_troposphere(self, cfngin_context: MockCfnginContext) -> None:
        """Test with troposphere object like returned from lambda hook.

        Validates the load=troposphere mode that extracts attributes from
        troposphere objects stored in hook_data, which is needed because
        Lambda hooks store Code objects that templates must destructure.
        """
        bucket = "test-bucket"
        s3_key = "lambda_functions/my_function"
        cfngin_context.set_hook_data("lambda", {"my_function": Code(S3Bucket=bucket, S3Key=s3_key)})
        var_bucket = Variable(
            "test",
            "${hook_data lambda.my_function::" + "load=troposphere,get=S3Bucket}",
            variable_type="cfngin",
        )
        var_key = Variable(
            "test", "${hook_data lambda.my_function::get=S3Key}", variable_type="cfngin"
        )
        var_bucket.resolve(cfngin_context)
        var_key.resolve(cfngin_context)

        assert var_bucket.value == bucket
        assert var_key.value == s3_key
