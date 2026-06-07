"""Tests for runway.cfngin.dag.

Validates the directed acyclic graph implementation that cfngin uses to
determine stack deployment order. Correct DAG behavior is critical because
it governs parallel execution, dependency ordering, and cycle detection
for CloudFormation stack operations.
"""

import threading
from typing import Any

import pytest

from runway.cfngin.dag import (
    DAG,
    DAGValidationError,
    ThreadedWalker,
    UnlimitedSemaphore,
)


def test_add_node(empty_dag: DAG) -> None:
    """Test add node.

    Adding a node with no edges is the base operation; verifies the graph
    correctly initializes an empty adjacency set for isolated nodes.
    """
    dag = empty_dag

    dag.add_node("a")
    assert dag.graph == {"a": set()}


def test_transpose(basic_dag: DAG) -> None:
    """Test transpose.

    Transposing reverses all edge directions; cfngin uses this to find
    predecessors (who depends on me) from a graph that stores successors.
    """
    dag = basic_dag

    transposed = dag.transpose()
    assert transposed.graph == {"d": {"c", "b"}, "c": {"a"}, "b": {"a"}, "a": set()}


def test_add_edge(empty_dag: DAG) -> None:
    """Test add edge.

    Edges represent stack dependencies; verifies the directed relationship
    is stored correctly (a depends on b, not the reverse).
    """
    dag = empty_dag

    dag.add_node("a")
    dag.add_node("b")
    dag.add_edge("a", "b")
    assert dag.graph == {"a": set("b"), "b": set()}


def test_from_dict(empty_dag: DAG) -> None:
    """Test from dict.

    Dict initialization is the primary way cfngin configs build the DAG;
    verifies that list-valued adjacency input is converted to sets correctly.
    """
    dag = empty_dag

    dag.from_dict({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []})
    assert dag.graph == {"a": {"b", "c"}, "b": {"d"}, "c": {"d"}, "d": set()}


def test_reset_graph(empty_dag: DAG) -> None:
    """Test reset graph.

    Resetting clears all nodes and edges, needed when cfngin re-initializes
    the plan graph (e.g., after filtering stacks by target).
    """
    dag = empty_dag

    dag.add_node("a")
    assert dag.graph == {"a": set()}
    dag.reset_graph()
    assert dag.graph == {}


def test_walk(empty_dag: DAG) -> None:
    """Test walk.

    Walk executes nodes in dependency order (leaves first). Nodes at the
    same depth (b, c) may execute in either order, reflecting the parallelism
    cfngin uses for independent stacks.
    """
    dag = empty_dag

    # b and c should be executed at the same time.
    dag.from_dict({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []})

    nodes: list[Any] = []

    def walk_func(node: Any) -> bool:
        nodes.append(node)
        return True

    dag.walk(walk_func)
    assert nodes in [["d", "c", "b", "a"], ["d", "b", "c", "a"]]


def test_ind_nodes(basic_dag: DAG) -> None:
    """Test ind nodes.

    Independent (root) nodes have no predecessors and are the starting
    points for topological traversal in the deployment plan.
    """
    dag = basic_dag
    assert dag.ind_nodes() == ["a"]


def test_topological_sort(empty_dag: DAG) -> None:
    """Test topological sort.

    Topological sort determines execution order for the deployment plan;
    a linear chain (c->b->a) must produce exactly one valid ordering.
    """
    dag = empty_dag
    dag.from_dict({"a": [], "b": ["a"], "c": ["b"]})
    assert dag.topological_sort() == ["c", "b", "a"]


def test_successful_validation(basic_dag: DAG) -> None:
    """Test successful validation.

    A valid DAG (no cycles) must pass validation, confirming that a correct
    dependency graph is accepted without false positives.
    """
    dag = basic_dag
    assert dag.validate()[0] is True


def test_failed_validation(empty_dag: DAG) -> None:
    """Test failed validation.

    Circular dependencies (a->b->a) would cause infinite loops during
    deployment; the DAG must reject them at construction time.
    """
    dag = empty_dag

    with pytest.raises(DAGValidationError):
        dag.from_dict({"a": ["b"], "b": ["a"]})


def test_downstream(basic_dag: DAG) -> None:
    """Test downstream.

    Downstream returns direct dependents — used by cfngin to identify
    which stacks are immediately blocked when a dependency fails.
    """
    dag = basic_dag
    assert set(dag.downstream("a")) == {"b", "c"}


def test_all_downstreams(basic_dag: DAG) -> None:
    """Test all downstreams.

    Transitive downstream traversal identifies the full blast radius of a
    stack failure — every stack that transitively depends on the failed one.
    """
    dag = basic_dag

    assert dag.all_downstreams("a") == ["b", "c", "d"]
    assert dag.all_downstreams("b") == ["d"]
    assert dag.all_downstreams("d") == []


