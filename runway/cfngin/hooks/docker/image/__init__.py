"""Docker image actions & argument parsers.

Replicates the functionality of ``docker image`` CLI commands.

Groups build, push, and remove operations under a single namespace so CFNgin
hook paths mirror the Docker CLI structure (docker.image.build, etc.) and
callers can import all image operations from one location.

"""

from ._build import DockerImageBuildApiOptions, ImageBuildArgs, build
from ._push import ImagePushArgs, push
from ._remove import ImageRemoveArgs, remove

__all__ = [
    "DockerImageBuildApiOptions",
    "ImageBuildArgs",
    "ImagePushArgs",
    "ImageRemoveArgs",
    "build",
    "push",
    "remove",
]
