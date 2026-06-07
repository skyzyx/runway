"""Hooks for AWS Lambda.

This package exists as a self-contained subsystem for building and uploading
Lambda deployment packages during cfngin pre_deploy, decoupling packaging
concerns from the CloudFormation stack definitions.
"""

# Eagerly import all submodules so that downstream code can access them via
# the package namespace without knowing the internal file layout.
from . import (
    base_classes,
    constants,
    deployment_package,
    docker,
    exceptions,
    models,
    python_requirements,
    source_code,
    type_defs,
)
from ._python_hooks import PythonFunction, PythonLayer

__all__ = [
    "PythonFunction",
    "PythonLayer",
    "base_classes",
    "constants",
    "deployment_package",
    "docker",
    "exceptions",
    "models",
    "python_requirements",
    "source_code",
    "type_defs",
]
