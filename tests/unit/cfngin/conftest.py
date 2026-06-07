"""Pytest fixtures and plugins.

Provides shared test infrastructure for all cfngin unit tests, centralizing
fixture data paths and reusable DAG instances so individual test modules don't
duplicate setup logic.
"""

from pathlib import Path

import pytest

from runway.cfngin.dag import DAG


@pytest.fixture(scope="package")
def cfngin_fixtures() -> Path:
    """CFNgin fixture directory Path object.

    Package-scoped so all cfngin tests share a single resolved path to the
    fixtures directory, avoiding repeated Path construction and ensuring
    consistent access to test data files (configs, envs, keypairs, etc.).
    """
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def empty_dag() -> DAG:
    """Create an empty DAG.

    Provides a clean DAG instance for tests that need to build graph
    structure incrementally and verify node/edge operations in isolation.
    """
    return DAG()


@pytest.fixture
def basic_dag() -> DAG:
    """Create a basic DAG.

    Pre-populates a diamond-shaped dependency graph (a -> b,c -> d) that
    exercises branching and convergence, the two fundamental DAG patterns
    cfngin uses for parallel stack deployment ordering.
    """
    dag = DAG()
    dag.from_dict({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []})
    return dag
