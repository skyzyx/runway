"""Tests for runway.cfngin.lookups.handlers.dynamodb.

Validates DynamoDB lookups including query parsing, item retrieval, type
coercion (string, number, list, map), and error handling for missing tables,
invalid keys, and unsupported DynamoDB data types.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from runway.cfngin.lookups.handlers.dynamodb import DynamodbLookup, QueryDataModel

if TYPE_CHECKING:
    from ....factories import MockCfnginContext

GET_ITEM_RESPONSE = {
    "Item": {
        "TestKey": {"S": "TestVal"},
        "TestMap": {
            "M": {
                "String1": {"S": "StringVal1"},
                "List1": {"L": [{"S": "ListVal1"}, {"S": "ListVal2"}]},
                "Number1": {"N": "12345"},
            }
        },
        "TestString": {"S": "TestStringVal"},
    }
}


class TestDynamoDBHandler:
    """Test runway.cfngin.lookups.handlers.dynamodb.DynamodbLookup.

    DynamoDB lookups enable config-time resolution of values stored in DDB,
    allowing stacks to share data without hard-coded values. These tests
    exercise the query DSL, API interaction, and error reporting.
    """

    @pytest.mark.parametrize(
        "query, expected_projection, expected_result",
        [
            (
                "TestTable@TestKey:TestVal.TestString",
                "TestKey,TestString",
                "TestStringVal",
            ),
            (
                "TestTable@TestKey:TestVal[S].TestString",
                "TestKey,TestString",
                "TestStringVal",
            ),
            (
                "TestTable@TestKey:TestVal.TestMap[M].String1",
                "TestKey,TestMap,String1",
                "StringVal1",
            ),
            (
                "TestTable@TestKey:TestVal[S].TestMap[M].String1",
                "TestKey,TestMap,String1",
                "StringVal1",
            ),
        ],
    )
    def test_handle(
        self,
        cfngin_context: MockCfnginContext,
        expected_projection: str,
        expected_result: str,
        query: str,
    ) -> None:
        """Test handle."""
        stubber = cfngin_context.add_stubber("dynamodb")
        expected_params = {
            "TableName": "TestTable",
            "Key": {"TestKey": {"S": "TestVal"}},
            "ProjectionExpression": expected_projection,
        }
        stubber.add_response("get_item", GET_ITEM_RESPONSE, expected_params)
        with stubber:
            assert DynamodbLookup.handle(query, context=cfngin_context) == expected_result
        stubber.assert_no_pending_responses()

    def test_handle_client_error(self, cfngin_context: MockCfnginContext) -> None:
        """Test handle ClientError.

        Ensures generic AWS client errors are caught and re-raised as
        ValueError with the original query included for debugging.
        """
        stubber = cfngin_context.add_stubber("dynamodb")
        expected_params = {
            "TableName": "TestTable",
            "Key": {"FakeKey": {"S": "TestVal"}},
            "ProjectionExpression": "FakeKey,TestMap,String1",
        }
        stubber.add_client_error(
            "get_item",
            expected_params=expected_params,
        )
        query = "TestTable@FakeKey:TestVal.TestMap[M].String1"
        with (
            stubber,
            pytest.raises(ValueError, match="The DynamoDB lookup '.*' encountered an error: .*"),
        ):
            DynamodbLookup.handle(query, context=cfngin_context)
        stubber.assert_no_pending_responses()

    def test_handle_empty_table_name(self, cfngin_context: MockCfnginContext) -> None:
        """Test handle with empty table_name.

        Validates regex-based query parsing rejects queries with an empty
        table name prefix, catching malformed lookup strings early.
        """
        query = "@TestKey:TestVal.TestMap[M].String1"
        with pytest.raises(ValueError, match="Query '.*' doesn't match regex:"):
            DynamodbLookup.handle(query, context=cfngin_context)

    def test_handle_invalid_partition_key(self, cfngin_context: MockCfnginContext) -> None:
        """Test handle with invalid partition key.

        Verifies the handler produces a user-friendly error when the partition
        key doesn't match DynamoDB's table schema (ValidationException).
        """
        stubber = cfngin_context.add_stubber("dynamodb")
        expected_params = {
            "TableName": "TestTable",
            "Key": {"FakeKey": {"S": "TestVal"}},
            "ProjectionExpression": "FakeKey,TestMap,String1",
        }
        service_error_code = "ValidationException"
        stubber.add_client_error(
            "get_item",
            service_error_code=service_error_code,
            expected_params=expected_params,
        )

        with (
            stubber,
            pytest.raises(
                ValueError,
                match="No DynamoDB record matched the partition key: FakeKey",
            ),
        ):
            DynamodbLookup.handle(
                "TestTable@FakeKey:TestVal.TestMap[M].String1", context=cfngin_context
            )
        stubber.assert_no_pending_responses()

    def test_handle_invalid_partition_value(self, cfngin_context: MockCfnginContext) -> None:
        """Test handle with invalid partition value.

        Covers the case where the key is valid but no item matches the
        partition value, resulting in an empty response that must be detected.
        """
        stubber = cfngin_context.add_stubber("dynamodb")
        expected_params = {
            "TableName": "TestTable",
            "Key": {"TestKey": {"S": "FakeVal"}},
            "ProjectionExpression": "TestKey,TestMap,String1",
        }
        empty_response: dict[str, Any] = {"ResponseMetadata": {}}
        stubber.add_response("get_item", empty_response, expected_params)
        with (
            stubber,
            pytest.raises(
                ValueError,
                match="The DynamoDB record could not be found using the following: "
                "{'TestKey': {'S': 'FakeVal'}}",
            ),
        ):
            DynamodbLookup.handle(
                "TestTable@TestKey:FakeVal.TestMap[M].String1", context=cfngin_context
            )

    def test_handle_list(self, cfngin_context: MockCfnginContext) -> None:
        """Test handle return list.

        Validates that DynamoDB List (L) type values are correctly unwrapped
        into Python lists, enabling multi-value lookups in CFNgin configs.
        """
        stubber = cfngin_context.add_stubber("dynamodb")
        expected_params = {
            "TableName": "TestTable",
            "Key": {"TestKey": {"S": "TestVal"}},
            "ProjectionExpression": "TestKey,TestMap,List1",
        }
        stubber.add_response("get_item", GET_ITEM_RESPONSE, expected_params)
        with stubber:
            assert DynamodbLookup.handle(
                "TestTable@TestKey:TestVal.TestMap[M].List1[L]", context=cfngin_context
            ) == ["ListVal1", "ListVal2"]
        stubber.assert_no_pending_responses()

    def test_handle_missing_table_name(self, cfngin_context: MockCfnginContext) -> None:
        """Test handle missing table_name.

        Validates that a query without the @ table delimiter is rejected
        before making any API calls.
        """
        query = "TestKey:TestVal.TestMap[M].String1"
        with pytest.raises(ValueError, match="'.*' missing delimiter for DynamoDB Table name:"):
            DynamodbLookup.handle(query, context=cfngin_context)

    def test_handle_number(self, cfngin_context: MockCfnginContext) -> None:
        """Test handle return number.

        Validates DynamoDB Number (N) types are converted to Python integers
        and that the optional region prefix in the query is parsed correctly.
        """
        stubber = cfngin_context.add_stubber("dynamodb")
        expected_params = {
            "TableName": "TestTable",
            "Key": {"TestKey": {"S": "TestVal"}},
            "ProjectionExpression": "TestKey,TestMap,Number1",
        }
        stubber.add_response("get_item", GET_ITEM_RESPONSE, expected_params)
        with stubber:
            assert (
                DynamodbLookup.handle(
                    cfngin_context.env.aws_region
                    + ":TestTable@TestKey:TestVal.TestMap[M].Number1[N]",
                    context=cfngin_context,
                )
                == 12345
            )
        stubber.assert_no_pending_responses()

    def test_handle_table_not_found(self, cfngin_context: MockCfnginContext) -> None:
        """Test handle DDB Table not found.

        Ensures ResourceNotFoundException is translated into a clear error
        message naming the missing table, rather than exposing raw AWS errors.
        """
        stubber = cfngin_context.add_stubber("dynamodb")
        expected_params = {
            "TableName": "FakeTable",
            "Key": {"TestKey": {"S": "TestVal"}},
            "ProjectionExpression": "TestKey,TestMap,String1",
        }
        service_error_code = "ResourceNotFoundException"
        stubber.add_client_error(
            "get_item",
            service_error_code=service_error_code,
            expected_params=expected_params,
        )
        with (
            stubber,
            pytest.raises(ValueError, match="Can't find the DynamoDB table: FakeTable"),
        ):
            DynamodbLookup.handle(
                "FakeTable@TestKey:TestVal.TestMap[M].String1", context=cfngin_context
            )
        stubber.assert_no_pending_responses()

    def test_handle_unsupported_data_type(self, cfngin_context: MockCfnginContext) -> None:
        """Test handle with unsupported data type.

        Confirms that unsupported DynamoDB types (e.g., Binary) raise a clear
        error rather than silently returning malformed data.
        """
        with pytest.raises(ValueError, match="CFNgin does not support looking up the data type: B"):
            DynamodbLookup.handle(
                "TestTable@TestKey:FakeVal.TestStringSet[B]", context=cfngin_context
            )


class TestQueryDataModel:
    """Test runway.cfngin.lookups.handlers.dynamodb.QueryDataModel.

    Validates parsing of the DynamoDB query DSL into structured data,
    including partition key type annotation extraction and validation.
    """

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("TestVal", {"S": "TestVal"}),
            ("TestVal[B]", {"B": "TestVal"}),
            ("TestVal[N]", {"N": "TestVal"}),
            ("TestVal[S]", {"S": "TestVal"}),
        ],
    )
    def test_item_key(self, expected: dict[str, Any], value: str) -> None:
        """Test item_key."""
        assert QueryDataModel(
            attribute="",
            partition_key="TestKey",
            partition_key_value=value,
            table_name="",
        ).item_key == {"TestKey": expected}

    def test_item_key_no_match(self) -> None:
        """Test item_key.

        Verifies that unsupported key type annotations (e.g., [L] for List)
        are rejected since only S, N, and B are valid DynamoDB key types.
        """
        obj = QueryDataModel(
            attribute="",
            partition_key="TestKey",
            partition_key_value="TestVal[L]",
            table_name="",
        )
        with pytest.raises(
            ValueError,
            match="Partition key value '.*' doesn't match regex: .*",
        ):
            assert obj.item_key
