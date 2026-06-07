"""Constant values.

Centralizes magic strings used across the awslambda hook subsystem so that
Docker image naming conventions can be changed in one place.
"""

# AWS SAM build images provide pre-configured Lambda-compatible build
# environments, avoiding the need to maintain custom Dockerfiles for each
# supported runtime.
AWS_SAM_BUILD_IMAGE_PREFIX = "public.ecr.aws/sam/build-"
"""Prefix for build image registries."""

# A consistent image name prevents orphaned images from accumulating when
# users rebuild without explicitly naming their images.
DEFAULT_IMAGE_NAME = "runway.cfngin.hooks.awslambda"
"""Default name to apply to an image when building from a Dockerfile."""

DEFAULT_IMAGE_TAG = "latest"
"""Default tag to apply to an image when building from a Dockerfile."""
