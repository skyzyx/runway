"""Tests for runway.cfngin.hooks.command."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from runway.cfngin.exceptions import ImproperlyConfigured
from runway.cfngin.hooks.command import run_command

if TYPE_CHECKING:
    from pytest_subprocess import FakeProcess


def test_run_command(fake_process: FakeProcess) -> None:
    """Test run_command.

    Validates the basic happy path: a command that exits 0 returns the
    expected result dict with returncode and null stdio fields.
    """
    fake_process.register_subprocess(["foo"], returncode=0)
    assert run_command(command=["foo"]) == {
        "returncode": 0,
        "stderr": None,
        "stdout": None,
    }


def test_run_command_capture(fake_process: FakeProcess) -> None:
    """Test run_command with ``capture``.

    Ensures stdout/stderr are captured and returned when capture=True,
    which downstream hooks rely on for parsing command output.
    """
    fake_process.register_subprocess(["foo"], returncode=0, stderr="bar", stdout="foobar")
    assert run_command(command=["foo"], capture=True) == {
        "returncode": 0,
        "stderr": b"bar",  # for some reason, pytest-subprocess returns these as bytes
        "stdout": b"foobar",
    }


def test_run_command_env(fake_process: FakeProcess) -> None:
    """Test run_command with ``env``.

    Confirms that custom environment variables can be passed without
    affecting the return structure or causing errors.
    """
    fake_process.register_subprocess(["foo"], returncode=0)
    assert run_command(command=["foo"], env={"TEST": "bar"}) == {
        "returncode": 0,
        "stderr": None,
        "stdout": None,
    }


def test_run_command_fail(fake_process: FakeProcess) -> None:
    """Test run_command non-zero exit code.

    Verifies that a non-zero exit code returns falsy so the hook framework
    treats it as a failure and can abort the pipeline.
    """
    fake_process.register_subprocess(["foo"], returncode=1)
    assert not run_command(command=["foo"])


def test_run_command_interactive(fake_process: FakeProcess) -> None:
    """Test run_command with ``interactive``.

    Ensures the interactive flag path still returns the expected dict
    structure; interactive mode affects stdio handling differently.
    """
    fake_process.register_subprocess(["foo"], returncode=0)
    assert run_command(command=["foo"], interactive=True) == {
        "returncode": 0,
        "stderr": None,
        "stdout": None,
    }


def test_run_command_ignore_status(fake_process: FakeProcess) -> None:
    """Test run_command with ``ignore_status``.

    Validates that ignore_status=True returns the result dict even on
    non-zero exit, allowing callers to inspect output without hook failure.
    """
    fake_process.register_subprocess(["foo"], returncode=1)
    assert run_command(command=["foo"], ignore_status=True) == {
        "returncode": 1,
        "stderr": None,
        "stdout": None,
    }


def test_run_command_quiet(fake_process: FakeProcess) -> None:
    """Test run_command with ``quiet``.

    Confirms that quiet mode suppresses output (returns None for stdio)
    while still reporting the exit code.
    """
    fake_process.register_subprocess(["foo"], returncode=0, stderr="", stdout="")
    assert run_command(command=["foo"], quiet=True) == {
        "returncode": 0,
        "stderr": None,
        "stdout": None,
    }


def test_run_command_raise_improperly_configured() -> None:
    """Test run_command raise ``ImproperlyConfigured``.

    Capture and quiet are mutually exclusive options; this validates that
    the hook raises early rather than producing confusing behavior.
    """
    with pytest.raises(ImproperlyConfigured):
        run_command(command=["foo"], capture=True, quiet=True)


def test_run_command_stdin(fake_process: FakeProcess) -> None:
    """Test run_command with ``stdin``.

    Ensures stdin data can be provided to the subprocess without
    affecting the return structure.
    """
    fake_process.register_subprocess(["foo"], returncode=0)
    assert run_command(command=["foo"], stdin="bar") == {
        "returncode": 0,
        "stderr": None,
        "stdout": None,
    }
