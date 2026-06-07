"""Docker hook.

This package exposes Docker operations as CFNgin lifecycle hooks so that
container images can be built, authenticated, pushed, and removed as part of
a CloudFormation deployment pipeline (e.g. ECS/Fargate stacks that reference
ECR image URIs).

"""

from ._login import LoginArgs, login

__all__ = ["LoginArgs", "login"]
