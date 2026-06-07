"""CFNgin lookups.

This package exists as a namespace boundary so that lookup handlers, the
registry, and helper utilities can be organized into submodules while
presenting a flat public API to the rest of cfngin.
"""

# Re-export registry functions here so consumers can import directly from the
# lookups package without knowing the internal module layout.
from .registry import register_lookup_handler, unregister_lookup_handler

__all__ = ["register_lookup_handler", "unregister_lookup_handler"]
