"""CFNgin UI manipulation.

This module centralizes all terminal output behind a thread-safe lock so that
concurrent stack operations do not interleave log lines or user prompts.
"""

from __future__ import annotations

import logging
import threading
from contextlib import AbstractContextManager
from getpass import getpass
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from types import TracebackType

    from typing_extensions import Self

LOGGER = logging.getLogger(__name__)


def get_raw_input(message: str) -> str:
    """Just a wrapper for :func:`input` for testing purposes.

    This indirection exists so tests can monkeypatch user input without
    patching the built-in ``input`` globally.
    """
    return input(message)


class UI(AbstractContextManager["UI"]):
    """Used internally from terminal output in a multithreaded environment.

    Ensures that two threads don't write over each other while asking a user
    for input (e.g. in interactive mode).

    CFNgin executes stack operations concurrently via a DAG-based plan, so
    a shared lock is needed to serialize any output that reaches the terminal.
    """

    def __init__(self) -> None:
        """Instantiate class."""
        # RLock (reentrant) allows nested acquire from the same thread,
        # which is necessary because log() acquires the lock and may be
        # called from within an already-locked context manager block.
        self._lock = threading.RLock()

    def log(
        self,
        lvl: int,
        msg: Exception | str,
        *args: Any,
        logger: logging.Logger | logging.LoggerAdapter[Any] = LOGGER,
        **kwargs: Any,
    ) -> None:
        """Log the message if the current thread owns the underlying lock.

        Acquiring the lock before logging prevents garbled output when multiple
        worker threads report stack status simultaneously.

        Args:
            lvl: Log level.
            msg: String template or exception to use for the log record.
            logger: Specific logger to log to.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        kwargs["stacklevel"] = kwargs.get("stacklevel", 1) + 1
        # Acquire the lock via the context manager to ensure atomic output,
        # then delegate to the provided logger so callers can target different
        # loggers while still benefiting from the thread-safety guarantee.
        with self:
            return logger.log(lvl, msg, *args, **kwargs)

    def info(
        self,
        msg: str,
        *args: Any,
        logger: logging.Logger | logging.LoggerAdapter[Any] = LOGGER,
        **kwargs: Any,
    ) -> None:
        """Log the line if the current thread owns the underlying lock.

        Args:
            msg: String template or exception to use
                for the log record.
            logger: Specific logger to log to.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        """
        kwargs["logger"] = logger
        self.log(logging.INFO, msg, *args, **kwargs)

    def ask(self, message: str) -> str:
        """Collect input from a user in a multithreaded environment.

        This wraps the built-in input function to ensure that only 1
        thread is asking for input from the user at a give time. Any process
        that tries to log output to the terminal will be blocked while the
        user is being prompted.

        Locking during prompts prevents other threads from printing status
        updates that would obscure the question or confuse the user.
        """
        with self:
            return get_raw_input(message)

    def getpass(self, prompt: str, stream: TextIO | None = None) -> str:
        """Wrap getpass to lock the UI.

        Ensures password entry is not interrupted by concurrent log output
        that could reveal terminal echo state changes.
        """
        with self:
            return getpass(prompt, stream)

    def __enter__(self) -> Self:
        """Enter the context manager."""
        self._lock.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the context manager."""
        self._lock.__exit__(exc_type, exc_value, traceback)


# Global UI singleton so all cfngin modules share one lock instance,
# ensuring consistent serialization of terminal output across the process.
ui = UI()
