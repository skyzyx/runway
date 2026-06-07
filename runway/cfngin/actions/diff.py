"""CFNgin diff action.

This module exists to provide a non-destructive preview of what a deploy would
change, allowing operators to review CloudFormation changesets before committing
to a real deployment.
"""

from __future__ import annotations

import logging
import sys
from operator import attrgetter
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generic,
    TypeVar,
    cast,
)

from botocore.exceptions import ClientError

from ...core.providers.aws.s3 import Bucket
from .. import exceptions
from ..status import (
    COMPLETE,
    INTERRUPTED,
    DoesNotExistInCloudFormation,
    NotSubmittedStatus,
    NotUpdatedStatus,
    SkippedStatus,
)
from . import deploy
from .base import build_walker

if TYPE_CHECKING:
    from ..._logging import RunwayLogger
    from ..stack import Stack
    from ..status import Status

_NV = TypeVar("_NV")
_OV = TypeVar("_OV")

LOGGER = cast("RunwayLogger", logging.getLogger(__name__))


class DictValue(Generic[_OV, _NV]):
    """Used to create a diff of two dictionaries.

    This class encapsulates the comparison logic for a single key-value pair so
    that diff formatting and status classification are co-located, enabling
    unified-diff-style output for parameter changes.
    """

    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"
    UNMODIFIED = "UNMODIFIED"

    formatter = "%s%s = %s"

    def __init__(self, key: str, old_value: _OV, new_value: _NV) -> None:
        """Instantiate class."""
        self.key = key
        self.old_value = old_value
        self.new_value = new_value

    def __eq__(self, other: object) -> bool:
        """Compare if self is equal to another object."""
        return self.__dict__ == other.__dict__

    def changes(self) -> list[str]:
        """Return changes to represent the diff between old and new value.

        Produces unified-diff-style output (prefixed +/-) so operators can
        quickly scan parameter changes in the same format they expect from
        version control tools.

        Returns:
            Representation of the change (if any) between old and new value.

        """
        output: list[str] = []
        if self.status() is self.UNMODIFIED:
            output = [self.formatter % (" ", self.key, self.old_value)]
        elif self.status() is self.ADDED:
            output.append(self.formatter % ("+", self.key, self.new_value))
        elif self.status() is self.REMOVED:
            output.append(self.formatter % ("-", self.key, self.old_value))
        elif self.status() is self.MODIFIED:
            output.append(self.formatter % ("-", self.key, self.old_value))
            output.append(self.formatter % ("+", self.key, self.new_value))
        return output

    def status(self) -> str:
        """Status of changes between the old value and new value."""
        if self.old_value == self.new_value:
            return self.UNMODIFIED
        if self.old_value is None:
            return self.ADDED
        if self.new_value is None:
            return self.REMOVED
        return self.MODIFIED


def diff_dictionaries(
    old_dict: dict[str, _OV], new_dict: dict[str, _NV]
) -> tuple[int, list[DictValue[_OV, _NV]]]:
    """Calculate the diff two single dimension dictionaries.

    This serves as the core comparison engine for stack parameters, using set
    operations to efficiently partition keys into added/removed/common buckets
    without requiring pre-sorted inputs.

    Args:
        old_dict: Old dictionary.
        new_dict: New dictionary.

    Returns:
        Number of changed records and the :class:`DictValue` object containing
        the changes.

    """
    old_set = set(old_dict)
    new_set = set(new_dict)

    added_set = new_set - old_set
    removed_set = old_set - new_set
    common_set = old_set & new_set

    changes = 0
    output: list[DictValue[Any, Any]] = []
    for key in added_set:
        changes += 1
        output.append(DictValue(key, None, new_dict[key]))

    for key in removed_set:
        changes += 1
        output.append(DictValue(key, old_dict[key], None))

    for key in common_set:
        output.append(DictValue(key, old_dict[key], new_dict[key]))
        if str(old_dict[key]) != str(new_dict[key]):
            changes += 1

    output.sort(key=attrgetter("key"))
    return changes, output


def format_params_diff(parameter_diff: list[DictValue[Any, Any]]) -> str:
    """Handle the formatting of differences in parameters.

    Presents parameter changes in a unified-diff header format so the output
    is visually consistent with what developers expect from diff tools.

    Args:
        parameter_diff: A list of :class:`DictValue` detailing the differences
            between two dicts returned by :func:`diff_dictionaries`.

    Returns:
        A formatted string that represents a parameter diff

    """
    return (
        "--- Old Parameters\n"
        "+++ New Parameters\n"
        "******************\n"
        + "\n".join(line for v in parameter_diff for line in v.changes())
        + "\n"
    )


def diff_parameters(
    old_params: dict[str, _OV], new_params: dict[str, _NV]
) -> list[DictValue[_OV, _NV]]:
    """Compare the old vs. new parameters and returns a "diff".

    Returns an empty list when there are no changes so callers can use a
    simple truthiness check to decide whether to display parameter output.

    If there are no changes, we return an empty list.

    Args:
        old_params: old parameters
        new_params: new parameters

    Returns:
        A list of differences.

    """
    changes, diff = diff_dictionaries(old_params, new_params)
    if changes == 0:
        return []
    return diff


