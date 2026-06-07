"""CFNgin statuses.

This module defines numeric status codes that drive the Step state machine's
transition logic, enabling the DAG executor to poll stack operations for
completion without blocking other independent steps.
"""

from __future__ import annotations

import operator
from typing import Any, Callable


class Status:
    """CFNgin status base class.

    Numeric codes allow the plan executor to compare statuses with ordering
    operators, determining whether a step should advance, retry, or halt.

    Attributes:
        name: Name of the status.
        code: Status code.
        reason: Reason for the status.

    """

    code: int
    name: str
    reason: str | None

    def __init__(self, name: str, code: int, reason: str | None = None) -> None:
        """Instantiate class.

        Args:
            name: Name of the status.
            code: Status code.
            reason: Reason for the status.

        """
        self.name = name
        self.code = code
        self.reason = reason or getattr(self, "reason", None)

    def _comparison(self, operator_: Callable[[Any, Any], bool], other: Any) -> bool:
        """Compare self to another object.

        Centralizes comparison logic so all rich-comparison dunders delegate here,
        ensuring consistent ordering semantics based solely on numeric codes.

        Args:
            operator_: Operator for the comparison.
            other: The other object to compare to self.

        Raises:
            NotImplemented: other does not have ``code`` attribute.

        """
        if hasattr(other, "code"):
            return operator_(self.code, other.code)
        return NotImplemented

    def __eq__(self, other: object) -> bool:
        """Compare if self is equal to another object."""
        return self._comparison(operator.eq, other)

    def __ne__(self, other: object) -> bool:
        """Compare if self is not equal to another object."""
        return self._comparison(operator.ne, other)

    def __lt__(self, other: Any) -> bool:
        """Compare if self is less than another object."""
        return self._comparison(operator.lt, other)

    def __gt__(self, other: Any) -> bool:
        """Compare if self is greater than another object."""
        return self._comparison(operator.gt, other)

    def __le__(self, other: Any) -> bool:
        """Compare if self is less than or equal to another object."""
        return self._comparison(operator.le, other)

    def __ge__(self, other: Any) -> bool:
        """Compare if self is greater than equal to another object."""
        return self._comparison(operator.ge, other)


class CompleteStatus(Status):
    """Status name of 'complete' with code of '2'.

    Code 2 ranks above SUBMITTED (1) so the plan executor can detect
    that no further polling is needed for this step.
    """

    def __init__(self, reason: str | None = None) -> None:
        """Instantiate class.

        Args:
            reason: Reason for the status.

        """
        super().__init__("complete", 2, reason)


class FailedStatus(Status):
    """Status name of 'failed' with code of '4'.

    Code 4 is the highest value so that any comparison against other
    statuses immediately signals a terminal failure state.
    """

    def __init__(self, reason: str | None = None) -> None:
        """Instantiate class.

        Args:
            reason: Reason for the status.

        """
        super().__init__("failed", 4, reason)


class PendingStatus(Status):
    """Status name of 'pending' with code of '0'.

    Code 0 is the initial state, representing a step that has not yet
    been submitted to CloudFormation for execution.
    """

    def __init__(self, reason: str | None = None) -> None:
        """Instantiate class.

        Args:
            reason: Reason for the status.

        """
        super().__init__("pending", 0, reason)


class SkippedStatus(Status):
    """Status name of 'skipped' with code of '3'.

    Represents a step that will not execute, either because it was disabled
    by configuration or because no changes were detected.
    """

    def __init__(self, reason: str | None = None) -> None:
        """Instantiate class.

        Args:
            reason: Reason for the status.

        """
        super().__init__("skipped", 3, reason)


class SubmittedStatus(Status):
    """Status name of 'submitted' with code of '1'.

    Indicates the step's CloudFormation operation has been initiated and
    the plan executor should continue polling for completion.
    """

    def __init__(self, reason: str | None = None) -> None:
        """Instantiate class.

        Args:
            reason: Reason for the status.

        """
        super().__init__("submitted", 1, reason)


class DidNotChangeStatus(SkippedStatus):
    """Skipped status with a reason of 'nochange'.

    Used when CloudFormation reports no diff between the desired and
    current template, avoiding a redundant update operation.
    """

    reason = "nochange"


class DoesNotExistInCloudFormation(SkippedStatus):
    """Skipped status with a reason of 'does not exist in cloudformation'.

    Used during destroy actions when the target stack was already deleted
    or never created, so there is nothing to tear down.
    """

    reason = "does not exist in cloudformation"


class NotSubmittedStatus(SkippedStatus):
    """Skipped status with a reason of 'disabled'.

    Represents a stack that is explicitly disabled in the configuration,
    allowing selective deployment within a single plan.
    """

    reason = "disabled"


class NotUpdatedStatus(SkippedStatus):
    """Skipped status with a reason of 'locked'.

    Represents a stack that is locked against updates, protecting
    production-critical infrastructure from accidental modification.
    """

    reason = "locked"


# Module-level singleton instances allow identity comparison (``is``) in the
# plan executor, avoiding repeated object allocation during polling loops.
COMPLETE = CompleteStatus()
FAILED = FailedStatus()
INTERRUPTED = FailedStatus(reason="interrupted")
NO_CHANGE = DidNotChangeStatus()
PENDING = PendingStatus()
SKIPPED = SkippedStatus()
SUBMITTED = SubmittedStatus()
WAITING = PendingStatus(reason="waiting")
