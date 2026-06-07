"""Test runway.cfngin.exceptions.

Validates that cfngin exception classes produce correct human-readable
messages from various combinations of optional parameters. These messages
surface directly in CLI output, so formatting correctness affects
operator experience during deploy failures.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from runway.cfngin.exceptions import (
    CfnginBucketRequired,
    InvalidConfig,
    PersistentGraphLocked,
    PersistentGraphUnlocked,
)

if TYPE_CHECKING:
    from runway.type_defs import AnyPath


class TestCfnginBucketRequired:
    """Test CfnginBucketRequired.

    This exception is raised when a cfngin operation needs S3 storage (for
    templates, persistent graph) but no bucket is configured. The message must
    clearly indicate which config triggered the error.
    """

    # Parametrized to cover all combinations of optional fields (config_path,
    # reason) since the message format changes depending on which are provided.
    @pytest.mark.parametrize(
        "config_path, reason, expected",
        [
            (None, None, ""),
            ("./test", None, f" ({Path('./test')})"),
            (Path("/tmp"), "something", f"; something ({Path('/tmp')})"),
        ],
    )
    def test___init__(self, config_path: AnyPath | None, reason: str | None, expected: str) -> None:
        """Test __init__."""
        expected_msg = f"cfngin_bucket is required{expected}"
        obj = CfnginBucketRequired(config_path=config_path, reason=reason)
        assert obj.message == expected_msg
        if config_path:
            if isinstance(config_path, str):
                assert obj.config_path == Path(config_path)
            else:
                assert obj.config_path == config_path


class TestInvalidConfig:
    """Test InvalidConfig.

    InvalidConfig aggregates one or more validation errors into a single
    exception. Tests verify both single-string and list-of-errors inputs
    produce correctly formatted messages for CLI display.
    """

    @pytest.mark.parametrize(
        "errors, expected_msg",
        [("error", "error"), (["error0", "error1"], "error0\nerror1")],
    )
    def test___init__(self, errors: str | list[Exception | str], expected_msg: str) -> None:
        """Test __init__."""
        obj = InvalidConfig(errors)
        assert obj.errors == errors
        assert obj.message == expected_msg


class TestPersistentGraphLocked:
    """Test PersistentGraphLocked.

    The persistent graph lock prevents concurrent cfngin runs from corrupting
    shared state. These tests verify message construction for all combinations
    of custom message vs reason parameters.
    """

    @pytest.mark.parametrize(
        "message, reason, expected_msg",
        [
            (
                None,
                None,
                "Persistent graph is locked. This action requires the graph to "
                "be unlocked to be executed.",
            ),
            ("message", None, "message"),
            ("message", "reason", "message"),
            (None, "reason", "Persistent graph is locked. reason"),
        ],
    )
    def test___init__(self, message: str | None, reason: str | None, expected_msg: str) -> None:
        """Test __init__."""
        obj = PersistentGraphLocked(message=message, reason=reason)
        assert obj.message == expected_msg


class TestPersistentGraphUnlocked:
    """Test PersistentGraphUnlocked.

    Counterpart to the locked exception — raised when an operation requires
    the graph to be locked but it isn't. Same parametrized pattern verifies
    consistent message formatting between both lock-state exceptions.
    """

    @pytest.mark.parametrize(
        "message, reason, expected_msg",
        [
            (
                None,
                None,
                "Persistent graph is unlocked. This action requires the graph to "
                "be locked to be executed.",
            ),
            ("message", None, "message"),
            ("message", "reason", "message"),
            (None, "reason", "Persistent graph is unlocked. reason"),
        ],
    )
    def test___init__(self, message: str | None, reason: str | None, expected_msg: str) -> None:
        """Test __init__."""
        obj = PersistentGraphUnlocked(message=message, reason=reason)
        assert obj.message == expected_msg
