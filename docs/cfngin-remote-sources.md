# CFNgin Remote Sources

## Overview

Remote Sources (configured via `package_sources`) allow CFNgin to pull in
external code and configuration from locations outside the current project
directory. This enables teams to share reusable blueprints, hooks, and
configuration fragments across multiple CFNgin projects without duplicating
code.

When CFNgin processes a configuration file, it fetches the defined package
sources, caches them locally, adds their paths to Python's `sys.path` (making
them importable), and optionally merges their configuration files into the
current configuration.

There are three types of package sources:

* **Local** — a directory on the local filesystem
* **S3** — an archived file (zip, tar, tar.gz) stored in an AWS S3 bucket
* **Git** — a remote git repository

## Configuration

Package sources are defined under the `package_sources` key in a CFNgin
configuration file:

```yaml
namespace: my-app
cfngin_bucket: my-cfngin-bucket

package_sources:
  local:
    - source: ../shared-blueprints
      paths:
        - blueprints/
  git:
    - uri: git@github.com:myorg/cfngin-modules.git
      tag: v2.1.0
      paths:
        - src/
      configs:
        - stacks/base.yaml
  s3:
    - bucket: my-artifacts-bucket
      key: packages/networking-v1.0.0.zip
      paths:
        - networking/

stacks:
  - name: vpc
    class_path: networking.vpc.Blueprint
```

### Cache directory

Remote sources are downloaded to a local cache directory to avoid repeated
fetches. The default location is:

```text
{work_dir}/cache/packages/
```

Where `work_dir` defaults to `.runway/` in the current working directory. This
can be overridden with the `cfngin_cache_dir` configuration option:

```yaml
cfngin_cache_dir: /tmp/my-cfngin-cache
```

## Source types

### Local

Local package sources reference directories on the local filesystem. No
downloading or caching is needed — CFNgin adds the specified paths directly
to `sys.path`.

```yaml
package_sources:
  local:
    - source: ../shared-code
      paths:
        - blueprints/
        - hooks/
      configs:
        - base-config.yaml
```

| Field     | Type      | Required | Description                                                       |
|-----------|-----------|----------|-------------------------------------------------------------------|
| `source`  | string    | yes      | Path relative to the config file (or absolute) to the source root |
| `paths`   | list[str] | no       | Subdirectories to add to `sys.path`                               |
| `configs` | list[str] | no       | Config files (relative to source root) to merge                   |

If `paths` is omitted, the source root directory itself is added to
`sys.path`.

### Git repository

Git package sources clone a remote repository to the local cache and check
out a specific ref.

```yaml
package_sources:
  git:
    - uri: git@github.com:myorg/cfngin-blueprints.git
      tag: v1.2.0
      paths:
        - src/blueprints/
    - uri: https://github.com/myorg/common-hooks.git
      branch: main
      configs:
        - cfngin/base.yaml
    - uri: git@github.com:myorg/infra-modules.git
      commit: 5d83f7ff1ad6527233be2c27e9f68816599b6c57
```

| Field     | Type      | Required | Description                                   |
|-----------|-----------|----------|-----------------------------------------------|
| `uri`     | string    | yes      | Git repository URI (SSH or HTTPS)             |
| `branch`  | string    | no       | Branch name to check out                      |
| `commit`  | string    | no       | Specific commit hash to check out             |
| `tag`     | string    | no       | Tag to check out                              |
| `paths`   | list[str] | no       | Subdirectories to add to `sys.path`           |
| `configs` | list[str] | no       | Config files (relative to repo root) to merge |

Only one of `branch`, `commit`, or `tag` may be specified. If none is
provided, the repository's HEAD is used.

#### Ref resolution priority

When determining which commit to check out, CFNgin resolves refs in this
order:

1. `commit` — used directly as-is
2. `tag` — used as-is
3. `branch` — resolved to a commit ID via `git ls-remote` before cloning

This ensures pinned dependencies (commit or tag) produce reproducible
deployments, while branch refs always get the latest commit.

#### Caching behavior

Cloned repositories are cached in a directory named by sanitizing the URI and
appending the resolved ref:

```text
{cache_dir}/packages/{sanitized_uri}-{ref}/
```

If the cached directory already exists, the clone is skipped entirely. This
means that for branch-based sources, the cache is keyed by the commit ID at
the time of first fetch. Delete the cache directory to force a fresh clone.

