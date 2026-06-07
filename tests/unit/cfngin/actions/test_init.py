"""Test runway.cfngin.actions.init.

Validates the init action that bootstraps the cfngin bucket. Covers bucket
existence checks, access-denied handling, the default bucket stack blueprint
fallback, and region override for cross-region bucket creation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from runway._logging import LogLevels
from runway.cfngin.actions.init import Action
from runway.cfngin.exceptions import CfnginBucketAccessDenied
from runway.config.models.cfngin import CfnginStackDefinitionModel
from runway.core.providers.aws.s3 import Bucket

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from runway.context import CfnginContext

MODULE = "runway.cfngin.actions.init"


class TestAction:
    """Test Action.

    Exercises the init action's responsibility to ensure the cfngin S3 bucket
    exists before any deploy can upload templates. Covers creation, pre-existing
    bucket detection, access-denied errors, and bucket region overrides.
    """

    def test___init__(self, cfngin_context: CfnginContext, mocker: MockerFixture) -> None:
        """Test __init__.

        The init action must copy the context to avoid mutating the caller's
        state when it modifies the config (e.g., injecting the bucket stack).
        """
        copied_context = mocker.patch.object(cfngin_context, "copy")
        obj = Action(cfngin_context)
        copied_context.assert_called_once_with()
        assert obj.context == copied_context.return_value

    def test__stack_action(self, cfngin_context: CfnginContext) -> None:
        """Test _stack_action."""
        assert Action(cfngin_context)._stack_action is None

    def test_cfngin_bucket(self, cfngin_context: CfnginContext, mocker: MockerFixture) -> None:
        """Test cfngin_bucket."""
        mocker.patch.object(cfngin_context, "copy", return_value=cfngin_context)
        mocker.patch.object(cfngin_context, "s3_client")
        bucket = mocker.patch(f"{MODULE}.Bucket")
        bucket_name = mocker.patch.object(cfngin_context, "bucket_name", "bucket_name")
        bucket_region = mocker.patch.object(cfngin_context, "bucket_region", "bucket_region")
        obj = Action(cfngin_context)
        assert obj.cfngin_bucket == bucket.return_value
        bucket.assert_called_once_with(cfngin_context, name=bucket_name, region=bucket_region)

    def test_cfngin_bucket_handle_no_bucket(
        self, cfngin_context: CfnginContext, mocker: MockerFixture
    ) -> None:
        """Test cfngin_bucket.

        When bucket_name is None (not configured), the property must return
        None without attempting to construct a Bucket object.
        """
        mocker.patch.object(cfngin_context, "copy", return_value=cfngin_context)
        mocker.patch.object(cfngin_context, "s3_client")
        bucket = mocker.patch(f"{MODULE}.Bucket")
        mocker.patch.object(cfngin_context, "bucket_name", None)
        mocker.patch.object(cfngin_context, "bucket_region", "bucket_region")
        assert not Action(cfngin_context).cfngin_bucket
        bucket.assert_not_called()

    def test_default_cfngin_bucket_stack(
        self, cfngin_context: CfnginContext, mocker: MockerFixture
    ) -> None:
        """Test default_cfngin_bucket_stack."""
        mocker.patch.object(cfngin_context, "copy", return_value=cfngin_context)
        bucket_name = mocker.patch.object(cfngin_context, "bucket_name", "bucket_name")
        assert Action(cfngin_context).default_cfngin_bucket_stack == CfnginStackDefinitionModel(
            class_path="runway.cfngin.blueprints.cfngin_bucket.CfnginBucket",
            in_progress_behavior="wait",
            name="cfngin-bucket",
            termination_protection=True,
            variables={"BucketName": bucket_name},
        )

    def test_run(
        self,
        caplog: pytest.LogCaptureFixture,
        cfngin_context: CfnginContext,
        mocker: MockerFixture,
    ) -> None:
        """Test run.

        When the bucket doesn't exist and no stack is pre-configured, the init
        action must inject the default bucket blueprint and delegate to deploy
        with upload_disabled=True (since the bucket doesn't exist yet).
        """
        caplog.set_level(LogLevels.NOTICE, logger=MODULE)
        cancel = Mock()
        mock_deploy = mocker.patch(f"{MODULE}.deploy")
        provider_builder = Mock()
        mocker.patch.object(cfngin_context, "copy", return_value=cfngin_context)
        mocker.patch.object(cfngin_context, "get_stack", return_value=None)
        mocker.patch.object(
            Action, "cfngin_bucket", Mock(exists=False, forbidden=False, spec=Bucket)
        )
        obj = Action(cfngin_context, provider_builder, cancel)
        assert not obj.run(concurrency=3, tail=True, upload_disabled=False)
        assert "using default blueprint to create cfngin_bucket..." in caplog.messages
        assert cfngin_context.config.stacks == [obj.default_cfngin_bucket_stack]
        mock_deploy.Action.assert_called_once_with(
            context=cfngin_context, provider_builder=provider_builder, cancel=cancel
        )
        mock_deploy.Action.return_value.run.assert_called_once_with(
            concurrency=3,
            tail=True,
            upload_disabled=True,
        )

    def test_run_cfngin_bucket_region(
        self,
        caplog: pytest.LogCaptureFixture,
        cfngin_context: CfnginContext,
        mocker: MockerFixture,
    ) -> None:
        """Test run.

        When a bucket_region is configured that differs from the deploy region,
        the provider_builder.region must be overridden so the bucket stack is
        created in the correct region.
        """
        caplog.set_level(LogLevels.NOTICE, logger=MODULE)
        cancel = Mock()
        mock_deploy = mocker.patch(f"{MODULE}.deploy")
        provider_builder = Mock(region=None)
        mocker.patch.object(cfngin_context, "copy", return_value=cfngin_context)
        mocker.patch.object(cfngin_context, "get_stack", return_value=None)
        mocker.patch.object(cfngin_context, "s3_client", return_value=Mock())
        mocker.patch.object(
            Action, "cfngin_bucket", Mock(exists=False, forbidden=False, spec=Bucket)
        )
        cfngin_context.bucket_region = "ca-central-1"
        obj = Action(cfngin_context, provider_builder, cancel)
        assert not obj.run(concurrency=3, tail=True, upload_disabled=False)
        assert "using default blueprint to create cfngin_bucket..." in caplog.messages
        assert cfngin_context.config.stacks == [obj.default_cfngin_bucket_stack]
        assert provider_builder.region == "ca-central-1"
        mock_deploy.Action.assert_called_once_with(
            context=cfngin_context, provider_builder=provider_builder, cancel=cancel
        )
        mock_deploy.Action.return_value.run.assert_called_once_with(
            concurrency=3,
            tail=True,
            upload_disabled=True,
        )

    def test_run_exists(
        self,
        caplog: pytest.LogCaptureFixture,
        cfngin_context: CfnginContext,
        mocker: MockerFixture,
    ) -> None:
        """Test run.

        When the bucket already exists, init must short-circuit without
        deploying anything to avoid unnecessary CloudFormation operations.
        """
        caplog.set_level(LogLevels.INFO, logger=MODULE)
        cfngin_bucket = mocker.patch.object(
            Action,
            "cfngin_bucket",
            Mock(exists=True, forbidden=False, spec=Bucket),
        )
        cfngin_bucket.name = "name"
        assert not Action(cfngin_context).run()
        assert f"cfngin_bucket {cfngin_bucket.name} already exists" in caplog.messages

    def test_run_forbidden(self, cfngin_context: CfnginContext, mocker: MockerFixture) -> None:
        """Test run.

        If the bucket exists but access is denied, the action must raise
        CfnginBucketAccessDenied so the operator knows the IAM permissions
        need fixing rather than proceeding with a broken state.
        """
        cfngin_bucket = mocker.patch.object(
            Action,
            "cfngin_bucket",
            Mock(forbidden=True, spec=Bucket),
        )
        cfngin_bucket.name = "cfngin_bucket.name"
        with pytest.raises(CfnginBucketAccessDenied, match="cfngin_bucket.name"):
            assert Action(cfngin_context).run()

    def test_run_get_stack(
        self,
        caplog: pytest.LogCaptureFixture,
        cfngin_context: CfnginContext,
        mocker: MockerFixture,
    ) -> None:
        """Test run.

        When a pre-existing cfngin-bucket stack is found in the config, init
        must reuse it (scoping to just that stack) rather than injecting the
        default blueprint, supporting custom bucket configurations.
        """
        caplog.set_level(LogLevels.VERBOSE, logger=MODULE)
        cancel = Mock()
        mock_deploy = mocker.patch(f"{MODULE}.deploy")
        provider_builder = Mock()
        mocker.patch.object(cfngin_context, "copy", return_value=cfngin_context)
        get_stack = mocker.patch.object(cfngin_context, "get_stack", return_value=True)
        mocker.patch.object(
            Action, "cfngin_bucket", Mock(exists=False, forbidden=False, spec=Bucket)
        )
        assert not Action(cfngin_context, provider_builder, cancel).run()
        get_stack.assert_called_once_with("cfngin-bucket")
        assert "found stack for creating cfngin_bucket: cfngin-bucket" in caplog.messages
        assert cfngin_context.stack_names == ["cfngin-bucket"]
        mock_deploy.Action.assert_called_once_with(
            context=cfngin_context, provider_builder=provider_builder, cancel=cancel
        )
        mock_deploy.Action.return_value.run.assert_called_once_with(
            concurrency=0,
            tail=False,
            upload_disabled=True,
        )

    def test_run_no_cfngin_bucket(
        self,
        caplog: pytest.LogCaptureFixture,
        cfngin_context: CfnginContext,
        mocker: MockerFixture,
    ) -> None:
        """Test run.

        When no cfngin_bucket is configured at all, init must skip gracefully
        since templates will be submitted inline without S3.
        """
        caplog.set_level(LogLevels.INFO, logger=MODULE)
        mocker.patch.object(Action, "cfngin_bucket", None)
        assert not Action(cfngin_context).run()
        assert "skipped; cfngin_bucket not defined" in caplog.messages
