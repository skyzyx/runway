"""CFNgin Bucket Blueprint.

This built-in blueprint is used by the CFNgin init action to bootstrap the S3
bucket that CFNgin uses for storing rendered CloudFormation templates. Without
this bucket, CFNgin cannot upload templates that exceed the CloudFormation
inline size limit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from troposphere import Equals, If, Not, NoValue, Or, Tag, Tags, s3

from ... import __version__
from ...compat import cached_property
from .base import Blueprint
from .variables.types import CFNString

if TYPE_CHECKING:
    from troposphere import AWSHelperFn

    from .type_defs import BlueprintVariableTypeDef


class CfnginBucket(Blueprint):
    """CFNgin Bucket Blueprint.

    Provides a reusable, subclass-friendly blueprint for the CFNgin template
    storage bucket so that users can customize encryption, tagging, or naming
    without reimplementing the full bucket resource definition.
    """

    DESCRIPTION: ClassVar[str] = f"{__name__}.CFNginBucket (v{__version__})"
    VARIABLES: ClassVar[dict[str, BlueprintVariableTypeDef]] = {
        "AccessControl": {
            "allowed_values": [
                "AuthenticatedRead",
                "AwsExecRead",
                "BucketOwnerFullControl",
                "BucketOwnerRead",
                "LogDeliveryWrite",
                "Private",
                "PublicRead",
                "PublicReadWrite",
            ],
            "default": "Private",
            "description": "A canned access control list (ACL) that grants "
            "predefined permissions to the bucket.",
            "type": CFNString,
        },
        "BucketName": {"description": "Name of the CFNgin bucket", "type": CFNString},
        "VersioningStatus": {
            "allowed_values": ["Enabled", "Suspended"],
            "default": "Enabled",
            "description": "Status of the bucket's VersioningConfiguration",
            "type": CFNString,
        },
    }

    @cached_property
    def bucket(self) -> s3.Bucket:
        """CFNgin Bucket.

        Consolidates the full bucket resource definition and its outputs in one
        place so subclasses only need to override individual cached properties
        (encryption, name, tags) rather than reconstructing the entire resource.
        """
        bucket = s3.Bucket(
            "Bucket",
            AccessControl=self.variables["AccessControl"].ref,
            BucketEncryption=self.bucket_encryption,
            BucketName=self.bucket_name,
            OwnershipControls=s3.OwnershipControls(
                Rules=[s3.OwnershipControlsRule(ObjectOwnership="BucketOwnerPreferred")]
            ),
            Tags=self.bucket_tags,
            VersioningConfiguration=s3.VersioningConfiguration(
                Status=self.variables["VersioningStatus"].ref
            ),
        )
        self.add_output("BucketArn", bucket.get_att("Arn"))
        self.add_output("BucketDomainName", bucket.get_att("DomainName"))
        self.add_output("BucketName", bucket.ref())
        self.add_output("BucketRegionalDomainName", bucket.get_att("RegionalDomainName"))
        return bucket

    @cached_property
    def bucket_encryption(self) -> AWSHelperFn | s3.BucketEncryption:
        """CFNgin bucket encryption.

        This cached property can be overridden in a subclass to customize the
        BucketEncryption property of the bucket without needing to override the
        bucket cached property.

        Defaults to AES256 server-side encryption because it requires no KMS
        key management while still satisfying security compliance requirements
        for data-at-rest encryption.
        """
        return s3.BucketEncryption(
            ServerSideEncryptionConfiguration=[
                s3.ServerSideEncryptionRule(
                    ServerSideEncryptionByDefault=s3.ServerSideEncryptionByDefault(
                        SSEAlgorithm="AES256"
                    )
                )
            ]
        )

    @cached_property
    def bucket_name(self) -> AWSHelperFn:
        """CFNgin Bucket name.

        Uses a CloudFormation condition to allow the bucket name to be optional;
        when no name is provided, CloudFormation auto-generates one, avoiding
        naming collisions across multiple deployments.
        """
        # Check both empty string and "undefined" because CFN parameters
        # cannot truly be optional — the condition handles both sentinel values.
        condition = self.template.add_condition(
            "BucketNameProvided",
            Or(
                Not(Equals(self.variables["BucketName"].ref, "")),
                Not(Equals(self.variables["BucketName"].ref, "undefined")),
            ),
        )
        return If(condition, self.variables["BucketName"].ref, NoValue)

    @cached_property
    def bucket_tags(self) -> Tags:
        """CFNgin bucket tags.

        This cached property can be overridden in a subclass to customize the
        Tags property of the bucket without needing to override the bucket cached
        property.

        """
        return Tags(Tag("version", __version__))

    def create_template(self) -> None:
        """Create template.

        Assembles the CloudFormation template by referencing the bucket cached
        property, which triggers lazy construction of all sub-resources and
        outputs in the correct dependency order.
        """
        self.template.set_description(self.DESCRIPTION)
        self.template.set_version("2010-09-09")
        self.template.add_resource(self.bucket)