class Action(deploy.Action):
    """Responsible for diffing CloudFormation stacks in AWS and locally.

    Generates the deploy plan based on stack dependencies (these dependencies
    are determined automatically based on references to output values from
    other stacks).

    The plan is then used to create a changeset for a stack using a
    generated template based on the current config.

    Inherits from deploy.Action because the diff workflow mirrors the deploy
    workflow (resolve blueprints, build parameters, submit to CloudFormation)
    but stops at changeset creation rather than executing the changeset.
    """

    DESCRIPTION = "Diff stacks"
    NAME = "diff"

    @property
    def _stack_action(self) -> Callable[..., Status]:
        """Run against a step."""
        return self._diff_stack

    def _diff_stack(self, stack: Stack, **_: Any) -> Status:  # noqa: C901
        """Handle diffing a stack in CloudFormation vs our config.

        Reuses the deploy submission pipeline but requests a changeset preview
        instead of executing, so operators see exactly what would change without
        any risk of modifying live infrastructure.
        """
        if self.cancel.wait(0):
            return INTERRUPTED

        if not deploy.should_submit(stack):
            return NotSubmittedStatus()

        provider = self.build_provider()

        if not deploy.should_update(stack):
            stack.set_outputs(provider.get_outputs(stack.fqn))
            return NotUpdatedStatus()

        tags = deploy.build_stack_tags(stack)

        try:
            provider_stack = provider.get_stack(stack.fqn)
        except exceptions.StackDoesNotExist:
            provider_stack = None

        try:
            stack.resolve(self.context, provider)
            parameters = self.build_parameters(stack, provider_stack)
            outputs = provider.get_stack_changes(
                stack,
                self._template(stack.blueprint),
                parameters,
                tags,
                retain_changeset=self.context.create_changeset,
            )
            # Retain the changeset ID so CI/CD pipelines can later execute
            # the exact changeset that was reviewed, avoiding drift between
            # diff and deploy.
            if self.context.create_changeset and "changeset_id" in outputs:
                self.context.changeset_results[stack.fqn] = outputs["changeset_id"]
            stack.set_outputs(outputs)
        except exceptions.StackDidNotChange:
            LOGGER.info("%s:no changes", stack.fqn)
            stack.set_outputs(provider.get_outputs(stack.fqn))
        except exceptions.StackDoesNotExist:
            if self.context.persistent_graph:
                return SkippedStatus("persistent graph: stack does not exist, will be removed")
            return DoesNotExistInCloudFormation()
        except AttributeError as err:
            # A stack scheduled for destruction in the persistent graph may
            # lack a blueprint class; catch that specific error to skip
            # gracefully rather than crashing the entire diff run.
            if self.context.persistent_graph and "defined class or template path" in str(err):
                return SkippedStatus("persistent graph: will be destroyed")
            raise
        except ClientError as err:
            # CloudFormation has a hard limit on inline template size;
            # detect this specific validation error and skip gracefully
            # so the rest of the diff run can continue.
            if (
                err.response["Error"]["Code"] == "ValidationError"
                and "length less than or equal to" in err.response["Error"]["Message"]
            ):
                LOGGER.error(
                    "%s:template is too large to provide directly to the API; S3 must be used",
                    stack.name,
                )
                return SkippedStatus("cfngin_bucket: existing bucket required")
            raise
        return COMPLETE

    def run(
        self,
        *,
        concurrency: int = 0,
        dump: bool | str = False,  # noqa: ARG002
        force: bool = False,  # noqa: ARG002
        outline: bool = False,  # noqa: ARG002
        tail: bool = False,  # noqa: ARG002
        upload_disabled: bool = False,  # noqa: ARG002
        **_kwargs: Any,
    ) -> None:
        """Kicks off the diffing of the stacks in the stack_definitions.

        Generates the plan without requiring an unlocked persistent graph
        because diff is a read-only operation that should never be blocked by
        another concurrent action holding the lock.
        """
        plan = self._generate_plan(require_unlocked=False, include_persistent_graph=True)
        plan.outline(logging.DEBUG)
        if plan.keys():
            LOGGER.info("diffing stacks: %s", ", ".join(plan.keys()))
        else:
            LOGGER.warning("no stacks detected (error in config?)")
        walker = build_walker(concurrency)
        plan.execute(walker)

    def pre_run(
        self,
        *,
        dump: bool | str = False,  # noqa: ARG002
        outline: bool = False,  # noqa: ARG002
        **_kwargs: Any,
    ) -> None:
        """Any steps that need to be taken prior to running the action.

        Handle CFNgin bucket access denied & not existing.

        Validates bucket access up front so the diff can proceed without a
        bucket (templates are submitted inline) rather than failing midway
        through the plan execution.
        """
        if not self.bucket_name:
            return
        bucket = Bucket(self.context, self.bucket_name, self.bucket_region)
        if bucket.forbidden:
            LOGGER.error("access denied for CFNgin bucket: %s", bucket.name)
            sys.exit(1)
        if bucket.not_found:
            LOGGER.warning(
                'cfngin_bucket "%s" does not exist and will be creating during the next deploy',
                bucket.name,
            )
            LOGGER.verbose("proceeding without a cfngin_bucket...")
            self.bucket_name = None

    def post_run(self, *, dump: bool | str = False, outline: bool = False, **__kwargs: Any) -> None:
        """Do nothing."""
