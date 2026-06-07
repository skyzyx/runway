"""Tests for runway.cfngin.providers.aws.default.

Validates the CloudFormation provider layer that wraps all boto3 interactions,
ensuring correct handling of stack CRUD, changeset workflows, interactive approval,
event tailing, and error translation for various CloudFormation API states.
"""

from __future__ import annotations

import copy
import locale
import random
import string
import threading
import unittest
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError, UnStubbedResponseError
from botocore.stub import Stubber

from runway.cfngin import exceptions
from runway.cfngin.actions.diff import DictValue
from runway.cfngin.providers.aws import default
from runway.cfngin.providers.aws.default import (
    DEFAULT_CAPABILITIES,
    MAX_TAIL_RETRIES,
    Provider,
    ask_for_approval,
    create_change_set,
    generate_cloudformation_args,
    output_full_changeset,
    requires_replacement,
    summarize_params_diff,
    wait_till_change_set_complete,
)
from runway.cfngin.providers.base import Template
from runway.cfngin.session_cache import get_session
from runway.cfngin.stack import Stack
from runway.utils import MutableMap

if TYPE_CHECKING:
    from mypy_boto3_cloudformation.type_defs import (
        ChangeTypeDef,
        ResourceChangeTypeDef,
        StackTypeDef,
    )
    from pytest_mock import MockerFixture
    from typing_extensions import Literal

    from runway.core.providers.aws.type_defs import TagSetTypeDef


def random_string(length: int = 12) -> str:
    """Return a random string of variable length.

    Generates non-deterministic test data so that tests don't accidentally
    pass due to hardcoded values matching expected outputs.

    Args:
        length: The # of characters to use in the random string.

    """
    return "".join([random.choice(string.ascii_letters) for _ in range(length)])  # noqa: S311


def generate_describe_stacks_stack(
    stack_name: str,
    creation_time: datetime | None = None,
    stack_status: Literal[
        "CREATE_IN_PROGRESS",
        "CREATE_FAILED",
        "CREATE_COMPLETE",
        "ROLLBACK_IN_PROGRESS",
        "ROLLBACK_FAILED",
        "ROLLBACK_COMPLETE",
        "DELETE_IN_PROGRESS",
        "DELETE_FAILED",
        "DELETE_COMPLETE",
        "UPDATE_IN_PROGRESS",
        "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
        "UPDATE_COMPLETE",
        "UPDATE_ROLLBACK_IN_PROGRESS",
        "UPDATE_ROLLBACK_FAILED",
        "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS",
        "UPDATE_ROLLBACK_COMPLETE",
        "REVIEW_IN_PROGRESS",
        "IMPORT_IN_PROGRESS",
        "IMPORT_COMPLETE",
        "IMPORT_ROLLBACK_IN_PROGRESS",
        "IMPORT_ROLLBACK_FAILED",
        "IMPORT_ROLLBACK_COMPLETE",
    ] = "CREATE_COMPLETE",
    tags: TagSetTypeDef | None = None,
    termination_protection: bool = False,
) -> StackTypeDef:
    """Generate describe stacks stack.

    Provides a reusable factory for DescribeStacks responses so tests can
    exercise different stack lifecycle states without duplicating boilerplate.
    """
    tags = tags or []
    return {
        "StackName": stack_name,
        "StackId": stack_name,
        "CreationTime": creation_time or datetime(2015, 1, 1),
        "StackStatus": stack_status,
        "Tags": tags,
        "EnableTerminationProtection": termination_protection,
    }


def generate_get_template(
    file_name: str = "cfn_template.json", stages_available: list[str] | None = None
) -> dict[str, Any]:
    """Generate get template.

    Loads real fixture templates so changeset diff logic is tested against
    realistic CloudFormation template bodies rather than empty stubs.
    """
    return {
        "StagesAvailable": stages_available or ["Original"],
        "TemplateBody": (Path(__file__).parent.parent.parent / "fixtures" / file_name).read_text(),
    }


def generate_stack_object(stack_name: str, outputs: dict[str, Any] | None = None) -> MagicMock:
    """Generate stack object.

    Creates a mock Stack with output definitions so tests can verify that
    the provider correctly infers output changes from changeset responses.
    """
    mock_stack = MagicMock(["name", "fqn", "blueprint"])
    if not outputs:
        outputs = {"FakeOutput": {"Value": {"Ref": "FakeResource"}}}
    mock_stack.name = stack_name
    mock_stack.fqn = stack_name
    mock_stack.blueprint = MagicMock(["output_definitions"])
    mock_stack.blueprint.output_definitions = outputs
    return mock_stack


def generate_resource_change(replacement: bool = True) -> ChangeTypeDef:
    """Generate resource change.

    Builds a single changeset resource entry to test that the provider
    correctly identifies resources requiring replacement vs in-place updates.
    """
    resource_change: ResourceChangeTypeDef = {
        "Action": "Modify",
        "Details": [],
        "LogicalResourceId": "Fake",
        "PhysicalResourceId": "arn:aws:fake",
        "Replacement": "True" if replacement else "False",
        "ResourceType": "AWS::Fake",
        "Scope": ["Properties"],
    }
    return {
        "ResourceChange": resource_change,
        "Type": "Resource",
    }


