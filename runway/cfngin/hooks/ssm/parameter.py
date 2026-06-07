"""AWS SSM Parameter Store hooks.

These hooks allow SSM parameters to be created, updated, and deleted as part
of the CFNgin deploy/destroy lifecycle, enabling secrets and configuration
values to be managed alongside stack resources without being stored in
CloudFormation templates.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, cast

from pydantic import ConfigDict, Field, field_validator
from typing_extensions import Literal, TypedDict

from ....compat import cached_property
from ....utils import BaseModel, JsonEncoder
from ..protocols import CfnginHookProtocol
from ..utils import TagDataModel

if TYPE_CHECKING:
    from mypy_boto3_ssm.client import SSMClient
    from mypy_boto3_ssm.literals import ParameterTierType
    from mypy_boto3_ssm.type_defs import ParameterTypeDef, TagTypeDef

    from ...._logging import RunwayLogger
    from ....context import CfnginContext
else:
    ParameterTierType = Literal["Advanced", "Intelligent-Tiering", "Standard"]

LOGGER = cast("RunwayLogger", logging.getLogger(__name__))


# PutParameterResultTypeDef but without metadata
class _PutParameterResultTypeDef(TypedDict):
    Tier: ParameterTierType
    Version: int


class ArgsDataModel(BaseModel):
    """Parameter hook args.

    Mirrors the AWS PutParameter API shape so that users can express
    parameter configuration in their CFNgin hook definitions using the
    same field names the AWS SDK expects.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    allowed_pattern: Annotated[str | None, Field(alias="AllowedPattern")] = None
    """A regular expression used to validate the parameter value."""

    data_type: Annotated[
        Literal["aws:ec2:image", "text"] | None,
        Field(alias="DataType"),
    ] = None
    """The data type for a String parameter.

    Supported data types include plain text and Amazon Machine Image IDs.

    """

    description: Annotated[str | None, Field(alias="Description")] = None
    """Information about the parameter."""

    force: bool = False
    """Skip checking the current value of the parameter, just put it.

    Can be used alongside ``overwrite`` to always update a parameter.

    """

    key_id: Annotated[str | None, Field(alias="KeyId")] = None
    """The KMS Key ID that you want to use to encrypt a parameter.

    Either the default AWS Key Management Service (AWS KMS) key automatically
    assigned to your AWS account or a custom key.
    Required for parameters that use the ``SecureString`` data type.

    """

    name: Annotated[str, Field(alias="Name")]
    """The fully qualified name of the parameter that you want to add to the system."""

    overwrite: Annotated[bool, Field(alias="Overwrite")] = True
    """Allow overwriting an existing parameter."""

    policies: Annotated[str | None, Field(alias="Policies")] = None
    """One or more policies to apply to a parameter. This field takes a JSON array."""

    tags: Annotated[list[TagDataModel] | None, Field(alias="Tags")] = None
    """Optional metadata that you assign to a resource."""

    tier: Annotated[ParameterTierType, Field(alias="Tier")] = "Standard"
    """The parameter tier to assign to a parameter."""

    type: Annotated[Literal["String", "StringList", "SecureString"], Field(alias="Type")]
    """The type of parameter."""

    value: Annotated[str | None, Field(alias="Value")] = None
    """The parameter value that you want to add to the system.

    Standard parameters have a value limit of 4 KB.
    Advanced parameters have a value limit of 8 KB.

    """

    @field_validator("policies", mode="before")
    @classmethod
    def _convert_policies(cls, v: list[dict[str, Any]] | str | Any) -> str:
        """Convert policies to acceptable value.

        The AWS API requires policies as a JSON string, but users often
        provide them as a list of dicts in YAML config for readability.
        """
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            return json.dumps(v, cls=JsonEncoder)
        raise ValueError(f"unexpected type {type(v)}; permitted: list[dict[str, Any]] | str | None")

    @field_validator("tags", mode="before")
    @classmethod
    def _convert_tags(cls, v: dict[str, str] | list[dict[str, str]] | Any) -> list[dict[str, str]]:
        """Convert tags to acceptable value.

        Accepts both the AWS-native Key/Value list format and a simpler
        dict format, normalizing to the list format the API requires.
        """
        if isinstance(v, list):  # TODO (kyle): improve with `typing.TypeIs` narrowing
            return cast("list[dict[str, str]]", v)
        if isinstance(v, dict):  # TODO (kyle): improve with `typing.TypeIs` narrowing
            return [{"Key": k, "Value": v} for k, v in cast("dict[str, str]", v).items()]
        raise ValueError(
            f"unexpected type {type(v)}; permitted: dict[str, str] | list[dict[str, str]] | none"
        )


