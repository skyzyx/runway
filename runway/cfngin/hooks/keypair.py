"""AWS EC2 keypair hook.

This module ensures EC2 key pairs exist before stacks that reference them
are created, supporting multiple provisioning strategies (import, generate
locally, or store in SSM) to accommodate different security workflows.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError
from typing_extensions import Literal, TypedDict

from ...utils import BaseModel
from ..ui import get_raw_input

if TYPE_CHECKING:
    from mypy_boto3_ec2.client import EC2Client
    from mypy_boto3_ec2.type_defs import ImportKeyPairResultTypeDef, KeyPairTypeDef
    from mypy_boto3_ssm.client import SSMClient

    from ...context import CfnginContext

LOGGER = logging.getLogger(__name__)

KEYPAIR_LOG_MESSAGE = "keypair %s (%s) %s"


class EnsureKeypairExistsHookArgs(BaseModel):
    """Hook arguments for ``ensure_keypair_exists``."""

    keypair: str
    """Name of the key pair to ensure exists."""

    public_key_path: str | None = None
    """Path to a public key file to be imported instead of generating a new key.
    Incompatible with the SSM options, as the private key will not be available for storing.

    """

    ssm_key_id: str | None = None
    """ID of a KMS key to encrypt the SSM parameter with.
    If omitted, the default key will be used.

    """

    ssm_parameter_name: str | None = None
    """Path to an SSM store parameter to receive the generated private key
    instead of importing it or storing it locally.

    """


class KeyPairInfo(TypedDict, total=False):
    """Value returned from get_existing_key_pair."""

    file_path: Path
    fingerprint: str
    key_name: str
    status: Literal["created", "exists", "imported"]


def get_existing_key_pair(ec2: EC2Client, keypair_name: str) -> KeyPairInfo | None:
    """Get existing keypair.

    Checks whether the keypair already exists so the hook can short-circuit
    and avoid regenerating or re-importing keys on subsequent deploys.
    """
    resp = ec2.describe_key_pairs()
    keypair = next(
        (kp for kp in resp.get("KeyPairs", []) if kp.get("KeyName") == keypair_name),
        None,
    )

    if keypair:
        LOGGER.info(
            KEYPAIR_LOG_MESSAGE,
            keypair.get("KeyName"),
            keypair.get("KeyFingerprint"),
            "exists",
        )
        return {
            "status": "exists",
            "key_name": keypair.get("KeyName", ""),
            "fingerprint": keypair.get("KeyFingerprint", ""),
        }

    LOGGER.info('keypair "%s" not found', keypair_name)
    return None


def import_key_pair(
    ec2: EC2Client, keypair_name: str, public_key_data: bytes
) -> ImportKeyPairResultTypeDef:
    """Import keypair.

    Imports a user-provided public key rather than generating one, allowing
    teams to use pre-existing SSH keys managed outside of AWS.
    """
    keypair = ec2.import_key_pair(
        KeyName=keypair_name, PublicKeyMaterial=public_key_data.strip(), DryRun=False
    )
    LOGGER.info(
        KEYPAIR_LOG_MESSAGE,
        keypair.get("KeyName"),
        keypair.get("KeyFingerprint"),
        "imported",
    )
    return keypair


def read_public_key_file(path: Path) -> bytes | None:
    """Read public key file.

    Validates the key format early to provide a clear error message rather
    than letting the AWS API reject malformed key material with a cryptic error.
    """
    try:
        data = path.read_bytes()
        if not data.startswith(b"ssh-rsa"):
            raise ValueError(
                "Bad public key data, must be an RSA key in SSH authorized "
                "keys format (beginning with `ssh-rsa`)"
            )
        return data.strip()
    except (ValueError, OSError) as err:
        LOGGER.error('failed to read public key file :%s": %s', path, str(err))
        return None


def create_key_pair_from_public_key_file(
    ec2: EC2Client, keypair_name: str, public_key_path: Path
) -> KeyPairInfo | None:
    """Create keypair from public key file.

    Provides a non-interactive path for CI pipelines where the public key
    file path is known ahead of time.
    """
    public_key_data = read_public_key_file(public_key_path)
    if not public_key_data:
        return None

    keypair = import_key_pair(ec2, keypair_name, public_key_data)
    return {
        "status": "imported",
        "key_name": keypair.get("KeyName", ""),
        "fingerprint": keypair.get("KeyFingerprint", ""),
    }


def create_key_pair_in_ssm(
    ec2: EC2Client,
    ssm: SSMClient,
    keypair_name: str,
    parameter_name: str,
    kms_key_id: str | None = None,
) -> KeyPairInfo | None:
    """Create keypair in SSM.

    Stores the generated private key in SSM Parameter Store so that it
    is never written to disk, enabling secure key management in automated
    pipelines where local file storage is undesirable.
    """
    keypair = create_key_pair(ec2, keypair_name)
    try:
        kms_key_label = "default"
        kms_args: dict[str, Any] = {}
        if kms_key_id:
            kms_key_label = kms_key_id
            kms_args = {"KeyId": kms_key_id}

        LOGGER.info(
            'storing generated key in SSM parameter "%s" using KMS key "%s"',
            parameter_name,
            kms_key_label,
        )

        ssm.put_parameter(
            Name=parameter_name,
            Description=f'SSH private key for KeyPair "{keypair_name}" (generated by Runway)',
            Value=keypair["KeyMaterial"],
            Type="SecureString",
            Overwrite=False,
            **kms_args,
        )
    except ClientError:
        # Erase the key pair if we failed to store it in SSM, since the
        # private key material is only returned once at creation time and
        # would be permanently lost without the SSM backup.

        LOGGER.exception(
            "failed to store generated key in SSM; deleting "
            "created key pair as private key will be lost"
        )
        ec2.delete_key_pair(KeyName=keypair_name, DryRun=False)
        return None

    return {
        "status": "created",
        "key_name": keypair.get("KeyName", ""),
        "fingerprint": keypair.get("KeyFingerprint", ""),
    }


def create_key_pair(ec2: EC2Client, keypair_name: str) -> KeyPairTypeDef:
    """Create keypair.

    Wraps the raw EC2 API call with logging so callers get consistent
    audit output regardless of which storage strategy is used.
    """
    keypair = ec2.create_key_pair(KeyName=keypair_name, DryRun=False)
    LOGGER.info(
        KEYPAIR_LOG_MESSAGE,
        keypair.get("KeyName"),
        keypair.get("KeyFingerprint"),
        "created",
    )
    return keypair


def create_key_pair_local(ec2: EC2Client, keypair_name: str, dest_dir: Path) -> KeyPairInfo | None:
    """Create local keypair.

    Provides a developer-friendly path that writes the private key to a local
    file for immediate SSH access during development or bootstrapping.
    """
    dest_dir = dest_dir.resolve()
    if not dest_dir.is_dir():
        LOGGER.error('"%s" is not a valid directory', dest_dir)
        return None

    key_path = dest_dir / f"{keypair_name}.pem"
    if key_path.is_file():
        # This mimics the old boto2 keypair.save error
        LOGGER.error('"%s" already exists in directory "%s"', key_path.name, dest_dir)
        return None

    keypair = create_key_pair(ec2, keypair_name)
    key_path.write_text(keypair.get("KeyMaterial", ""), encoding="ascii")

    return {
        "status": "created",
        "key_name": keypair.get("KeyName", ""),
        "fingerprint": keypair.get("KeyFingerprint", ""),
        "file_path": key_path,
    }


def interactive_prompt(
    keypair_name: str,
) -> tuple[Literal["create", "import"] | None, str | None]:
    """Interactive prompt.

    Provides a fallback for local development when neither public_key_path
    nor ssm_parameter_name is configured, allowing the user to decide the
    provisioning strategy at runtime.
    """
    if not sys.stdin.isatty():
        return None, None

    try:
        while True:
            action = get_raw_input(
                f'import or create keypair "{keypair_name}"? (import/create/cancel) '
            )

            if action.lower() == "cancel":
                break

            if action.lower() in ("i", "import"):
                path = get_raw_input("path to keypair file: ")
                return "import", path.strip()

            if action.lower() == "create":
                path = get_raw_input("directory to save keyfile: ")
                return "create", path.strip()
    except (EOFError, KeyboardInterrupt):
        return None, None

    return None, None


def ensure_keypair_exists(context: CfnginContext, *__args: Any, **kwargs: Any) -> KeyPairInfo:
    """Ensure a specific keypair exists within AWS.

    If the key doesn't exist, upload it.

    This is the main entry point that orchestrates the different key
    provisioning strategies (import, SSM, local, interactive) behind a
    single idempotent interface for the hook runner.

    """
    args = EnsureKeypairExistsHookArgs.model_validate(kwargs)

    if args.public_key_path and args.ssm_parameter_name:
        LOGGER.error("public_key_path and ssm_parameter_name cannot be specified at the same time")
        return {}

    session = context.get_session()
    ec2 = session.client("ec2")

    keypair_info = get_existing_key_pair(ec2, args.keypair)
    if keypair_info:
        return keypair_info

    if args.public_key_path:
        keypair_info = create_key_pair_from_public_key_file(
            ec2, args.keypair, Path(args.public_key_path)
        )
    elif args.ssm_parameter_name:
        ssm = session.client("ssm")
        keypair_info = create_key_pair_in_ssm(
            ec2, ssm, args.keypair, args.ssm_parameter_name, args.ssm_key_id
        )
    else:
        action, path = interactive_prompt(args.keypair)
        if action == "import" and path:
            keypair_info = create_key_pair_from_public_key_file(ec2, args.keypair, Path(path))
        elif action == "create" and path:
            keypair_info = create_key_pair_local(ec2, args.keypair, Path(path))
        else:
            LOGGER.error("no action to find keypair or path not provided")

    if not keypair_info:
        return {}

    return keypair_info
