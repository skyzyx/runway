"""CFNgin directed acyclic graph (DAG) implementation.

This module is the foundation of CFNgin's execution model. CloudFormation stacks
have inter-stack dependencies (outputs feeding inputs), so a DAG enforces correct
ordering while enabling maximum parallelism for independent stacks.
"""

from __future__ import annotations

import collections
import collections.abc
import contextlib
import logging
from collections import OrderedDict
from copy import copy, deepcopy
from threading import Thread
from typing import TYPE_CHECKING, Any, Callable, cast

if TYPE_CHECKING:
    import threading
    from collections.abc import Iterable

LOGGER = logging.getLogger(__name__)


class DAGValidationError(Exception):
    """Raised when DAG validation fails.

    Separate from KeyError so callers can distinguish structural graph
    violations (cycles) from simple missing-node errors.
    """


class DAG:
    """Directed acyclic graph implementation.

    Models stack dependencies as nodes and edges so the planner can derive
    execution order via topological sort and detect invalid circular references
    before any AWS calls are made.
    """

    graph: OrderedDict[str, set[str]]

    def __init__(self) -> None:
        """Instantiate a new DAG with no nodes or edges."""
        self.graph = collections.OrderedDict()

    def add_node(self, node_name: str) -> None:
        """Add a node if it does not exist yet, or error out.

        Strict insertion prevents silent overwrites of an existing node's edges,
        which would corrupt the dependency graph.

        Args:
            node_name: The unique name of the node to add.

        Raises:
            KeyError: Raised if a node with the same name already exist in the
                graph

        """
        graph = self.graph
        if node_name in graph:
            raise KeyError(f"node {node_name} already exists")
        graph[node_name] = cast("set[str]", set())

    def add_node_if_not_exists(self, node_name: str) -> None:
        """Add a node if it does not exist yet, ignoring duplicates.

        Used during graph construction from config where the same stack may
        appear as both a dependency target and an explicit definition.

        Args:
            node_name: The name of the node to add.

        """
        with contextlib.suppress(KeyError):
            self.add_node(node_name)

    def delete_node(self, node_name: str) -> None:
        """Delete this node and all edges referencing it.

        Removing dangling edges ensures the graph remains internally consistent
        after a stack is excluded from a plan (e.g., via filtering).

        Args:
            node_name: The name of the node to delete.

        Raises:
            KeyError: Raised if the node does not exist in the graph.

        """
        graph = self.graph
        if node_name not in graph:
            raise KeyError(f"node {node_name} does not exist")
        graph.pop(node_name)

        for edges in graph.values():
            if node_name in edges:
                edges.remove(node_name)

    def delete_node_if_exists(self, node_name: str) -> None:
        """Delete this node and all edges referencing it.

        Ignores any node that is not in the graph, rather than throwing an
        exception.

        Args:
            node_name: The name of the node to delete.

        """
        with contextlib.suppress(KeyError):
            self.delete_node(node_name)

    def add_edge(self, ind_node: str, dep_node: str) -> None:
        """Add an edge (dependency) between the specified nodes.

        Validates against cycles by testing on a deep copy first, because
        introducing a cycle would make topological sort impossible and deadlock
        the threaded walker.

        Args:
            ind_node: The independent node to add an edge to.
            dep_node: The dependent node that has a dependency on the ind_node.

        Raises:
            KeyError: Either the ind_node, or dep_node do not exist.
            DAGValidationError: Raised if the resulting graph is invalid.

        """
        graph = self.graph
        if ind_node not in graph:
            raise KeyError(f"independent node {ind_node} does not exist")
        if dep_node not in graph:
            raise KeyError(f"dependent node {dep_node} does not exist")
        test_graph = deepcopy(graph)
        test_graph[ind_node].add(dep_node)
        test_dag = DAG()
        test_dag.graph = test_graph
        is_valid, message = test_dag.validate()
        if is_valid:
            graph[ind_node].add(dep_node)
        else:
            raise DAGValidationError(message)

    def delete_edge(self, ind_node: str, dep_node: str) -> None:
        """Delete an edge from the graph.

        Args:
            ind_node: The independent node to delete an edge from.
            dep_node: The dependent node that has a dependency on the
                ind_node.

        Raises:
            KeyError: Raised when the edge doesn't already exist.

        """
        graph = self.graph
        if dep_node not in graph.get(ind_node, []):
            raise KeyError(f"No edge exists between {ind_node} and {dep_node}.")
        graph[ind_node].remove(dep_node)

    def transpose(self) -> DAG:
        """Build a new graph with the edges reversed.

        Used to derive "depended-on-by" relationships from the stored
        "depends-on" edges, enabling efficient predecessor lookups for
        destroy-order planning.
        """
        graph = self.graph
        transposed = DAG()
        for node in graph:
            transposed.add_node(node)
        for node, edges in graph.items():
            # for each edge A -> B, transpose it so that B -> A
            for edge in edges:
                transposed.add_edge(edge, node)
        return transposed

    def walk(self, walk_func: Callable[[str], Any]) -> None:
        """Walk each node of the graph in reverse topological order.

        Serial execution guarantees that each node's dependencies are fully
        resolved before it runs. Used as the simple single-threaded fallback
        when parallelism is not needed.

        This can be used to perform a set of operations, where the next
        operation depends on the previous operation. It's important to note
        that walking happens serially, and is not parallelized.

        Args:
            walk_func: The function to be called on each node of the graph.

        """
        nodes = self.topological_sort()
        # Reverse so we start with nodes that have no dependencies.
        nodes.reverse()

        for node in nodes:
            walk_func(node)

    def transitive_reduction(self) -> None:
        """Perform a transitive reduction on the DAG.

        Removes redundant edges so only direct dependencies remain. This
        simplifies plan visualization and avoids unnecessary waits in the
        threaded walker when a dependency is already implied transitively.

        The transitive reduction of a graph is a graph with as few edges as
        possible with the same reachability as the original graph.

        See https://en.wikipedia.org/wiki/Transitive_reduction

        """
        combinations: list[list[str]] = []
        for node, edges in self.graph.items():
            combinations += [[node, edge] for edge in edges]

        while True:
            new_combinations: list[list[str]] = []
            for comb1 in combinations:
                for comb2 in combinations:
                    if comb1[-1] != comb2[0]:
                        continue
                    new_entry = comb1 + comb2[1:]
                    if new_entry not in combinations:
                        new_combinations.append(new_entry)
            if not new_combinations:
                break
            combinations += new_combinations

        constructed = {(c[0], c[-1]) for c in combinations if len(c) != 2}
        for node, edges in self.graph.items():
            bad_nodes = {e for n, e in constructed if node == n}
            self.graph[node] = edges - bad_nodes

    def rename_edges(self, old_node_name: str, new_node_name: str) -> None:
        """Change references to a node in existing edges.

        Supports stack renaming without rebuilding the entire graph, preserving
        existing dependency relationships.

        Args:
            old_node_name: The old name for the node.
            new_node_name: The new name for the node.

        """
        graph = self.graph
        for node, edges in graph.items():
            if node == old_node_name:
                graph[new_node_name] = copy(edges)
                del graph[old_node_name]

            elif old_node_name in edges:
                edges.remove(old_node_name)
                edges.add(new_node_name)

    def predecessors(self, node: str) -> list[str]:
        """Return a list of all immediate predecessors of the given node.

        Identifies which stacks depend on this node, used to propagate
        failure status upstream through the execution plan.

        Args:
            node (str): The node whose predecessors you want to find.

        Returns:
            list[str]: A list of nodes that are immediate predecessors to node.

        """
        graph = self.graph
        return [key for key in graph if node in graph[key]]

    def downstream(self, node: str) -> list[str]:
        """Return a list of all nodes this node has edges towards.

        Returns direct dependencies of a stack, used by the threaded walker
        to determine what must complete before this node can execute.

        Args:
            node: The node whose downstream nodes you want to find.

        Returns:
            A list of nodes that are immediately downstream from the node.

        """
        graph = self.graph
        if node not in graph:
            raise KeyError(f"node {node} is not in graph")
        return list(graph[node])

    def all_downstreams(self, node: str) -> list[str]:
        """Return a list of all nodes downstream in topological order.

        Computes the full transitive closure of dependencies so the threaded
        walker knows all nodes that must finish before this one can start.

        Args:
             node: The node whose downstream nodes you want to find.

        Returns:
            A list of nodes that are downstream from the node.

        """
        nodes = [node]
        nodes_seen: set[str] = set()
        nodes_iter = nodes
        for node__ in nodes_iter:
            downstreams = self.downstream(node__)
            for downstream_node in downstreams:
                if downstream_node not in nodes_seen:
                    nodes_seen.add(downstream_node)
                    nodes.append(downstream_node)
        return [node_ for node_ in self.topological_sort() if node_ in nodes_seen]

    def filter(self, nodes: list[str]) -> DAG:
        """Return a new DAG with only the given nodes and their dependencies.

        Enables targeted deploys where the user specifies a subset of stacks
        and the planner automatically includes transitive dependencies.

        Args:
            nodes: The nodes you are interested in.

        """
        filtered_dag = DAG()

        # Add only the nodes we need.
        for node in nodes:
            filtered_dag.add_node_if_not_exists(node)
            for edge in self.all_downstreams(node):
                filtered_dag.add_node_if_not_exists(edge)

        # Now, rebuild the graph for each node that's present.
        for node, edges in self.graph.items():
            if node in filtered_dag.graph:
                filtered_dag.graph[node] = edges

        return filtered_dag

    def all_leaves(self) -> list[str]:
        """Return a list of all leaves (nodes with no downstreams).

        Leaf nodes are stacks with no dependencies and can execute first,
        forming the starting wave of parallel deployment.
        """
        graph = self.graph
        return [key for key in graph if not graph[key]]

    def from_dict(self, graph_dict: dict[str, Iterable[str] | Any]) -> None:
        """Reset the graph and build it from the passed dictionary.

        Provides a convenient initialization path from parsed configuration
        files where dependencies are expressed as adjacency lists.

        The dictionary takes the form of {node_name: [directed edges]}

        Args:
            graph_dict: The dictionary used to create the graph.

        Raises:
            TypeError: Raised if the value of items in the dict are not lists.

        """
        self.reset_graph()
        for new_node in graph_dict:
            self.add_node(new_node)
        for ind_node, dep_nodes in graph_dict.items():
            if not isinstance(dep_nodes, collections.abc.Iterable):
                raise TypeError(f"{ind_node}: dict values must be lists")
            for dep_node in cast("list[str]", dep_nodes):
                self.add_edge(ind_node, dep_node)

    def reset_graph(self) -> None:
        """Restore the graph to an empty state."""
        self.graph = collections.OrderedDict()

    def ind_nodes(self) -> list[str]:
        """Return a list of all nodes in the graph with no dependencies.

        Independent nodes are the entry points for execution — stacks that
        can begin immediately because nothing else needs to finish first.
        """
        graph = self.graph

        dependent_nodes = {node for dependents in graph.values() for node in dependents}

        return [node_ for node_ in graph if node_ not in dependent_nodes]

    def validate(self) -> tuple[bool, str]:
        """Return (Boolean, message) of whether DAG is valid.

        Catches cycles and isolated graphs early, before the planner
        attempts execution which would deadlock or produce undefined order.
        """
        if not self.ind_nodes():
            return (False, "no independent nodes detected")
        try:
            self.topological_sort()
        except ValueError as err:
            return False, str(err)
        return True, "valid"

    def topological_sort(self) -> list[str]:
        """Return a topological ordering of the DAG.

        Kahn's algorithm is used because it naturally detects cycles (remaining
        nodes with non-zero in-degree) and produces a deterministic order when
        ties are broken alphabetically via sorted().

        Raises:
            ValueError: Raised if the graph is not acyclic.

        """
        graph = self.graph

        in_degree = dict.fromkeys(graph, 0)
        for node in graph:
            for val in graph[node]:
                in_degree[val] += 1

        queue: collections.deque[str] = collections.deque()
        for node, value in in_degree.items():
            if value == 0:
                queue.appendleft(node)

        sorted_graph: list[str] = []
        while queue:
            node = queue.pop()
            sorted_graph.append(node)
            for val in sorted(graph[node]):
                in_degree[val] -= 1
                if in_degree[val] == 0:
                    queue.appendleft(val)

        if len(sorted_graph) == len(graph):
            return sorted_graph
        raise ValueError("graph is not acyclic")

    def size(self) -> int:
        """Count of nodes in the graph."""
        return len(self)

    def __len__(self) -> int:
        """How the length of a DAG is calculated."""
        return len(self.graph)


