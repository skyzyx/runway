"""CFNgin base action.

Centralizes the shared lifecycle (build graph → create plan → execute plan)
so that concrete actions only need to define their per-stack operation and
any pre/post hooks, avoiding duplicated orchestration logic.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import TYPE_CHECKING, Any, Callable, ClassVar

import botocore.exceptions

from ..dag import ThreadedWalker, UnlimitedSemaphore, walk
from ..exceptions import CfnginBucketNotFound, PlanFailed
from ..plan import Graph, Plan, Step, merge_graphs
from ..utils import ensure_s3_bucket, get_s3_endpoint, stack_template_key_name

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

    from ...context import CfnginContext
    from ..blueprints.base import Blueprint
    from ..providers.aws.default import Provider, ProviderBuilder
    from ..stack import Stack

LOGGER = logging.getLogger(__name__)

# After submitting a stack update/create, this controls how long we'll wait
# between calls to DescribeStacks to check on it's status. Most stack updates
# take at least a couple minutes, so 30 seconds is pretty reasonable and inline
# with the suggested value in
# https://github.com/boto/botocore/blob/1.6.1/botocore/data/cloudformation/2010-05-15/waiters-2.json#L22
#
# This can be controlled via an environment variable, mostly for testing.
# Environment-variable override exists so integration tests can use a short
# interval without modifying source code or waiting minutes per stack.
STACK_POLL_TIME = int(os.environ.get("CFNGIN_STACK_POLL_TIME", "30"))


def build_walker(concurrency: int) -> Callable[..., Any]:
    """Return a function for waling a graph.

    Passed to :class:`runway.cfngin.plan.Plan` for walking the graph.
    Encapsulates the concurrency strategy decision in one place so that
    callers do not need to understand semaphore or threading details.

    If concurrency is 1 (no parallelism) this will return a simple topological
    walker that doesn't use any multithreading.

    If concurrency is 0, this will return a walker that will walk the graph as
    fast as the graph topology allows.

    If concurrency is greater than 1, it will return a walker that will only
    execute a maximum of concurrency steps at any given time.

    Args:
        concurrency: Number of threads to use while walking.

    Returns:
        Function to walk a :class:`runway.cfngin.dag.DAG`.

    """
    if concurrency == 1:
        return walk

    semaphore = UnlimitedSemaphore()
    if concurrency > 1:
        semaphore = threading.Semaphore(concurrency)

    return ThreadedWalker(semaphore).walk


def stack_template_url(bucket_name: str, blueprint: Blueprint, endpoint: str) -> str:
    """Produce an s3 url for a given blueprint.

    Exists as a module-level helper so both the base action and tests can
    construct template URLs without instantiating a full action object.

    Args:
        bucket_name: The name of the S3 bucket where the resulting
            templates are stored.
        blueprint: The blueprint object to create the URL to.
        endpoint: The s3 endpoint used for the bucket.

    """
    return f"{endpoint}/{bucket_name}/{stack_template_key_name(blueprint)}"


class BaseAction:
    """Actions perform the actual work of each Command.

    Each action is responsible for building the :class:`runway.cfngin.plan.Plan`
    that will be executed. This base class exists to enforce a uniform lifecycle
    (pre_run → run → post_run) and provide shared infrastructure (S3 template
    storage, provider construction, plan generation) so concrete actions focus
    only on their stack-level logic.

    Attributes:
        DESCRIPTION: Description used when creating a plan for an action.
        NAME: Name of the action.
        bucket_name: S3 bucket used by the action.
        bucket_region: AWS region where S3 bucket is located.
        cancel: Cancel handler.
        context: The context for the current run.
        provider_builder: An object that will build a provider that will be
            interacted with in order to perform the necessary actions.
        s3_conn: Boto3 S3 client.

    """

    DESCRIPTION: ClassVar[str] = "Base action"
    NAME: ClassVar[str | None] = None

    bucket_name: str | None
    bucket_region: str | None
    cancel: threading.Event
    context: CfnginContext
    provider_builder: ProviderBuilder | None
    s3_conn: S3Client

    def __init__(
        self,
        context: CfnginContext,
        provider_builder: ProviderBuilder | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        """Instantiate class.

        Captures the run context, provider factory, and cancellation signal so
        that subclasses have everything needed to build and execute a plan
        without re-resolving configuration or credentials.

        Args:
            context: The context for the current run.
            provider_builder: An object that will build a provider that will be
                interacted with in order to perform the necessary actions.
            cancel: Cancel handler.

        """
        self.context = context
        self.provider_builder = provider_builder
        self.bucket_name = context.bucket_name
        self.cancel = cancel or threading.Event()
        # Fall back to the provider's region when the config does not
        # explicitly specify a bucket region, keeping bucket access in the
        # same region as the stacks being managed.
        self.bucket_region = context.config.cfngin_bucket_region
        if not self.bucket_region and provider_builder:
            self.bucket_region = provider_builder.region
        self.s3_conn = self.context.s3_client

    @property
    def _stack_action(self) -> Callable[..., Any]:
        """Run against a step.

        Subclasses override this to supply the per-stack callable (e.g.
        create/update/delete) that the plan executor invokes for each node
        in the dependency graph.
        """
        raise NotImplementedError

    @property
    def provider(self) -> Provider:
        """Return a generic provider using the default region.

        Used for running things like hooks. Provides a region-agnostic
        provider for operations that are not tied to a specific stack's
        region, such as pre/post-run hooks.

        """
        if not self.provider_builder:
            raise ValueError("ProviderBuilder required to build a provider")
        return self.provider_builder.build()

    def build_provider(self) -> Provider:
        """Build a CFNgin provider.

        Wraps provider construction behind a method so subclasses and helpers
        (like _tail_stack) obtain a provider without knowing builder details.
        """
        if not self.provider_builder:
            raise ValueError("ProviderBuilder required to build a provider")
        return self.provider_builder.build()

    def ensure_cfn_bucket(self) -> None:
        """CloudFormation bucket where templates will be stored.

        Validates the bucket exists before attempting uploads, providing a
        clear error message instead of a cryptic S3 403/404 during template
        push.
        """
        if self.bucket_name:
            try:
                ensure_s3_bucket(self.s3_conn, self.bucket_name, self.bucket_region, create=False)
            except botocore.exceptions.ClientError:
                raise CfnginBucketNotFound(bucket_name=self.bucket_name) from None

    def execute(self, **kwargs: Any) -> None:
        """Run the action with pre and post steps.

        Wraps the three-phase lifecycle in a single entry point so callers
        do not need to remember the ordering, and guarantees that a
        PlanFailed error results in a non-zero exit rather than an
        unhandled exception propagating to the user.
        """
        try:
            self.pre_run(**kwargs)
            self.run(**kwargs)
            self.post_run(**kwargs)
        except PlanFailed as err:
            LOGGER.error(str(err))
            sys.exit(1)

    def pre_run(self, *, dump: bool | str = False, outline: bool = False, **__kwargs: Any) -> None:
        """Perform steps before running the action.

        Hook point for subclasses to validate prerequisites (e.g. S3 bucket
        existence) or upload templates before the plan executes.
        """

    def post_run(self, *, dump: bool | str = False, outline: bool = False, **__kwargs: Any) -> None:
        """Perform steps after running the action.

        Hook point for subclasses to perform cleanup or finalization (e.g.
        persistent graph updates) after the plan has completed.
        """

    def run(
        self,
        *,
        concurrency: int = 0,
        dump: bool | str = False,
        force: bool = False,
        outline: bool = False,
        tail: bool = False,
        upload_disabled: bool = False,
        **_kwargs: Any,
    ) -> None:
        """Abstract method for running the action.

        Each concrete action implements this to build and execute its plan.
        The wide parameter signature accommodates the CLI flags that various
        actions support without requiring intermediate adapter layers.
        """
        raise NotImplementedError('Subclass must implement "run" method')

    def s3_stack_push(self, blueprint: Blueprint, force: bool = False) -> str:
        """Push the rendered blueprint's template to S3.

        Verifies that the template doesn't already exist in S3 before
        pushing. This avoids redundant uploads for unchanged templates,
        reducing deploy time and S3 PUT costs when iterating on stacks that
        share a template.

        Returns:
            URL to the template in S3.

        """
        if not self.bucket_name:
            raise ValueError("bucket_name required")
        key_name = stack_template_key_name(blueprint)
        template_url = self.stack_template_url(blueprint)
        # Use head_object to check existence without downloading the full
        # template body, which can be large for complex stacks.
        try:
            template_exists = bool(self.s3_conn.head_object(Bucket=self.bucket_name, Key=key_name))
        except botocore.exceptions.ClientError as err:
            if err.response["Error"]["Code"] == "404":
                template_exists = False
            else:
                raise

        if template_exists and not force:
            LOGGER.debug("CloudFormation template already exists: %s", template_url)
            return template_url
        self.s3_conn.put_object(
            Bucket=self.bucket_name,
            Key=key_name,
            Body=blueprint.rendered.encode(),
            ServerSideEncryption="AES256",
            ACL="bucket-owner-full-control",
        )
        LOGGER.debug("blueprint %s pushed to %s", blueprint.name, template_url)
        return template_url

    def stack_template_url(self, blueprint: Blueprint) -> str:
        """S3 URL for CloudFormation template object.

        Instance method wrapper around the module-level helper, binding the
        action's bucket name and S3 endpoint automatically.
        """
        if not self.bucket_name:
            raise ValueError("bucket_name required")
        return stack_template_url(self.bucket_name, blueprint, get_s3_endpoint(self.s3_conn))

    def _generate_plan(
        self,
        tail: bool = False,
        reverse: bool = False,
        require_unlocked: bool = True,
        include_persistent_graph: bool = False,
    ) -> Plan:
        """Create a plan for this action.

        Builds the dependency graph from the context's stack list and
        optionally merges the persistent graph so that remotely-tracked stacks
        are included in destroy operations without requiring them in the local
        config.

        Args:
            tail: Whether to tail the stack progress.
            reverse: If True, execute the graph in reverse (useful for destroy actions).
            require_unlocked: If the persistent graph is locked, an error is raised.
            include_persistent_graph: Include the persistent graph
                in the :class:`runway.cfngin.plan.Plan` (if there is one).
                This will handle basic merging of the local and persistent
                graphs if an action does not require more complex logic.

        """
        tail_fn = self._tail_stack if tail else None

        steps = [
            Step(stack, fn=self._stack_action, watch_func=tail_fn) for stack in self.context.stacks
        ]

        graph = Graph.from_steps(steps)

        if include_persistent_graph and self.context.persistent_graph:
            # Merge remotely-tracked stacks into the local graph so that
            # destroy actions can remove stacks no longer in the config
            # without losing dependency ordering information.
            persist_steps = Step.from_persistent_graph(
                self.context.persistent_graph.to_dict(),
                self.context,
                fn=self._stack_action,
                watch_func=tail_fn,
            )
            persist_graph = Graph.from_steps(persist_steps)
            graph = merge_graphs(graph, persist_graph)

        return Plan(
            context=self.context,
            description=self.DESCRIPTION,
            graph=graph,
            reverse=reverse,
            require_unlocked=require_unlocked,
        )

    def _tail_stack(
        self, stack: Stack, cancel: threading.Event, retries: int = 0, **kwargs: Any
    ) -> None:
        """Tail a stack's event stream.

        Delegates to the provider's tail implementation so the user can
        observe real-time CloudFormation events during long-running
        operations without polling manually.
        """
        provider = self.build_provider()
        return provider.tail_stack(stack, cancel, action=self.NAME, retries=retries, **kwargs)
