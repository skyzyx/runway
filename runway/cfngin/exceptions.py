"""CFNgin exceptions.

This module defines a hierarchy of CFNgin-specific exceptions that provide
structured error context (stack names, changeset IDs, configuration paths)
so callers can programmatically react to failures rather than parsing
generic error strings.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..exceptions import RunwayError

if TYPE_CHECKING:
    from ..type_defs import AnyPath
    from ..variables import Variable
    from .plan import Step


class CfnginError(RunwayError):
    """Base class for custom exceptions raised by Runway.

    All CFNgin exceptions inherit from this class so that callers can catch
    the entire family with a single except clause when needed.
    """

    message: str


class CancelExecution(CfnginError):
    """Raised when we want to cancel executing the plan.

    Provides a clean abort path (e.g. from a pre-deploy hook) that the plan
    executor can distinguish from an unexpected failure.
    """

    message: str = "Plan canceled"


class CfnginBucketAccessDenied(CfnginError):
    """Access denied to CFNgin bucket.

    This can occur when the bucket exists in another AWS account and/or the
    credentials being used do not have adequate permissions to access the bucket.

    Raised early to give operators a clear signal that IAM permissions need
    adjustment, rather than failing deep in a template upload operation.
    """

    bucket_name: str
    message: str

    def __init__(self, bucket_name: str) -> None:
        """Instantiate class.

        Args:
            bucket_name: Name of the CFNgin bucket.

        """
        self.bucket_name = bucket_name
        self.message = f"access denied for cfngin_bucket {bucket_name}"
        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.bucket_name,)


class CfnginBucketNotFound(CfnginError):
    """CFNgin bucket specified or default bucket being used but it does not exist.

    This can occur when using a custom stack to deploy the CFNgin bucket but the
    custom stack does not create bucket that is expected.

    Raised before template upload so the operator knows the bucket prerequisite
    is missing, rather than receiving a cryptic S3 NoSuchBucket error.
    """

    bucket_name: str
    message: str

    def __init__(self, bucket_name: str) -> None:
        """Instantiate class.

        Args:
            bucket_name: Name of the CFNgin bucket.

        """
        self.bucket_name = bucket_name
        self.message = f"cfngin_bucket does not exist {bucket_name}"
        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.bucket_name,)


class CfnginBucketRequired(CfnginError):
    """CFNgin bucket is required to use a feature but it not provided/disabled.

    Some features (e.g. persistent graph, large template upload) depend on
    the CFNgin S3 bucket. This exception surfaces the misconfiguration at
    plan-build time with a clear reason rather than at execution time.
    """

    config_path: Path | None
    reason: str | None
    message: str

    def __init__(self, config_path: AnyPath | None = None, reason: str | None = None) -> None:
        """Instantiate class.

        Args:
            config_path: Path to the CFNgin config file.
            reason: Reason why CFNgin bucket is needed.

        """
        self.message = "cfngin_bucket is required"
        self.reason = reason
        if reason:
            self.message += f"; {reason}"
        if isinstance(config_path, str):
            config_path = Path(config_path)
        if config_path:
            self.message += f" ({config_path})"
        self.config_path = config_path
        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.config_path, self.reason)


class CfnginOnlyLookupError(CfnginError):
    """Attempted to use a CFNgin lookup outside of CFNgin.

    Some lookups (e.g. hook_data, rxref) depend on CFNgin-specific context
    objects that do not exist in the broader Runway execution environment.
    """

    lookup_name: str

    def __init__(self, lookup_name: str) -> None:
        """Instantiate class."""
        self.lookup_name = lookup_name
        self.message = f"attempted to use CFNgin only lookup {lookup_name} outside of CFNgin"
        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.lookup_name,)


class ChangesetDidNotStabilize(CfnginError):
    """Raised when the applying a changeset fails.

    CloudFormation changesets can stall in intermediate states; this exception
    surfaces the specific changeset ID so operators can inspect it in the
    console for root-cause diagnosis.
    """

    message: str
    change_set_id: str

    def __init__(self, change_set_id: str) -> None:
        """Instantiate class.

        Args:
            change_set_id: The changeset that failed.

        """
        self.change_set_id = change_set_id
        self.message = f"Changeset '{change_set_id}' did not reach a completed state."
        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.change_set_id,)


class GraphError(CfnginError):
    """Raised when the graph is invalid (e.g. acyclic dependencies).

    Catches DAG construction errors early (typically circular dependencies)
    and surfaces both the offending stack and dependency so operators can
    fix the configuration without debugging the graph traversal.
    """

    message: str

    def __init__(
        self,
        exception: Exception,
        stack: str,
        dependency: str,
    ) -> None:
        """Instantiate class.

        Args:
            exception: The exception that was raised by the invalid
                graph.
            stack: Name of the stack causing the error.
            dependency: Name of the dependency causing the error.

        """
        self.stack = stack
        self.dependency = dependency
        self.exception = exception
        self.message = (
            f"Error detected when adding '{dependency}' as a dependency of '{stack}': {exception}"
        )
        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.exception, self.stack, self.dependency)


class ImproperlyConfigured(CfnginError):
    """Raised when a component is improperly configured.

    Wraps instantiation failures for dynamically-loaded classes (hooks,
    lookups, blueprints) so the user sees which class failed and why,
    rather than a raw import or constructor traceback.
    """

    kls: Any
    error: Exception
    message: str

    def __init__(self, kls: Any, error: Exception, *args: Any, **kwargs: Any) -> None:
        """Instantiate class.

        Args:
            kls: The class that was improperly configured.
            error: The exception that was raised when trying to use cls.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        self.kls = kls
        self.error = error
        self.message = f'Class "{kls}" is improperly configured: {error}'
        super().__init__(*args, **kwargs)

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.kls, self.error)


