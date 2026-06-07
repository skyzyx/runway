"""CFNgin graph action.

This module exists to let operators visualize the dependency DAG for debugging
deployment order and identifying unexpected dependency chains between stacks.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import TYPE_CHECKING, Any, TextIO

from ..plan import merge_graphs
from .base import BaseAction

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..plan import Graph, Step

LOGGER = logging.getLogger(__name__)


def each_step(graph: Graph) -> Iterable[tuple[Step, list[Step]]]:
    """Yield each step and it's direct dependencies.

    Reverses the topological sort so that output reads top-down from root
    stacks to leaf stacks, matching the natural reading order for dependency
    graphs.

    Args:
        graph: Graph to iterate over.

    """
    steps = graph.topological_sort()
    steps.reverse()

    for step in steps:
        deps = graph.downstream(step.name)
        yield step, deps


def dot_format(out: TextIO, graph: Graph, name: str = "digraph") -> None:
    """Output a graph using the graphviz "dot" format.

    Uses DOT format because it is the de facto standard for graph
    visualization tools and can be piped directly into graphviz to produce
    PNG/SVG diagrams of the dependency structure.

    Args:
        out: Where output will be written.
        graph: Graph to be output.
        name: Name of the graph.

    """
    out.write(f"digraph {name} {{\n")
    for step, deps in each_step(graph):
        out.writelines(f'  "{step}" -> "{dep}";\n' for dep in deps)

    out.write("}\n")


def json_format(out: TextIO, graph: Graph) -> None:
    """Output the graph in a machine readable JSON format.

    Provides a structured alternative to DOT for programmatic consumption by
    CI/CD pipelines and custom tooling that need to inspect the dependency
    graph without parsing graphviz syntax.

    Args:
        out: Where output will be written.
        graph: Graph to be output.

    """
    steps = {step.name: {"deps": [dep.name for dep in deps]} for step, deps in each_step(graph)}

    json.dump({"steps": steps}, out, indent=4)
    out.write("\n")


FORMATTERS = {
    "dot": dot_format,
    "json": json_format,
}


class Action(BaseAction):
    """Responsible for outputting a graph for the current CFNgin config.

    This action exists as a standalone command (rather than a flag on deploy)
    so operators can inspect the dependency structure without triggering any
    AWS API calls or requiring valid credentials beyond what plan generation
    needs.
    """

    DESCRIPTION = "Print graph"
    NAME = "graph"

    @property
    def _stack_action(self) -> Any:
        """Run against a step."""
        return None

    def run(
        self,
        *,
        concurrency: int = 0,  # noqa: ARG002
        dump: bool | str = False,  # noqa: ARG002
        force: bool = False,  # noqa: ARG002
        outline: bool = False,  # noqa: ARG002
        tail: bool = False,  # noqa: ARG002
        upload_disabled: bool = False,  # noqa: ARG002
        **kwargs: Any,
    ) -> None:
        """Generate the underlying graph and prints it.

        Merges the persistent graph (if present) so the visualization reflects
        the complete set of managed stacks, not just those in the current
        config file.
        """
        graph = self._generate_plan(require_unlocked=False, include_persistent_graph=True).graph
        if self.context.persistent_graph:
            graph = merge_graphs(self.context.persistent_graph, graph)
        if kwargs.get("reduce"):
            # Transitive reduction removes redundant edges (if A→B→C, drop
            # A→C) to produce a cleaner visual in DOT/PNG output without
            # changing the logical dependency order.
            graph.transitive_reduction()

        fn = FORMATTERS[str(kwargs.get("format", "json"))]
        fn(sys.stdout, graph)
        sys.stdout.flush()
