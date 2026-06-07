"""CFNgin hook for cleaning up resources prior to CFN stack deletion.

This module exists because CloudFormation cannot delete S3 buckets that contain
objects; this hook empties the bucket first so the stack deletion can succeed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError

from ...utils import BaseModel

if TYPE_CHECKING:
    from ...context import CfnginContext

LOGGER = logging.getLogger(__name__)


class PurgeBucketHookArgs(BaseModel):
    """Hook arguments for ``purge_bucket``.

    Provides validated, typed access to the bucket name so the hook can rely
    on Pydantic validation rather than manual kwarg parsing.
    """

    bucket_name: str
    """Name of the bucket to purge."""


def purge_bucket(context: CfnginContext, *__args: Any, **kwargs: Any) -> bool:
    """Delete objects in bucket.

    Removes all object versions so CloudFormation can delete the bucket resource;
    without this, stack deletion fails with "BucketNotEmpty" errors.
    """
    args = PurgeBucketHookArgs.model_validate(kwargs)
    session = context.get_session()
    s3_resource = session.resource("s3")
    # Check if the bucket exists before attempting purge; if it was already
    # deleted (e.g., manual intervention or previous failed run), treat as
    # success to allow the stack deletion to proceed.
    try:
        s3_resource.meta.client.head_bucket(Bucket=args.bucket_name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            LOGGER.info('bucket "%s" does not exist; unable to complete purge', args.bucket_name)
            return True
        raise

    # Delete all object versions (including delete markers) to handle
    # versioned buckets; a simple object delete would only add markers.
    bucket = s3_resource.Bucket(args.bucket_name)
    bucket.object_versions.delete()
    return True
