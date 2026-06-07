"""CFNgin hook for cleaning up resources prior to CFN stack deletion.

This module exists because SSM parameters created by hooks are not managed by
CloudFormation; they must be explicitly deleted before stack teardown to avoid
orphaned parameters accumulating in the account.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ...utils import BaseModel

if TYPE_CHECKING:
    from ...context import CfnginContext

LOGGER = logging.getLogger(__name__)


class DeleteParamHookArgs(BaseModel):
    """Hook arguments for ``delete_param``.

    Provides validated, typed access to the parameter name so the hook can
    rely on Pydantic validation rather than manual kwarg parsing.
    """

    parameter_name: str
    """Name of the bucket to purge."""


def delete_param(context: CfnginContext, *__args: Any, **kwargs: Any) -> bool:
    """Delete SSM parameter.

    Removes hook-managed SSM parameters that CloudFormation does not track,
    preventing orphaned parameters from persisting after stack deletion.
    """
    args = DeleteParamHookArgs.model_validate(kwargs)

    session = context.get_session()
    ssm_client = session.client("ssm")

    # Treat ParameterNotFound as success; the parameter may have already been
    # deleted in a previous run or by manual cleanup.
    try:
        ssm_client.delete_parameter(Name=args.parameter_name)
    except ssm_client.exceptions.ParameterNotFound:
        LOGGER.info('parameter "%s" does not exist', args.parameter_name)
    return True