def test_all_downstreams_pass_graph(empty_dag: DAG) -> None:
    """Test all downstreams pass graph.

    Verifies transitive downstream with a non-diamond graph structure to
    confirm the algorithm isn't accidentally hardcoded to one topology.
    """
    dag = empty_dag
    dag.from_dict({"a": ["c"], "b": ["d"], "c": ["d"], "d": []})
    assert dag.all_downstreams("a") == ["c", "d"]
    assert dag.all_downstreams("b") == ["d"]
    assert dag.all_downstreams("d") == []


def test_predecessors(basic_dag: DAG) -> None:
    """Test predecessors.

    Predecessors (who must complete before me) are used to determine when
    a stack is unblocked and ready to execute.
    """
    dag = basic_dag

    assert set(dag.predecessors("a")) == set()
    assert set(dag.predecessors("b")) == {"a"}
    assert set(dag.predecessors("c")) == {"a"}
    assert set(dag.predecessors("d")) == {"b", "c"}


def test_filter(basic_dag: DAG) -> None:
    """Test filter.

    Filtering extracts a subgraph for targeted deployments (e.g., deploying
    only stacks b and c) while preserving their downstream dependencies.
    """
    dag = basic_dag

    dag2 = dag.filter(["b", "c"])
    assert dag2.graph == {"b": set("d"), "c": set("d"), "d": set()}


def test_all_leaves(basic_dag: DAG) -> None:
    """Test all leaves.

    Leaf nodes have no dependencies and can execute immediately; cfngin
    starts parallel deployment from these nodes.
    """
    dag = basic_dag

    assert dag.all_leaves() == ["d"]


def test_size(basic_dag: DAG) -> None:
    """Test size.

    Verifies node count tracks additions and deletions, used by the plan
    to determine progress and completion.
    """
    dag = basic_dag

    assert dag.size() == 4
    dag.delete_node("a")
    assert dag.size() == 3


def test_transitive_reduction_no_reduction(empty_dag: DAG) -> None:
    """Test transitive reduction no reduction.

    When no redundant edges exist, transitive reduction must leave the
    graph unchanged — confirms the algorithm doesn't incorrectly remove
    necessary edges.
    """
    dag = empty_dag
    dag.from_dict({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []})
    dag.transitive_reduction()
    assert dag.graph == {"a": {"b", "c"}, "b": {"d"}, "c": {"d"}, "d": set()}


def test_transitive_reduction(empty_dag: DAG) -> None:
    """Test transitive reduction.

    Removes redundant edges (e.g., a->d when a->b->d already exists) to
    minimize parallel wait time and simplify the deployment plan.
    Uses the Wikipedia reference graph to validate against a known result.
    """
    dag = empty_dag
    # https://en.wikipedia.org/wiki/Transitive_reduction#/media/File:Tred-G.svg
    dag.from_dict({"a": ["b", "c", "d", "e"], "b": ["d"], "c": ["d", "e"], "d": ["e"], "e": []})
    dag.transitive_reduction()
    # https://en.wikipedia.org/wiki/Transitive_reduction#/media/File:Tred-Gprime.svg
    assert dag.graph == {
        "a": {"b", "c"},
        "b": {"d"},
        "c": {"d"},
        "d": {"e"},
        "e": set(),
    }


def test_transitive_deep_reduction(empty_dag: DAG) -> None:
    """Test transitive deep reduction.

    Verifies reduction works for longer transitive paths (a->b->c->d makes
    a->d redundant), catching bugs in depth-limited traversal.
    """
    dag = empty_dag
    # https://en.wikipedia.org/wiki/Transitive_reduction#/media/File:Tred-G.svg
    dag.from_dict({"a": ["b", "d"], "b": ["c"], "c": ["d"], "d": []})
    dag.transitive_reduction()
    # https://en.wikipedia.org/wiki/Transitive_reduction#/media/File:Tred-Gprime.svg
    assert dag.graph == {"a": set("b"), "b": set("c"), "c": set("d"), "d": set()}


def test_threaded_walker(empty_dag: DAG) -> None:
    """Test threaded walker.

    The threaded walker is cfngin's actual execution engine for parallel
    stack operations. Verifies correct ordering under concurrent execution
    with the UnlimitedSemaphore (no parallelism cap).
    """
    dag = empty_dag

    walker = ThreadedWalker(UnlimitedSemaphore())

    # b and c should be executed at the same time.
    dag.from_dict({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []})

    lock = threading.Lock()  # Protects nodes from concurrent access
    nodes: list[Any] = []

    def walk_func(node: Any) -> bool:
        with lock:
            nodes.append(node)
        return True

    walker.walk(dag, walk_func)
    assert nodes in [["d", "c", "b", "a"], ["d", "b", "c", "a"]]
