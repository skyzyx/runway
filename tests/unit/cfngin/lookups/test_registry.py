"""Tests for runway.cfngin.lookups.registry.

Validates lookup handler registration, ensuring the plugin system correctly
discovers, registers, and unregisters lookup handlers at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from runway.cfngin.lookups.handlers.default import DefaultLookup
from runway.cfngin.lookups.registry import (
    CFNGIN_LOOKUP_HANDLERS,
    register_lookup_handler,
    unregister_lookup_handler,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_autoloaded_lookup_handlers(mocker: MockerFixture) -> None:
    """Test autoloaded lookup handlers.

    Ensures all expected built-in lookup handlers are auto-discovered on import,
    preventing regressions where a new handler is added but not registered.
    """
    mocker.patch.dict(CFNGIN_LOOKUP_HANDLERS, {})
    handlers = [
        "ami",
        "awslambda",
        "awslambda.Code",
        "awslambda.CodeSha256",
        "awslambda.CompatibleArchitectures",
        "awslambda.CompatibleRuntimes",
        "awslambda.Content",
        "awslambda.LicenseInfo",
        "awslambda.Runtime",
        "awslambda.S3Bucket",
        "awslambda.S3Key",
        "awslambda.S3ObjectVersion",
        "cfn",
        "default",
        "dynamodb",
        "ecr",
        "env",
        "envvar",
        "file",
        "hook_data",
        "kms",
        "output",
        "random.string",
        "rxref",
        "split",
        "ssm",
        "xref",
    ]
    for handler in handlers:
        assert handler in CFNGIN_LOOKUP_HANDLERS, f'Lookup handler: "{handler}" not registered'
    assert len(CFNGIN_LOOKUP_HANDLERS) == len(handlers), (
        f"expected {len(handlers)} autoloaded handlers but found {len(CFNGIN_LOOKUP_HANDLERS)}"
    )


def test_register_lookup_handler_function() -> None:
    """Test register_lookup_handler function.

    Verifies that plain functions are rejected because lookup handlers must be
    classes that inherit from LookupHandler to guarantee a consistent interface.
    """

    def fake_lookup(**_: Any) -> None:
        """Fake lookup."""

    with pytest.raises(TypeError):
        register_lookup_handler("test", fake_lookup)


def test_register_lookup_handler_not_subclass() -> None:
    """Test register_lookup_handler no subclass.

    Verifies that arbitrary classes not inheriting from the base handler are
    rejected, enforcing the type contract for all registered lookups.
    """

    class FakeLookup:
        """Fake lookup."""

    with pytest.raises(TypeError):
        register_lookup_handler("test", FakeLookup)


def test_register_lookup_handler_str(mocker: MockerFixture) -> None:
    """Test register_lookup_handler from string.

    Validates the string-based registration path used by config files, where
    handlers are specified as dotted import paths rather than class references.
    """
    mocker.patch.dict(CFNGIN_LOOKUP_HANDLERS, {})
    register_lookup_handler("test", "runway.cfngin.lookups.handlers.default.DefaultLookup")
    assert "test" in CFNGIN_LOOKUP_HANDLERS
    assert CFNGIN_LOOKUP_HANDLERS["test"] == DefaultLookup


def test_unregister_lookup_handler(mocker: MockerFixture) -> None:
    """Test unregister_lookup_handler.

    Confirms handlers can be cleanly removed, which is needed for testing
    isolation and for users who want to override built-in lookup behavior.
    """
    mocker.patch.dict(CFNGIN_LOOKUP_HANDLERS, {"test": "something"})
    assert "test" in CFNGIN_LOOKUP_HANDLERS
    unregister_lookup_handler("test")
    assert "test" not in CFNGIN_LOOKUP_HANDLERS
