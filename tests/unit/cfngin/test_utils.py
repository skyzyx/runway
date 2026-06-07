"""Tests for runway.cfngin.utils.

Validates the utility functions that support S3 bucket management, file path
resolution, YAML parsing, CloudFormation template processing, archive
extraction, and the SourceProcessor for fetching remote package sources.
"""

from __future__ import annotations

import logging
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from pydantic import ValidationError

from runway.cfngin.utils import (
    Extractor,
    SourceProcessor,
    TarExtractor,
    TarGzipExtractor,
    ZipExtractor,
    camel_to_snake,
    cf_safe_name,
    ensure_s3_bucket,
    get_client_region,
    get_s3_endpoint,
    is_within_directory,
    parse_cloudformation_template,
    read_value_from_path,
    s3_bucket_location_constraint,
    safe_tar_extract,
    yaml_to_ordered_dict,
)
from runway.config.models.cfngin import GitCfnginPackageSourceDefinitionModel

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

# All AWS regions that CFNgin supports, used by tests that validate
# region-dependent behavior like S3 endpoint construction and location
# constraints.
AWS_REGIONS = [
    "us-east-1",
    "cn-north-1",
    "ap-northeast-1",
    "eu-west-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "us-west-2",
    "us-gov-west-1",
    "us-west-1",
    "eu-central-1",
    "sa-east-1",
]
MODULE = "runway.cfngin.utils"


def mock_create_cache_directories(self: Any, **kwargs: Any) -> int:  # noqa: ARG001
    """Mock create cache directories.

    Don't actually need the directories created in testing.
    Avoids filesystem side-effects so SourceProcessor tests focus on
    git ref resolution and URI sanitization logic.
    """
    return 1


def test_ensure_s3_bucket() -> None:
    """Test ensure_s3_bucket.

    Verifies the happy path: an existing bucket is detected via
    head_bucket and no creation attempt is made.
    """
    s3_client = boto3.client("s3")
    stubber = Stubber(s3_client)
    stubber.add_response("head_bucket", {}, {"Bucket": "test-bucket"})
    with stubber:
        assert not ensure_s3_bucket(s3_client, "test-bucket")
    stubber.assert_no_pending_responses()


def test_ensure_s3_bucket_forbidden(caplog: pytest.LogCaptureFixture) -> None:
    """Test ensure_s3_bucket.

    Validates that a 403 Forbidden error (bucket exists but owned by
    another account) raises with a helpful log message about globally
    unique naming — a common user mistake.
    """
    caplog.set_level(logging.ERROR, logger=MODULE)
    s3_client = boto3.client("s3")
    stubber = Stubber(s3_client)
    stubber.add_client_error("head_bucket", service_message="Forbidden")
    with stubber, pytest.raises(ClientError, match="Forbidden"):
        assert ensure_s3_bucket(s3_client, "test-bucket")
    stubber.assert_no_pending_responses()
    assert (
        "Access denied for bucket test-bucket. Did you remember to use a globally unique name?"
        in "\n".join(caplog.messages)
    )


def test_ensure_s3_bucket_not_found(mocker: MockerFixture) -> None:
    """Test ensure_s3_bucket.

    Verifies that a missing bucket triggers auto-creation with the
    correct location constraint derived from the region.
    """
    mock_s3_bucket_location_constraint = mocker.patch(
        f"{MODULE}.s3_bucket_location_constraint", return_value="something"
    )
    s3_client = boto3.client("s3")
    stubber = Stubber(s3_client)
    stubber.add_client_error("head_bucket", service_message="Not Found")
    stubber.add_response(
        "create_bucket",
        {},
        {
            "Bucket": "test-bucket",
            "CreateBucketConfiguration": {
                "LocationConstraint": mock_s3_bucket_location_constraint.return_value
            },
        },
    )
    with stubber:
        assert not ensure_s3_bucket(s3_client, "test-bucket", "us-east-1")
    stubber.assert_no_pending_responses()
    mock_s3_bucket_location_constraint.assert_called_once_with("us-east-1")


def test_ensure_s3_bucket_not_found_not_create() -> None:
    """Test ensure_s3_bucket.

    Confirms that when create=False, a missing bucket raises rather
    than being silently created — important for read-only operations.
    """
    s3_client = boto3.client("s3")
    stubber = Stubber(s3_client)
    stubber.add_client_error("head_bucket", service_message="Not Found")
    with stubber, pytest.raises(ClientError, match="Not Found"):
        assert not ensure_s3_bucket(s3_client, "test-bucket", create=False)
    stubber.assert_no_pending_responses()


