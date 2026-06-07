"""Tests for runway.cfngin.plan."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

from runway.cfngin.dag import walk
from runway.cfngin.exceptions import (
    CancelExecution,
    GraphError,
    PersistentGraphLocked,
    PlanFailed,
)
from runway.cfngin.lookups.registry import (
    register_lookup_handler,
    unregister_lookup_handler,
)
from runway.cfngin.plan import Graph, Plan, Step
from runway.cfngin.stack import Stack
from runway.cfngin.status import COMPLETE, FAILED, SKIPPED, SUBMITTED
from runway.cfngin.utils import stack_template_key_name
from runway.config import CfnginConfig
from runway.context import CfnginContext
from runway.lookups.handlers.base import LookupHandler

from .factories import generate_definition, mock_context

if TYPE_CHECKING:
    from runway.cfngin.status import Status


class TestStep(unittest.TestCase):
    """Tests for runway.cfngin.plan.Step.

    Validates the Step state machine that tracks individual stack operation
    lifecycle (pending → submitted → complete). Correct state transitions
    are critical because the DAG executor polls step status to decide when
    dependent steps can proceed.
    """

    def setUp(self) -> None:
        """Run before tests."""
        stack = mock.MagicMock()
        stack.name = "stack"
        stack.fqn = "namespace-stack"
        self.step = Step(stack=stack, fn=None)

    def test_status(self) -> None:
        """Test status.

        Verifies the full lifecycle state machine: a step must transition
        through submitted before reaching complete, and status objects must
        not compare equal to arbitrary values (guards against accidental
        truthiness checks).
        """
        assert not self.step.submitted
        assert not self.step.completed

        self.step.submit()
        assert self.step.status == SUBMITTED
        assert self.step.submitted
        assert not self.step.completed

        self.step.complete()
        assert self.step.status == COMPLETE
        assert self.step.status != SUBMITTED
        assert self.step.submitted
        assert self.step.completed

        assert self.step.status is not True
        assert self.step.status is not False
        assert self.step.status != "banana"

    def test_from_stack_name(self) -> None:
        """Return step from step name.

        Confirms steps can be constructed from a bare name string, which is
        required when rebuilding execution state from a persistent graph.
        """
        context = mock_context()
        stack_name = "test-stack"
        result = Step.from_stack_name(stack_name, context)

        assert isinstance(result, Step)
        assert stack_name == result.stack.name

    def test_from_persistent_graph(self) -> None:
        """Return list of steps from graph dict.

        Validates that the persistent graph JSON representation can be
        deserialized back into Step objects with correct dependency edges,
        ensuring graph state survives across cfngin invocations.
        """
        context = mock_context()
        graph_dict: dict[str, Any] = {"stack1": [], "stack2": ["stack1"]}
        result = Step.from_persistent_graph(graph_dict, context)

        assert len(result) == 2
        assert isinstance(result, list)

        for step in result:
            assert isinstance(step, Step)
            assert step.stack.name in graph_dict


class TestGraph(unittest.TestCase):
    """Tests for runway.cfngin.plan.Graph.

    Validates the dependency graph data structure that determines execution
    order. Correct graph construction and serialization is essential because
    the persistent graph feature relies on accurate JSON round-tripping
    between cfngin runs.
    """

    def setUp(self) -> None:
        """Run before tests."""
        self.context = mock_context()
        self.graph_dict: dict[str, Any] = {"stack1": [], "stack2": ["stack1"]}
        self.graph_dict_expected = {"stack1": set(), "stack2": {"stack1"}}
        self.steps = Step.from_persistent_graph(self.graph_dict, self.context)

    def test_add_steps(self) -> None:
        """Test add steps.

        Confirms that steps are stored in insertion order and that the
        dependency edges from the persistent graph dict are preserved.
        """
        graph = Graph()
        graph.add_steps(self.steps)

        assert self.steps == list(graph.steps.values())
        assert [step.name for step in self.steps] == list(graph.steps.keys())
        assert self.graph_dict_expected == graph.to_dict()

    def test_pop(self) -> None:
        """Test pop.

        Validates that removing a step also cleans up its dependency edges,
        which is required when the destroy action removes stacks from the
        persistent graph.
        """
        graph = Graph()
        graph.add_steps(self.steps)

        stack2 = next(step for step in self.steps if step.name == "stack2")

        assert stack2 == graph.pop(stack2)
        assert graph.to_dict() == {"stack1": set()}

    def test_dumps(self) -> None:
        """Test dumps.

        Ensures the graph can be serialized to JSON for storage in S3 as the
        persistent graph, allowing state to survive between cfngin runs.
        """
        graph = Graph()
        graph.add_steps(self.steps)

        assert json.dumps(self.graph_dict) == graph.dumps()

    def test_from_dict(self) -> None:
        """Test from dict.

        Validates round-trip deserialization from a JSON-compatible dict,
        confirming that the persistent graph can be reconstructed after
        being loaded from S3.
        """
        graph = Graph.from_dict(self.graph_dict, self.context)

        assert isinstance(graph, Graph)
        assert [step.name for step in self.steps] == list(graph.steps.keys())
        assert self.graph_dict_expected == graph.to_dict()

    def test_from_steps(self) -> None:
        """Test from steps.

        Confirms the primary construction path used during normal execution
        where steps are built from stack definitions rather than persistent
        graph state.
        """
        graph = Graph.from_steps(self.steps)

        assert self.steps == list(graph.steps.values())
        assert [step.name for step in self.steps] == list(graph.steps.keys())
        assert self.graph_dict_expected == graph.to_dict()


class TestPlan(unittest.TestCase):
    """Tests for runway.cfngin.plan.Plan.

    Validates the plan executor that walks the DAG, coordinates stack
    operations, manages persistent graph state, and propagates failures.
    These tests exercise the full execution lifecycle including edge cases
    like locked stacks, filtered targets, and mid-flight cancellations.
    """

    def setUp(self) -> None:
        """Run before tests."""
        self.count = 0
        self.config = CfnginConfig.parse_obj({"namespace": "namespace"})
        self.context = CfnginContext(config=self.config)

        class FakeLookup(LookupHandler):
            """False Lookup."""

            @classmethod
            def handle(cls, _value: str, *__args: Any, **__kwargs: Any) -> str:  # type: ignore
                """Perform the lookup."""
                return "test"

        register_lookup_handler("noop", FakeLookup)

    def tearDown(self) -> None:
        """Run after tests."""
        unregister_lookup_handler("noop")

    def test_plan(self) -> None:
        """Test plan.

        Verifies that the dependency graph is correctly constructed from
        stack definitions, with requires relationships mapped as DAG edges.
        """
        vpc = Stack(definition=generate_definition("vpc", 1), context=self.context)
        bastion = Stack(
            definition=generate_definition("bastion", 1, requires=[vpc.name]),
            context=self.context,
        )

        graph = Graph.from_steps([Step(vpc, fn=None), Step(bastion, fn=None)])
        plan = Plan(description="Test", graph=graph)

        assert plan.graph.to_dict() == {"bastion-1": {"vpc-1"}, "vpc-1": set()}

    def test_plan_reverse(self) -> None:
        """Test plan reverse.

        The destroy action needs dependency edges reversed so that dependent
        stacks are deleted before their dependencies.
        """
        vpc = Stack(definition=generate_definition("vpc", 1), context=self.context)
        bastion = Stack(
            definition=generate_definition("bastion", 1, requires=[vpc.name]),
            context=self.context,
        )
        graph = Graph.from_steps([Step(vpc, fn=None), Step(bastion, fn=None)])
        plan = Plan(description="Test", graph=graph, reverse=True)

        # order is different between python2/3 so can't compare dicts
        result_graph_dict = plan.graph.to_dict()
        assert set() == result_graph_dict.get("bastion-1")
        assert {"bastion-1"} == result_graph_dict.get("vpc-1")

    def test_plan_targeted(self) -> None:
        """Test plan targeted.

        When users specify a subset of stacks via CLI, only those stacks
        (and their transitive dependencies) should appear in the plan.
        """
        context = CfnginContext(config=self.config)
        vpc = Stack(definition=generate_definition("vpc", 1), context=context)
        bastion = Stack(
            definition=generate_definition("bastion", 1, requires=[vpc.name]),
            context=context,
        )
        context.stack_names = [vpc.name]
        graph = Graph.from_steps([Step(vpc, fn=None), Step(bastion, fn=None)])
        plan = Plan(description="Test", graph=graph, context=context)

        assert plan.graph.to_dict() == {vpc.name: set()}

    def test_execute_plan(self) -> None:
        """Test execute plan.

        End-to-end execution: verifies dependency ordering is respected,
        removed stacks are destroyed, and the persistent graph is updated
        to reflect the final state.
        """
        context = CfnginContext(config=self.config)
        context.put_persistent_graph = mock.MagicMock()
        vpc = Stack(definition=generate_definition("vpc", 1), context=context)
        bastion = Stack(
            definition=generate_definition("bastion", 1, requires=[vpc.name]),
            context=context,
        )
        removed = Stack(definition=generate_definition("removed", 1, requires=[]), context=context)
        context._persistent_graph = Graph.from_steps([Step(removed)])

        calls: list[str] = []

        def _launch_stack(stack: Stack, status: Status | None = None) -> Status:  # noqa: ARG001
            calls.append(stack.fqn)
            return COMPLETE

        def _destroy_stack(stack: Stack, status: Status | None = None) -> Status:  # noqa: ARG001
            calls.append(stack.fqn)
            return COMPLETE

        graph = Graph.from_steps(
            [
                Step(removed, fn=_destroy_stack),
                Step(vpc, fn=_launch_stack),
                Step(bastion, fn=_launch_stack),
            ]
        )
        plan = Plan(description="Test", graph=graph, context=context)
        plan.context._persistent_graph_lock_code = plan.lock_code  # type: ignore
        plan.execute(walk)

        # the order these are appended changes between python2/3
        assert "namespace-vpc-1" in calls
        assert "namespace-bastion-1" in calls
        assert "namespace-removed-1" in calls
        context.put_persistent_graph.assert_called()

        # order is different between python2/3 so can't compare dicts
        result_graph_dict = context.persistent_graph.to_dict()  # type: ignore
        assert len(result_graph_dict) == 2
        assert set() == result_graph_dict.get("vpc-1")
        assert {"vpc-1"} == result_graph_dict.get("bastion-1")
        assert result_graph_dict.get("namespace-removed-1") is None

    def test_execute_plan_no_persist(self) -> None:
        """Test execute plan with no persistent graph.

        Confirms that without a persistent graph, execution still proceeds
        normally and no S3 write is attempted.
        """
        context = CfnginContext(config=self.config)
        context.put_persistent_graph = mock.MagicMock()
        vpc = Stack(definition=generate_definition("vpc", 1), context=context)
        bastion = Stack(
            definition=generate_definition("bastion", 1, requires=[vpc.name]),
            context=context,
        )

        calls: list[str] = []

        def _launch_stack(stack: Stack, status: Status | None = None) -> Status:  # noqa: ARG001
            calls.append(stack.fqn)
            return COMPLETE

        graph = Graph.from_steps([Step(vpc, fn=_launch_stack), Step(bastion, fn=_launch_stack)])
        plan = Plan(description="Test", graph=graph, context=context)

        plan.execute(walk)

        assert calls == ["namespace-vpc-1", "namespace-bastion-1"]
        context.put_persistent_graph.assert_not_called()

    def test_execute_plan_locked(self) -> None:
        """Test execute plan locked.

        Locked stacks still need to have their requires evaluated when
        they're being created. This ensures the DAG respects dependency
        ordering even when a stack's CloudFormation template is frozen.

        """
        vpc = Stack(definition=generate_definition("vpc", 1), context=self.context)
        bastion = Stack(
            definition=generate_definition("bastion", 1, locked=True, requires=[vpc.name]),
            context=self.context,
        )

        calls: list[str] = []

        def fn(stack: Stack, status: Status | None = None) -> Status:  # noqa: ARG001
            calls.append(stack.fqn)
            return COMPLETE

        graph = Graph.from_steps([Step(vpc, fn=fn), Step(bastion, fn=fn)])
        plan = Plan(description="Test", graph=graph)
        plan.execute(walk)

        assert calls == ["namespace-vpc-1", "namespace-bastion-1"]

    def test_execute_plan_filtered(self) -> None:
        """Test execute plan filtered.

        Verifies that targeting a mid-graph stack (db) still executes its
        upstream dependencies (vpc) but skips unrelated downstream stacks
        (app), preventing unnecessary CloudFormation operations.
        """
        vpc = Stack(definition=generate_definition("vpc", 1), context=self.context)
        db = Stack(
            definition=generate_definition("db", 1, requires=[vpc.name]),
            context=self.context,
        )
        app = Stack(
            definition=generate_definition("app", 1, requires=[db.name]),
            context=self.context,
        )

        calls: list[str] = []

        def fn(stack: Stack, status: Status | None = None) -> Status:  # noqa: ARG001
            calls.append(stack.fqn)
            return COMPLETE

        context = mock.MagicMock()
        context.persistent_graph_locked = False
        context.stack_names = ["db-1"]
        graph = Graph.from_steps([Step(vpc, fn=fn), Step(db, fn=fn), Step(app, fn=fn)])
        plan = Plan(context=context, description="Test", graph=graph)
        plan.execute(walk)

        assert calls == ["namespace-vpc-1", "namespace-db-1"]

    def test_execute_plan_exception(self) -> None:
        """Test execute plan exception.

        Verifies that an unhandled exception in a step function marks the
        step as FAILED and raises PlanFailed, halting execution of
        dependent stacks to avoid cascading failures.
        """
        vpc = Stack(definition=generate_definition("vpc", 1), context=self.context)
        bastion = Stack(
            definition=generate_definition("bastion", 1, requires=[vpc.name]),
            context=self.context,
        )

        calls: list[str] = []

        def fn(stack: Stack, status: Status | None = None) -> Status:  # noqa: ARG001
            calls.append(stack.fqn)
            if stack.name == vpc_step.name:
                raise ValueError("Boom")
            return COMPLETE

        vpc_step = Step(vpc, fn=fn)
        bastion_step = Step(bastion, fn=fn)

        graph = Graph.from_steps([vpc_step, bastion_step])
        plan = Plan(description="Test", graph=graph)

        with pytest.raises(PlanFailed):
            plan.execute(walk)

        assert calls == ["namespace-vpc-1"]
        assert vpc_step.status == FAILED

    def test_execute_plan_skipped(self) -> None:
        """Test execute plan skipped.

        A SKIPPED status (e.g., stack already up-to-date) must not block
        dependent stacks from proceeding, unlike FAILED which halts them.
        """
        vpc = Stack(definition=generate_definition("vpc", 1), context=self.context)
        bastion = Stack(
            definition=generate_definition("bastion", 1, requires=[vpc.name]),
            context=self.context,
        )

        calls: list[str] = []

        def fn(stack: Stack, status: Status | None = None) -> Status:  # noqa: ARG001
            calls.append(stack.fqn)
            if stack.fqn == vpc_step.name:
                return SKIPPED
            return COMPLETE

        vpc_step = Step(vpc, fn=fn)
        bastion_step = Step(bastion, fn=fn)

        graph = Graph.from_steps([vpc_step, bastion_step])
        plan = Plan(description="Test", graph=graph)
        plan.execute(walk)

        assert calls == ["namespace-vpc-1", "namespace-bastion-1"]

    def test_execute_plan_failed(self) -> None:
        """Test execute plan failed.

        When a step returns FAILED, its downstream dependents must be
        skipped while independent branches (db) still execute. This tests
        selective failure propagation through the DAG.
        """
        vpc = Stack(definition=generate_definition("vpc", 1), context=self.context)
        bastion = Stack(
            definition=generate_definition("bastion", 1, requires=[vpc.name]),
            context=self.context,
        )
        db = Stack(definition=generate_definition("db", 1), context=self.context)

        calls: list[str] = []

        def fn(stack: Stack, status: Status | None = None) -> Status:  # noqa: ARG001
            calls.append(stack.fqn)
            if stack.name == vpc_step.name:
                return FAILED
            return COMPLETE

        vpc_step = Step(vpc, fn=fn)
        bastion_step = Step(bastion, fn=fn)
        db_step = Step(db, fn=fn)

        graph = Graph.from_steps([vpc_step, bastion_step, db_step])
        plan = Plan(description="Test", graph=graph)
        with pytest.raises(PlanFailed):
            plan.execute(walk)

        calls.sort()

        assert calls == ["namespace-db-1", "namespace-vpc-1"]

    def test_execute_plan_cancelled(self) -> None:
        """Test execute plan cancelled.

        CancelExecution is a soft abort: unlike hard exceptions, it allows
        remaining independent steps to run and does not raise PlanFailed.
        """
        vpc = Stack(definition=generate_definition("vpc", 1), context=self.context)
        bastion = Stack(
            definition=generate_definition("bastion", 1, requires=[vpc.name]),
            context=self.context,
        )

        calls: list[str] = []

        def fn(stack: Stack, status: Status | None = None) -> Status:  # noqa: ARG001
            calls.append(stack.fqn)
            if stack.fqn == vpc_step.name:
                raise CancelExecution
            return COMPLETE

        vpc_step = Step(vpc, fn=fn)
        bastion_step = Step(bastion, fn=fn)

        graph = Graph.from_steps([vpc_step, bastion_step])
        plan = Plan(description="Test", graph=graph)
        plan.execute(walk)

        assert calls == ["namespace-vpc-1", "namespace-bastion-1"]

    def test_execute_plan_graph_locked(self) -> None:
        """Test execute plan with locked persistent graph.

        If another cfngin process holds the graph lock, execution must
        fail fast with PersistentGraphLocked to prevent concurrent mutations.
        """
        context = CfnginContext(config=self.config)
        context._persistent_graph = Graph.from_dict({"stack1": []}, context)
        context._persistent_graph_lock_code = "1111"
        plan = Plan(description="Test", graph=Graph(), context=context)
        with pytest.raises(PersistentGraphLocked):
            plan.execute()

    def test_build_graph_missing_dependency(self) -> None:
        """Test build graph missing dependency.

        A stack referencing a non-existent dependency must raise GraphError
        at plan construction time, not at execution time, so users get
        immediate feedback on configuration errors.
        """
        bastion = Stack(
            definition=generate_definition("bastion", 1, requires=["vpc-1"]),
            context=self.context,
        )

        with pytest.raises(GraphError) as expected:
            Graph.from_steps([Step(bastion)])
        message_starts = "Error detected when adding 'vpc-1' as a dependency of 'bastion-1':"
        message_contains = "dependent node vpc-1 does not exist"
        assert str(expected.value).startswith(message_starts)
        assert message_contains in str(expected.value)

    def test_build_graph_cyclic_dependencies(self) -> None:
        """Test build graph cyclic dependencies.

        Circular dependencies would cause infinite loops during execution,
        so they must be detected and rejected during graph construction.
        """
        vpc = Stack(definition=generate_definition("vpc", 1), context=self.context)
        db = Stack(
            definition=generate_definition("db", 1, requires=["app-1"]),
            context=self.context,
        )
        app = Stack(
            definition=generate_definition("app", 1, requires=["db-1"]),
            context=self.context,
        )

        with pytest.raises(GraphError) as expected:
            Graph.from_steps([Step(vpc), Step(db), Step(app)])
        message = (
            "Error detected when adding 'db-1' as a dependency of 'app-1': graph is not acyclic"
        )
        assert str(expected.value) == message

    def test_dump(self) -> None:
        """Test dump.

        Validates that the plan can serialize all stack templates to disk,
        which is used by the diff/info actions to show users what would be
        deployed without actually executing CloudFormation operations.
        """
        requires: list[str] = []
        steps: list[Step] = []

        for i in range(5):
            overrides = {
                "variables": {
                    "PublicSubnets": "1",
                    "SshKeyName": "1",
                    "PrivateSubnets": "1",
                    "Random": "${noop something}",
                },
                "requires": requires,
            }

            stack = Stack(
                definition=generate_definition("vpc", i, **overrides),
                context=self.context,
            )
            requires = [stack.name]

            steps += [Step(stack)]

        graph = Graph.from_steps(steps)
        plan = Plan(description="Test", graph=graph)

        tmp_dir = tempfile.mkdtemp()
        try:
            plan.dump(directory=tmp_dir, context=self.context)

            for step in plan.steps:
                assert (Path(tmp_dir) / stack_template_key_name(step.stack.blueprint)).is_file()
        finally:
            shutil.rmtree(tmp_dir)