class InvalidConfig(CfnginError):
    """Provided config file is invalid.

    Aggregates all validation errors into a single exception so operators
    see the full list of problems in one pass rather than fixing them
    one at a time.
    """

    errors: str | list[Exception | str]
    message: str

    def __init__(self, errors: str | list[Exception | str]) -> None:
        """Instantiate class.

        Args:
            errors: Errors or error messages that are raised to identify that a
                config is invalid.

        """
        self.errors = errors
        if isinstance(errors, list):
            self.message = "\n".join(str(e) for e in errors)
        else:
            self.message = errors
        super().__init__(errors)

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.errors,)


class InvalidDockerizePipConfiguration(CfnginError):
    """Raised when the provided configuration for dockerized pip is invalid.

    Dockerized pip has specific requirements (image name, volume mounts) that
    differ from standard pip usage; this exception clarifies what went wrong.
    """

    message: str

    def __init__(self, msg: str) -> None:
        """Instantiate class.

        Args:
            msg: The reason for the error being raised.

        """
        self.message = msg
        super().__init__()


class InvalidUserdataPlaceholder(CfnginError):
    """Raised when a placeholder name in raw_user_data is not valid.

    E.g ``${100}`` would raise this.

    Userdata placeholders must be valid Python identifiers; numeric or
    otherwise invalid names cause string.Template to fail at render time.
    """

    blueprint_name: str
    exception_message: str
    message: str

    def __init__(
        self,
        blueprint_name: str,
        exception_message: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Instantiate class.

        Args:
            blueprint_name: Name of the blueprint with invalid userdata placeholder.
            exception_message: Message from the exception that was raised while
                parsing the userdata.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        self.blueprint_name = blueprint_name
        self.exception_message = exception_message
        self.message = (
            f'{exception_message}. Could not parse userdata in blueprint {blueprint_name}". '
            "Make sure to escape all $ symbols with a $$."
        )
        super().__init__(*args, **kwargs)

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.blueprint_name, self.exception_message)


class MissingEnvironment(CfnginError):
    """Raised when an environment lookup is used but the key doesn't exist.

    Catches typos and missing environment variables at config-resolution time
    rather than letting them propagate as empty values into CloudFormation
    parameters.
    """

    message: str
    key: str

    def __init__(self, key: str, *args: Any, **kwargs: Any) -> None:
        """Instantiate class.

        Args:
            key: The key that was used but doesn't exist in the environment.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        self.key = key
        self.message = f"Environment missing key {key}."
        super().__init__(*args, **kwargs)

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.key,)


class MissingParameterException(CfnginError):
    """Raised if a required parameter with no default is missing.

    Validates that all required CloudFormation parameters have values before
    the API call, providing a clearer error than the CFN service response.
    """

    message: str
    parameters: list[str]

    def __init__(self, parameters: list[str], *args: Any, **kwargs: Any) -> None:
        """Instantiate class.

        Args:
            parameters: A list of the parameters that are missing.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        self.parameters = parameters
        self.message = f"Missing required cloudformation parameters: {', '.join(parameters)}"
        super().__init__(*args, **kwargs)

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.parameters,)