def test_ensure_s3_bucket_not_found_persist_graph() -> None:
    """Test ensure_s3_bucket.

    When persist_graph is enabled and the bucket doesn't exist yet,
    versioning must be enabled during creation to support graph history.
    """
    s3_client = boto3.client("s3")
    stubber = Stubber(s3_client)
    stubber.add_client_error("head_bucket", service_message="Not Found")
    stubber.add_response("create_bucket", {}, {"Bucket": "test-bucket"})
    stubber.add_response(
        "put_bucket_versioning",
        {},
        {"Bucket": "test-bucket", "VersioningConfiguration": {"Status": "Enabled"}},
    )
    with stubber:
        assert not ensure_s3_bucket(s3_client, "test-bucket", persist_graph=True)
    stubber.assert_no_pending_responses()


def test_ensure_s3_bucket_persist_graph(caplog: pytest.LogCaptureFixture) -> None:
    """Test ensure_s3_bucket.

    Confirms that an existing bucket with versioning already enabled
    produces no warnings — the ideal state for persistent graphs.
    """
    caplog.set_level(logging.WARNING, logger=MODULE)
    s3_client = boto3.client("s3")
    stubber = Stubber(s3_client)
    stubber.add_response("head_bucket", {}, {"Bucket": "test-bucket"})
    stubber.add_response("get_bucket_versioning", {"Status": "Enabled"}, {"Bucket": "test-bucket"})
    with stubber:
        assert not ensure_s3_bucket(s3_client, "test-bucket", persist_graph=True)
    stubber.assert_no_pending_responses()
    assert not caplog.messages


def test_ensure_s3_bucket_persist_graph_mfa_delete(caplog: pytest.LogCaptureFixture) -> None:
    """Test ensure_s3_bucket.

    MFADelete prevents programmatic graph object deletion, so CFNgin
    must warn users that persistent graph management will fail.
    """
    caplog.set_level(logging.WARNING, logger=MODULE)
    s3_client = boto3.client("s3")
    stubber = Stubber(s3_client)
    stubber.add_response("head_bucket", {}, {"Bucket": "test-bucket"})
    stubber.add_response(
        "get_bucket_versioning",
        {"Status": "Enabled", "MFADelete": "Enabled"},
        {"Bucket": "test-bucket"},
    )
    with stubber:
        assert not ensure_s3_bucket(s3_client, "test-bucket", persist_graph=True)
    stubber.assert_no_pending_responses()
    assert (
        'MFADelete must be disabled on bucket "test-bucket" when using persistent '
        "graphs to allow for proper management of the graphs" in "\n".join(caplog.messages)
    )


@pytest.mark.parametrize(
    "versioning_response", [{"Status": "Disabled"}, {"Status": "Suspended"}, {}]
)
def test_ensure_s3_bucket_persist_graph_versioning_not_enabled(
    caplog: pytest.LogCaptureFixture, versioning_response: dict[str, Any]
) -> None:
    """Test ensure_s3_bucket.

    Parametrized across all non-enabled versioning states to verify
    the warning fires whenever versioning isn't active — important
    because persistent graphs rely on version history for rollback.
    """
    caplog.set_level(logging.WARNING, logger=MODULE)
    s3_client = boto3.client("s3")
    stubber = Stubber(s3_client)
    stubber.add_response("head_bucket", {}, {"Bucket": "test-bucket"})
    stubber.add_response("get_bucket_versioning", versioning_response, {"Bucket": "test-bucket"})
    with stubber:
        assert not ensure_s3_bucket(s3_client, "test-bucket", persist_graph=True)
    stubber.assert_no_pending_responses()
    assert "it is recommended to enable versioning when using persistent graphs" in "\n".join(
        caplog.messages
    )


def test_ensure_s3_bucket_raise_client_error(caplog: pytest.LogCaptureFixture) -> None:
    """Test ensure_s3_bucket.

    Validates that unexpected AWS errors (not 403 or 404) propagate
    with a logged message, since they indicate infrastructure problems
    rather than user configuration issues.
    """
    caplog.set_level(logging.ERROR, logger=MODULE)
    s3_client = boto3.client("s3")
    stubber = Stubber(s3_client)
    stubber.add_client_error("head_bucket")
    with stubber, pytest.raises(ClientError):
        assert not ensure_s3_bucket(s3_client, "test-bucket")
    stubber.assert_no_pending_responses()
    assert 'error creating bucket "test-bucket"' in caplog.messages


