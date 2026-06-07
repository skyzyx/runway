"""CFNgin init action.

This module bootstraps the S3 bucket that CFNgin uses for template storage,
ensuring the required infrastructure exists before any deploy action attempts
to upload templates. Running init as a separate step allows idempotent
re-runs and cleaner error messages when bucket permissions are misconfigured.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from ...compat import cached_property
from ...config.models.cfngin import CfnginStackDefinitionModel
from ...core.providers.aws.s3 import Bucket
from ..exceptions import CfnginBucketAccessDenied
from . import deploy
from .base import BaseAction

if TYPE_CHECKING:
    import threading

    from ..._logging import RunwayLogger
    from ...context import CfnginContext
    from ..providers.aws.default import ProviderBuilder

LOGGER = cast("RunwayLogger", logging.getLogger(__name__))


class Action(BaseAction):
    """Initialize environment.

    Separated from the deploy action so that bucket creation can be retried
    independently and so that deploy never has to handle the chicken-and-egg
    problem of needing a bucket to upload templates for the bucket's own stack.
    """

    NAME = "init"
    DESCRIPTION = "Initialize environment"

    def __init__(
        self,
        context: CfnginContext,
        provider_builder: ProviderBuilder | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        """Instantiate class.

        This class creates a copy of the context object prior to initialization
        as some of it can perform destructive actions on the context object.

        Copies the context because init mutates stack lists and config
        properties (e.g. replacing stacks with the default bucket blueprint),
        and those mutations must not leak into the caller's context for
        subsequent actions.

        Args:
            context: The context for the current run.
            provider_builder: An object that will build a provider that will be
                interacted with in order to perform the necessary actions.
            cancel: Cancel handler.

        """
        super().__init__(context=context.copy(), provider_builder=provider_builder, cancel=cancel)

    @property
    def _stack_action(self) -> Any:
        """Run against a step."""
        return None

    @cached_property
    def cfngin_bucket(self) -> Bucket | None:
        """CFNgin bucket.

        Returns None when no bucket is configured so callers can skip bucket
        operations entirely in bucket-less (inline template) deployments.

        Raises:
            CfnginBucketRequired: cfngin_bucket not defined.

        """
        if not self.context.bucket_name:
            return None
        return Bucket(
            self.context,
            name=self.context.bucket_name,
            region=self.context.bucket_region,
        )

    @cached_property
    def default_cfngin_bucket_stack(self) -> CfnginStackDefinitionModel:
        """CFNgin bucket stack.

        Provides a built-in blueprint so that users do not need to manually
        define a stack for the CFNgin bucket in their config; init can
        self-bootstrap with sensible defaults including termination protection.
        """
        return CfnginStackDefinitionModel(
            class_path="runway.cfngin.blueprints.cfngin_bucket.CfnginBucket",
            in_progress_behavior="wait",
            name="cfngin-bucket",
            termination_protection=True,
            variables={"BucketName": self.context.bucket_name},
        )

    def run(
        self,
        *,
        concurrency: int = 0,
        dump: bool | str = False,  # noqa: ARG002
        force: bool = False,  # noqa: ARG002
        outline: bool = False,  # noqa: ARG002
        tail: bool = False,
        upload_disabled: bool = True,  # noqa: ARG002
        **_kwargs: Any,
    ) -> None:
        """Run the action.

        Args:
            concurrency: The maximum number of concurrent deployments.
            dump: Not used by this action
            force: Not used by this action.
            outline: Not used by this action.
            tail: Tail the stack's events.
            upload_disabled: Not used by this action.

        Raises:
            CfnginBucketAccessDenied: Could not head cfngin_bucket.

        """
        # attr can be falsy but still be Bucket so need to check type
        if not isinstance(self.cfngin_bucket, Bucket):
            LOGGER.info("skipped; cfngin_bucket not defined")
            return
        if self.cfngin_bucket.forbidden:
            raise CfnginBucketAccessDenied(bucket_name=self.cfngin_bucket.name)
        if self.cfngin_bucket.exists:
            LOGGER.info("cfngin_bucket %s already exists", self.cfngin_bucket.name)
            return
        if self.context.get_stack("cfngin-bucket"):
            LOGGER.verbose(
                "found stack for creating cfngin_bucket: cfngin-bucket",
            )
            self.context.stack_names = ["cfngin-bucket"]
        else:
            LOGGER.notice("using default blueprint to create cfngin_bucket...")
            self.context.config.stacks = [self.default_cfngin_bucket_stack]
            # Clear cached stacks so the context re-evaluates with the new
            # config; without this, subsequent code would operate on stale
            # stack objects from the original config.
            self.context._del_cached_property("stacks", "stacks_dict")  # noqa: SLF001
        # Force the provider to use the bucket region so the deploy action
        # creates the CloudFormation stack in the same region as the bucket.
        if self.provider_builder:
            self.provider_builder.region = self.context.bucket_region
        deploy.Action(
            context=self.context,
            provider_builder=self.provider_builder,
            cancel=self.cancel,
        ).run(
            concurrency=concurrency,
            tail=tail,
            upload_disabled=True,
        )
        return

    def pre_run(
        self,
        *,
        dump: bool | str = False,
        outline: bool = False,
        **__kwargs: Any,
    ) -> None:
        """Do nothing."""

    def post_run(
        self,
        *,
        dump: bool | str = False,
        outline: bool = False,
        **__kwargs: Any,
    ) -> None:
        """Do nothing."""