### AWS S3

S3 package sources download an archived file from S3, extract it locally, and
add the extracted paths to `sys.path`.

```yaml
package_sources:
  s3:
    - bucket: my-artifacts
      key: packages/blueprints-v2.0.0.tar.gz
      paths:
        - blueprints/
      configs:
        - config/defaults.yaml
    - bucket: shared-tools
      key: hooks/monitoring.zip
      requester_pays: true
      use_latest: true
```

| Field            | Type      | Required | Description                                                    |
|------------------|-----------|----------|----------------------------------------------------------------|
| `bucket`         | string    | yes      | S3 bucket name                                                 |
| `key`            | string    | yes      | S3 object key (must end in `.zip`, `.tar`, or `.tar.gz`)       |
| `paths`          | list[str] | no       | Subdirectories to add to `sys.path`                            |
| `configs`        | list[str] | no       | Config files (relative to archive root) to merge               |
| `requester_pays` | bool      | no       | Set to `true` if the bucket requires requester pays            |
| `use_latest`     | bool      | no       | Re-download if S3 last-modified date changes (default: `true`) |

#### Supported archive formats

| Extension | Format              |
|-----------|---------------------|
| `.tar.gz` | Gzip-compressed tar |
| `.tar`    | Uncompressed tar    |
| `.zip`    | Zip archive         |

The archive format is determined by the file extension of the S3 key. If the
key does not end in one of the supported extensions, CFNgin raises a
`ValueError`.

#### Caching and freshness

S3 packages are cached in a directory named by sanitizing the bucket and key:

```text
{cache_dir}/packages/s3-{bucket}-{key_without_ext}/
```

When `use_latest` is `true` (the default), CFNgin queries the object's
`LastModified` date and appends it to the directory name as a timestamp. If
the timestamp changes (object was re-uploaded), a fresh download occurs.

When `use_latest` is `false`, CFNgin uses the cached directory without checking
S3 for updates.

## Configuration merging

When a package source defines `configs`, CFNgin reads those YAML files and
deep-merges them into the current configuration. The merge follows these
rules:

* The current config file takes precedence over remote configs.
* Remote configs are merged in the order they appear in `configs_to_merge`
  (local sources first, then S3, then git — matching the processing order).
* Deep merge is recursive: nested dicts are merged key-by-key, lists are
  concatenated.
* After merging, the combined config is re-rendered through the template
  engine, allowing merged content to reference parameters.

This enables a pattern where a shared base configuration defines common
stacks, hooks, or defaults, and the local config overrides or extends specific
values:

```yaml
# remote: base-config.yaml
namespace: ${namespace}
stacks:
  - name: shared-vpc
    class_path: shared.vpc.Blueprint
    variables:
      CidrBlock: 10.0.0.0/16

# local config
namespace: my-app
package_sources:
  git:
    - uri: git@github.com:myorg/base-infra.git
      tag: v1.0.0
      configs:
        - base-config.yaml

stacks:
  - name: my-app-stack
    class_path: app.Blueprint
```

The result is a merged configuration containing both `shared-vpc` and
`my-app-stack`, with the local `namespace` value (`my-app`) taking precedence.

## Processing order

Package sources are processed in a deterministic order:

1. **Local** sources — processed first since they require no network access
2. **S3** sources — downloaded and extracted
3. **Git** sources — cloned and checked out

Within each type, sources are processed in the order they are listed in the
configuration file. This order matters because earlier sources are added to
`sys.path` first, giving them import priority over later sources.

## Path manipulation

For each package source, CFNgin manipulates `sys.path` to make the source's
code importable:

* If `paths` is specified, each listed subdirectory (resolved as an absolute
  path) is appended to `sys.path`.
* If `paths` is omitted, the package root directory itself is appended to
  `sys.path`.

This means blueprints and hooks from remote sources can be referenced by their
Python import path in stack definitions just like local code:

```yaml
stacks:
  - name: vpc
    class_path: networking.vpc.VpcBlueprint  # from remote source
```

## Architecture

### Key components

