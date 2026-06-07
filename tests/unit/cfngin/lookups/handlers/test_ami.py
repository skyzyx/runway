"""Tests for runway.cfngin.lookups.handlers.ami.

Validates the AMI lookup handler's ability to query EC2 for images by owner,
executable users, and name regex, ensuring the correct (most recent) image
is selected from potentially many matches.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from runway.cfngin.lookups.handlers.ami import AmiLookup, ImageNotFound

if TYPE_CHECKING:
    from ....factories import MockCfnginContext

REGION = "us-east-1"


class TestAMILookup:
    """Tests for runway.cfngin.lookups.handlers.ami.AmiLookup.

    AMI lookups are critical because selecting the wrong image can deploy
    instances with outdated or incompatible operating systems. These tests
    verify filtering, regex matching, date-based ordering, and error paths.
    """

    def test_basic_lookup_single_image(self, cfngin_context: MockCfnginContext) -> None:
        """Test basic lookup single image.

        Validates the happy path where exactly one image matches the query,
        including executable_users filtering which restricts AMI visibility.
        """
        executable_users = ["123456789012", "234567890123"]
        stubber = cfngin_context.add_stubber("ec2")
        image_id = "ami-fffccc111"
        stubber.add_response(
            "describe_images",
            {
                "Images": [
                    {
                        "OwnerId": "897883143566",
                        "Architecture": "x86_64",
                        "CreationDate": "2011-02-13T01:17:44.000Z",
                        "State": "available",
                        "ImageId": image_id,
                        "Name": "Fake Image 1",
                        "VirtualizationType": "hvm",
                    }
                ]
            },
            {
                "ExecutableUsers": executable_users,
                "Filters": [],
                "Owners": ["self"],
            },
        )

        with stubber:
            assert (
                AmiLookup.handle(
                    value=f"owners:self executable_users:{','.join(executable_users)} "
                    r"name_regex:Fake\sImage\s\d",
                    context=cfngin_context,
                )
                == image_id
            )

    def test_basic_lookup_with_region(self, cfngin_context: MockCfnginContext) -> None:
        """Test basic lookup with region.

        Validates cross-region AMI resolution using the region@ prefix syntax,
        which is needed when deploying to a different region than the context's
        default.
        """
        stubber = cfngin_context.add_stubber("ec2", region="us-west-1")
        image_id = "ami-fffccc111"
        stubber.add_response(
            "describe_images",
            {
                "Images": [
                    {
                        "OwnerId": "897883143566",
                        "Architecture": "x86_64",
                        "CreationDate": "2011-02-13T01:17:44.000Z",
                        "State": "available",
                        "ImageId": image_id,
                        "Name": "Fake Image 1",
                        "VirtualizationType": "hvm",
                    }
                ]
            },
            {"Filters": [], "Owners": ["amazon"]},
        )

        with stubber:
            assert (
                AmiLookup.handle(
                    value=r"us-west-1@owners:amazon name_regex:Fake\sImage\s\d",
                    context=cfngin_context,
                )
                == image_id
            )

    def test_basic_lookup_multiple_images(self, cfngin_context: MockCfnginContext) -> None:
        """Test basic lookup multiple images.

        Verifies that when multiple images match, the most recently created one
        is returned. Also includes an ARI (without a Name field) to ensure the
        handler tolerates heterogeneous image types in the response.
        """
        stubber = cfngin_context.add_stubber("ec2")
        image_id = "ami-fffccc111"
        stubber.add_response(
            "describe_images",
            {
                "Images": [
                    {
                        "OwnerId": "897883143566",
                        "Architecture": "x86_64",
                        "CreationDate": "2011-02-13T01:17:44.000Z",
                        "State": "available",
                        "ImageId": "ami-fffccc110",
                        "Name": "Fake Image 1",
                        "VirtualizationType": "hvm",
                    },
                    {
                        "OwnerId": "897883143566",
                        "Architecture": "x86_64",
                        "CreationDate": "2011-02-14T01:17:44.000Z",
                        "State": "available",
                        "ImageId": image_id,
                        "Name": "Fake Image 2",
                        "VirtualizationType": "hvm",
                    },
                    # include an ARI in the response to ensure it can be handled
                    # (these don't include a 'Name')
                    {
                        "OwnerId": "897883143566",
                        "Architecture": "x86_64",
                        "CreationDate": "2011-06-24T20:34:25.000Z",
                        "State": "available",
                        "ImageId": "ari-e6bc478f",
                        "VirtualizationType": "paravirtual",
                    },
                ]
            },
            {"Filters": [], "Owners": ["self"]},
        )

        with stubber:
            assert (
                AmiLookup.handle(
                    value=r"owners:self name_regex:Fake\sImage\s\d",
                    context=cfngin_context,
                )
                == image_id
            )

    def test_basic_lookup_multiple_images_name_match(
        self, cfngin_context: MockCfnginContext
    ) -> None:
        """Test basic lookup multiple images name match.

        Ensures the name_regex filter correctly excludes images whose names
        don't match, even when multiple images are returned by the AWS API.
        """
        stubber = cfngin_context.add_stubber("ec2")
        image_id = "ami-fffccc111"
        stubber.add_response(
            "describe_images",
            {
                "Images": [
                    {
                        "OwnerId": "897883143566",
                        "Architecture": "x86_64",
                        "CreationDate": "2011-02-13T01:17:44.000Z",
                        "State": "available",
                        "ImageId": "ami-fffccc110",
                        "Name": "Fa---ke Image 1",
                        "VirtualizationType": "hvm",
                    },
                    {
                        "OwnerId": "897883143566",
                        "Architecture": "x86_64",
                        "CreationDate": "2011-02-14T01:17:44.000Z",
                        "State": "available",
                        "ImageId": image_id,
                        "Name": "Fake Image 2",
                        "VirtualizationType": "hvm",
                    },
                ]
            },
            {"Filters": [], "Owners": ["self"]},
        )

        with stubber:
            assert (
                AmiLookup.handle(
                    value=r"owners:self name_regex:Fake\sImage\s\d",
                    context=cfngin_context,
                )
                == image_id
            )

    def test_basic_lookup_no_matching_images(self, cfngin_context: MockCfnginContext) -> None:
        """Test basic lookup no matching images.

        Validates that ImageNotFound is raised when the EC2 API returns an
        empty result set, giving users a clear error rather than a KeyError.
        """
        stubber = cfngin_context.add_stubber("ec2")
        stubber.add_response("describe_images", {"Images": []})

        with stubber, pytest.raises(ImageNotFound):
            AmiLookup.handle(
                value=r"owners:self name_regex:Fake\sImage\s\d", context=cfngin_context
            )

    def test_basic_lookup_no_matching_images_from_name(
        self, cfngin_context: MockCfnginContext
    ) -> None:
        """Test basic lookup no matching images from name.

        Covers the case where images are returned by EC2 but none match the
        name_regex. This is distinct from an empty API response because the
        filtering happens client-side after the API call.
        """
        stubber = cfngin_context.add_stubber("ec2")
        image_id = "ami-fffccc111"
        stubber.add_response(
            "describe_images",
            {
                "Images": [
                    {
                        "OwnerId": "897883143566",
                        "Architecture": "x86_64",
                        "CreationDate": "2011-02-13T01:17:44.000Z",
                        "State": "available",
                        "ImageId": image_id,
                        "Name": "Fake Image 1",
                        "VirtualizationType": "hvm",
                    }
                ]
            },
        )

        with stubber, pytest.raises(ImageNotFound):
            AmiLookup.handle(value=r"owners:self name_regex:MyImage\s\d", context=cfngin_context)
