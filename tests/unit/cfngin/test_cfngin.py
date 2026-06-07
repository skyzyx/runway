"""Tests for runway.cfngin entry point.

Validates the CFNgin facade class that orchestrates environment file discovery,
parameter merging, action dispatch, and skip logic — the primary user-facing
entry point for all CloudFormation stack operations.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING
from unittest.mock import Mock, call

import pytest
from yaml.constructor import ConstructorError

from runway.cfngin.cfngin import CFNgin
from runway.core.components import DeployEnvironment

from ..factories import MockRunwayContext

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def copy_fixture(src: Path, dest: Path) -> Path:
    """Wrap shutil.copy to backport use with Path objects.

    Ensures consistent fixture copying across Python versions where Path
    support in shutil was not always guaranteed.
    """
    return shutil.copy(src.absolute(), dest.absolute())  # type: ignore[return-value]


def copy_basic_fixtures(cfngin_fixtures: Path, tmp_path: Path) -> None:
    """Copy the basic env file and config file to a tmp_path.

    Provides the minimal filesystem layout CFNgin needs to discover and
    load configuration, reused by most action-dispatch tests.
    """
    copy_fixture(src=cfngin_fixtures / "envs" / "basic.env", dest=tmp_path / "test-us-east-1.env")
    copy_fixture(src=cfngin_fixtures / "configs" / "basic.yml", dest=tmp_path / "basic.yml")


@pytest.fixture
def patch_safehaven(mocker: MockerFixture) -> Mock:
    """Patch SafeHaven.

    Isolates tests from the real SafeHaven context manager which modifies
    sys.modules and environment variables during action execution.
    """
    mock_haven = mocker.patch("runway.cfngin.cfngin.SafeHaven")
    mock_haven.return_value = mock_haven
    return mock_haven


class TestCFNgin:
    """Test runway.cfngin.CFNgin.

    Validates the facade that ties together env file discovery, parameter
    injection from env files, action dispatch (deploy/destroy/init/plan),
    and the skip-when-no-config logic that allows graceful no-ops.
    """

    @staticmethod
    def configure_mock_action_instance(mock_action: Mock) -> Mock:
        """Configure a mock action.

        Provides a reusable pattern for verifying that CFNgin dispatches
        to the correct action class and calls execute with expected args.
        """
        mock_instance = Mock(return_value=None)
        mock_action.return_value = mock_instance
        mock_instance.execute = Mock()
        return mock_instance

    @staticmethod
    def get_context(name: str = "test", region: str = "us-east-1") -> MockRunwayContext:
        """Create a basic Runway context object."""
        context = MockRunwayContext(deploy_environment=DeployEnvironment(explicit_name=name))
        context.env.aws_region = region
        return context

    def test_env_file(self, tmp_path: Path) -> None:
        """Test that the correct env file is selected.

        Verifies the env file resolution priority: region-specific files
        take precedence over generic ones, ensuring deployments get the
        correct per-region configuration values.
        """
        test_env = tmp_path / "test.env"
        test_env.write_text("test_value: test")

        result = CFNgin(ctx=self.get_context(), sys_path=tmp_path)
        assert result.env_file["test_value"] == "test"

        test_us_east_1 = tmp_path / "test-us-east-1.env"
        test_us_east_1.write_text("test_value: test-us-east-1")

        test_us_west_2 = tmp_path / "test-us-west-2.env"
        test_us_west_2.write_text("test_value: test-us-west-2")

        lab_ca_central_1 = tmp_path / "lab-ca-central-1.env"
        lab_ca_central_1.write_text("test_value: lab-ca-central-1")

        result = CFNgin(ctx=self.get_context(), sys_path=tmp_path)
        assert result.env_file["test_value"] == "test-us-east-1"

        result = CFNgin(ctx=self.get_context(region="us-west-2"), sys_path=tmp_path)
        assert result.env_file["test_value"] == "test-us-west-2"

        result = CFNgin(ctx=self.get_context(name="lab", region="ca-central-1"), sys_path=tmp_path)
        assert result.env_file["test_value"] == "lab-ca-central-1"

    def test_deploy(
        self,
        cfngin_fixtures: Path,
        mocker: MockerFixture,
        tmp_path: Path,
        patch_safehaven: Mock,
    ) -> None:
        """Test deploy with two files & class init.

        Validates the full deploy lifecycle: env file loading, parameter
        merging (from env file + explicit params), multi-config dispatch,
        SafeHaven environment isolation, and CI-mode detection.
        """
        mock_action = mocker.patch("runway.cfngin.actions.deploy.Action", Mock())
        mock_instance = self.configure_mock_action_instance(mock_action)
        copy_basic_fixtures(cfngin_fixtures, tmp_path)
        copy_fixture(src=cfngin_fixtures / "configs" / "basic.yml", dest=tmp_path / "basic2.yml")

        context = self.get_context()
        context.env.vars["CI"] = "1"

        cfngin = CFNgin(
            ctx=context,
            parameters={"test_param": "test-param-value"},
            sys_path=tmp_path,
        )
        cfngin.deploy()

        assert cfngin.concurrency == 0
        assert not cfngin.interactive
        assert cfngin.parameters["bucket_name"] == "cfngin-bucket"
        assert cfngin.parameters["environment"] == "test"
        assert cfngin.parameters["namespace"] == "test-namespace"
        assert cfngin.parameters["region"] == "us-east-1"
        assert cfngin.parameters["test_key"] == "test_value"
        assert cfngin.parameters["test_param"] == "test-param-value"
        assert cfngin.recreate_failed
        assert cfngin.region == "us-east-1"
        assert cfngin.sys_path == tmp_path
        assert not cfngin.tail

        assert mock_action.call_count == 2
        mock_instance.__call__(
            [{"concurrency": 0, "tail": False}, {"concurrency": 0, "tail": False}]
        )
        patch_safehaven.assert_has_calls(
            [
                call(
                    environ=context.env.vars,
                    sys_modules_exclude=["awacs", "troposphere"],
                ),
                call.__enter__(),
                call(sys_modules_exclude=["awacs", "troposphere"]),
                call.__enter__(),
                call.__exit__(None, None, None),
                call(sys_modules_exclude=["awacs", "troposphere"]),
                call.__enter__(),
                call.__exit__(None, None, None),
                call.__exit__(None, None, None),
            ]
        )

    def test_deploy_skip(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        patch_safehaven: Mock,
    ) -> None:
        """Test deploy skip.

        Ensures no action is dispatched and no SafeHaven context is
        entered when should_skip returns True, preventing partial
        operations when config files are absent.
        """
        should_skip = mocker.patch.object(CFNgin, "should_skip", return_value=True)
        cfngin = CFNgin(
            ctx=self.get_context(),
            sys_path=tmp_path,
        )
        cfngin.deploy()
        should_skip.assert_called_once_with(False)
        patch_safehaven.assert_not_called()

    def test_destroy(
        self,
        cfngin_fixtures: Path,
        mocker: MockerFixture,
        tmp_path: Path,
        patch_safehaven: Mock,
    ) -> None:
        """Test destroy.

        Verifies the destroy action is dispatched with force=True and
        that SafeHaven wraps the operation without module exclusions,
        since destroy doesn't need troposphere/awacs isolation.
        """
        mock_action = mocker.patch("runway.cfngin.actions.destroy.Action", Mock())
        mock_instance = self.configure_mock_action_instance(mock_action)
        copy_basic_fixtures(cfngin_fixtures, tmp_path)

        context = self.get_context()
        cfngin = CFNgin(ctx=context, sys_path=tmp_path)
        cfngin.destroy()

        mock_action.assert_called_once()
        mock_instance.execute.assert_called_once_with(concurrency=0, force=True, tail=False)
        patch_safehaven.assert_has_calls(
            [
                call(environ=context.env.vars),
                call.__enter__(),
                call(),
                call.__enter__(),
                call.__exit__(None, None, None),
                call.__exit__(None, None, None),
            ]
        )

    def test_destroy_skip(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        patch_safehaven: Mock,
    ) -> None:
        """Test destroy skip.

        Confirms the same skip-guard applies to destroy, preventing
        accidental teardowns when no config files are found.
        """
        should_skip = mocker.patch.object(CFNgin, "should_skip", return_value=True)
        cfngin = CFNgin(
            ctx=self.get_context(),
            sys_path=tmp_path,
        )
        cfngin.destroy()
        should_skip.assert_called_once_with(False)
        patch_safehaven.assert_not_called()

    def test_init(
        self,
        cfngin_fixtures: Path,
        mocker: MockerFixture,
        patch_safehaven: Mock,
        tmp_path: Path,
    ) -> None:
        """Test init.

        Verifies init dispatches the init action with sys_modules_exclude
        for troposphere/awacs, since init may trigger blueprint imports
        that need module isolation.
        """
        mock_action = mocker.patch("runway.cfngin.actions.init.Action", Mock())
        mock_instance = self.configure_mock_action_instance(mock_action)
        copy_basic_fixtures(cfngin_fixtures, tmp_path)

        context = self.get_context()
        cfngin = CFNgin(ctx=context, sys_path=tmp_path)
        cfngin.init()

        mock_action.assert_called_once()
        mock_instance.execute.assert_called_once_with(concurrency=0, tail=False)
        patch_safehaven.assert_has_calls(
            [
                call(
                    environ=context.env.vars,
                    sys_modules_exclude=["awacs", "troposphere"],
                ),
                call.__enter__(),
                call(sys_modules_exclude=["awacs", "troposphere"]),
                call.__enter__(),
                call.__exit__(None, None, None),
                call.__exit__(None, None, None),
            ]
        )

    def test_init_skip(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        patch_safehaven: Mock,
    ) -> None:
        """Test init skip.

        Confirms the skip-guard applies to init, avoiding bucket
        creation attempts when no configuration is present.
        """
        should_skip = mocker.patch.object(CFNgin, "should_skip", return_value=True)
        cfngin = CFNgin(
            ctx=self.get_context(),
            sys_path=tmp_path,
        )
        cfngin.init()
        should_skip.assert_called_once_with(False)
        patch_safehaven.assert_not_called()

    def test_load(self, cfngin_fixtures: Path, tmp_path: Path) -> None:
        """Test load.

        Validates that a YAML config file is correctly parsed into a
        CfnginConfig object with the expected namespace and stack
        definitions — the contract between config files and the runtime.
        """
        copy_basic_fixtures(cfngin_fixtures, tmp_path)
        cfngin = CFNgin(ctx=self.get_context(), sys_path=tmp_path)
        result = cfngin.load(tmp_path / "basic.yml")

        assert not result.bucket_name
        assert result.namespace == "test-namespace"
        assert len(result.stacks) == 1
        assert result.stacks[0].name == "test-stack"

    def test_load_raise_constructor_error(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Test load raise ConstructorError.

        Ensures YAML constructor errors propagate rather than being
        swallowed, so users get clear feedback about malformed configs.
        """
        config = Mock(load=Mock(side_effect=ConstructorError(problem="something else")))
        get_config = mocker.patch.object(CFNgin, "_get_config", return_value=config)
        with pytest.raises(ConstructorError, match="something else"):
            assert CFNgin(ctx=self.get_context(), sys_path=tmp_path).load(tmp_path)
        get_config.assert_called_once_with(tmp_path)

    def test_plan(
        self,
        cfngin_fixtures: Path,
        mocker: MockerFixture,
        tmp_path: Path,
        patch_safehaven: Mock,
    ) -> None:
        """Test plan.

        Verifies plan dispatches the diff action (dry-run preview)
        without concurrency or tail args, since plan is read-only.
        """
        mock_action = mocker.patch("runway.cfngin.actions.diff.Action", Mock())
        mock_instance = self.configure_mock_action_instance(mock_action)
        copy_basic_fixtures(cfngin_fixtures, tmp_path)

        context = self.get_context()
        cfngin = CFNgin(ctx=context, sys_path=tmp_path)
        cfngin.plan()

        mock_action.assert_called_once()
        mock_instance.execute.assert_called_once_with()
        patch_safehaven.assert_has_calls(
            [
                call(environ=context.env.vars),
                call.__enter__(),
                call(),
                call.__enter__(),
                call.__exit__(None, None, None),
                call.__exit__(None, None, None),
            ]
        )

    def test_plan_skip(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        patch_safehaven: Mock,
    ) -> None:
        """Test plan skip.

        Confirms plan respects the same skip logic as mutating operations.
        """
        should_skip = mocker.patch.object(CFNgin, "should_skip", return_value=True)
        cfngin = CFNgin(
            ctx=self.get_context(),
            sys_path=tmp_path,
        )
        cfngin.plan()
        should_skip.assert_called_once_with(False)
        patch_safehaven.assert_not_called()

    def test_should_skip(self, cfngin_fixtures: Path, tmp_path: Path) -> None:
        """Test should_skip.

        Exercises the skip logic boundary conditions: missing env file
        triggers skip, force flag overrides skip, and presence of config
        files disables skip — ensuring CFNgin only operates when it has
        valid configuration to work with.
        """
        cfngin = CFNgin(ctx=self.get_context(), sys_path=tmp_path)
        del cfngin.env_file  # clear cached value and force load

        assert cfngin.should_skip()
        del cfngin.env_file  # clear cached value and force load
        assert not cfngin.should_skip(force=True)  # does not repopulate env_file

        copy_basic_fixtures(cfngin_fixtures, tmp_path)
        assert not cfngin.should_skip()
        del cfngin.env_file  # clear cached value and force load
        assert not cfngin.should_skip(force=True)  # does not repopulate env_file

        env_region_file = tmp_path / "test-us-east-1.env"
        env_file = tmp_path / "test.env"
        copy_fixture(env_region_file, env_file)
        env_region_file.unlink()
        assert not cfngin.should_skip()
        del cfngin.env_file  # clear cached value and force load
        assert not cfngin.should_skip(force=True)  # does not repopulate env_file

    def test_find_config_files(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Test find_config_files.

        Verifies the static method delegates to CfnginConfig's file
        finder with the correct exclude list, maintaining the contract
        for config discovery used by the Runway module system.
        """
        mock_config = mocker.patch("runway.cfngin.cfngin.CfnginConfig", Mock())
        CFNgin.find_config_files(sys_path=tmp_path, exclude=["file"])
        mock_config.find_config_file.assert_called_once_with(tmp_path, exclude=["file"])
