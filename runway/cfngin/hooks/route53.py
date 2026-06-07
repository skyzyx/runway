"""AWS Route 53 hook.

This module pre-creates Route 53 hosted zones so that other stacks can
reference the zone ID without introducing a dependency on the DNS stack
itself, enabling parallel deployment of resources that need DNS records.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ...utils import BaseModel
from ..utils import create_route53_zone

if TYPE_CHECKING:
    from ...context import CfnginContext

LOGGER = logging.getLogger(__name__)


class CreateDomainHookArgs(BaseModel):
    """Hook arguments for ``create_domain``."""

    domain: str
    """Domain name for the Route 53 hosted zone to be created."""


def create_domain(context: CfnginContext, *_args: Any, **kwargs: Any) -> dict[str, str]:
    """Create a domain within route53.

    This hook delegates to the shared ``create_route53_zone`` utility so that
    zone creation is idempotent and the zone_id can be stored in hook_data
    for downstream stacks to reference.

    Args:
        context: CFNgin context object.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dict containing ``domain`` and ``zone_id``.

    """
    args = CreateDomainHookArgs.model_validate(kwargs)
    client = context.get_session().client("route53")
    zone_id = create_route53_zone(client, args.domain)
    return {"domain": args.domain, "zone_id": zone_id}