def test_read_value_from_path_abs(tmp_path: Path) -> None:
    """Test read_value_from_path absolute path.

    Validates the basic contract: file:// URIs with absolute paths
    resolve and return file contents.
    """
    test_file = tmp_path / "test.txt"
    test_file.write_text("success")
    assert read_value_from_path(f"file://{test_file.absolute()}") == "success"


def test_read_value_from_path_dir(tmp_path: Path) -> None:
    """Test read_value_from_path directory.

    Directories are not valid value sources; must raise to prevent
    silent misconfigurations.
    """
    with pytest.raises(ValueError):  # noqa: PT011
        read_value_from_path(f"file://{tmp_path.absolute()}")


def test_read_value_from_path_not_exist(tmp_path: Path) -> None:
    """Test read_value_from_path does not exist.

    Missing files must raise rather than returning empty, since a
    missing value source is always a configuration error.
    """
    with pytest.raises(ValueError):  # noqa: PT011
        read_value_from_path(f"file://{(tmp_path / 'something.txt').absolute()}")


def test_read_value_from_path_no_root_path(cd_tmp_path: Path) -> None:
    """Test read_value_from_path no root_path.

    Verifies relative file:// URIs resolve against cwd when no
    explicit root_path is provided.
    """
    test_file = cd_tmp_path / "test.txt"
    test_file.write_text("success")
    assert read_value_from_path(f"file://./{test_file.name}") == "success"


def test_read_value_from_path_root_path_dir(tmp_path: Path) -> None:
    """Test read_value_from_path root_path is dir.

    Validates that relative URIs resolve against root_path when it
    points to a directory.
    """
    test_file = tmp_path / "test.txt"
    test_file.write_text("success")
    assert read_value_from_path(f"file://./{test_file.name}", root_path=tmp_path) == "success"


def test_read_value_from_path_root_path_file(tmp_path: Path) -> None:
    """Test read_value_from_path root_path is file.

    When root_path points to a file, the parent directory is used
    for resolution — supports config files referencing sibling files.
    """
    test_file = tmp_path / "test.txt"
    test_file.write_text("success")
    assert (
        read_value_from_path(f"file://./{test_file.name}", root_path=tmp_path / "something.json")
        == "success"
    )