def walk(dag: DAG, walk_func: Callable[[str], Any]) -> None:
    """Walk a DAG."""
    return dag.walk(walk_func)


class UnlimitedSemaphore:
    """threading.Semaphore, but acquire always succeeds.

    Used as the default when no parallelism limit is configured, avoiding
    conditional semaphore logic throughout the walker code.
    """

    def acquire(self, *args: Any) -> Any:
        """Do nothing."""

    def release(self) -> Any:
        """Do nothing."""


class ThreadedWalker:
    """Walk a DAG as quickly as the graph topology allows, using threads.

    Enables independent stacks (those with no mutual dependencies) to execute
    concurrently, dramatically reducing total deploy time for wide graphs while
    respecting dependency ordering for connected stacks.
    """

    def __init__(self, semaphore: threading.Semaphore | UnlimitedSemaphore) -> None:
        """Instantiate class.

        Args:
            semaphore: A semaphore object which can be used to control how many
                steps are executed in parallel.

        """
        self.semaphore = semaphore

    def walk(self, dag: DAG, walk_func: Callable[[str], Any]) -> None:
        """Walk each node of the graph, in parallel if it can.

        The walk_func is only called when the nodes dependencies have been
        satisfied.

        """
        # Topological sort with reversal ensures threads are allocated for
        # leaf nodes (no deps) first, preventing join() on unstarted threads.
        #
        # TODO(ejholmes): An alternative would be to ensure that Thread.join
        # blocks if the thread has not yet been started.
        nodes = dag.topological_sort()
        nodes.reverse()

        # This maps a node name to a thread of execution.
        threads: dict[str, Any] = {}

        # Polling with a 0.5s timeout instead of blocking join() allows the
        # walker to remain responsive and detect deadlocks or interrupts.
        def wait_for(nodes: list[str]) -> None:
            """Wait for nodes."""
            for node in nodes:
                thread = threads[node]
                while thread.is_alive():
                    threads[node].join(0.5)

        # Each node gets its own thread so independent stacks execute
        # concurrently. The semaphore limits active concurrent operations
        # to avoid overwhelming AWS API rate limits.
        for node in nodes:

            def _fn(node_: str, deps: list[str]) -> Any:
                if deps:
                    LOGGER.debug("%s waiting for %s to complete", node_, ", ".join(deps))

                # Wait for all dependencies to complete.
                wait_for(deps)

                LOGGER.debug("%s starting", node_)

                self.semaphore.acquire()
                try:
                    return walk_func(node_)
                finally:
                    self.semaphore.release()

            deps = dag.all_downstreams(node)
            threads[node] = Thread(target=_fn, args=(node, deps), name=node)

        # Start up all of the threads.
        for node in nodes:
            threads[node].start()

        # Wait for all threads to complete executing.
        wait_for(nodes)