class MissingVariable(CfnginError):
    """Raised when a variable with no default is not provided a value.

    Ensures blueprint authors receive immediate feedback about missing
    variable bindings at resolution time rather than hitting NoneType
    errors during template rendering.
    """

    blueprint_name: str
    variable_name: str
    message: str

    def __init__(
        self,
        blueprint_name: str,
        variable_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Instantiate class.

        Args:
            blueprint_name: Name of the blueprint.
            variable_name: Name of the variable missing a value.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        self.blueprint_name = blueprint_name
        self.variable_name = variable_name
        self.message = f'Variable "{variable_name}" in blueprint "{blueprint_name}" is missing'
        super().__init__(*args, **kwargs)

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.blueprint_name, self.variable_name)


class PipError(CfnginError):
    """Raised when pip returns a non-zero exit code.

    Wraps the subprocess failure into a CFNgin exception so the Lambda
    packaging hook can report the error through the standard hook failure
    path rather than an unhandled CalledProcessError.
    """

    message: str

    def __init__(self) -> None:
        """Instantiate class."""
        self.message = (
            "A non-zero exit code was returned when invoking "
            "pip. More information can be found in the error above."
        )
        super().__init__()


class PersistentGraphCannotLock(CfnginError):
    """Raised when the persistent graph in S3 cannot be locked.

    Locking prevents concurrent CFNgin runs from modifying the graph
    simultaneously, which could lead to orphaned stacks or lost state.
    """

    message: str
    reason: str

    def __init__(self, reason: str) -> None:
        """Instantiate class."""
        self.reason = reason
        self.message = f"Could not lock persistent graph; {reason}"
        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.reason,)


class PersistentGraphCannotUnlock(CfnginError):
    """Raised when the persistent graph in S3 cannot be unlocked.

    An unlock failure leaves the graph in a locked state, blocking subsequent
    runs until manually resolved; this exception makes that situation explicit.
    """

    message: str
    reason: str | Exception

    def __init__(self, reason: Exception | str) -> None:
        """Instantiate class."""
        self.reason = reason
        self.message = f"Could not unlock persistent graph; {reason}"
        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.reason,)


class PersistentGraphLocked(CfnginError):
    """Raised when the persistent graph in S3 is lock.

    The action being executed requires it to be unlocked before attempted.

    Prevents accidental concurrent modifications; the operator must explicitly
    unlock the graph or wait for the other run to complete.
    """

    reason: str | None
    message: str

    def __init__(self, message: str | None = None, reason: str | None = None) -> None:
        """Instantiate class."""
        self.reason = reason
        if message:
            self.message = message
        else:
            reason = reason or "This action requires the graph to be unlocked to be executed."
            self.message = f"Persistent graph is locked. {reason}"
        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.message, self.reason)


class PersistentGraphLockCodeMismatch(CfnginError):
    """Raised when the provided persistent graph lock code does not match.

    The code used to unlock the persistent graph must match the s3 object lock
    code.

    This verification prevents one CFNgin run from accidentally releasing
    a lock held by a different concurrent run.
    """

    provided_code: str
    s3_code: str | None
    message: str

    def __init__(self, provided_code: str, s3_code: str | None) -> None:
        """Instantiate class."""
        self.provided_code = provided_code
        self.s3_code = s3_code
        self.message = (
            f"The provided lock code '{provided_code}' does not match the S3 "
            f"object lock code '{s3_code}'"
        )
        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.provided_code, self.s3_code)


class PersistentGraphUnlocked(CfnginError):
    """Raised when the persistent graph in S3 is unlock.

    The action being executed requires it to be locked before attempted.

    Some operations (e.g. destroy with graph cleanup) require exclusive
    access; this exception prevents running them on an unprotected graph.
    """

    reason: str | None
    message: str

    def __init__(self, message: str | None = None, reason: str | None = None) -> None:
        """Instantiate class."""
        self.reason = reason
        if message:
            self.message = message
        else:
            reason = reason or "This action requires the graph to be locked to be executed."
            self.message = f"Persistent graph is unlocked. {reason}"
        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.message, self.reason)