| Component                                                                 | Role                                                    |
|---------------------------------------------------------------------------|---------------------------------------------------------|
| `CfnginConfig.process_package_sources()`                                  | Entry point; orchestrates source processing and merging |
| `SourceProcessor`                                                         | Fetches, caches, and registers package sources          |
| `SourceProcessor.fetch_local_package()`                                   | Handles local source path registration                  |
| `SourceProcessor.fetch_s3_package()`                                      | Downloads, extracts, and caches S3 archives             |
| `SourceProcessor.fetch_git_package()`                                     | Clones, checks out, and caches git repositories         |
| `SourceProcessor.update_paths_and_config()`                               | Adds paths to `sys.path` and queues configs for merge   |
| `Extractor` (base) / `TarExtractor` / `TarGzipExtractor` / `ZipExtractor` | Archive extraction                                      |
| `CfnginPackageSourcesDefinitionModel`                                     | Pydantic model validating the `package_sources` config  |
| `merge_dicts()`                                                           | Deep-merges remote config dicts into the current config |

### Data flow

```text
┌────────────────────────┐
│ CFNgin Config YAML     │
│ package_sources:       │
│   local: [...]         │
│   s3: [...]            │
│   git: [...]           │
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│ CfnginConfig           │
│ .process_package_      │
│  sources()             │
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐       ┌──────────────────────────┐
│ SourceProcessor        │──────►│ Local Cache              │
│                        │       │ {cache_dir}/packages/    │
│ .fetch_local_package() │       │   ../shared-code/        │
│ .fetch_s3_package()    │       │   s3-bucket-key-ts/      │
│ .fetch_git_package()   │       │   git_repo-ref/          │
└───────────┬────────────┘       └──────────────────────────┘
            │
            ├── sys.path.append(...)
            │
            ├── configs_to_merge = [path1, path2, ...]
            │
            ▼
┌────────────────────────┐
│ merge_dicts()          │
│ Deep-merge remote      │
│ configs into current   │
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│ Final merged config    │
│ (re-rendered with      │
│  parameters)           │
└────────────────────────┘
```

## Use cases

### Sharing blueprints across teams

A central team maintains a git repository of vetted CloudFormation blueprints.
Application teams reference specific tagged versions:

```yaml
package_sources:
  git:
    - uri: git@github.com:platform-team/cfngin-blueprints.git
      tag: v3.2.1
      paths:
        - src/

stacks:
  - name: vpc
    class_path: platform.networking.VpcBlueprint
```

### Distributing compiled packages via S3

For environments where git access is restricted (CI/CD pipelines, locked-down
networks), pre-packaged archives in S3 provide an alternative distribution
mechanism:

```yaml
package_sources:
  s3:
    - bucket: platform-artifacts
      key: cfngin/blueprints-v3.2.1.tar.gz
```

### Base configuration inheritance

A shared base config defines common infrastructure patterns. Each environment
overlays its own overrides:

```yaml
package_sources:
  git:
    - uri: git@github.com:platform-team/base-infra.git
      tag: v1.0.0
      configs:
        - cfngin/base.yaml
        - cfngin/monitoring.yaml

# Local overrides take precedence
stacks:
  - name: app
    class_path: app.Blueprint
    variables:
      Environment: production
```

### Combining local development with remote sources

During development, reference a local checkout for rapid iteration; in CI, use
a pinned git tag:

```yaml
package_sources:
  local:
    - source: ../my-blueprints  # local dev checkout
      paths:
        - src/
```

## Troubleshooting

### Import errors after adding a package source

* Verify the `paths` entry points to the correct subdirectory within the
  source. The directory should contain the Python package (a folder with
  `__init__.py` or a standalone module).
* Check the cache directory to confirm the source was downloaded correctly.
* Remember that `sys.path` additions are order-dependent — earlier sources
  take precedence.

### Stale cached sources

* For git sources pinned to a branch, the cache is keyed by the commit ID at
  first fetch. Delete the cached directory to force a re-clone.
* For S3 sources with `use_latest: true`, re-uploading the archive with a new
  timestamp triggers a fresh download.
* The cache directory can be cleared entirely by deleting
  `{work_dir}/cache/packages/`.

### Archive format not recognized

S3 package source keys must end in `.zip`, `.tar`, or `.tar.gz`. If the S3
object has a different extension, CFNgin raises a `ValueError`. Rename the
object or re-upload with a supported extension.

### Git authentication failures

Git sources use the system's git configuration for authentication. Ensure
SSH keys are configured for SSH URIs (`git@...`) or credentials are available
for HTTPS URIs. The `git` binary must be available on `PATH`.