class TestUtil(unittest.TestCase):
    """Tests for runway.cfngin.utils.

    Groups tests for pure utility functions (cf_safe_name, camel_to_snake,
    YAML parsing) and filesystem-dependent operations (tar extraction,
    path traversal protection) that need setUp/tearDown lifecycle.
    """

    tmp_path: Path

    def setUp(self) -> None:
        """Set up test case."""
        self.tmp_path = Path(tempfile.mkdtemp())

        # Set up files for testing tar file extraction
        self.tar_file = Path("test_tar_file.tar")
        test_tar_file1 = self.tmp_path / "file1.txt"
        test_tar_file1.write_text("Content of file1")
        test_tar_subdir = self.tmp_path / "subdir"
        test_tar_subdir.mkdir()
        test_tar_file2 = test_tar_subdir / "file2.txt"
        test_tar_file2.write_text("Content of file2")

        # Create a tar file using the temporary directory
        with tarfile.open(self.tmp_path / self.tar_file, "w") as tar:
            tar.add(self.tmp_path, arcname=os.path.basename(self.tmp_path))  # noqa: PTH119

    def tearDown(self) -> None:
        """Tear down test case."""
        shutil.rmtree(self.tmp_path, ignore_errors=True)

    def test_cf_safe_name(self) -> None:
        """Test cf safe name.

        Validates the conversion of arbitrary identifiers to
        CloudFormation-safe names (PascalCase, no special chars),
        which is required by the CF API for resource naming.
        """
        tests = (("abc-def", "AbcDef"), ("GhI", "GhI"), ("jKlm.noP", "JKlmNoP"))
        for test in tests:
            assert cf_safe_name(test[0]) == test[1]

    def test_camel_to_snake(self) -> None:
        """Test camel to snake.

        Covers standard camelCase, PascalCase, mixed underscore, and
        all-lowercase inputs to ensure the regex-based conversion
        handles edge cases without data loss.
        """
        tests = (
            ("TestTemplate", "test_template"),
            ("testTemplate", "test_template"),
            ("test_Template", "test__template"),
            ("testtemplate", "testtemplate"),
        )
        for test in tests:
            assert camel_to_snake(test[0]) == test[1]

    def test_yaml_to_ordered_dict(self) -> None:
        """Test yaml to ordered dict.

        Confirms key ordering is preserved during YAML parsing, which
        is critical for hook execution order where sequence matters.
        """
        raw_config = """
        pre_deploy:
          hook2:
            path: foo.bar
          hook1:
            path: foo1.bar1
        """
        config = yaml_to_ordered_dict(raw_config)
        assert next(iter(config["pre_deploy"].keys())) == "hook2"
        assert config["pre_deploy"]["hook2"]["path"] == "foo.bar"

    def test_get_client_region(self) -> None:
        """Test get client region.

        Verifies region extraction from boto3 clients across multiple
        partitions, ensuring CFNgin can determine deployment region
        from existing client objects.
        """
        regions = ["us-east-1", "us-west-1", "eu-west-1", "sa-east-1"]
        for region in regions:
            client = boto3.client("s3", region_name=region)
            assert get_client_region(client) == region

    def test_get_s3_endpoint(self) -> None:
        """Test get s3 endpoint.

        Validates custom endpoint URL extraction, needed for S3-compatible
        services (e.g., localstack, MinIO) used in testing and private clouds.
        """
        endpoint_url = "https://example.com"
        client = boto3.client("s3", region_name="us-east-1", endpoint_url=endpoint_url)
        assert get_s3_endpoint(client) == endpoint_url

    def test_s3_bucket_location_constraint(self) -> None:
        """Test s3 bucket location constraint.

        us-east-1 is special: AWS requires an empty string (not the
        region name) as the location constraint when creating buckets
        there. All other regions use their name directly.
        """
        tests = (("us-east-1", ""), ("us-west-1", "us-west-1"))
        for region, result in tests:
            assert s3_bucket_location_constraint(region) == result

    def test_parse_cloudformation_template(self) -> None:
        """Test parse cloudformation template.

        Validates that CF-specific YAML tags (!Ref, !Join) are correctly
        resolved into their JSON equivalents, ensuring templates can be
        round-tripped through CFNgin's YAML parser.
        """
        template = """AWSTemplateFormatVersion: "2010-09-09"
Parameters:
  Param1:
    Type: String
Resources:
  Bucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName:
        !Join
          - "-"
          - - !Ref "AWS::StackName"
            - !Ref "AWS::Region"
Outputs:
  DummyId:
    Value: dummy-1234"""
        parsed_template = {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Outputs": {"DummyId": {"Value": "dummy-1234"}},
            "Parameters": {"Param1": {"Type": "String"}},
            "Resources": {
                "Bucket": {
                    "Type": "AWS::S3::Bucket",
                    "Properties": {
                        "BucketName": {
                            "Fn::Join": [
                                "-",
                                [{"Ref": "AWS::StackName"}, {"Ref": "AWS::Region"}],
                            ]
                        }
                    },
                }
            },
        }
        assert parse_cloudformation_template(template) == parsed_template

    def test_is_within_directory(self) -> None:
        """Test is within directory.

        Exercises the path containment check that guards against path
        traversal attacks in archive extraction — tests both valid
        membership and escape attempts.
        """
        directory = Path("my_directory")

        # Assert if the target is within the directory.
        target = "my_directory/sub_directory/file.txt"
        assert is_within_directory(directory, target)

        # Assert if the target is NOT within the directory.
        target = "other_directory/file.txt"
        assert not is_within_directory(directory, target)

        # Assert if the target is the directory.
        target = "my_directory"
        assert is_within_directory(directory, target)

    def test_safe_tar_extract_all_within(self) -> None:
        """Test when all tar file contents are within the specified directory.

        Happy path: extraction succeeds when no members escape the
        target directory.
        """
        path = self.tmp_path / "my_directory"
        with tarfile.open(self.tmp_path / self.tar_file, "r") as tar:
            assert safe_tar_extract(tar, path) is None

    def test_safe_tar_extract_path_traversal(self) -> None:
        """Test when a tar file tries to go outside the specified area.

        Security test: malicious tar files with "../" prefixed members
        must be rejected to prevent arbitrary file overwrites (CVE-type
        vulnerability in naive tar extraction).
        """
        with tarfile.open(self.tmp_path / self.tar_file, "r") as tar:
            for member in tar.getmembers():
                member.name = f"../{member.name}"

            path = self.tmp_path / "my_directory"
            with pytest.raises(Exception) as excinfo:  # noqa: PT011
                safe_tar_extract(tar, path)
            assert str(excinfo.value) == "Attempted Path Traversal in Tar File"  # type: ignore

    def test_extractors(self) -> None:
        """Test extractors.

        Verifies the extractor class hierarchy correctly associates
        file extensions with archive types, ensuring the right
        extraction strategy is selected by filename.
        """
        assert Extractor(Path("test.zip")).archive == Path("test.zip")
        assert TarExtractor().extension == ".tar"
        assert TarGzipExtractor().extension == ".tar.gz"
        assert ZipExtractor().extension == ".zip"
        for i in [TarExtractor(), ZipExtractor(), ZipExtractor()]:
            i.set_archive(Path("/tmp/foo"))
            assert i.archive.name.endswith(i.extension) is True  # type: ignore

    def test_SourceProcessor_helpers(self) -> None:  # noqa: N802
        """Test SourceProcessor helpers.

        Validates git path sanitization (special chars to underscores),
        URI sanitization, branch/tag/commit ref resolution, and the
        mutual exclusivity constraint on git ref config options.
        """
        with mock.patch.object(
            SourceProcessor,
            "create_cache_directories",
            new=mock_create_cache_directories,
        ):
            sp = SourceProcessor(cache_dir=self.tmp_path, sources={})  # type: ignore

            assert sp.sanitize_git_path("git@github.com:foo/bar.git") == "git_github.com_foo_bar"
            assert (
                sp.sanitize_uri_path("http://example.com/foo/bar.gz@1")
                == "http___example.com_foo_bar.gz_1"
            )
            assert (
                sp.sanitize_git_path("git@github.com:foo/bar.git", "v1")
                == "git_github.com_foo_bar-v1"
            )
            assert (
                sp.determine_git_ls_remote_ref(
                    GitCfnginPackageSourceDefinitionModel(branch="foo", uri="test")
                )
                == "refs/heads/foo"
            )
            for i in [cast("dict[str, Any]", {}), {"tag": "foo"}, {"commit": "1234"}]:
                assert (
                    sp.determine_git_ls_remote_ref(
                        GitCfnginPackageSourceDefinitionModel(uri="git@foo", **i)
                    )
                    == "HEAD"
                )

            assert (
                sp.git_ls_remote(
                    "https://github.com/remind101/stacker.git", "refs/heads/release-1.0"
                )
                == "857b4834980e582874d70feef77bb064b60762d1"
            )

            bad_configs = [
                {"uri": "x", "commit": "1234", "tag": "v1", "branch": "x"},
                {"uri": "x", "commit": "1234", "tag": "v1"},
                {"uri": "x", "commit": "1234", "branch": "x"},
                {"uri": "x", "tag": "v1", "branch": "x"},
                {"uri": "x", "commit": "1234", "branch": "x"},
            ]
            for i in bad_configs:
                with pytest.raises(ValidationError):
                    sp.determine_git_ref(GitCfnginPackageSourceDefinitionModel(**i))

            assert (
                sp.determine_git_ref(
                    GitCfnginPackageSourceDefinitionModel(
                        uri="https://github.com/remind101/stacker.git", branch="release-1.0"
                    )
                )
                == "857b4834980e582874d70feef77bb064b60762d1"
            )
            assert (
                sp.determine_git_ref(
                    GitCfnginPackageSourceDefinitionModel(uri="git@foo", commit="1234")
                )
                == "1234"
            )
            assert (
                sp.determine_git_ref(
                    GitCfnginPackageSourceDefinitionModel(uri="git@foo", tag="v1.0.0")
                )
                == "v1.0.0"
            )


