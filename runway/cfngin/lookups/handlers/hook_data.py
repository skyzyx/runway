"""Hook data lookup.

This lookup bridges the gap between hook execution and stack configuration,
allowing hooks (which run before stacks) to pass computed values into stack
parameters without requiring intermediate config file modifications.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from troposphere import BaseAWSObject

from ....lookups.handlers.base import LookupHandler
from ....utils import MutableMap

if TYPE_CHECKING:
    from ....context import CfnginContext

LOGGER = logging.getLogger(__name__)


class HookDataLookup(LookupHandler["CfnginContext"]):
    """Hook data lookup.

    Retrieves values stored by pre_deploy hooks into the context's hook_data
    dict, enabling data flow between the hook phase and the stack phase without
    coupling the two through config file changes.
    """

    TYPE_NAME: ClassVar[str] = "hook_data"
    """Name that the Lookup is registered as."""

    @classmethod
    def handle(cls, value: str, context: CfnginContext, **_: Any) -> Any:
        """Return the data from ``hook_data``.

        Args:
            value: Parameter(s) given to this lookup.
            context: Context instance.

        """
        query, args = cls.parse(value)

        hook_data = MutableMap(**context.hook_data)

        result = hook_data.find(query, args.get("default"))

        # Auto-detect Troposphere objects and set load="troposphere" so that
        # format_results can serialize them correctly for CloudFormation.
        if isinstance(result, BaseAWSObject) and args.get("get") and not args.get("load"):
            args["load"] = "troposphere"

        if not result:
            raise ValueError(f'Could not find a value for "{value}"')

        if result == args.get("default"):
            # assume default value has already been processed so no need to
            # use these
            args.pop("load", None)
            args.pop("get", None)

        return cls.format_results(result, **args)
