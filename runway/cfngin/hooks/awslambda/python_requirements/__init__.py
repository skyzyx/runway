"""Handle python requirements.

This subpackage isolates Python-specific packaging concerns (pip, poetry,
.pyc stripping) from the language-agnostic Lambda hook framework, allowing
each runtime to evolve its dependency workflow independently.

"""

from ._deployment_package import PythonDeploymentPackage
from ._docker import PythonDockerDependencyInstaller
from ._project import PythonProject

__all__ = [
    "PythonDeploymentPackage",
    "PythonDockerDependencyInstaller",
    "PythonProject",
]
