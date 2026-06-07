"""AWS Lambda Python Deployment Package.

Extends the base DeploymentPackage with Python-specific gitignore rules for
slimming (.pyc, dist-info, __pycache__) and layer directory insertion, because
Python Lambda packages have unique artifacts that other runtimes do not produce.

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from igittigitt import IgnoreParser

from .....compat import cached_property
from ..deployment_package import DeploymentPackage

if TYPE_CHECKING:
    from pathlib import Path

    from . import PythonProject


class PythonDeploymentPackage(DeploymentPackage["PythonProject"]):
    """AWS Lambda Python Deployment Package.

    Specializes the generic deployment package for Python by adding
    bytecode/dist-info exclusion filters and the ``python/`` prefix required
    by Lambda Layers, since these conventions are unique to the Python runtime.

    """

    project: PythonProject

    @cached_property
    def gitignore_filter(self) -> IgnoreParser | None:
        """Filter to use when zipping dependencies.

        This should be overridden by subclasses if a filter should be used.

        Applying gitignore-style exclusion rules at zip time reduces the
        deployment package size significantly by removing Python build
        artifacts that are unnecessary in the Lambda execution environment.

        """
        if self.project.args.slim:
            gitignore_filter = IgnoreParser()
            # Exclude metadata and bytecode artifacts that inflate package size
            # without contributing to runtime functionality.
            gitignore_filter.add_rule("**/*.dist-info*", self.project.dependency_directory)
            gitignore_filter.add_rule("**/*.py[c|d|i|o]", self.project.dependency_directory)
            gitignore_filter.add_rule("**/__pycache__*", self.project.dependency_directory)
            if self.project.args.strip:
                # Shared object files are stripped separately; excluding them
                # here removes debug symbols that bloat compiled extensions.
                gitignore_filter.add_rule("**/*.so", self.project.dependency_directory)
            return gitignore_filter
        return None

    @staticmethod
    def insert_layer_dir(file_path: Path, relative_to: Path) -> Path:
        """Insert ``python`` directory into local file path for layer archive.

        Lambda Layers require a ``python/`` prefix in the zip archive so the
        runtime can locate layer dependencies on the import path automatically.

        Args:
            file_path: Path to local file.
            relative_to: Path to a directory that the file_path will be relative
                to in the deployment package.

        """
        return relative_to / f"python/{file_path.relative_to(relative_to)}"
