"""Hook data models.

These are makeshift data models for use until Runway v2 is released and pydantic
can be used.

Typed models centralize validation and URI construction for Docker/ECR
resources, preventing raw dict manipulation from scattering registry-specific
logic across multiple hook functions.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, ClassVar, cast

from docker.models.images import Image
from pydantic import ConfigDict, Field, PrivateAttr, model_validator

from ....core.providers.aws import AccountDetails
from ....utils import BaseModel, MutableMap

if TYPE_CHECKING:
    from ....context import CfnginContext

ECR_REPO_FQN_TEMPLATE = "{aws_account_id}.dkr.ecr.{aws_region}.amazonaws.com/{repo_name}"


class ElasticContainerRegistry(BaseModel):
    """AWS Elastic Container Registry.

    Encapsulates the public/private ECR distinction so that hook callers
    provide registry details declaratively and the model constructs the
    correct URI format automatically.
    """

    PUBLIC_URI_TEMPLATE: ClassVar[str] = "public.ecr.aws/{registry_alias}/"
    URI_TEMPLATE: ClassVar[str] = "{aws_account_id}.dkr.ecr.{aws_region}.amazonaws.com/"

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    account_id: str | None = None
    """AWS account ID that owns the registry being logged into."""

    alias: str | None = None
    """If it is a public repository, the alias of the repository."""

    public: bool = True
    """Whether the repository is public."""

    region: str | None = Field(default=None, alias="aws_region")
    """AWS region where the registry is located."""

    @property
    def fqn(self) -> str:
        """Fully qualified ECR name."""
        if self.public:
            return self.PUBLIC_URI_TEMPLATE.format(registry_alias=self.alias)
        return self.URI_TEMPLATE.format(aws_account_id=self.account_id, aws_region=self.region)

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Set default values based on other values.

        Derives public/private state and resolves account_id/region from the
        CFNgin context when not explicitly provided, so callers only need to
        supply the minimum required configuration.
        """
        values.setdefault("public", bool(values.get("alias")))

        if not values["public"]:
            account_id = values.get("account_id")
            ctx: CfnginContext | None = values.get("context")
            aws_region = values.get("aws_region")
            if not ctx and not (account_id or aws_region):
                raise ValueError("context is required to resolve values")
            if ctx:
                if not account_id:
                    values["account_id"] = AccountDetails(ctx).id
                if not aws_region:
                    values["aws_region"] = ctx.env.aws_region or "us-east-1"
        return values


class DockerImage(BaseModel):
    """Wrapper for :class:`docker.models.images.Image`.

    Provides a stable, serializable interface over the Docker SDK's Image
    object so that downstream hooks can access tags and URIs without coupling
    to the SDK's mutable attrs dict.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _repo: str | None = PrivateAttr(default=None)
    image: Image

    @property
    def id(self) -> str:
        """ID of the image."""
        return self.image.id

    @property
    def repo(self) -> str:
        """Repository URI.

        Extracts the repo from the first RepoTag because the Docker SDK does
        not expose the repository name as a dedicated attribute.
        """
        if not self._repo:
            self._repo = self.image.attrs["RepoTags"][0].rsplit(":", 1)[0]
        return cast("str", self._repo)

    @property
    def short_id(self) -> str:
        """ID of the image truncated to 10 characters plus the ``sha256:`` prefix."""
        return self.image.short_id

    @property
    def tags(self) -> list[str]:
        """List of image tags.

        Calls reload() to pick up any tags applied after the image was first
        built, since the Docker SDK caches the initial state.
        """
        self.image.reload()
        return [uri.split(":")[-1] for uri in self.image.tags]

    @property
    def uri(self) -> MutableMap:
        """Return a mapping of tag to image URI.

        Presents tags as a MutableMap so CFNgin lookups can reference
        individual image URIs by tag name (e.g. hook_data docker.image.uri.latest).
        """
        return MutableMap(**{uri.split(":")[-1]: uri for uri in self.image.tags})

    def __bool__(self) -> bool:
        """Evaluate the boolean value of the object instance."""
        return True


class ElasticContainerRegistryRepository(BaseModel):
    """AWS Elastic Container Registry (ECR) Repository.

    Combines a registry reference with a repository name so that the fully
    qualified image URI can be derived without manual string concatenation
    in hook configurations.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: Annotated[str, Field(alias="repo_name")]
    """The name of the repository."""

    registry: ElasticContainerRegistry
    """Information about an ECR registry."""

    @property
    def fqn(self) -> str:
        """Fully qualified ECR repo name."""
        return self.registry.fqn + self.name
