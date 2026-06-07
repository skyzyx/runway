"""Tests for runway.cfngin.hooks.cleanup_s3."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from botocore.exceptions import ClientError

from runway.cfngin.hooks.cleanup_s3 import purge_bucket

if TYPE_CHECKING:
    from ...factories import MockCfnginContext


def test_purge_bucket(cfngin_context: MockCfnginContext) -> None:
    """Test purge_bucket.

    Validates the happy path where the bucket exists and is empty, ensuring
    the hook returns success after listing object versions.
    """
    stub = cfngin_context.add_stubber("s3")

    stub.add_response("head_bucket", {}, {"Bucket": "foo"})
    stub.add_response("list_object_versions", {"DeleteMarkers": [], "Versions": []})
    with stub:
        assert purge_bucket(cfngin_context, bucket_name="foo")
    stub.assert_no_pending_responses()


def test_purge_bucket_does_not_exist(cfngin_context: MockCfnginContext) -> None:
    """Test purge_bucket Bucket doesn't exist.

    Ensures the hook gracefully handles a missing bucket (404) rather than
    raising, since the desired end state (no bucket content) is already met.
    """
    stub = cfngin_context.add_stubber("s3")

    stub.add_client_error("head_bucket", service_error_code="404")
    with stub:
        assert purge_bucket(cfngin_context, bucket_name="foo")
    stub.assert_no_pending_responses()


def test_purge_bucket_unhandled_exception(cfngin_context: MockCfnginContext) -> None:
    """Test purge_bucket with unhandled exception.

    Verifies that non-404 errors (e.g. 403 permission denied) propagate as
    exceptions so callers are alerted to access issues rather than silently
    succeeding.
    """
    stub = cfngin_context.add_stubber("s3")

    stub.add_client_error("head_bucket", service_error_code="403")
    with stub, pytest.raises(ClientError):
        purge_bucket(cfngin_context, bucket_name="foo")
    stub.assert_no_pending_responses()
