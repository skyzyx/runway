"""AWS ECS hook.

This module exists because ECS clusters must be created before CloudFormation
stacks that reference them can be deployed, and the cluster creation API is
simple enough to call directly rather than managing a separate stack.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import field_validator
from typing_extensions import TypedDict

from ...utils import BaseModel

if TYPE_CHECKING:
    from mypy_boto3_ecs.type_defs import CreateClusterResponseTypeDef

    from ...context import CfnginContext

LOGGER = logging.getLogger(__name__)


class CreateClustersHookArgs(BaseModel):
    """Hook arguments for ``create_clusters``.

    Uses a Pydantic model to allow users to pass either a single cluster name
    string or a list, normalizing the input before the hook logic runs.
    """

    clusters: list[str]
    """List of cluster names to create."""

    @field_validator("clusters", mode="before")
    @classmethod
    def _convert_clusters(cls, v: list[str] | str) -> list[str]:
        """Convert value of ``clusters`` from str to list.

        Allows YAML authors to specify a single cluster as a plain string
        for convenience while the hook logic always operates on a list.
        """
        if isinstance(v, str):
            return [v]
        return v


class CreateClustersResponseTypeDef(TypedDict):
    """Response from create_clusters."""

    clusters: dict[str, CreateClusterResponseTypeDef]


def create_clusters(
    context: CfnginContext, *_args: Any, **kwargs: Any
) -> CreateClustersResponseTypeDef:
    """Create ECS clusters.

    This hook enables pre-creating ECS clusters as a prerequisite so that
    subsequent stacks can reference the cluster names without circular
    dependencies between the cluster and the services deployed into it.

    Args:
        context: CFNgin context object.
        **kwargs: Arbitrary keyword arguments.

    """
    args = CreateClustersHookArgs.model_validate(kwargs)
    ecs_client = context.get_session().client("ecs")

    cluster_info: dict[str, Any] = {}
    for cluster in args.clusters:
        LOGGER.debug("creating ECS cluster: %s", cluster)
        response = ecs_client.create_cluster(clusterName=cluster)
        cluster_info[response.get("cluster", {}).get("clusterName", "")] = response
    return {"clusters": cluster_info}
