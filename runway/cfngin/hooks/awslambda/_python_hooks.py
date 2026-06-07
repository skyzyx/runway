"""Hook for creating an AWS Lambda Function using Python runtime.

Specializes the base AwsLambdaHook for Python projects, wiring up pip-based
dependency installation and Python-specific project detection so that users
only need to point at a source directory with a requirements file.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from ....compat import cached_property
from .base_classes import AwsLambdaHook
from .models.args import PythonHookArgs
from .python_requirements import PythonDeploymentPackage, PythonProject

if TYPE_CHECKING:
    from ....context import CfnginContext
    from .base_classes import DeploymentPackage

# Strip the leading underscore from the logger name so log output uses the
# public module path (awslambda.python_hooks) rather than the private file name.
LOGGER = logging.getLogger(__name__.replace("._", "."))


class PythonFunction(AwsLambdaHook[PythonProject]):
    """Hook for creating an AWS Lambda Function using Python runtime.

    Orchestrates the full build-and-upload lifecycle for a Python Lambda
    Function: resolve dependencies via pip, package source and deps into a
    zip, upload to S3, and surface metadata for the CloudFormation template.
    """

    BUILD_LAYER: ClassVar[bool] = False
    """Flag to denote that this hook creates a Lambda Function deployment package."""

    args: PythonHookArgs
    """Parsed hook arguments."""

    def __init__(self, context: CfnginContext, **kwargs: Any) -> None:
        """Instantiate class."""
        super().__init__(context)
        self.args = PythonHookArgs.model_validate(kwargs)

    @cached_property
    def deployment_package(self) -> DeploymentPackage[PythonProject]:
        """AWS Lambda deployment package."""
        return PythonDeploymentPackage.init(
            self.project, "layer" if self.BUILD_LAYER else "function"
        )

    @cached_property
    def project(self) -> PythonProject:
        """Project being deployed as an AWS Lambda Function."""
        return PythonProject(self.args, self.ctx)

    def cleanup(self) -> None:
        """Cleanup after execution."""
        self.project.cleanup()

    def cleanup_on_error(self) -> None:
        """Cleanup after an error has occurred."""
        self.deployment_package.delete()
        self.project.cleanup_on_error()

    def pre_deploy(self) -> Any:
        """Run during the **pre_deploy** stage.

        Executes in pre_deploy so the deployment package is ready in S3
        before CloudFormation attempts to create or update the Function
        resource.
        """
        try:
            self.deployment_package.upload()
            return self.build_response("deploy").model_dump(by_alias=True)
        except BaseException:
            self.cleanup_on_error()
            raise
        finally:
            self.cleanup()


class PythonLayer(PythonFunction):
    """Hook for creating an AWS Lambda Layer using Python runtime.

    Reuses all of PythonFunction's build logic but sets BUILD_LAYER to True,
    which causes the deployment package to use the layer-specific directory
    structure (python/ prefix) required by the Lambda Layers API.
    """

    BUILD_LAYER: ClassVar[bool] = True
    """Flag to denote that this hook creates a Lambda Layer deployment package."""
