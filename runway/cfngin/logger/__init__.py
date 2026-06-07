"""CFNgin logger.

Centralizes log format configuration so all CFNgin components produce
consistent, timestamped output. Color and verbosity are controlled from a
single entry point rather than scattered across modules.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

# Three format tiers provide progressively more detail: INFO for normal
# operation, COLOR for interactive terminals, DEBUG for troubleshooting
# with thread and source location context.
DEBUG_FORMAT = (
    "[%(asctime)s] %(levelname)s %(threadName)s %(name)s:%(lineno)d(%(funcName)s): %(message)s"
)
INFO_FORMAT = "[%(asctime)s] %(message)s"
COLOR_FORMAT = "[%(asctime)s] \033[%(color)sm%(message)s\033[39m"

ISO_8601 = "%Y-%m-%dT%H:%M:%S"


class ColorFormatter(logging.Formatter):
    """Handles colorizing formatted log messages if color provided.

    Provides a safe default color code so log records without an explicit
    color attribute don't raise KeyError during format string interpolation.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log message."""
        if "color" not in record.__dict__:
            record.__dict__["color"] = 37
        return super().format(record)


def setup_logging(verbosity: int, formats: dict[str, Any] | None = None) -> None:
    """Configure a proper logger based on verbosity and optional log formats.

    Single entry point for log setup ensures all CFNgin threads share the same
    handler and format, preventing interleaved or inconsistent output during
    parallel stack operations.

    Args:
        verbosity: 0, 1, 2
        formats: Keys (``info``, ``color``, ``debug``) which may override the
            associated default log formats.

    """
    if formats is None:
        formats = {}

    log_level = logging.INFO

    log_format = formats.get("info", INFO_FORMAT)

    if sys.stdout.isatty():
        log_format = formats.get("color", COLOR_FORMAT)

    if verbosity > 0:
        log_level = logging.DEBUG
        log_format = formats.get("debug", DEBUG_FORMAT)

    # Suppress botocore's extremely verbose debug logging unless the user
    # explicitly requests maximum verbosity (level 2+), as it drowns out
    # CFNgin's own diagnostic output.
    if verbosity < 2:
        logging.getLogger("botocore").setLevel(logging.CRITICAL)

    hdlr = logging.StreamHandler()
    hdlr.setFormatter(ColorFormatter(log_format, ISO_8601))
    logging.root.addHandler(hdlr)
    logging.root.setLevel(log_level)
