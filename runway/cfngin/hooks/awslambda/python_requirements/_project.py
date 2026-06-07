"""Python project.

Extends the base Project class with Python-specific metadata detection
(poetry vs pip), dependency export, and installation orchestration so
the hook framework can handle both poetry and pip projects transparently.

"""

from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING, ClassVar

from .....compat import cached_property
from .....dependency_managers import Pip, Poetry, PoetryNotFoundError
from ..base_classes import Project
from ..models.args import PythonHookArgs
from . import PythonDockerDependencyInstaller

if TYPE_CHECKING:
    from pathlib import Path

    from typing_extensions import Literal

LOGGER = logging.getLogger(__name__.replace("._", "."))


class PythonProject(Project[PythonHookArgs]):
    """Python project.

    Specializes the generic Project with pip/poetry detection, requirements
    export, and Docker-based installation routing, because Python has two
    competing dependency managers that require different export and install
    strategies.

    """

    DEFAULT_CACHE_DIR_NAME: ClassVar[str] = "pip_cache"
    """Name of the default cache directory."""

    @cached_property
    def docker(self) -> PythonDockerDependencyInstaller | None:
        """Docker interface that can be used to build the project.

        Returns a Docker installer when Docker is configured, enabling compiled
        C extensions to be built against the Lambda execution environment's OS.

        """
        return PythonDockerDependencyInstaller.from_project(self)

    @cached_property
    def metadata_files(self) -> tuple[Path, ...]:
        """Project metadata files.

        Files are only included in return value if they exist.

        Identifies which config files are present to compute a cache key that
        changes whenever dependency specifications change.

        """
        if self.project_type == "poetry":
            config_files = [self.project_root / config_file for config_file in Poetry.CONFIG_FILES]
        else:
            config_files = [self.project_root / config_file for config_file in Pip.CONFIG_FILES]
        return tuple(path for path in config_files if path.exists())

    @cached_property
    def runtime(self) -> str:
        """Runtime of the build system.

        Value should be a valid Lambda Function runtime
        (https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html).

        Prefers the Docker container's detected runtime over the local pip
        version, because Docker-built dependencies must match the container's
        Python version rather than the host's.

        """
        if self._runtime_from_docker:
            return self._validate_runtime(self._runtime_from_docker)
        return self._validate_runtime(
            f"python{self.pip.python_version.major}.{self.pip.python_version.minor}"
        )

    @cached_property
    def pip(self) -> Pip:
        """Pip dependency manager.

        Always available regardless of project type, because pip is the
        underlying installer even when poetry is used for dependency resolution.

        """
        return Pip(self.ctx, self.project_root)

    @cached_property
    def poetry(self) -> Poetry | None:
        """Poetry dependency manager.

        Return:
            If the project uses poetry and poetry is not explicitly disabled,
            an object for interfacing with poetry will be returned.

        Raises:
            PoetryNotFound: poetry is not installed or not found in PATH.

        Provides a poetry interface only when the project actually uses poetry,
        allowing the hook to export a requirements.txt from pyproject.toml
        lock data for pip-based installation.

        """
        if self.project_type != "poetry":
            return None
        if Poetry.found_in_path():
            return Poetry(self.ctx, self.project_root)
        raise PoetryNotFoundError

    @cached_property
    def project_type(self) -> Literal["pip", "poetry"]:
        """Type of python project.

        Auto-detects the project type by checking for poetry markers while
        respecting the user's explicit opt-out, enabling transparent support
        for both dependency managers without manual configuration.

        """
        if Poetry.dir_is_project(self.project_root):
            if self.args.use_poetry:
                return "poetry"
            LOGGER.warning("poetry project detected but use of poetry is explicitly disabled")
        return "pip"

    @cached_property
    def requirements_txt(self) -> Path | None:
        """Dependency file for the project.

        Provides a unified requirements.txt path regardless of whether
        dependencies are managed by pip directly or exported from poetry,
        because pip install always consumes a requirements.txt file.

        """
        if self.poetry:  # prioritize poetry
            return self.poetry.export(output=self.tmp_requirements_txt)
        requirements_txt = self.project_root / "requirements.txt"
        if Pip.dir_is_project(self.project_root, file_name=requirements_txt.name):
            return requirements_txt
        return None

    @cached_property
    def supported_metadata_files(self) -> set[str]:
        """Names of all supported metadata files.

        Returns:
            Set of file names - not paths.

        Aggregates config file names from both pip and poetry so the cache
        invalidation logic can detect changes to any supported dependency file.

        """
        file_names = {*Pip.CONFIG_FILES}
        if self.args.use_poetry:
            file_names.update(Poetry.CONFIG_FILES)
        return file_names

    @cached_property
    def tmp_requirements_txt(self) -> Path:
        """Temporary requirements.txt file.

        This path is only used when exporting from another format.

        Uses the source code MD5 hash in the filename to avoid collisions when
        multiple Lambda functions are built in the same work directory.

        """
        return self.ctx.work_dir / f"{self.source_code.md5_hash}.requirements.txt"

    def cleanup(self) -> None:
        """Cleanup temporary files after the build process has run.

        Removes exported requirements and installed dependencies to avoid
        stale artifacts from accumulating across repeated builds.

        """
        if self.poetry and self.tmp_requirements_txt.exists():
            self.tmp_requirements_txt.unlink()
        shutil.rmtree(self.dependency_directory, ignore_errors=True)
        if not any(self.build_directory.iterdir()):
            # remove build_directory if it's empty
            shutil.rmtree(self.build_directory, ignore_errors=True)

    def install_dependencies(self) -> None:
        """Install project dependencies.

        Routes installation through Docker when configured (for compiled
        extensions) or falls back to local pip, centralizing the decision
        so callers do not need to know the installation strategy.

        """
        if self.requirements_txt:
            LOGGER.debug("installing dependencies to %s...", self.dependency_directory)
            if self.docker:
                self.docker.install()
            else:
                # no_deps is set when poetry is used because poetry's exported
                # requirements.txt already contains fully resolved transitive
                # dependencies; letting pip re-resolve would introduce conflicts.
                self.pip.install(
                    cache_dir=self.args.cache_dir,
                    extend_args=self.args.extend_pip_args,
                    no_cache_dir=not self.args.use_cache,
                    no_deps=bool(self.poetry),
                    requirements=self.requirements_txt,
                    target=self.dependency_directory,
                )
            LOGGER.debug("dependencies successfully installed to %s", self.dependency_directory)
        else:
            LOGGER.info("skipped installing dependencies; none found")