class PlanFailed(CfnginError):
    """Raised if any step of a plan fails.

    Aggregates all failed steps into a single exception so the top-level
    executor can report every failure at once rather than stopping at the
    first one.
    """

    message: str
    failed_steps: list[Step]

    def __init__(self, failed_steps: list[Step], *args: Any, **kwargs: Any) -> None:
        """Instantiate class.

        Args:
            failed_steps: The steps that failed.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        self.failed_steps = failed_steps
        step_names = ", ".join(step.name for step in failed_steps)
        self.message = f"The following steps failed: {step_names}"

        super().__init__(*args, **kwargs)

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.failed_steps,)


class StackDidNotChange(CfnginError):
    """Raised when there are no changes to be made by the provider.

    Used as a control-flow signal so the action layer can distinguish
    "no-op" from "error" and set the appropriate status (NO_CHANGE).
    """

    message: str = "Stack did not change"


class StackDoesNotExist(CfnginError):
    """Raised when a stack does not exist in AWS.

    Surfaces which stack is missing and whether it's an output-lookup
    failure or a dependency issue, aiding troubleshooting of cross-stack
    references.
    """

    message: str
    stack_name: str

    def __init__(self, stack_name: str, *args: Any, **kwargs: Any) -> None:
        """Instantiate class.

        Args:
            stack_name: Name of the stack that does not exist.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        self.stack_name = stack_name
        self.message = (
            f'Stack: "{stack_name}" does not exist in outputs or the lookup is '
            "not available in this CFNgin run"
        )
        super().__init__(*args, **kwargs)

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.stack_name,)


class StackUpdateBadStatus(CfnginError):
    """Raised if the state of a stack can't be handled.

    Some CloudFormation states (e.g. ROLLBACK_COMPLETE) require manual
    intervention; this exception prevents the provider from attempting an
    update that would fail with an unhelpful API error.
    """

    stack_name: str
    stack_status: str
    reason: str
    message: str

    def __init__(
        self,
        stack_name: str,
        stack_status: str,
        reason: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Instantiate class.

        Args:
            stack_name: Name of the stack.
            stack_status: The stack's status.
            reason: The reason for the current status.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        self.stack_name = stack_name
        self.stack_status = stack_status
        self.reason = reason
        self.message = (
            f'Stack: "{stack_name}" cannot be updated nor re-created from state '
            f"{stack_status}: {reason}"
        )
        super().__init__(*args, **kwargs)

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.stack_name, self.stack_status, self.reason)


class StackFailed(CfnginError):
    """Raised when a stack action fails.

    Primarily used with hooks that act on stacks.

    Provides a unified failure signal for hooks that wait on stack
    operations, carrying the status reason from CloudFormation events.
    """

    stack_name: str
    status_reason: str | None
    message: str

    def __init__(self, stack_name: str, status_reason: str | None = None) -> None:
        """Instantiate class.

        Args:
            stack_name: Name of the stack.
            status_reason: The reason for the current status.

        """
        self.stack_name = stack_name
        self.status_reason = status_reason

        self.message = f'Stack "{stack_name}" failed'
        if status_reason:
            self.message += f' with reason "{status_reason}"'
        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.stack_name, self.status_reason)


class UnableToExecuteChangeSet(CfnginError):
    """Raised if changeset execution status is not ``AVAILABLE``.

    CloudFormation may mark a changeset as UNAVAILABLE or OBSOLETE if another
    change superseded it; attempting execution in that state would silently
    fail without this guard.
    """

    stack_name: str
    change_set_id: str
    execution_status: str
    message: str

    def __init__(
        self,
        stack_name: str,
        change_set_id: str,
        execution_status: str,
    ) -> None:
        """Instantiate class.

        Args:
            stack_name: Name of the stack.
            change_set_id: The changeset that failed.
            execution_status: The value of the changeset's ``ExecutionStatus``
                attribute.

        """
        self.stack_name = stack_name
        self.change_set_id = change_set_id
        self.execution_status = execution_status

        self.message = (
            f"Changeset '{change_set_id}' on stack '{stack_name}' had bad "
            f"execution status: {execution_status}"
        )

        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.stack_name, self.change_set_id, self.execution_status)