class MockException1(Exception):
    """Mock exception 1."""


class MockException(Exception):
    """Mock exception 2."""


class TestExceptionRetries(unittest.TestCase):
    """Test exception retries.

    Validates the retry mechanism helper functions used to test that
    operations succeed on retry, fail with specific exceptions, and
    respect exception type filtering.
    """

    def setUp(self) -> None:
        """Run before tests."""
        self.counter = 0

    def _works_immediately(self, a: Any, b: Any, x: Any = None, y: Any = None) -> list[Any]:
        """Works immediately."""
        self.counter += 1
        return [a, b, x, y]

    def _works_second_attempt(self, a: Any, b: Any, x: Any = None, y: Any = None) -> list[Any]:
        """Works second_attempt."""
        self.counter += 1
        if self.counter == 2:
            return [a, b, x, y]
        raise Exception("Broke.")

    def _second_raises_exception2(self, a: Any, b: Any, x: Any = None, y: Any = None) -> list[Any]:
        """Second raises exception2."""
        self.counter += 1
        if self.counter == 2:
            return [a, b, x, y]
        raise MockException("Broke.")

    def _throws_exception2(
        self,
        a: Any,  # noqa: ARG002
        b: Any,  # noqa: ARG002
        x: Any = None,  # noqa: ARG002
        y: Any = None,  # noqa: ARG002
    ) -> list[Any]:
        """Throws exception2."""
        self.counter += 1
        raise MockException("Broke.")
