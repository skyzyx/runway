"""Provider base class.

This module defines the abstract interface that all CFNgin providers must
implement, decoupling action logic from any specific cloud API so that the
system can be tested with stub providers that make no real API calls.
"""

from __future__ import annotations

from typing import Any


def not_implemented(method: str) -> None:
    """Wrap NotImplimentedError with a formatted message.

    Centralizes the error message format so that all abstract methods
    produce consistent, descriptive errors identifying which provider
    capability is missing.
    """
    raise NotImplementedError(f"Provider does not support '{method}' method.")


class BaseProviderBuilder:
    """ProviderBuilder base class.

    This exists so that providers can be constructed lazily with
    region-specific configuration, supporting multi-region deployments
    where each region needs its own provider instance.
    """

    def build(self, region: str | None = None) -> Any:  # noqa: ARG002
        """Abstract method."""
        not_implemented("build")


class BaseProvider:
    """Provider base class.

    Defines the minimal contract that CFNgin actions depend on, allowing
    the AWS default provider to be swapped with stubs during testing
    without changing the action implementations.
    """

    def get_stack(self, stack_name: str, *_args: Any, **_kwargs: Any) -> Any:  # noqa: ARG002
        """Abstract method."""
        not_implemented("get_stack")

    def get_outputs(self, stack_name: str, *_args: Any, **_kwargs: Any) -> Any:  # noqa: ARG002
        """Abstract method."""
        not_implemented("get_outputs")

    def get_output(self, stack: str, output: str) -> str:
        """Abstract method."""
        return self.get_outputs(stack)[output]


class Template:
    """CloudFormation stack template, which could be optionally uploaded to s3.

    Presence of the url attribute indicates that the template was uploaded to
    S3, and the uploaded template should be used for
    ``CreateStack``/``UpdateStack`` calls.

    This abstraction exists because CloudFormation imposes a size limit on
    inline template bodies; large templates must be uploaded to S3 first,
    and callers need a uniform way to reference templates regardless of
    which path was taken.
    """

    def __init__(self, url: str | None = None, body: str | None = None) -> None:
        """Instantiate class."""
        self.url = url
        self.body = body
