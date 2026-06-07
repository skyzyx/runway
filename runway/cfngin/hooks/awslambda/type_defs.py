"""Type definitions.

Provides TypedDict definitions that give static type safety to the
dictionary payloads exchanged between the awslambda hook and CFNgin
lookups without requiring full Pydantic model deserialization.
"""

from __future__ import annotations

from typing_extensions import TypedDict


# Uses PascalCase keys to match CloudFormation property names so the dict
# can be passed directly to CFNgin lookups without key transformation.
class AwsLambdaHookDeployResponseTypedDict(TypedDict):
    """Dict output of :class:`runway.cfngin.hooks.awslambda.models.response.AwsLambdaHookDeployResponse` using aliases."""

    CodeSha256: str
    Runtime: str
    S3Bucket: str
    S3Key: str
    S3ObjectVersion: str | None
