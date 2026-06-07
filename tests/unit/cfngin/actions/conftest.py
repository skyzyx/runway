"""Pytest fixtures and plugins.

Provides shared fixtures for action tests that need a mocked AWS provider,
avoiding real CloudFormation API calls while exercising action decision logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from runway.cfngin.providers.aws.default import Provider

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from mypy_boto3_cloudformation.type_defs import StackTypeDef
    from pytest_mock import MockerFixture


@pytest.fixture
def provider_get_stack(mocker: MockerFixture) -> MagicMock:
    """Patches ``runway.cfngin.providers.aws.default.Provider.get_stack``.

    Actions branch heavily on the current stack state returned by the provider.
    This fixture supplies a stable "stack exists in CREATE_COMPLETE" baseline so
    tests can override individual fields without hitting AWS.
    """
    return_value: StackTypeDef = {
        "CreationTime": datetime(2015, 1, 1),
        "Description": "something",
        "Outputs": [],
        "Parameters": [],
        "StackId": "123",
        "StackName": "foo",
        "StackStatus": "CREATE_COMPLETE",
    }
    return mocker.patch.object(Provider, "get_stack", return_value=return_value)
