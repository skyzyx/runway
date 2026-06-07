"""AWS IAM hook.

This module manages IAM resources (roles, certificates) that must exist
before stacks referencing them are created, bridging the gap between
prerequisites that are too dynamic for static templates and full
CloudFormation-managed resources.
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any, cast

from awacs import ecs
from awacs.aws import Allow, Policy, Statement
from awacs.helpers.trust import get_ecs_assumerole_policy
from botocore.exceptions import ClientError

from ...utils import BaseModel
from . import utils

if TYPE_CHECKING:
    from mypy_boto3_iam.type_defs import (
        GetServerCertificateResponseTypeDef,
        UploadServerCertificateResponseTypeDef,
    )

    from ...context import CfnginContext

LOGGER = logging.getLogger(__name__)

# The ECS service role policy grants the minimum permissions required for
# the ECS agent to manage container instances and register tasks.
ECS_SERVICE_ROLE_NAME = "ecsServiceRole"
ECS_SERVICE_ROLE_POLICY = Policy(
    Version="2012-10-17",
    Statement=[
        Statement(
            Effect=Allow,
            Resource=["*"],
            Action=[
                ecs.CreateCluster,
                ecs.DeregisterContainerInstance,
                ecs.DiscoverPollEndpoint,
                ecs.Poll,
                ecs.Action("Submit*"),
            ],
        )
    ],
)


class CreateEcsServiceRoleHookArgs(BaseModel):
    """Hook arguments for ``create_ecs_service_role``."""

    role_name: str = ECS_SERVICE_ROLE_NAME
    """Name of the role to create."""


class EnsureServerCertExistsHookArgs(BaseModel):
    """Hook arguments for ``ensure_server_cert_exists``."""

    cert_name: str
    """Name of the certificate that should exist."""

    path_to_certificate: str | None = None
    """Path to certificate file."""

    path_to_chain: str | None = None
    """Path to chain file."""

    path_to_private_key: str | None = None
    """Path to private key file."""

    prompt: bool = True
    """Whether to prompt to upload a certificate if one does not exist."""


def create_ecs_service_role(context: CfnginContext, *_args: Any, **kwargs: Any) -> bool:
    """Create ecsServiceRole IAM role.

    This hook exists because ECS historically required a service-linked role
    to be explicitly created before services could be launched, and the role
    must be idempotent (tolerate "already exists" errors) across repeated deploys.

    https://docs.aws.amazon.com/AmazonECS/latest/developerguide/using-service-linked-roles.html

    Args:
        context: Context instance. (passed in by CFNgin)
        **kwargs: Arbitrary keyword arguments.

    """
    args = CreateEcsServiceRoleHookArgs.model_validate(kwargs)
    client = context.get_session().client("iam")

    try:
        client.create_role(
            RoleName=args.role_name,
            AssumeRolePolicyDocument=get_ecs_assumerole_policy().to_json(),
        )
    except ClientError as err:
        # Tolerate "already exists" so this hook is idempotent across
        # repeated deployments without requiring a pre-check API call.
        if "already exists" not in str(err):
            raise
    client.put_role_policy(
        RoleName=args.role_name,
        PolicyName="AmazonEC2ContainerServiceRolePolicy",
        PolicyDocument=ECS_SERVICE_ROLE_POLICY.to_json(),
    )
    return True


def _get_cert_arn_from_response(
    response: GetServerCertificateResponseTypeDef | UploadServerCertificateResponseTypeDef,
) -> str:
    """Extract the certificate ARN from either a GET or UPLOAD API response.

    The two response shapes nest the ARN at different depths, so this helper
    normalizes access to avoid duplicating the extraction logic at each call site.
    """
    result = copy.deepcopy(response)
    # The GET response wraps metadata in an extra "ServerCertificate" key
    # that the UPLOAD response does not have.
    if "ServerCertificate" in response:
        return cast("GetServerCertificateResponseTypeDef", result)["ServerCertificate"][
            "ServerCertificateMetadata"
        ]["Arn"]
    return (
        cast("UploadServerCertificateResponseTypeDef", result)
        .get("ServerCertificateMetadata", {"Arn": ""})
        .get("Arn", "")
    )


def _get_cert_contents(kwargs: dict[str, Any]) -> dict[str, Any]:  # noqa: C901
    """Build parameters with server cert file contents.

    This function handles both automated (path-based) and interactive (prompt)
    certificate provisioning so that the hook works in CI pipelines and local
    development alike.

    Args:
        kwargs: The keyword args passed to ensure_server_cert_exists, optionally
            containing the paths to the cert, key and chain files.

    Returns:
        A dictionary containing the appropriate parameters to supply to
        upload_server_certificate. An empty dictionary if there is a problem.

    """
    paths = {
        "certificate": kwargs.get("path_to_certificate"),
        "private_key": kwargs.get("path_to_private_key"),
        "chain": kwargs.get("path_to_chain"),
    }

    for key, value in paths.items():
        if value is not None:
            continue

        path = input(f"Path to {key} (skip): ")
        if path == "skip" or not path.strip():
            continue

        paths[key] = path

    parameters: dict[str, str] = {}

    for key, path in paths.items():
        if not path:
            continue

        # Allow passing of file like object for tests
        try:
            contents = path.read()
        except AttributeError:
            with open(utils.full_path(path), encoding="utf-8") as read_file:  # noqa: PTH123
                contents = read_file.read()

        if key == "certificate":
            parameters["CertificateBody"] = contents
        elif key == "private_key":
            parameters["PrivateKey"] = contents
        elif key == "chain":
            parameters["CertificateChain"] = contents

    if parameters and "cert_name" in kwargs:
        parameters["ServerCertificateName"] = kwargs["cert_name"]

    return parameters


def ensure_server_cert_exists(context: CfnginContext, *_args: Any, **kwargs: Any) -> dict[str, str]:
    """Ensure server cert exists.

    This hook implements an idempotent certificate provisioning pattern:
    check if the cert already exists, and only upload if missing, so that
    stacks depending on the cert ARN always have a valid reference.

    Args:
        context: CFNgin context object.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dict containing ``status``, ``cert_name``, and ``cert_arn``.

    """
    args = EnsureServerCertExistsHookArgs.model_validate(kwargs)
    client = context.get_session().client("iam")
    status = "unknown"
    try:
        response = client.get_server_certificate(ServerCertificateName=args.cert_name)
        cert_arn = _get_cert_arn_from_response(response)
        status = "exists"
        LOGGER.info("certificate exists: %s (%s)", args.cert_name, cert_arn)
    except ClientError:
        if args.prompt:
            upload = input(f"Certificate '{args.cert_name}' wasn't found. Upload it now? (yes/no) ")
            if upload != "yes":
                return {}

        parameters = _get_cert_contents(args.model_dump())
        if not parameters:
            return {}
        response = client.upload_server_certificate(**parameters)
        cert_arn = _get_cert_arn_from_response(response)
        status = "uploaded"
        LOGGER.info("uploaded certificate: %s (%s)", args.cert_name, cert_arn)

    return {
        "status": status,
        "cert_name": args.cert_name,
        "cert_arn": cert_arn,
    }
