"""CFNgin info action.

This module provides a read-only introspection command so operators can query
current stack outputs without needing to open the AWS console or use the CLI
directly.
"""

import logging
from typing import Any

from .. import exceptions
from .base import BaseAction

LOGGER = logging.getLogger(__name__)


class Action(BaseAction):
    """Get information on CloudFormation stacks.

    Displays the outputs for the set of CloudFormation stacks.

    Exists as a lightweight diagnostic action that queries live stack state
    without executing any plan, making it safe to run at any time regardless
    of lock state or ongoing deployments.
    """

    NAME = "info"

    @property
    def _stack_action(self) -> Any:
        """Run against a step."""
        return None

    def run(self, *_args: Any, **_kwargs: Any) -> None:
        """Get information on CloudFormation stacks.

        Iterates all configured stacks rather than using the DAG-based plan
        because info only reads outputs and does not need dependency ordering.
        """
        LOGGER.info("outputs for stacks: %s", self.context.get_fqn())
        if not self.context.stacks:
            LOGGER.warning("no stacks detected (error in config?)")
        for stack in self.context.stacks:
            provider = self.build_provider()

            try:
                provider_stack = provider.get_stack(stack.fqn)
            except exceptions.StackDoesNotExist:
                LOGGER.info("%s:stack does not exist", stack.fqn)
                continue

            LOGGER.info("%s:", stack.fqn)
            if "Outputs" in provider_stack:
                for output in provider_stack["Outputs"]:
                    LOGGER.info("\t%s: %s", output.get("OutputKey"), output.get("OutputValue"))
