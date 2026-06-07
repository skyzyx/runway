"""Docker login hook.

Authenticates with a Docker registry before build/push operations so that
subsequent hooks in the same CFNgin config can push images without separate
credential management steps.

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from ....context import CfnginContext
from ....utils import BaseModel
from .data_models import ElasticContainerRegistry
from .hook_data import DockerHookData

if TYPE_CHECKING:
    from pydantic import ValidationInfo

LOGGER = logging.getLogger(__name__.replace("._", "."))


class LoginArgs(BaseModel):
    """Args passed to the docker.login hook.

    Validates and normalizes login credentials, supporting both explicit
    registry URIs and ECR shorthand so users can authenticate to ECR with
    minimal configuration (just the ECR block) instead of constructing the
    full registry URI themselves.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ctx: Annotated[CfnginContext | None, Field(alias="context", exclude=True)] = None

    dockercfg_path: str | None = None
    """Path to a non-default Docker config file."""

    ecr: ElasticContainerRegistry | None = Field(default=None, exclude=True)
    """Information describing an ECR registry."""

    email: str | None = None
    """The email for the registry account."""

    password: str
    """The plaintext password for the registry account."""

    registry: Annotated[str | None, Field(validate_default=True)] = None
    """URI of the registry to login to."""

    username: str = "AWS"
    """The registry username."""

    @model_validator(mode="before")
    @classmethod
    def _set_ecr(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Set the value of ``ecr``.

        Eagerly constructs the ElasticContainerRegistry model so that
        the registry field validator can derive the URI from it without
        needing to re-parse the raw dict.
        """
        if "ecr" in values and isinstance(values["ecr"], dict):
            values["ecr"] = ElasticContainerRegistry.model_validate(
                {"context": values.get("context"), **values["ecr"]}
            )
        return values

    @field_validator("registry", mode="before")
    @classmethod
    def _set_registry(cls, v: Any, info: ValidationInfo) -> Any:
        """Set the value of ``registry``.

        Falls back to the ECR fully qualified name when no explicit registry
        is provided, enabling ECR authentication with only the ecr config block.
        """
        if v:
            return v

        ecr: ElasticContainerRegistry | None = info.data.get("ecr")
        if ecr:
            return ecr.fqn

        return None


def login(*, context: CfnginContext, **kwargs: Any) -> DockerHookData:
    """Docker login hook.

    Replicates the functionality of ``docker login`` cli command.

    This hook must run before build/push hooks so that the Docker daemon has
    valid credentials for the target registry.

    kwargs are parsed by :class:`~runway.cfngin.hooks.docker.LoginArgs`.

    """
    args = LoginArgs.model_validate({"context": context, **kwargs})
    docker_hook_data = DockerHookData.from_cfngin_context(context)
    docker_hook_data.client.login(**args.model_dump())
    LOGGER.info("logged into %s", args.registry)
    return docker_hook_data.update_context(context)
