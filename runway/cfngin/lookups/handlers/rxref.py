"""Handler for fetching outputs from a stack in the current namespace."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from ....lookups.handlers.base import LookupHandler
from ....lookups.handlers.cfn import CfnLookup
from ....utils import DOC_SITE
from .output import OutputQuery, deconstruct

if TYPE_CHECKING:
    from ....context import CfnginContext
    from ....lookups.handlers.base import ParsedArgsTypeDef
    from ...providers.aws.default import Provider

LOGGER = logging.getLogger(__name__)


class RxrefLookup(LookupHandler["CfnginContext"]):
    """Rxref lookup.

    Provides a relative cross-reference that automatically prepends the current
    CFNgin namespace to the stack name, so config authors can reference stacks
    in the same namespace without hard-coding the fully-qualified name.
    """

    DEPRECATION_MSG = (
        'lookup query syntax "<relative-stack-name>::<OutputName>" has been deprecated; '
        "to learn how to use the new lookup query syntax visit "
        f"{DOC_SITE}/page/cfngin/lookups/rxref.html"
    )
    TYPE_NAME: ClassVar[str] = "rxref"
    """Name that the Lookup is registered as."""

    @classmethod
    def legacy_parse(cls, value: str) -> tuple[OutputQuery, ParsedArgsTypeDef]:
        """Retain support for legacy lookup syntax.

        Preserves backward compatibility with the deprecated ``::`` separator
        so existing configs continue working during the migration to the new
        dot-separated query format.

        Format of value:
            <relative-stack-name>::<OutputName>

        """
        LOGGER.warning("${%s %s}: %s", cls.TYPE_NAME, value, cls.DEPRECATION_MSG)
        return deconstruct(value), {}

    @classmethod
    def handle(cls, value: str, context: CfnginContext, *, provider: Provider, **_: Any) -> Any:
        """Fetch an output from the designated stack in the current namespace.

        The ``output`` lookup supports fetching outputs from stacks created
        within a single config file. Sometimes it's useful to fetch outputs
        from stacks created outside of the current config file but using the
        same namespace. ``rxref`` supports this by using the
        :class:`runway.context.CfnginContext` to expand the fqn of the stack.

        Args:
            value: Parameter(s) given to this lookup. `"<relative-stack-name>.<OutputName>``
            context: Context instance.
            provider: Provider instance.

        """
        try:
            raw_query, _args = cls.parse(value)
            query = OutputQuery(*raw_query.split("."))
            colon_split = value.split("::", 1)
            raw_args = colon_split[1] if len(colon_split) > 1 else ""
        except ValueError:
            query, _args = cls.legacy_parse(value)
            raw_args = ""
        # Expand the relative stack name to a fully-qualified name using the
        # current namespace, then delegate to CfnLookup which handles the
        # actual CloudFormation API call.
        stack_fqn = context.get_fqn(query.stack_name)
        return CfnLookup.handle(
            f"{stack_fqn}.{query.output_name}" + (f"::{raw_args}" if raw_args else ""),
            context=context,
            provider=provider,
        )
