"""AWS Elastic Container Registry (ECR) hook.

This package provides hooks for managing ECR repository lifecycle alongside
CloudFormation stacks, since CloudFormation cannot delete repositories that
still contain images.
"""

from ._purge_repository import purge_repository

__all__ = ["purge_repository"]
