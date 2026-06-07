"""CFNgin prehook responsible for creation of Lambda@Edge functions.

Lambda@Edge does not support environment variables, so this hook injects
runtime configuration by template-substituting a shared Python config file
before packaging each function for upload to S3.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import shutil
import tempfile
from tempfile import mkstemp
from typing import TYPE_CHECKING, Any

from ... import aws_lambda
from ...base import HookArgsBaseModel

if TYPE_CHECKING:
    from .....context import CfnginContext
    from ....providers.aws.default import Provider

# The functions associated with Auth@Edge
# Each function corresponds to a specific CloudFront viewer/origin event:
# authentication check, token refresh, OAuth callback parse, sign-out, and
# security headers injection.
FUNCTIONS = ["check_auth", "refresh_auth", "parse_auth", "sign_out", "http_headers"]


LOGGER = logging.getLogger(__name__)


class HookArgs(HookArgsBaseModel):
    """Hook arguments.

    Contains all dynamic configuration values that must be baked into the
    Lambda@Edge source code since environment variables are unavailable at edge.
    """

    bucket: str
    """S3 bucket name."""

    client_id: str
    """The ID of the Cognito User Pool Client."""

    cookie_settings: dict[str, Any]
    """The settings for our customized cookies."""

    http_headers: dict[str, Any]
    """The additional headers added to our requests."""

    nonce_signing_secret_param_name: str
    """SSM param name to store nonce signing secret."""

    oauth_scopes: list[str]
    """The validation scopes for our OAuth requests."""

    redirect_path_refresh: str
    """The URL path for authorization refresh redirect (Correlates to the refresh auth lambda)."""

    redirect_path_sign_in: str
    """The URL path to be redirected to after sign in (Correlates to the parse auth lambda)."""

    redirect_path_sign_out: str
    """The URL path to be redirected to after sign out (Correlates to the root to
    be asked to resigning).

    """

    required_group: str | None = None
    """Optional User Pool group to which access should be restricted."""


def write(
    context: CfnginContext, provider: Provider, *__args: Any, **kwargs: Any
) -> dict[str, Any]:
    """Writes/Uploads the configured lambdas for Auth@Edge.

    Lambda@Edge does not have the ability to allow Environment variables
    at the time of this writing. In order to configure our lambdas with
    dynamic variables we first will go through and update a "shared" template
    with all of the configuration elements and add that to a temporary
    folder along with each of the individual Lambda@Edge functions. This
    temporary folder is then used with the CFNgin awsLambda hook to build
    the functions.

    """
    cognito_domain = context.hook_data["aae_domain_updater"].get("domain")
    args = HookArgs.model_validate(kwargs)
    config = {
        "client_id": args.client_id,
        "cognito_auth_domain": cognito_domain,
        "cookie_settings": args.cookie_settings,
        "http_headers": args.http_headers,
        "oauth_scopes": args.oauth_scopes,
        "redirect_path_auth_refresh": args.redirect_path_refresh,
        "redirect_path_sign_in": args.redirect_path_sign_in,
        "redirect_path_sign_out": args.redirect_path_sign_out,
        "required_group": args.required_group,
        "user_pool_id": context.hook_data["aae_user_pool_id_retriever"]["id"],
        "nonce_signing_secret": get_nonce_signing_secret(
            args.nonce_signing_secret_param_name, context
        ),
    }

    # Shared file that contains the method called for configuration data
    # Uses the template as a base and replaces its placeholder dict with
    # actual runtime values via regex to produce a self-contained config module.
    path = os.path.join(os.path.dirname(__file__), "templates", "shared.py")  # noqa: PTH120, PTH118
    context_dict: dict[str, Any] = {}

    with open(path, encoding="utf-8") as file_:  # noqa: PTH123
        # Dynamically replace our configuration values
        # in the shared.py template file with actual
        # calculated values.
        # The regex targets the first dict literal in the file (the config
        # placeholder) and replaces it with the populated config dict.
        shared = re.sub(
            r"{.+?(})$",
            str(config),
            file_.read(),
            count=1,
            flags=re.DOTALL | re.MULTILINE,
        )

        filedir, temppath = mkstemp()

        # Save the file to a temp path
        with open(temppath, "w", encoding="utf-8") as tmp:  # noqa: PTH123
            tmp.write(shared)
            config = temppath
        os.close(filedir)

        # Get all of the different Auth@Edge functions
        # Each function is packaged independently because Lambda@Edge
        # deployments are per-CloudFront event type and must be self-contained.
        for handler in FUNCTIONS:
            # Create a temporary folder
            dirpath = tempfile.mkdtemp()

            # Copy the template code for the specific Lambda function
            # to the temporary folder
            shutil.copytree(
                os.path.join(  # noqa: PTH118
                    os.path.dirname(__file__),  # noqa: PTH120
                    "templates",
                    handler,
                ),
                dirpath,
                dirs_exist_ok=True,
            )

            # Save our dynamic configuration shared file to the
            # temporary folder
            with open(config, encoding="utf-8") as shared:  # noqa: PTH123
                raw = shared.read()
                filename = "shared.py"
                with open(os.path.join(dirpath, filename), "wb") as newfile:  # noqa: PTH118, PTH123
                    newfile.write(raw.encode())

            # Copy the shared jose-dependent util module to the temporary folder
            shutil.copyfile(
                os.path.join(  # noqa: PTH118
                    os.path.dirname(__file__),  # noqa: PTH120
                    "templates",
                    "shared_jose.py",
                ),
                os.path.join(dirpath, "shared_jose.py"),  # noqa: PTH118
            )

            # Upload our temporary folder to our S3 bucket for
            # Lambda use
            lamb = aws_lambda.upload_lambda_functions(
                context,
                provider,
                bucket=args.bucket,
                functions={
                    handler: {
                        "path": dirpath,
                        "python_dontwritebytecode": True,
                        "python_exclude_bin_dir": True,
                        "python_exclude_setuptools_dirs": True,
                    }
                },
            )

            # Add the lambda code reference to our context_dict
            context_dict.update(lamb)

    return context_dict


def get_nonce_signing_secret(param_name: str, context: CfnginContext) -> str:
    """Retrieve signing secret, generating & storing it first if not present.

    The nonce signing secret must persist across deployments to ensure tokens
    signed by a previous deployment can still be validated after a redeploy.
    SSM Parameter Store provides durable, encrypted storage for this secret.
    """
    session = context.get_session()
    ssm_client = session.client("ssm")
    try:
        response = ssm_client.get_parameter(Name=param_name, WithDecryption=True)
        return response["Parameter"].get("Value", "")
    except ssm_client.exceptions.ParameterNotFound:
        secret = random_key(16)
        ssm_client.put_parameter(
            Description="Auth@Edge nonce signing secret",
            Name=param_name,
            Type="String",
            Value=secret,
        )
        return secret


def random_key(length: int = 16) -> str:
    """Generate a random key of specified length from the allowed secret characters.

    Uses a restricted character set (URL-safe without reserved characters) to
    ensure the generated secret can be safely embedded in cookies and query
    parameters without encoding issues.

    Args:
        length: The length of the random key.

    """
    secret_allowed_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    return "".join(secrets.choice(secret_allowed_chars) for _ in range(length))