def generate_change_set_response(
    status: str,
    execution_status: str = "AVAILABLE",
    changes: list[dict[str, Any]] | None = None,
    status_reason: str = "FAKE",
) -> dict[str, Any]:
    """Generate change set response.

    Simulates the full DescribeChangeSet API response shape so tests can
    exercise status polling, failure handling, and change extraction paths.
    """
    return {
        "ChangeSetName": "string",
        "ChangeSetId": "string",
        "StackId": "string",
        "StackName": "string",
        "Description": "string",
        "Parameters": [
            {
                "ParameterKey": "string",
                "ParameterValue": "string",
                "UsePreviousValue": False,
            },
        ],
        "CreationTime": datetime(2015, 1, 1),
        "ExecutionStatus": execution_status,
        "Status": status,
        "StatusReason": status_reason,
        "NotificationARNs": ["string"],
        "Capabilities": ["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        "Tags": [{"Key": "string", "Value": "string"}],
        "Changes": changes or [],
        "NextToken": "string",
    }


def generate_change(
    action: str = "Modify",
    resource_type: str = "EC2::Instance",
    replacement: str = "False",
    requires_recreation: str = "Never",
) -> dict[str, Any]:
    """Generate a minimal change for a changeset.

    Produces a single resource-level change entry with randomized IDs so
    tests can build multi-change changesets without colliding identifiers.
    """
    return {
        "Type": "Resource",
        "ResourceChange": {
            "Action": action,
            "LogicalResourceId": random_string(),
            "PhysicalResourceId": random_string(),
            "ResourceType": resource_type,
            "Replacement": replacement,
            "Scope": ["Properties"],
            "Details": [
                {
                    "Target": {
                        "Attribute": "Properties",
                        "Name": random_string(),
                        "RequiresRecreation": requires_recreation,
                    },
                    "Evaluation": "Static",
                    "ChangeSource": "ResourceReference",
                    "CausingEntity": random_string(),
                },
            ],
        },
    }


class TestMethods(unittest.TestCase):
    """Tests for runway.cfngin.providers.aws.default.

    Validates the module-level utility functions that support changeset
    workflows, ensuring correct filtering, summarization, and user approval
    logic independent of the Provider class state.
    """

    def setUp(self) -> None:
        """Run before tests."""
        self.cfn = boto3.client("cloudformation")
        self.stubber = Stubber(self.cfn)

    def test_requires_replacement(self) -> None:
        """Test requires replacement.

        Verifies that only resources marked for replacement are filtered out,
        because these represent destructive changes the user must be warned about.
        """
        changeset = [
            generate_resource_change(),
            generate_resource_change(replacement=False),
            generate_resource_change(),
        ]
        replacement = requires_replacement(changeset)
        assert len(replacement) == 2
        for resource in replacement:
            assert resource.get("ResourceChange", {}).get("Replacement") == "True"

    def test_summarize_params_diff(self) -> None:
        """Test summarize params diff.

        Ensures the human-readable summary correctly categorizes parameter
        changes into added/removed/modified, which is displayed to users
        during interactive approval to help them assess deployment impact.
        """
        unmodified_param = DictValue("ParamA", "new-param-value", "new-param-value")
        modified_param = DictValue("ParamB", "param-b-old-value", "param-b-new-value-delta")
        added_param = DictValue("ParamC", None, "param-c-new-value")
        removed_param = DictValue("ParamD", "param-d-old-value", None)

        params_diff = [
            unmodified_param,
            modified_param,
            added_param,
            removed_param,
        ]
        assert summarize_params_diff([]) == ""
        assert (
            summarize_params_diff(params_diff)
            == "Parameters Added: ParamC\nParameters Removed: ParamD\nParameters Modified: ParamB\n"
        )

        only_modified_params_diff = [modified_param]
        assert summarize_params_diff(only_modified_params_diff) == "Parameters Modified: ParamB\n"

        only_added_params_diff = [added_param]
        assert summarize_params_diff(only_added_params_diff) == "Parameters Added: ParamC\n"

        only_removed_params_diff = [removed_param]
        assert summarize_params_diff(only_removed_params_diff) == "Parameters Removed: ParamD\n"

    def test_ask_for_approval(self) -> None:
        """Test ask for approval.

        Validates that the interactive approval gate correctly accepts 'y',
        rejects other inputs with CancelExecution, and supports the 'v'
        verbose mode path — critical for preventing accidental deployments.
        """
        get_input_path = "runway.cfngin.ui.get_raw_input"
        with patch(get_input_path, return_value="y"):
            assert ask_for_approval([], [], False) is None  # type: ignore[func-returns-value]

        for v in ("n", "N", "x", "\n"):
            with patch(get_input_path, return_value=v), pytest.raises(exceptions.CancelExecution):
                ask_for_approval([], [])

        with patch(get_input_path, side_effect=["v", "n"]) as mock_get_input:
            with patch(
                "runway.cfngin.providers.aws.default.output_full_changeset"
            ) as mock_full_changeset:
                with pytest.raises(exceptions.CancelExecution):
                    ask_for_approval([], [], True)
                assert mock_full_changeset.call_count == 1
            assert mock_get_input.call_count == 2

    def test_ask_for_approval_with_params_diff(self) -> None:
        """Test ask for approval with params diff.

        Ensures the approval flow still works correctly when parameter diffs
        are present, since params_diff alters the displayed output to the user.
        """
        get_input_path = "runway.cfngin.ui.get_raw_input"
        params_diff = [
            DictValue("ParamA", None, "new-param-value"),
            DictValue("ParamB", "param-b-old-value", "param-b-new-value-delta"),
        ]
        with patch(get_input_path, return_value="y"):
            assert ask_for_approval([], params_diff, False) is None  # type: ignore[func-returns-value]

        for v in ("n", "N", "x", "\n"):
            with patch(get_input_path, return_value=v), pytest.raises(exceptions.CancelExecution):
                ask_for_approval([], params_diff)

        with patch(get_input_path, side_effect=["v", "n"]) as mock_get_input:
            with patch(
                "runway.cfngin.providers.aws.default.output_full_changeset"
            ) as mock_full_changeset:
                with pytest.raises(exceptions.CancelExecution):
                    ask_for_approval([], params_diff, True)
                assert mock_full_changeset.call_count == 1
            assert mock_get_input.call_count == 2

    @patch("runway.cfngin.providers.aws.default.format_params_diff")
    @patch("runway.cfngin.providers.aws.default.yaml.safe_dump")
    def test_output_full_changeset(
        self, mock_safe_dump: MagicMock, patched_format: MagicMock
    ) -> None:
        """Test output full changeset.

        Validates the verbose changeset display logic handles all user input
        paths (y/Y/v/V to show, n/N to skip, x to cancel) and only formats
        params_diff when actual parameter changes exist.
        """
        get_input_path = "runway.cfngin.ui.get_raw_input"

        safe_dump_counter = 0

        for v in ["y", "v", "Y", "V"]:
            with patch(get_input_path, return_value=v) as prompt:
                assert output_full_changeset(full_changeset=[], params_diff=[], fqn=None) is None  # type: ignore[func-returns-value]
                assert prompt.call_count == 1
                safe_dump_counter += 1
                assert mock_safe_dump.call_count == safe_dump_counter
                assert patched_format.call_count == 0

        for v in ["n", "N"]:
            with patch(get_input_path, return_value=v) as prompt:
                output_full_changeset(full_changeset=[], params_diff=[], answer=None, fqn=None)
                assert prompt.call_count == 1
                assert mock_safe_dump.call_count == safe_dump_counter
                assert patched_format.call_count == 0

        with pytest.raises(exceptions.CancelExecution):
            output_full_changeset(full_changeset=[], params_diff=[], answer="x", fqn=None)

        output_full_changeset(
            full_changeset=[],
            params_diff=[DictValue("mock", "", "")],
            answer="y",
            fqn=None,
        )
        safe_dump_counter += 1
        assert mock_safe_dump.call_count == safe_dump_counter
        assert patched_format.call_count == 1

    def test_wait_till_change_set_complete_success(self) -> None:
        """Test wait till change set complete success.

        Confirms the poller exits cleanly on terminal states (CREATE_COMPLETE
        and FAILED) without raising, since both represent stabilized changesets.
        """
        self.stubber.add_response(
            "describe_change_set", generate_change_set_response("CREATE_COMPLETE")
        )
        with self.stubber:
            wait_till_change_set_complete(self.cfn, "FAKEID")

        self.stubber.add_response("describe_change_set", generate_change_set_response("FAILED"))
        with self.stubber:
            wait_till_change_set_complete(self.cfn, "FAKEID")

    def test_wait_till_change_set_complete_failed(self) -> None:
        """Test wait till change set complete failed.

        Ensures the poller raises ChangesetDidNotStabilize when retries are
        exhausted, preventing indefinite hangs on stuck changesets.
        """
        # Need 2 responses for try_count
        for _ in range(2):
            self.stubber.add_response(
                "describe_change_set", generate_change_set_response("CREATE_PENDING")
            )
        with self.stubber, pytest.raises(exceptions.ChangesetDidNotStabilize):
            wait_till_change_set_complete(self.cfn, "FAKEID", try_count=2, sleep_time=0.1)

    def test_create_change_set_stack_did_not_change(self) -> None:
        """Test create change set stack did not change.

        Validates that when CloudFormation reports no changes, the changeset is
        cleaned up and StackDidNotChange is raised — this is the expected
        no-op path that prevents unnecessary stack updates.
        """
        self.stubber.add_response("create_change_set", {"Id": "CHANGESETID", "StackId": "STACKID"})

        self.stubber.add_response(
            "describe_change_set",
            generate_change_set_response("FAILED", status_reason="Stack didn't contain changes."),
        )

        self.stubber.add_response(
            "delete_change_set", {}, expected_params={"ChangeSetName": "CHANGESETID"}
        )

        with self.stubber, pytest.raises(exceptions.StackDidNotChange):
            create_change_set(
                cfn_client=self.cfn,
                fqn="my-fake-stack",
                template=Template(url="http://fake.template.url.com/"),
                parameters=[],
                tags=[],
            )

    def test_create_change_set_unhandled_failed_status(self) -> None:
        """Test create change set unhandled failed status.

        Ensures unexpected failure reasons bubble up as UnhandledChangeSetStatus
        rather than being silently swallowed, so operators can investigate.
        """
        self.stubber.add_response("create_change_set", {"Id": "CHANGESETID", "StackId": "STACKID"})

        self.stubber.add_response(
            "describe_change_set",
            generate_change_set_response("FAILED", status_reason="Some random bad thing."),
        )

        with self.stubber, pytest.raises(exceptions.UnhandledChangeSetStatus):
            create_change_set(
                cfn_client=self.cfn,
                fqn="my-fake-stack",
                template=Template(url="http://fake.template.url.com/"),
                parameters=[],
                tags=[],
            )

    def test_create_change_set_bad_execution_status(self) -> None:
        """Test create change set bad execution status.

        Verifies that a changeset in UNAVAILABLE execution status raises
        UnableToExecuteChangeSet, since executing such a changeset would fail
        at the API level anyway.
        """
        self.stubber.add_response("create_change_set", {"Id": "CHANGESETID", "StackId": "STACKID"})

        self.stubber.add_response(
            "describe_change_set",
            generate_change_set_response(status="CREATE_COMPLETE", execution_status="UNAVAILABLE"),
        )

        with self.stubber, pytest.raises(exceptions.UnableToExecuteChangeSet):
            create_change_set(
                cfn_client=self.cfn,
                fqn="my-fake-stack",
                template=Template(url="http://fake.template.url.com/"),
                parameters=[],
                tags=[],
            )

    def test_generate_cloudformation_args(self) -> None:
        """Test generate cloudformation args.

        Validates the argument builder correctly maps provider options to the
        CloudFormation API parameter shape, including optional fields like
        service role, change set name, stack policy, and template body fallback.
        """
        stack_name = "mystack"
        template_url = "http://fake.s3url.com/blah.json"
        template_body = '{"fake_body": "woot"}'
        std_args: dict[str, Any] = {
            "stack_name": stack_name,
            "parameters": [],
            "tags": [],
            "template": Template(url=template_url),
        }
        std_return: dict[str, Any] = {
            "StackName": stack_name,
            "Parameters": [],
            "Tags": [],
            "Capabilities": DEFAULT_CAPABILITIES,
            "TemplateURL": template_url,
        }
        result = generate_cloudformation_args(**std_args)
        assert result == std_return

        result = generate_cloudformation_args(service_role="FakeRole", **std_args)
        service_role_result = copy.deepcopy(std_return)
        service_role_result["RoleARN"] = "FakeRole"
        assert result == service_role_result

        result = generate_cloudformation_args(change_set_name="MyChanges", **std_args)
        change_set_result = copy.deepcopy(std_return)
        change_set_result["ChangeSetName"] = "MyChanges"
        assert result == change_set_result

        # Check stack policy
        stack_policy = Template(body="{}")
        result = generate_cloudformation_args(stack_policy=stack_policy, **std_args)
        stack_policy_result = copy.deepcopy(std_return)
        stack_policy_result["StackPolicyBody"] = "{}"
        assert result == stack_policy_result

        # If not TemplateURL is provided, use TemplateBody
        std_args["template"] = Template(body=template_body)
        template_body_result = copy.deepcopy(std_return)
        del template_body_result["TemplateURL"]
        template_body_result["TemplateBody"] = template_body
        result = generate_cloudformation_args(**std_args)
        assert result == template_body_result


class TestProvider:
    """Test Provider.

    Validates Provider instance methods that inspect stack events and status,
    ensuring correct extraction of failure reasons from CloudFormation event
    history — essential for meaningful error messages during deployments.
    """

    def test_get_delete_failed_status_reason(self, mocker: MockerFixture) -> None:
        """Test get_delete_failed_status_reason.

        Ensures the provider can extract a human-readable reason from
        DELETE_FAILED events, and gracefully returns None when no reason exists.
        """
        mock_get_event_by_resource_status = mocker.patch.object(
            Provider,
            "get_event_by_resource_status",
            side_effect=[{"ResourceStatusReason": "reason"}, {}],
        )
        obj = Provider(MagicMock())
        assert obj.get_delete_failed_status_reason("test") == "reason"
        mock_get_event_by_resource_status.assert_called_once_with(
            "test", "DELETE_FAILED", chronological=True
        )
        assert not obj.get_delete_failed_status_reason("test")

    def test_get_event_by_resource_status(self, mocker: MockerFixture) -> None:
        """Test get_event_by_resource_status.

        Validates that the first matching event is returned when searching
        chronologically, and that missing statuses return None rather than
        raising — both paths are used during error reporting.
        """
        events = [
            {"StackName": "0"},
            {"StackName": "1", "ResourceStatus": "no match"},
            {"StackName": "2", "ResourceStatus": "match"},
            {"StackName": "3", "ResourceStatus": "match"},
        ]
        mock_get_events = mocker.patch.object(Provider, "get_events", return_value=events)
        obj = Provider(MagicMock())

        result = obj.get_event_by_resource_status("test", "match")
        assert result
        assert result["StackName"] == "2"
        mock_get_events.assert_called_once_with("test", chronological=True)

        assert not obj.get_event_by_resource_status("test", "missing", chronological=False)
        mock_get_events.assert_called_with("test", chronological=False)

    def test_get_rollback_status_reason(self, mocker: MockerFixture) -> None:
        """Test get_rollback_status_reason.

        Exercises the fallback chain: first checks UPDATE_ROLLBACK_IN_PROGRESS,
        then ROLLBACK_IN_PROGRESS, then returns None — this mirrors the
        multiple rollback event types CloudFormation can produce.
        """
        mock_get_event_by_resource_status = mocker.patch.object(
            Provider,
            "get_event_by_resource_status",
            side_effect=[
                {"ResourceStatusReason": "reason0"},
                {},
                {"ResourceStatusReason": "reason2"},
                {},
                {},
            ],
        )
        obj = Provider(MagicMock())
        assert obj.get_rollback_status_reason("test") == "reason0"
        mock_get_event_by_resource_status.assert_called_once_with(
            "test", "UPDATE_ROLLBACK_IN_PROGRESS", chronological=False
        )
        assert obj.get_rollback_status_reason("test") == "reason2"
        mock_get_event_by_resource_status.assert_called_with(
            "test", "ROLLBACK_IN_PROGRESS", chronological=True
        )
        assert not obj.get_rollback_status_reason("test")

    def test_get_stack_status_reason(self) -> None:
        """Test get_stack_status_reason.

        Confirms the static helper safely extracts StackStatusReason when
        present and returns None when absent, avoiding KeyError on stacks
        that have no reason field (e.g., successfully completed stacks).
        """
        stack_details = generate_describe_stacks_stack("test")
        assert Provider.get_stack_status_reason(stack_details) is None
        stack_details["StackStatusReason"] = "reason"
        assert Provider.get_stack_status_reason(stack_details) == "reason"

    @pytest.mark.parametrize(
        "status, expected",
        [("DELETE_FAILED", False), ("CREATE_FAILED", True), ("CREATE_COMPLETE", True)],
    )
    def test_is_stack_destroy_possible(self, expected: bool, status: str) -> None:
        """Test is_stack_destroy_possible.

        Parametrized across stack states to confirm that DELETE_FAILED stacks
        cannot be destroyed again (requires manual intervention), while other
        states allow deletion to proceed.
        """
        assert (
            Provider(MagicMock()).is_stack_destroy_possible(
                generate_describe_stacks_stack("test", stack_status=status)  # type: ignore
            )
            is expected
        )


class TestProviderDefaultMode(unittest.TestCase):
    """Tests for runway.cfngin.providers.aws.default default mode.

    Validates non-interactive (CI/CD) provider behavior including direct stack
    creation, changeset-based updates, stack preparation logic for various
    lifecycle states, and event tailing retry resilience.
    """

    def setUp(self) -> None:
        """Run before tests."""
        region = "us-east-1"
        self.session = get_session(region=region)
        self.provider = Provider(self.session, region=region, recreate_failed=False)
        self.stubber = Stubber(self.provider.cloudformation)

    def test_create_stack_no_changeset(self) -> None:
        """Test create_stack, no changeset, template url.

        Validates the direct CreateStack API path used in non-interactive mode,
        ensuring termination protection and timeout are passed through correctly.
        """
        stack_name = "fake_stack"
        template = Template(url="http://fake.template.url.com/")
        parameters: list[Any] = []
        tags: list[Any] = []

        expected_args = generate_cloudformation_args(stack_name, parameters, tags, template)
        expected_args["EnableTerminationProtection"] = False
        expected_args["TimeoutInMinutes"] = 60

        self.stubber.add_response("create_stack", {"StackId": stack_name}, expected_args)

        with self.stubber:
            self.provider.create_stack(stack_name, template, parameters, tags, timeout=60)
        self.stubber.assert_no_pending_responses()

    @patch("runway.cfngin.providers.aws.default.Provider.update_termination_protection")
    @patch("runway.cfngin.providers.aws.default.create_change_set")
    def test_create_stack_with_changeset(
        self, patched_create_change_set: MagicMock, patched_update_term: MagicMock
    ) -> None:
        """Test create_stack, force changeset, termination protection.

        Validates the changeset-based creation path which is required when
        termination protection is enabled, since it must be set after the
        stack transitions from REVIEW_IN_PROGRESS to created.
        """
        stack_name = "fake_stack"
        template_path = Path("./tests/unit/cfngin/fixtures/cfn_template.yaml")
        template = Template(
            body=template_path.read_text(encoding=locale.getpreferredencoding(do_setlocale=False))
        )
        parameters: list[Any] = []
        tags: list[Any] = []

        changeset_id = "CHANGESETID"

        patched_create_change_set.return_value = ([], changeset_id)

        self.stubber.add_response("execute_change_set", {}, {"ChangeSetName": changeset_id})

        with self.stubber:
            self.provider.create_stack(
                stack_name,
                template,
                parameters,
                tags,
                force_change_set=True,
                termination_protection=True,
            )
        self.stubber.assert_no_pending_responses()

        patched_create_change_set.assert_called_once_with(
            self.provider.cloudformation,
            stack_name,
            template,
            parameters,
            tags,
            "CREATE",
            service_role=self.provider.service_role,
        )
        patched_update_term.assert_called_once_with(stack_name, True)

    def test_destroy_stack(self) -> None:
        """Test destroy stack.

        Confirms the basic delete path issues a DeleteStack call and
        returns None on success — the simplest happy path for stack removal.
        """
        stack = {"StackName": "MockStack"}

        self.stubber.add_response("delete_stack", {}, stack)

        with self.stubber:
            assert self.provider.destroy_stack(stack) is None  # type: ignore
            self.stubber.assert_no_pending_responses()

    def test_get_stack_stack_does_not_exist(self) -> None:
        """Test get stack stack does not exist.

        Verifies that the provider translates CloudFormation's ValidationError
        into a typed StackDoesNotExist exception for cleaner upstream handling.
        """
        stack_name = "MockStack"
        self.stubber.add_client_error(
            "describe_stacks",
            service_error_code="ValidationError",
            service_message=f"Stack with id {stack_name} does not exist",
            expected_params={"StackName": stack_name},
        )

        with pytest.raises(exceptions.StackDoesNotExist), self.stubber:
            self.provider.get_stack(stack_name)

    def test_get_stack_stack_exists(self) -> None:
        """Test get stack stack exists.

        Confirms the happy path returns the stack dict from DescribeStacks.
        """
        stack_name = "MockStack"
        stack_response = {"Stacks": [generate_describe_stacks_stack(stack_name)]}
        self.stubber.add_response(
            "describe_stacks", stack_response, expected_params={"StackName": stack_name}
        )

        with self.stubber:
            response = self.provider.get_stack(stack_name)

        assert response["StackName"] == stack_name

    def test_select_destroy_method(self) -> None:
        """Test select destroy method.

        Ensures the method dispatcher correctly routes to noninteractive or
        interactive destroy based on the force_interactive flag.
        """
        for i in [
            [{"force_interactive": False}, self.provider.noninteractive_destroy_stack],
            [{"force_interactive": True}, self.provider.interactive_destroy_stack],
        ]:
            assert self.provider.select_destroy_method(**i[0]) == i[1]  # type: ignore

    def test_select_update_method(self) -> None:
        """Test select update method.

        Validates the update method selection matrix: interactive mode takes
        precedence over force_change_set, and the default path is used only
        when neither flag is set.
        """
        for i in [
            [
                {"force_interactive": True, "force_change_set": False},
                self.provider.interactive_update_stack,
            ],
            [
                {"force_interactive": False, "force_change_set": False},
                self.provider.default_update_stack,
            ],
            [
                {"force_interactive": False, "force_change_set": True},
                self.provider.noninteractive_changeset_update,
            ],
            [
                {"force_interactive": True, "force_change_set": True},
                self.provider.interactive_update_stack,
            ],
        ]:
            assert self.provider.select_update_method(**i[0]) == i[1]  # type: ignore

    def test_prepare_stack_for_update_completed(self) -> None:
        """Test prepare stack for update completed.

        Confirms stacks in a terminal success state are ready for update
        without any preparatory action needed.
        """
        with self.stubber:
            stack_name = "MockStack"
            stack = generate_describe_stacks_stack(stack_name, stack_status="UPDATE_COMPLETE")

            assert self.provider.prepare_stack_for_update(stack, [])

    def test_prepare_stack_for_update_in_progress(self) -> None:
        """Test prepare stack for update in progress.

        Validates that stacks currently being modified cannot be updated
        concurrently, raising StackUpdateBadStatus with an in-progress message.
        """
        stack_name = "MockStack"
        stack = generate_describe_stacks_stack(stack_name, stack_status="UPDATE_IN_PROGRESS")

        with self.stubber, pytest.raises(exceptions.StackUpdateBadStatus) as raised:
            self.provider.prepare_stack_for_update(stack, [])

        assert "in-progress" in str(raised.value)

    def test_prepare_stack_for_update_non_recreatable(self) -> None:
        """Test prepare stack for update non recreatable.

        Ensures stacks in REVIEW_IN_PROGRESS (changeset-created but never
        executed) are rejected since they cannot be updated in place.
        """
        stack_name = "MockStack"
        stack = generate_describe_stacks_stack(stack_name, stack_status="REVIEW_IN_PROGRESS")

        with pytest.raises(exceptions.StackUpdateBadStatus) as excinfo, self.stubber:
            self.provider.prepare_stack_for_update(stack, [])

        assert "Unsupported state" in str(excinfo.value)

    def test_prepare_stack_for_update_disallowed(self) -> None:
        """Test prepare stack for update disallowed.

        Confirms ROLLBACK_COMPLETE stacks are rejected when recreate_failed is
        disabled, and the error message includes the --recreate-failed hint
        so users know how to proceed.
        """
        stack_name = "MockStack"
        stack = generate_describe_stacks_stack(stack_name, stack_status="ROLLBACK_COMPLETE")

        with pytest.raises(exceptions.StackUpdateBadStatus) as excinfo, self.stubber:
            self.provider.prepare_stack_for_update(stack, [])

        assert "re-creation is disabled" in str(excinfo.value)
        # Ensure we point out to the user how to enable re-creation
        assert "--recreate-failed" in str(excinfo.value)

    def test_prepare_stack_for_update_bad_tags(self) -> None:
        """Test prepare stack for update bad tags.

        Verifies that even with recreate_failed enabled, tag mismatches
        prevent recreation — this guards against accidentally destroying a
        stack that belongs to a different namespace.
        """
        stack_name = "MockStack"
        stack = generate_describe_stacks_stack(stack_name, stack_status="ROLLBACK_COMPLETE")

        self.provider.recreate_failed = True

        with pytest.raises(exceptions.StackUpdateBadStatus) as excinfo, self.stubber:
            self.provider.prepare_stack_for_update(
                stack, tags=[{"Key": "cfngin_namespace", "Value": "test"}]
            )

        assert "tags differ" in str(excinfo.value).lower()

    def test_prepare_stack_for_update_recreate(self) -> None:
        """Test prepare stack for update recreate.

        Confirms that ROLLBACK_COMPLETE stacks are deleted when recreate_failed
        is enabled, returning False to signal the caller must create anew.
        """
        stack_name = "MockStack"
        stack = generate_describe_stacks_stack(stack_name, stack_status="ROLLBACK_COMPLETE")

        self.stubber.add_response("delete_stack", {}, expected_params={"StackName": stack_name})

        self.provider.recreate_failed = True

        with self.stubber:
            assert not self.provider.prepare_stack_for_update(stack, [])

    def test_noninteractive_changeset_update_no_stack_policy(self) -> None:
        """Test noninteractive changeset update no stack policy.

        Validates the changeset update path without stack policy, ensuring
        the changeset is created, described, and executed in sequence.
        """
        self.stubber.add_response("create_change_set", {"Id": "CHANGESETID", "StackId": "STACKID"})
        changes = [generate_change()]
        self.stubber.add_response(
            "describe_change_set",
            generate_change_set_response(
                status="CREATE_COMPLETE", execution_status="AVAILABLE", changes=changes
            ),
        )

        self.stubber.add_response("execute_change_set", {})

        with self.stubber:
            stack_name = "MockStack"
            self.provider.noninteractive_changeset_update(
                fqn=stack_name,
                template=Template(url="http://fake.template.url.com/"),
                old_parameters=[],
                parameters=[],
                stack_policy=None,
                tags=[],
            )

    def test_noninteractive_changeset_update_with_stack_policy(self) -> None:
        """Test noninteractive changeset update with stack policy.

        Ensures that when a stack policy is provided, set_stack_policy is
        called before execute_change_set — order matters because the policy
        must be in place before the update proceeds.
        """
        self.stubber.add_response("create_change_set", {"Id": "CHANGESETID", "StackId": "STACKID"})
        changes = [generate_change()]
        self.stubber.add_response(
            "describe_change_set",
            generate_change_set_response(
                status="CREATE_COMPLETE", execution_status="AVAILABLE", changes=changes
            ),
        )
        self.stubber.add_response("set_stack_policy", {})
        self.stubber.add_response("execute_change_set", {})

        with self.stubber:
            stack_name = "MockStack"
            self.provider.noninteractive_changeset_update(
                fqn=stack_name,
                template=Template(url="http://fake.template.url.com/"),
                old_parameters=[],
                parameters=[],
                stack_policy=Template(body="{}"),
                tags=[],
            )

    def test_noninteractive_destroy_stack_termination_protected(self) -> None:
        """Test noninteractive_destroy_stack with termination protection.

        Validates the auto-disable-and-retry flow: when delete fails due to
        termination protection, the provider disables it and retries — this
        is the expected behavior for automated teardown pipelines.
        """
        self.stubber.add_client_error("delete_stack", service_message="TerminationProtection")
        self.stubber.add_response(
            "describe_stacks",
            {
                "Stacks": [
                    generate_describe_stacks_stack("fake-stack", stack_status="ROLLBACK_COMPLETE")
                ]
            },
        )
        self.stubber.add_response(
            "describe_stacks",
            {"Stacks": [generate_describe_stacks_stack("fake-stack", termination_protection=True)]},
        )
        self.stubber.add_response(
            "update_termination_protection",
            {},
            {"EnableTerminationProtection": False, "StackName": "fake-stack"},
        )
        self.stubber.add_response("delete_stack", {}, {"StackName": "fake-stack"})

        with self.stubber:
            self.provider.noninteractive_destroy_stack("fake-stack")
        self.stubber.assert_no_pending_responses()

    def test_noninteractive_destroy_stack_termination_protected_not_allowed(
        self,
    ) -> None:
        """Test noninteractive_destroy_stack with termination protection.

        Ensures that when auto-disable is explicitly forbidden, the original
        ClientError propagates — preventing accidental destruction of
        protected stacks in restricted environments.
        """
        self.stubber.add_client_error("delete_stack", service_message="TerminationProtection")

        with self.stubber, pytest.raises(ClientError):
            self.provider.noninteractive_destroy_stack(
                "fake-stack", allow_disable_termination_protection=False
            )
        self.stubber.assert_no_pending_responses()

    @patch("runway.cfngin.providers.aws.default.output_full_changeset")
    def test_get_stack_changes_update(self, mock_output_full_cs: MagicMock) -> None:
        """Test get stack changes update.

        Validates the dry-run changeset workflow for existing stacks: creates
        a temporary changeset, extracts changes and inferred outputs, then
        cleans up — used by the diff action to preview updates without applying.
        """
        stack_name = "MockStack"
        mock_stack = generate_stack_object(stack_name)

        self.stubber.add_response(
            "describe_stacks", {"Stacks": [generate_describe_stacks_stack(stack_name)]}
        )
        self.stubber.add_response("get_template", generate_get_template("cfn_template.yaml"))
        self.stubber.add_response("create_change_set", {"Id": "CHANGESETID", "StackId": stack_name})
        changes = [generate_change()]
        self.stubber.add_response(
            "describe_change_set",
            generate_change_set_response(
                status="CREATE_COMPLETE", execution_status="AVAILABLE", changes=changes
            ),
        )
        self.stubber.add_response("delete_change_set", {})
        self.stubber.add_response(
            "describe_stacks", {"Stacks": [generate_describe_stacks_stack(stack_name)]}
        )

        with self.stubber:
            result = self.provider.get_stack_changes(
                stack=mock_stack,
                template=Template(url="http://fake.template.url.com/"),
                parameters=[],
                tags=[],
            )

        mock_output_full_cs.assert_called_with(
            full_changeset=changes, params_diff=[], fqn=stack_name, answer="y"
        )
        expected_outputs = {
            "FakeOutput": "<inferred-change = MockStack.FakeOutput={'Ref': 'FakeResource'}>"
        }
        assert self.provider.get_outputs(stack_name) == expected_outputs
        assert result == expected_outputs

    @patch("runway.cfngin.providers.aws.default.output_full_changeset")
    def test_get_stack_changes_create(self, mock_output_full_cs: MagicMock) -> None:
        """Test get stack changes create.

        Tests the preview path for new stacks (REVIEW_IN_PROGRESS): after
        extracting changes the temporary stack is deleted since it was only
        created to generate a changeset for preview purposes.
        """
        stack_name = "MockStack"
        mock_stack = generate_stack_object(stack_name)

        self.stubber.add_response(
            "describe_stacks",
            {
                "Stacks": [
                    generate_describe_stacks_stack(stack_name, stack_status="REVIEW_IN_PROGRESS")
                ]
            },
        )
        self.stubber.add_response("create_change_set", {"Id": "CHANGESETID", "StackId": stack_name})
        changes = [generate_change()]
        self.stubber.add_response(
            "describe_change_set",
            generate_change_set_response(
                status="CREATE_COMPLETE", execution_status="AVAILABLE", changes=changes
            ),
        )
        self.stubber.add_response("delete_change_set", {})
        self.stubber.add_response(
            "describe_stacks",
            {
                "Stacks": [
                    generate_describe_stacks_stack(stack_name, stack_status="REVIEW_IN_PROGRESS")
                ]
            },
        )
        self.stubber.add_response(
            "describe_stacks",
            {
                "Stacks": [
                    generate_describe_stacks_stack(stack_name, stack_status="REVIEW_IN_PROGRESS")
                ]
            },
        )

        self.stubber.add_response("delete_stack", {})

        with self.stubber:
            self.provider.get_stack_changes(
                stack=mock_stack,
                template=Template(url="http://fake.template.url.com/"),
                parameters=[],
                tags=[],
            )

        mock_output_full_cs.assert_called_with(
            full_changeset=changes, params_diff=[], fqn=stack_name, answer="y"
        )

    def test_tail_stack_retry_on_missing_stack(self) -> None:
        """Test tail stack retry on missing stack.

        Validates that event tailing retries when the stack doesn't exist yet
        (race condition during creation) and eventually gives up after
        MAX_TAIL_RETRIES to avoid infinite loops.
        """
        stack_name = "SlowToCreateStack"
        stack = MagicMock(spec=Stack)
        stack.fqn = f"my-namespace-{stack_name}"

        default.TAIL_RETRY_SLEEP = 0.01  # type: ignore[assignment]

        # Ensure the stack never appears before we run out of retries
        for i in range(MAX_TAIL_RETRIES + 5):
            self.stubber.add_client_error(
                "describe_stack_events",
                service_error_code="ValidationError",
                service_message=f"Stack [{stack_name}] does not exist",
                http_status_code=400,
                response_meta={"attempt": i + 1},
            )

        with self.stubber:
            try:
                self.provider.tail_stack(stack, threading.Event())
            except ClientError as exc:
                assert (  # noqa: PT017
                    exc.response.get("ResponseMetadata", {}).get("attempt") == MAX_TAIL_RETRIES  # type: ignore[typeddict-item]
                )

    def test_tail_stack_retry_on_missing_stack_eventual_success(self) -> None:
        """Test tail stack retry on missing stack eventual success.

        Ensures that after transient "stack does not exist" errors, the tailer
        recovers once the stack appears and begins delivering events — this
        is the expected behavior during slow stack creation.
        """
        stack_name = "SlowToCreateStack"
        stack = MagicMock(spec=Stack)
        stack.fqn = f"my-namespace-{stack_name}"

        default.TAIL_RETRY_SLEEP = 0.01  # type: ignore[assignment]

        received_events: list[Any] = []

        def mock_log_func(event: Any) -> None:
            received_events.append(event)

        def valid_event_response(stack: Stack, event_id: str) -> dict[str, Any]:
            return {
                "StackEvents": [
                    {
                        "StackId": stack.fqn + "12345",
                        "EventId": event_id,
                        "StackName": stack.fqn,
                        "Timestamp": datetime.now(),
                    },
                ]
            }

        # Ensure the stack never appears before we run out of retries
        for i in range(3):
            self.stubber.add_client_error(
                "describe_stack_events",
                service_error_code="ValidationError",
                service_message=f"Stack [{stack_name}] does not exist",
                http_status_code=400,
                response_meta={"attempt": i + 1},
            )

        self.stubber.add_response(
            "describe_stack_events", valid_event_response(stack, "InitialEvents")
        )

        self.stubber.add_response("describe_stack_events", valid_event_response(stack, "Event1"))

        with self.stubber, suppress(UnStubbedResponseError):
            # Eventually we run out of responses - could not happen in
            # regular execution
            # normally this would just be dealt with when the threads were
            # shutdown, but doing so here is a little difficult because
            # we can't control the `tail_stack` loop
            self.provider.tail_stack(stack, threading.Event(), log_func=mock_log_func)

        assert received_events[0]["EventId"] == "Event1"

    def test_update_termination_protection(self) -> None:
        """Test update_termination_protection.

        Exercises all four combinations of current AWS state vs desired state
        to confirm the provider only calls UpdateTerminationProtection when
        the value actually needs to change, avoiding unnecessary API calls.
        """
        stack_name = "fake-stack"
        test_cases = [
            MutableMap(aws=False, defined=True, expected=True),
            MutableMap(aws=True, defined=False, expected=False),
            MutableMap(aws=True, defined=True, expected=None),
            MutableMap(aws=False, defined=False, expected=None),
        ]

        for test in test_cases:
            self.stubber.add_response(
                "describe_stacks",
                {
                    "Stacks": [
                        generate_describe_stacks_stack(
                            stack_name, termination_protection=test["aws"]
                        )
                    ]
                },
                {"StackName": stack_name},
            )
            if isinstance(test["expected"], bool):
                self.stubber.add_response(
                    "update_termination_protection",
                    {"StackId": stack_name},
                    {
                        "EnableTerminationProtection": test["expected"],
                        "StackName": stack_name,
                    },
                )
            with self.stubber:
                self.provider.update_termination_protection(stack_name, test["defined"])
            self.stubber.assert_no_pending_responses()


class TestProviderInteractiveMode(unittest.TestCase):
    """Tests for runway.cfngin.providers.aws.default interactive mode.

    Validates the interactive (human-in-the-loop) provider behavior where
    users must approve changes before execution, ensuring the approval gate
    cannot be bypassed and termination protection toggling works correctly.
    """

    def setUp(self) -> None:
        """Run before tests."""
        region = "us-east-1"
        self.session = get_session(region=region)
        self.provider = Provider(self.session, interactive=True, recreate_failed=True)
        self.stubber = Stubber(self.provider.cloudformation)

    @patch("runway.cfngin.ui.get_raw_input")
    def test_interactive_destroy_stack(self, patched_input: MagicMock) -> None:
        """Test interactive_destroy_stack.

        Confirms the user is prompted for approval and deletion proceeds
        only after explicit 'y' input — the core safety mechanism for
        interactive mode.
        """
        stack_name = "fake-stack"
        stack = {"StackName": stack_name}
        patched_input.return_value = "y"

        self.stubber.add_response("delete_stack", {}, stack)

        with self.stubber:
            assert self.provider.interactive_destroy_stack(stack_name) is None  # type: ignore[func-returns-value]
            self.stubber.assert_no_pending_responses()

    @patch("runway.cfngin.providers.aws.default.Provider.update_termination_protection")
    @patch("runway.cfngin.ui.get_raw_input")
    def test_interactive_destroy_stack_termination_protected(
        self, patched_input: MagicMock, patched_update_term: MagicMock
    ) -> None:
        """Test interactive_destroy_stack with termination protection.

        Validates that in interactive mode, termination protection is disabled
        after user confirmation, then deletion retries successfully.
        """
        stack_name = "fake-stack"
        stack = {"StackName": stack_name}
        patched_input.return_value = "y"

        self.stubber.add_client_error("delete_stack", service_message="TerminationProtection")
        self.stubber.add_response("delete_stack", {}, stack)

        with self.stubber:
            self.provider.interactive_destroy_stack(stack_name, approval="y")
        self.stubber.assert_no_pending_responses()
        patched_input.assert_called_once()
        patched_update_term.assert_called_once_with(stack_name, False)

    @patch("runway.cfngin.ui.get_raw_input")
    def test_destroy_stack_canceled(self, patched_input: MagicMock) -> None:
        """Test destroy stack canceled.

        Ensures answering 'n' raises CancelExecution, preventing any
        destructive API calls from being made.
        """
        patched_input.return_value = "n"

        with pytest.raises(exceptions.CancelExecution):
            self.provider.destroy_stack({"StackName": "MockStack"})  # type: ignore

    def test_successful_init(self) -> None:
        """Test successful init.

        Confirms provider initialization correctly passes through the
        replacements_only flag used to restrict changeset display.
        """
        replacements = True
        provider = Provider(self.session, interactive=True, replacements_only=replacements)
        assert provider.replacements_only == replacements

    @patch("runway.cfngin.providers.aws.default.Provider.update_termination_protection")
    @patch("runway.cfngin.providers.aws.default.ask_for_approval")
    def test_update_stack_execute_success_no_stack_policy(
        self, patched_approval: MagicMock, patched_update_term: MagicMock
    ) -> None:
        """Test update stack execute success no stack policy.

        Validates the full interactive update flow: changeset creation,
        user approval prompt, and execution — confirming the approval gate
        is called with the correct changeset details.
        """
        stack_name = "my-fake-stack"

        self.stubber.add_response("create_change_set", {"Id": "CHANGESETID", "StackId": "STACKID"})
        changes = [generate_change()]

        self.stubber.add_response(
            "describe_change_set",
            generate_change_set_response(
                status="CREATE_COMPLETE", execution_status="AVAILABLE", changes=changes
            ),
        )

        self.stubber.add_response("execute_change_set", {})

        with self.stubber:
            self.provider.update_stack(
                fqn=stack_name,
                template=Template(url="http://fake.template.url.com/"),
                old_parameters=[],
                parameters=[],
                tags=[],
            )

        patched_approval.assert_called_once_with(
            full_changeset=changes, params_diff=[], include_verbose=True, fqn=stack_name
        )
        patched_update_term.assert_called_once_with(stack_name, False)

    @patch("runway.cfngin.providers.aws.default.Provider.update_termination_protection")
    @patch("runway.cfngin.providers.aws.default.ask_for_approval")
    def test_update_stack_execute_success_with_stack_policy(
        self, patched_approval: MagicMock, patched_update_term: MagicMock
    ) -> None:
        """Test update stack execute success with stack policy.

        Ensures the stack policy is applied alongside the changeset execution
        when provided in interactive mode.
        """
        stack_name = "my-fake-stack"

        self.stubber.add_response("create_change_set", {"Id": "CHANGESETID", "StackId": "STACKID"})
        changes = [generate_change()]

        self.stubber.add_response(
            "describe_change_set",
            generate_change_set_response(
                status="CREATE_COMPLETE", execution_status="AVAILABLE", changes=changes
            ),
        )

        self.stubber.add_response("set_stack_policy", {})

        self.stubber.add_response("execute_change_set", {})

        with self.stubber:
            self.provider.update_stack(
                fqn=stack_name,
                template=Template(url="http://fake.template.url.com/"),
                old_parameters=[],
                parameters=[],
                tags=[],
                stack_policy=Template(body="{}"),
            )

        patched_approval.assert_called_once_with(
            full_changeset=changes, params_diff=[], include_verbose=True, fqn=stack_name
        )
        patched_update_term.assert_called_once_with(stack_name, False)

    def test_select_destroy_method(self) -> None:
        """Test select destroy method.

        In interactive mode, destroy always routes to interactive_destroy_stack
        regardless of force_interactive, since the provider is already interactive.
        """
        for i in [
            [{"force_interactive": False}, self.provider.interactive_destroy_stack],
            [{"force_interactive": True}, self.provider.interactive_destroy_stack],
        ]:
            assert self.provider.select_destroy_method(**i[0]) == i[1]  # type: ignore

    def test_select_update_method(self) -> None:
        """Test select update method.

        In interactive mode, all flag combinations route to
        interactive_update_stack since user approval is always required.
        """
        for i in [
            [
                {"force_interactive": False, "force_change_set": False},
                self.provider.interactive_update_stack,
            ],
            [
                {"force_interactive": True, "force_change_set": False},
                self.provider.interactive_update_stack,
            ],
            [
                {"force_interactive": False, "force_change_set": True},
                self.provider.interactive_update_stack,
            ],
            [
                {"force_interactive": True, "force_change_set": True},
                self.provider.interactive_update_stack,
            ],
        ]:
            assert self.provider.select_update_method(**i[0]) == i[1]  # type: ignore

    @patch("runway.cfngin.providers.aws.default.output_full_changeset")
    @patch("runway.cfngin.providers.aws.default.output_summary")
    def test_get_stack_changes_interactive(
        self, mock_output_summary: MagicMock, mock_output_full_cs: MagicMock
    ) -> None:
        """Test get stack changes interactive.

        Validates that in interactive mode, both the summary and full changeset
        are displayed to the user for review before any approval prompt.
        """
        stack_name = "MockStack"
        mock_stack = generate_stack_object(stack_name)

        self.stubber.add_response(
            "describe_stacks", {"Stacks": [generate_describe_stacks_stack(stack_name)]}
        )
        self.stubber.add_response("get_template", generate_get_template("cfn_template.yaml"))
        self.stubber.add_response("create_change_set", {"Id": "CHANGESETID", "StackId": stack_name})
        changes = [generate_change()]
        self.stubber.add_response(
            "describe_change_set",
            generate_change_set_response(
                status="CREATE_COMPLETE", execution_status="AVAILABLE", changes=changes
            ),
        )
        self.stubber.add_response("delete_change_set", {})
        self.stubber.add_response(
            "describe_stacks", {"Stacks": [generate_describe_stacks_stack(stack_name)]}
        )

        with self.stubber:
            self.provider.get_stack_changes(
                stack=mock_stack,
                template=Template(url="http://fake.template.url.com/"),
                parameters=[],
                tags=[],
            )

        mock_output_summary.assert_called_with(
            stack_name, "changes", changes, [], replacements_only=False
        )
        mock_output_full_cs.assert_called_with(
            full_changeset=changes, params_diff=[], fqn=stack_name
        )
