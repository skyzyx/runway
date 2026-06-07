"""Tests for runway.cfngin.lookups.handlers.kms.

Validates KMS decryption lookup that decodes base64-encoded ciphertext blobs
using AWS KMS, enabling encrypted secrets to be stored safely in config files
and decrypted at deploy time.
"""

from __future__ import annotations

import codecs
import string
from typing import TYPE_CHECKING

import pytest

from runway.cfngin.lookups.handlers.kms import KmsLookup

if TYPE_CHECKING:
    from ....factories import MockCfnginContext

SECRET = "my secret"


class TestKMSHandler:
    """Tests for runway.cfngin.lookups.handlers.kms.KmsLookup.

    KMS lookups decrypt ciphertext at deploy time, keeping secrets encrypted
    at rest in version control. Tests verify the base64 decoding and AWS API
    interaction including cross-region support.
    """

    def test_handle(self, cfngin_context: MockCfnginContext) -> None:
        """Test handle."""
        stubber = cfngin_context.add_stubber("kms")
        stubber.add_response(
            "decrypt",
            {"Plaintext": SECRET.encode()},
            {"CiphertextBlob": codecs.decode(SECRET.encode(), "base64")},
        )

        with stubber:
            assert KmsLookup.handle(SECRET, context=cfngin_context) == SECRET
            stubber.assert_no_pending_responses()

    @pytest.mark.parametrize("template", ["${region}@${blob}", "${blob}::region=${region}"])
    def test_handle_with_region(self, cfngin_context: MockCfnginContext, template: str) -> None:
        """Test handle with region.

        Validates both region specification syntaxes (prefix@ and ::region=)
        which are needed when the KMS key lives in a different region than the
        deployment context.
        """
        region = "us-west-2"
        query = string.Template(template).substitute({"blob": SECRET, "region": region})
        stubber = cfngin_context.add_stubber("kms", region=region)

        stubber.add_response(
            "decrypt",
            {"Plaintext": SECRET.encode()},
            {"CiphertextBlob": codecs.decode(SECRET.encode(), "base64")},
        )

        with stubber:
            assert KmsLookup.handle(query, context=cfngin_context) == SECRET
            stubber.assert_no_pending_responses()

    def test_legacy_parse(self) -> None:
        """Test legacy_parse.

        Validates backward-compatible parsing of the deprecated region@blob
        format used in older CFNgin configurations.
        """
        assert KmsLookup.legacy_parse("us-east-1@foo") == (
            "foo",
            {"region": "us-east-1"},
        )
