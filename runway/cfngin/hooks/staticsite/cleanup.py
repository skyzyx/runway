"""Replicated Lambda Function cleanup warning.

Lambda@Edge replicas cannot be immediately deleted by CloudFormation; AWS removes
them asynchronously. This hook warns operators about orphaned functions so they
can manually clean up after the replication lag passes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..base import HookArgsBaseModel

if TYPE_CHECKING:
    from mypy_boto3_cloudformation.type_defs import OutputTypeDef

    from ....context import CfnginContext

LOGGER = logging.getLogger(__name__)
# Lambda@Edge function ARN output keys from the static site CloudFormation stack.
# These identify replicated functions that may become orphaned on stack deletion.
REPLICATED_FUNCTION_OUTPUTS = [
    "LambdaCheckAuthArn",
    "LambdaHttpHeadersArn",
    "LambdaParseAuthArn",
    "LambdaRefreshAuthArn",
    "LambdaSignOutArn",
    "LambdaCFDirectoryIndexRewriteArn",
]
# Stack statuses that indicate the stack is already gone or rolling back,
# meaning there are no active outputs to inspect for orphaned functions.
STACK_STATUSES_TO_IGNORE = [
    "ROLLBACK_IN_PROGRESS",
    "ROLLBACK_FAILED",
    "ROLLBACK_COMPLETE",
    "DELETE_IN_PROGRESS",
    "DELETE_FAILED",
    "DELETE_COMPLETE",
    "IMPORT_ROLLBACK_IN_PROGRESS",
    "IMPORT_ROLLBACK_FAILED",
    "IMPORT_ROLLBACK_COMPLETE",
]


class HookArgs(HookArgsBaseModel):
    """Hook arguments."""

    stack_relative_name: str
    """Name of the CloudFormation Stack as defined in the config file (no namespace)."""


def get_replicated_function_names(outputs: list[OutputTypeDef]) -> list[str]:
    """Extract replicated function names from CFN outputs.

    Parses function names from ARNs so operators can run delete commands
    without having to manually inspect the stack's output section.
    """
    function_names: list[str] = []
    for i in REPLICATED_FUNCTION_OUTPUTS:
        function_arn = next(
            (output.get("OutputValue") for output in outputs if output.get("OutputKey") == i),
            None,
        )
        if function_arn:
            function_names.append(function_arn.split(":")[-1])
    return function_names


def warn(context: CfnginContext, *_args: Any, **kwargs: Any) -> bool:
    """Notify the user of Lambda functions to delete.

    Arguments parsed by :class:`~runway.cfngin.hooks.staticsite.cleanup.HookArgs`.

    This hook runs before stack destruction to give operators actionable cleanup
    commands, because AWS does not surface orphaned Lambda@Edge replicas in any
    standard console view.

    Args:
        context: The context instance.
        **kwargs: Arbitrary keyword arguments.

    """
    args = HookArgs.model_validate(kwargs)
    cfn_client = context.get_session().client("cloudformation")
    try:
        describe_response = cfn_client.describe_stacks(
            StackName=context.namespace + context.namespace_delimiter + args.stack_relative_name
        )
        stack = next(
            x
            for x in describe_response.get("Stacks", [])
            if (x.get("StackStatus") and x.get("StackStatus") not in STACK_STATUSES_TO_IGNORE)
        )
        functions = get_replicated_function_names(stack.get("Outputs", []))
        if functions:
            cmd = f"aws lambda delete-function --function-name $x --region {context.env.aws_region}"
            LOGGER.warning(
                "About to delete the Static Site stack that contains "
                "replicated Lambda functions. These functions cannot "
                "be deleted until AWS automatically deletes their "
                "replicas. After some time has passed (a day is "
                "typically sufficient), they can be manually deleted. "
                "E.g.:"
            )
            LOGGER.warning("On macOS/Linux:")
            LOGGER.warning("for x in %s; do %s; done", (" ").join(functions), cmd)
            LOGGER.warning("On Windows:")
            LOGGER.warning('Foreach ($x in "%s") { %s }', ('","').join(functions), cmd)
    except Exception:  # noqa: S110, BLE001
        # There's no harm in continuing on in the event of an error
        # Orphaned functions have no cost
        pass
    return True
