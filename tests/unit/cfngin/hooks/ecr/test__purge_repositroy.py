"""Test runway.cfngin.hooks.ecr._purge_repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
import pytest
from botocore.stub import Stubber

from runway.cfngin.hooks.ecr import purge_repository
from runway.cfngin.hooks.ecr._purge_repository import delete_ecr_images, list_ecr_images

if TYPE_CHECKING:
    from mypy_boto3_ecr.type_defs import ImageIdentifierTypeDef
    from pytest_mock import MockerFixture

    from ....factories import MockCfnginContext

MODULE = "runway.cfngin.hooks.ecr._purge_repository"


def test_delete_ecr_images() -> None:
    """Test delete_ecr_images.

    Validates the happy path where all images are successfully deleted
    from the repository with no failures reported.
    """
    client = boto3.client("ecr")
    stubber = Stubber(client)
    image_ids: list[ImageIdentifierTypeDef] = [{"imageDigest": "image0"}]
    repo_name = "test-repo"

    stubber.add_response(
        "batch_delete_image",
        {"imageIds": image_ids, "failures": []},
        {"repositoryName": repo_name, "imageIds": image_ids},
    )

    with stubber:
        assert not delete_ecr_images(client, image_ids=image_ids, repository_name=repo_name)


def test_delete_ecr_images_failures() -> None:
    """Test delete_ecr_images with failures.

    Ensures partial delete failures raise ValueError so the caller
    is alerted that some images were not cleaned up.
    """
    client = boto3.client("ecr")
    stubber = Stubber(client)
    image_ids: list[ImageIdentifierTypeDef] = [{"imageDigest": "image0"}]
    repo_name = "test-repo"

    stubber.add_response(
        "batch_delete_image",
        {
            "imageIds": image_ids,
            "failures": [
                {
                    "imageId": {"imageDigest": "abc123"},
                    "failureCode": "InvalidImageDigest",
                    "failureReason": "reason",
                }
            ],
        },
        {"repositoryName": repo_name, "imageIds": image_ids},
    )

    with stubber, pytest.raises(ValueError):  # noqa: PT011
        delete_ecr_images(client, image_ids=image_ids, repository_name=repo_name)


def test_list_ecr_images() -> None:
    """Test list_ecr_images.

    Exercises pagination: two pages of results are merged, and tagged
    images without a digest are excluded since batch_delete_image
    requires imageDigest.
    """
    client = boto3.client("ecr")
    stubber = Stubber(client)
    repo_name = "test-repo"
    next_token = "abc123"

    stubber.add_response(
        "list_images",
        {
            "imageIds": [{"imageDigest": "image0"}, {"imageTag": "image1"}],
            "nextToken": next_token,
        },
        {"filter": {"tagStatus": "ANY"}, "repositoryName": repo_name},
    )
    stubber.add_response(
        "list_images",
        {"imageIds": [{"imageDigest": "image2"}]},
        {
            "filter": {"tagStatus": "ANY"},
            "nextToken": next_token,
            "repositoryName": repo_name,
        },
    )

    with stubber:
        result = list_ecr_images(client, repository_name=repo_name)
        # order in response is not maintained so testing membership rather than equality
        assert len(result) == 2
        assert {"imageDigest": "image0"} in result
        assert {"imageDigest": "image2"} in result


def test_list_ecr_images_repository_not_found() -> None:
    """Test list_ecr_images RepositoryNotFoundException.

    Ensures a missing repository returns an empty list rather than
    raising, since the desired state (no images) is already met.
    """
    client = boto3.client("ecr")
    stubber = Stubber(client)

    stubber.add_client_error("list_images", "RepositoryNotFoundException")
    with stubber:
        assert list_ecr_images(client, repository_name="test-repo") == []


def test_purge_repository(cfngin_context: MockCfnginContext, mocker: MockerFixture) -> None:
    """Test purge_repository.

    Validates the orchestration: list images then delete them, returning
    a success status dict for the hook framework.
    """
    mock_list_ecr_images = mocker.patch(
        MODULE + ".list_ecr_images", return_value=[{"imageDigest": "abc123"}]
    )
    mock_delete_ecr_images = mocker.patch(MODULE + ".delete_ecr_images")
    cfngin_context.add_stubber("ecr")
    client = cfngin_context.get_session().client("ecr")
    repo_name = "test-repo"

    assert purge_repository(cfngin_context, repository_name=repo_name) == {"status": "success"}
    mock_list_ecr_images.assert_called_once_with(client, repository_name=repo_name)
    mock_delete_ecr_images.assert_called_once_with(
        client, image_ids=mock_list_ecr_images.return_value, repository_name=repo_name
    )


def test_purge_repository_skip(cfngin_context: MockCfnginContext, mocker: MockerFixture) -> None:
    """Test purge_repository when no images exist.

    Ensures delete is not called when the repository is already empty,
    avoiding unnecessary API calls.
    """
    mock_list_ecr_images = mocker.patch(MODULE + ".list_ecr_images", return_value=[])
    mock_delete_ecr_images = mocker.patch(MODULE + ".delete_ecr_images")
    cfngin_context.add_stubber("ecr")
    client = cfngin_context.get_session().client("ecr")
    repo_name = "test-repo"

    assert purge_repository(cfngin_context, repository_name=repo_name) == {"status": "skipped"}
    mock_list_ecr_images.assert_called_once_with(client, repository_name=repo_name)
    mock_delete_ecr_images.assert_not_called()