class _Parameter(CfnginHookProtocol):
    """AWS SSM Parameter Store Parameter.

    Encapsulates the full CRUD lifecycle of a single SSM parameter so that
    deployment hooks can create/update on deploy and delete on destroy using
    the same configuration object.
    """

    ARGS_PARSER: ClassVar = ArgsDataModel
    """Class used to parse arguments passed to the hook."""

    args: ArgsDataModel

    def __init__(
        self,
        context: CfnginContext,
        *,
        name: str,
        type: Literal["String", "StringList", "SecureString"],  # noqa: A002
        **kwargs: Any,
    ) -> None:
        """Instantiate class.

        Args:
            context: CFNgin context object.
            name: The fully qualified name of the parameter that you want to add to
                the system.
            type: The type of parameter.
            **kwargs: Arbitrary keyword arguments.

        """
        self.args = ArgsDataModel.model_validate({"name": name, "type": type, **kwargs})
        self.ctx = context

    @cached_property
    def client(self) -> SSMClient:
        """AWS SSM client.

        Uses cached_property so a single client instance is reused across
        multiple API calls within the same hook invocation.
        """
        return self.ctx.get_session().client("ssm")

    def delete(self) -> bool:
        """Delete parameter.

        Returns True even when the parameter does not exist because
        the desired end state (parameter absent) is already satisfied.
        """
        try:
            self.client.delete_parameter(Name=self.args.name)
            LOGGER.info("deleted SSM Parameter %s", self.args.name)
        except self.client.exceptions.ParameterNotFound:
            LOGGER.info("delete parameter skipped; %s not found", self.args.name)
        return True

    def get(self) -> ParameterTypeDef:
        """Get parameter.

        Fetches the current value so that put() can skip the write when
        the value is unchanged, avoiding unnecessary parameter versions.
        """
        # Guard: force flag intentionally skips the value comparison so that
        # external changes (e.g., console edits) are always overwritten.
        if self.args.force:  # bypass getting current value
            return {}
        try:
            return self.client.get_parameter(Name=self.args.name, WithDecryption=True).get(
                "Parameter", {}
            )
        except self.client.exceptions.ParameterNotFound:
            LOGGER.verbose("parameter %s does not exist", self.args.name)
            return {}

    def get_current_tags(self) -> list[TagTypeDef]:
        """Get Tags currently applied to Parameter.

        Retrieved separately from the parameter value because the SSM API
        does not include tags in GetParameter responses.
        """
        try:
            return self.client.list_tags_for_resource(
                ResourceId=self.args.name, ResourceType="Parameter"
            ).get("TagList", [])
        except (
            self.client.exceptions.InvalidResourceId,
            self.client.exceptions.ParameterNotFound,
        ):
            return []

    def post_deploy(self) -> _PutParameterResultTypeDef:
        """Run during the *post_deploy* stage."""
        result = self.put()
        self.update_tags()
        return result

    def post_destroy(self) -> bool:
        """Run during the *post_destroy* stage."""
        return self.delete()

    def pre_deploy(self) -> _PutParameterResultTypeDef:
        """Run during the *pre_deploy* stage."""
        result = self.put()
        self.update_tags()
        return result

    def pre_destroy(self) -> bool:
        """Run during the *pre_destroy* stage."""
        return self.delete()

    def put(self) -> _PutParameterResultTypeDef:
        """Put parameter.

        Compares the desired value against the current value to avoid
        creating unnecessary parameter versions on every deployment.
        """
        if not self.args.value:
            LOGGER.info(
                "skipped putting SSM Parameter; value provided for %s is falsy",
                self.args.name,
            )
            return {"Tier": self.args.tier, "Version": 0}
        current_param = self.get()
        if current_param.get("Value") != self.args.value:
            try:
                result = self.client.put_parameter(
                    **self.args.model_dump(
                        by_alias=True, exclude_none=True, exclude={"force", "tags"}
                    )
                )
            except self.client.exceptions.ParameterAlreadyExists:
                LOGGER.warning(
                    "parameter %s already exists; to overwrite it's value, "
                    'set the overwrite field to "true"',
                    self.args.name,
                )
                return {
                    "Tier": current_param.get("Tier", self.args.tier),  # type: ignore[typeddict-item]
                    "Version": current_param.get("Version", 0),
                }
        else:
            result: _PutParameterResultTypeDef = {  # type: ignore[no-redef]
                "Tier": current_param.get("Tier", self.args.tier),  # type: ignore[typeddict-item]
                "Version": current_param.get("Version", 0),
            }
        LOGGER.info("put SSM Parameter %s", self.args.name)
        return result

    def update_tags(self) -> None:
        """Update tags.

        Performs a diff between current and desired tags to remove stale
        keys and apply new ones, since the SSM API has no atomic
        replace-tags operation.
        """
        current_tags = self.get_current_tags()
        # Compute the symmetric difference of tag keys to identify which
        # tags to remove before applying the desired set.
        if self.args.tags and current_tags:
            diff_tag_keys = list({i["Key"] for i in current_tags} ^ {i.key for i in self.args.tags})
        elif self.args.tags:
            diff_tag_keys = []
        else:
            diff_tag_keys = [i["Key"] for i in current_tags]

        try:
            if diff_tag_keys:
                diff_tag_keys.sort()
                self.client.remove_tags_from_resource(
                    ResourceId=self.args.name,
                    ResourceType="Parameter",
                    TagKeys=diff_tag_keys,
                )
                LOGGER.debug("removed tags for parameter %s: %s", self.args.name, diff_tag_keys)

            if self.args.tags:
                tags_to_add = [
                    cast("TagTypeDef", tag.model_dump(by_alias=True)) for tag in self.args.tags
                ]
                self.client.add_tags_to_resource(
                    ResourceId=self.args.name,
                    ResourceType="Parameter",
                    Tags=tags_to_add,
                )
                LOGGER.debug(
                    "added tags to parameter %s: %s",
                    self.args.name,
                    [tag["Key"] for tag in tags_to_add],
                )
        except self.client.exceptions.InvalidResourceId:
            LOGGER.info("skipped updating tags; parameter %s does not exist", self.args.name)
        else:
            LOGGER.info("updated tags for parameter %s", self.args.name)


class SecureString(_Parameter):
    """AWS SSM Parameter Store SecureString Parameter.

    Provides a convenience subclass that hardcodes the parameter type to
    SecureString, preventing accidental storage of sensitive values as
    plain-text String parameters.
    """

    def __init__(
        self,
        context: CfnginContext,
        *,
        name: str,
        **kwargs: Any,
    ) -> None:
        """Instantiate class.

        Args:
            context: CFNgin context object.
            name: The fully qualified name of the parameter that you want to add to
                the system.
            **kwargs: Arbitrary keyword arguments.

        """
        # Ensure the type kwarg is always SecureString regardless of what
        # the user passed, preventing accidental plain-text storage.
        for k in ["Type", "type"]:  # ensure neither of these are set
            kwargs.pop(k, None)
        super().__init__(context, name=name, type="SecureString", **kwargs)
