"""CFNgin environment file parsing.

This module exists to decouple environment variable resolution from
the CFNgin configuration loader, allowing environment files to be
parsed independently and merged into parameters during config loading.
"""

from typing import Any


def parse_environment(raw_environment: str) -> dict[str, Any]:
    """Parse environment file contents.

    This provides a simple key:value file format so that operators can
    parameterize CFNgin configs per-environment without modifying the
    config files themselves.

    Args:
        raw_environment: Environment file read into a string.

    """
    environment: dict[str, Any] = {}
    for raw_line in raw_environment.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        # Allow operators to annotate environment files with
        # human-readable context without affecting parsed output.
        if line.startswith("#"):
            continue

        # Split on first colon only so that values containing colons
        # (e.g., ARNs, URLs) are preserved intact.
        try:
            key, value = line.split(":", 1)
        except ValueError:
            raise ValueError("Environment must be in key: value format") from None

        environment[key] = value.strip()
    return environment
