"""Purge all images from an ECR repository.

CloudFormation cannot delete an ECR repository that contains images, so this
hook removes all images first to unblock stack teardown.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ....utils import BaseModel

if TYPE_CHECKING:
    from mypy_boto3_ecr.client import ECRClient
    from mypy_boto3_ecr.type_defs import ImageIdentifierTypeDef

    from ....context import CfnginContext

# Strip the leading underscore from the module path so log messages appear
# under the public package name rather than the private module name.
LOGGER = logging.getLogger(__name__.replace("._", "."))


class HookArgs(BaseModel):
    """Hook arguments for ``purge_repository``.

    Validates and normalizes user-supplied hook configuration before the
    purge operation begins.
    """

    repository_name: str
    """Name of the repository to purge."""


def delete_ecr_images(
    client: ECRClient,
    image_ids: list[ImageIdentifierTypeDef],
    repository_name: str,
) -> None:
    """Delete images from an ECR repository.

    Separated from the listing step so each operation can be retried or
    tested independently.
    """
    response = client.batch_delete_image(repositoryName=repository_name, imageIds=image_ids)
    if response.get("failures"):
        for msg in response["failures"]:
            LOGGER.info(
                "failed to delete image %s: (%s) %s",
                msg.get("imageId", {}).get("imageDigest") or msg.get("imageId", {}).get("imageTag"),
                msg.get("failureCode"),
                msg.get("failureReason"),
            )
        raise ValueError("failures present in response")


def list_ecr_images(client: ECRClient, repository_name: str) -> list[ImageIdentifierTypeDef]:
    """List all images in an ECR repository.

    Paginates through all images and deduplicates by digest because the
    batch_delete_image API requires digest-based identifiers.
    """
    image_ids: list[ImageIdentifierTypeDef] = []
    try:
        response = client.list_images(repositoryName=repository_name, filter={"tagStatus": "ANY"})
        image_ids.extend(response["imageIds"])
        while "nextToken" in response:
            response = client.list_images(
                filter={"tagStatus": "ANY"},
                nextToken=response["nextToken"],
                repositoryName=repository_name,
            )
            image_ids.extend(response["imageIds"])
        # Deduplicate by digest because the same image can appear multiple
        # times with different tags; batch_delete_image only needs the digest.
        return [
            {"imageDigest": digest}
            for digest in {image.get("imageDigest") for image in image_ids}
            if digest
        ]
    except client.exceptions.RepositoryNotFoundException:
        LOGGER.info("repository %s does not exist", repository_name)
        return []


def purge_repository(context: CfnginContext, *_args: Any, **kwargs: Any) -> dict[str, str]:
    """Purge all images from an ECR repository.

    This hook is typically run as a pre_destroy action so that CloudFormation
    can successfully delete the now-empty repository resource.

    Args:
        context: CFNgin context object.
        **kwargs: Arbitrary keyword arguments.

    """
    args = HookArgs.model_validate(kwargs)
    client = context.get_session().client("ecr")
    image_ids = list_ecr_images(client, repository_name=args.repository_name)
    if not image_ids:
        LOGGER.info("no images found in repository %s", args.repository_name)
        return {"status": "skipped"}
    delete_ecr_images(client, image_ids=image_ids, repository_name=args.repository_name)
    LOGGER.info("purged all images from repository")
    return {"status": "success"}