class UnhandledChangeSetStatus(CfnginError):
    """Raised when creating a changeset failed for an unhandled reason.

    Handled failure reasons include: no changes

    Acts as a catch-all for unexpected changeset creation failures so the
    provider doesn't silently proceed when CloudFormation returns an
    unknown status.
    """

    stack_name: str
    id: str
    status: str
    status_reason: str
    message: str

    def __init__(
        self,
        stack_name: str,
        change_set_id: str,
        status: str,
        status_reason: str,
    ) -> None:
        """Instantiate class.

        Args:
            stack_name: Name of the stack.
            change_set_id: The changeset that failed.
            status: The state that could not be handled.
            status_reason: Cause of the current state.

        """
        self.stack_name = stack_name
        self.id = change_set_id
        self.status = status
        self.status_reason = status_reason
        self.message = (
            f"Changeset '{change_set_id}' on stack '{stack_name}' returned an unhandled status "
            f"'{status}: {status_reason}'."
        )

        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.stack_name, self.id, self.status, self.status_reason)


class UnresolvedBlueprintVariable(CfnginError):
    """Raised when trying to use a variable before it has been resolved.

    Lookups must be resolved before a blueprint accesses variable values;
    this guard prevents rendering templates with placeholder objects.
    """

    blueprint_name: str
    variable: Variable
    message: str = "Variable has not been resolved"

    def __init__(
        self,
        blueprint_name: str,
        variable: Variable,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Instantiate class.

        Args:
            blueprint_name: Name of the blueprint that tried to use
                the unresolved variables.
            variable: The unresolved variable.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        self.blueprint_name = blueprint_name
        self.variable = variable
        self.message = (
            f'Variable "{variable.name}" in blueprint "{blueprint_name}" hasn\'t been resolved'
        )
        super().__init__(*args, **kwargs)

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.blueprint_name, self.variable)


class UnresolvedBlueprintVariables(CfnginError):
    """Raised when trying to use variables before they has been resolved.

    Similar to UnresolvedBlueprintVariable but covers the case where the
    entire variable set was never resolved, catching blueprint logic that
    skips the resolution step entirely.
    """

    message: str
    blueprint_name: str

    def __init__(self, blueprint_name: str, *args: Any, **kwargs: Any) -> None:
        """Instantiate class.

        Args:
            blueprint_name: Name of the blueprint that tried to use the unresolved
                variables.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        self.blueprint_name = blueprint_name
        self.message = f"Blueprint: \"{blueprint_name}\" hasn't resolved it's variables"
        super().__init__(*args, **kwargs)

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.blueprint_name,)


class ValidatorError(CfnginError):
    """Used for errors raised by custom validators of blueprint variables.

    Blueprint variables can declare custom validator functions; this exception
    wraps their failures with the variable name and value context so
    operators know exactly which input violated which constraint.
    """

    variable: str
    validator: str
    value: str
    exception: Exception
    message: str

    def __init__(
        self,
        variable: str,
        validator: str,
        value: str,
        exception: Exception,
    ) -> None:
        """Instantiate class.

        Args:
            variable: The variable that failed validation.
            validator: The validator that was not passed.
            value: The value of the variable that did not pass the validator.
            exception: The exception raised by the validator.

        """
        self.variable = variable
        self.validator = validator
        self.value = value
        self.exception = exception
        self.message = (
            f"Validator '{self.validator}' failed for variable '{self.variable}' "
            f"with value '{self.value}'"
        )

        if self.exception:
            self.message += f": {self.exception.__class__.__name__}: {self.exception!s}"
        super().__init__()

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.variable, self.validator, self.value, self.exception)

    def __str__(self) -> str:
        """Return the exception's message when converting to a string."""
        return self.message


class VariableTypeRequired(CfnginError):
    """Raised when a variable defined in a blueprint is missing a type.

    Types are required so that the variable resolution system knows how
    to coerce and validate the raw config value before passing it to the
    blueprint template logic.
    """

    blueprint_name: str
    variable_name: str
    message: str

    def __init__(
        self,
        blueprint_name: str,
        variable_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Instantiate class.

        Args:
            blueprint_name: Name of the blueprint.
            variable_name: Name of the variable missing a type.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        self.blueprint_name = blueprint_name
        self.variable_name = variable_name
        self.message = (
            f'Variable "{variable_name}" in blueprint "{blueprint_name}" does not have a type'
        )
        super().__init__(*args, **kwargs)

    def __reduce__(self) -> tuple[type[Exception], tuple[Any, ...]]:
        """Support for pickling."""
        return self.__class__, (self.blueprint_name, self.variable_name)
