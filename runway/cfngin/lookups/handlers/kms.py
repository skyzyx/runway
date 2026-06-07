"""AWS KMS lookup.

This lookup enables storing encrypted secrets (database passwords, API keys)
directly in cfngin configuration files and decrypting them at deploy time,
so that secrets never need to exist as plaintext in source control.
"""

from __future__ import annotations

import codecs
import logging
from typing import TYPE_CHECKING, Any, BinaryIO, ClassVar, cast

from ....lookups.handlers.base import LookupHandler
from ....utils import DOC_SITE
from ...utils import read_value_from_path

if TYPE_CHECKING:
    from ....context import CfnginContext
    from ....lookups.handlers.base import ParsedArgsTypeDef

LOGGER = logging.getLogger(__name__)


class KmsLookup(LookupHandler["CfnginContext"]):
    """AWS KMS lookup.

    Wraps the KMS Decrypt API behind the standard lookup interface so that
    encrypted ciphertext blobs in config files are transparently decrypted
    into plaintext values at deploy time.
    """

    DEPRECATION_MSG = (
        'lookup query syntax "<region>@<encrypted-blob>" has been deprecated; '
        "to learn how to use the new lookup query syntax visit "
        f"{DOC_SITE}/page/cfngin/lookups/kms.html"
    )
    TYPE_NAME: ClassVar[str] = "kms"
    """Name that the Lookup is registered as."""

    @classmethod
    def legacy_parse(cls, value: str) -> tuple[str, ParsedArgsTypeDef]:
        """Retain support for legacy lookup syntax.

        Preserves backward compatibility with the older ``region@blob`` format
        while emitting a deprecation warning to guide users toward the new
        key=value argument syntax.

        Format of value::

            <region>@<encrypted-blob>

        """
        LOGGER.warning("${%s %s}: %s", cls.TYPE_NAME, value, cls.DEPRECATION_MSG)
        region, value = read_value_from_path(value).split("@", 1)
        return value, {"region": region}

    @classmethod
    def handle(cls, value: str, context: CfnginContext, **_: Any) -> str:
        r"""Decrypt the specified value with a master key in KMS.

        Decryption happens at deploy time so that config files can store only
        the ciphertext blob, keeping secrets out of version control while still
        allowing them to flow into CloudFormation parameters.

        Args:
            value: Parameter(s) given to this lookup.
            context: Context instance.

        """
        # Support both legacy (region@blob) and new (key=value) query formats.
        if "@" in value:
            query, args = cls.legacy_parse(value)
        else:
            query, args = cls.parse(value)

        kms = context.get_session(region=cast("str | None", args.get("region"))).client("kms")

        decrypted = cast(
            "BinaryIO | bytes",
            kms.decrypt(CiphertextBlob=codecs.decode(query.encode(), "base64")).get(
                "Plaintext", b""
            ),
        )
        if isinstance(decrypted, bytes):
            return cls.format_results(decrypted.decode(), **args)
        return cls.format_results(decrypted.read().decode(), **args)
