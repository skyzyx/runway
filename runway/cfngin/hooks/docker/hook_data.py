"""Docker hook_data object.

Provides a shared state container persisted in the CFNgin context's hook_data
dict so that sequential Docker hooks (login → build → push → remove) can
share the Docker client connection and built image reference without redundant
initialization.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, overload

from docker import DockerClient

from ....compat import cached_property
from ....utils import MutableMap

if TYPE_CHECKING:
    from ....context import CfnginContext
    from .data_models import DockerImage


class DockerHookData(MutableMap):
    """Docker hook_data object.

    Extends MutableMap to act as the single source of truth for Docker state
    within a CFNgin run, stored under context.hook_data["docker"] so downstream
    hooks and lookups can retrieve the client and built image without
    re-initializing.
    """

    image: DockerImage | None = None

    @cached_property
    def client(self) -> DockerClient:
        """Docker client.

        Lazily initialized from environment variables so the Docker socket
        connection is only opened when a hook actually needs it.
        """
        return DockerClient.from_env()

    @overload
    def update_context(self, context: CfnginContext) -> DockerHookData: ...

    @overload
    def update_context(self, context: None = ...) -> None: ...

    def update_context(self, context: CfnginContext | None = None) -> DockerHookData | None:
        """Update context object with new the current DockerHookData.

        Persists the current state back into the context so that subsequent
        hooks in the same CFNgin configuration see the latest image and client.
        """
        if not context:
            return None
        context.hook_data["docker"] = self
        return self

    @classmethod
    def from_cfngin_context(cls, context: CfnginContext) -> DockerHookData:
        """Get existing object or create a new one.

        Ensures a single DockerHookData instance per CFNgin run, reusing an
        existing one (and its cached client) if a prior Docker hook already
        stored it in hook_data.
        """
        if "docker" in context.hook_data:
            found = context.hook_data["docker"]
            if isinstance(found, cls):
                return found
        new_obj = cls()
        context.hook_data["docker"] = new_obj
        return new_obj

    def __bool__(self) -> bool:
        """Implement evaluation of instances as a bool."""
        return True
