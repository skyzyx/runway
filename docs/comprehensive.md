# Deep Architecture Audit

## Entry points

### CLI binary

```text
[project.scripts]
runway = "runway._cli.main:cli"
```

Installed via `pip install runway` or `uv sync`, the `runway` command invokes
`runway._cli.main:cli`.

### Programmatic API

```python
from runway.core import Runway
from runway.config import RunwayConfig
from runway.context import RunwayContext
```

The `Runway` class can be instantiated directly for embedding in other tools.

### CFNgin standalone

CFNgin (the CloudFormation engine) can be used independently via its own
context and config classes, though this is not a documented public API.

## CLI startup and initialization flow

```text
runway (shell command)
 → runway/_cli/main.py :: cli()
   ├─ _CliGroup.invoke() — parses global options via argparse
   ├─ setup_logging() — configures coloredlogs, debug levels
   ├─ CliContext(**opts) — stored in ctx.obj
   └─ Click dispatches to subcommand
```

### `_CliGroup` class

Extends `click.Group` to intercept invocation and pre-parse global options
(`--ci`, `--debug`, `--deploy-environment`, `--no-color`, `--verbose`) using
`argparse` before Click processes the subcommand. This allows global options
to appear anywhere in the command line.

### `CliContext`

Lightweight dataclass (`runway/_cli/utils.py`) that holds parsed global options
and lazily creates:

* `RunwayConfig` — parsed from `runway.yml`/`runway.yaml`
* `RunwayContext` — runtime context with environment, region, AWS session

## Command-specific flows

### `runway deploy`

```text
_deploy.py :: deploy()
 ├─ If --execute-changesets: execute_changesets_from_file() → return
 ├─ select_deployments() — filter by --tag/--module or interactive prompt
 └─ Runway(config, context).deploy(deployments)
     └─ __run_action("deploy", deployments)
         └─ Deployment.run_list(action, context, deployments, future, variables)
```

### `runway destroy`

Same as deploy but reverses deployment and module order before execution.

### `runway plan`

Executes the `plan` action on each module. For Terraform this runs
`terraform plan`. For CFNgin it creates CloudFormation changesets and outputs
a diff.

### `runway init`

Runs initialization logic (e.g., `terraform init`, CFNgin setup) without
deploying.

### `runway new`

Generates a sample `runway.yml` in the current directory.

### `runway gen-sample`

Scaffolds starter project templates for each supported module type.

### `runway tfenv install/list/run`

Manages Terraform binary versions. Downloads from HashiCorp releases and
caches in `~/.runway/`.

## File and module responsibilities

### Core orchestration

| File                                     | Role                                          |
|------------------------------------------|-----------------------------------------------|
| `runway/_cli/main.py`                    | Click CLI entry point and global option parse |
| `runway/_cli/commands/_deploy.py`        | `runway deploy` command definition            |
| `runway/_cli/commands/_destroy.py`       | `runway destroy` command definition           |
| `runway/_cli/commands/_plan.py`          | `runway plan` command definition              |
| `runway/_cli/utils.py`                   | `CliContext`, `select_deployments()`          |
| `runway/core/__init__.py`                | `Runway` class — top-level orchestrator       |
| `runway/core/components/_deployment.py`  | `Deployment` — region iteration, role assume  |
| `runway/core/components/_module.py`      | `Module` — type resolution, handler dispatch  |
| `runway/core/components/_module_type.py` | `RunwayModuleType` — class detection logic    |

### Configuration

| File                                      | Role                                     |
|-------------------------------------------|------------------------------------------|
| `runway/config/__init__.py`               | `RunwayConfig`, `CfnginConfig` parsers   |
| `runway/config/models/runway/__init__.py` | Pydantic models for runway.yml           |
| `runway/config/models/cfngin/__init__.py` | Pydantic models for CFNgin YAML          |
| `runway/config/components/runway/`        | Definition wrappers (deployment, module) |

### Module handlers

| File                                  | Module type    | Tool invoked       |
|---------------------------------------|----------------|--------------------|
| `runway/module/terraform.py`          | Terraform      | `terraform` CLI    |
| `runway/module/cloudformation.py`     | CloudFormation | CFNgin engine      |
| `runway/module/cdk.py`                | CDK            | `cdk` CLI via npx  |
| `runway/module/serverless.py`         | Serverless     | `sls` CLI via npx  |
| `runway/module/staticsite/handler.py` | Static Site    | CFNgin + S3 sync   |
| `runway/module/base.py`               | Base class     | Abstract interface |

### CFNgin engine

| File                                     | Role                                      |
|------------------------------------------|-------------------------------------------|
| `runway/cfngin/cfngin.py`                | `CFNgin` — config loading, action routing |
| `runway/cfngin/actions/deploy.py`        | Stack deploy action (create/update)       |
| `runway/cfngin/actions/destroy.py`       | Stack destroy action (delete)             |
| `runway/cfngin/actions/diff.py`          | Stack diff/changeset action               |
| `runway/cfngin/actions/base.py`          | `BaseAction` — DAG planning, execution    |
| `runway/cfngin/plan.py`                  | `Plan` — DAG-based execution plan         |
| `runway/cfngin/providers/aws/default.py` | AWS CloudFormation API provider           |
| `runway/cfngin/blueprints/base.py`       | `Blueprint` — Troposphere wrapper         |
| `runway/cfngin/hooks/`                   | Lifecycle hooks (pre/post deploy)         |

### Context and environment

| File                        | Role                                    |
|-----------------------------|-----------------------------------------|
| `runway/context/_runway.py` | `RunwayContext` — session state         |
| `runway/context/_cfngin.py` | `CfnginContext` — CFNgin-specific state |
| `runway/context/_base.py`   | `BaseContext` — shared AWS session mgmt |

### Variable resolution

| File                              | Role                                      |
|-----------------------------------|-------------------------------------------|
| `runway/variables.py`             | `Variable`, `VariableValue` resolution    |
| `runway/lookups/handlers/base.py` | `LookupHandler` base class                |
| `runway/lookups/handlers/var.py`  | `${var}` — resolve from variables file    |
| `runway/lookups/handlers/env.py`  | `${env}` — resolve from environment vars  |
| `runway/lookups/handlers/ssm.py`  | `${ssm}` — resolve from AWS SSM Parameter |

## Decision points and side effects

### Environment matching

`Module.environment_matches_defined` determines if a module should run in the
current environment. Returns:

* `True` — module is explicitly enabled for this env
* `False` — module is explicitly excluded
* `None` — no environments defined (module runs unconditionally)

This cascades from deployment-level `environments` merged with module-level
`environments`, merged with `runway.module.yml` environments.

### IAM role assumption

`Deployment.run()` wraps execution in `AssumeRole` context manager. The role
ARN comes from the deployment's `assume_role` config. If the current account
doesn't match `account_id` or `account_alias`, execution halts with
`sys.exit(1)`.

### Working directory changes

`Module.run()` uses `change_dir()` context manager to `cd` into the module
root before invoking the handler. This is why parallel module execution uses
`fork` (ProcessPoolExecutor) rather than threads — `os.chdir()` is
process-wide.

### Variable resolution timing

Variables resolve lazily. The `RunwayDeploymentDefinition.resolve()` call
triggers lookup resolution at two points:

1. `pre_process=True` — resolves deployment-level variables before module
   iteration
2. Per-module — each module resolves its own variables in its context copy

Failed lookups raise `UnresolvedVariable`, which surfaces as a deployment
error.

### CFNgin stack dependency ordering

`BaseAction` builds a topological sort of stacks based on the `requires` field
in each stack definition. Stacks without dependencies run first (respecting
concurrency limits). The DAG is visualized in `--dump` output.

### Side effects of deploy

* **CloudFormation** — creates/updates stacks, potentially creating IAM roles,
  S3 buckets, Lambda functions, etc.
* **Terraform** — applies state changes to cloud resources
* **CDK** — synthesizes and deploys CloudFormation via the CDK toolkit
* **Serverless** — packages and deploys Lambda functions
* **Static Site** — syncs local build artifacts to S3, invalidates CloudFront

## Risks, gaps, and follow-up inspections

### Concurrency model

* `ProcessPoolExecutor(mp_context="fork")` is used for both parallel regions
  and parallel modules
* Fork-safety depends on no library holding resources (DB connections, file
  locks) before fork
* The `max_concurrent_regions` and `max_concurrent_modules` context attrs
  control parallelism but have no backpressure mechanism

### Error handling

* Many error paths call `sys.exit(1)` directly rather than raising exceptions
* This makes the code difficult to embed in larger applications
* CFNgin actions catch broad `Exception` in some paths, potentially masking
  root causes

### Vendored code

* `runway/aws_sso_botocore/` — frozen SSO credential logic; will diverge from
  upstream botocore
* `runway/cfngin/hooks/staticsite/auth_at_edge/templates/` — Lambda@Edge
  functions vendored inline

### Type system gaps

* s3transfer API is untyped — `call_args` attributes are accessed dynamically
* boto3 stubs have kwargs signature issues with `**dict` unpacking
* Pydantic `model_copy()` loses generic type information

### Deprecated features

* Static site module — deprecated, pending removal in next major version
* `parse_obj` on config models — Pydantic v1 compatibility shim

### Test coverage gaps

* 13 pre-existing test failures on the current branch (keypair, tfenv,
  staticsite/handler)
* Functional tests require real AWS credentials and are not run in CI by
  default
* Integration tests exercise the CLI subprocess but not all code paths

### Configuration coupling

* `hk.pkl` passes explicit file paths to zuban (`{{ files }}`), bypassing
  zuban's `exclude` config — per-module `[[tool.mypy.overrides]]` is the
  mechanism for suppression
* Ruff's `extend-exclude` and zuban's `exclude` must be kept in sync manually

## Design rationale

### Why use click for the CLI

* Declarative command/option registration
* Automatic help generation
* Context passing between group and subcommands
* Widely understood in the Python ecosystem

### Why use pydantic v2 for config models

* Runtime validation of user-provided YAML
* Discriminated unions for polymorphic config (deployment types, module types)
* Model inheritance maps cleanly to the config hierarchy
* `model_validate()` provides clear error messages with field paths

### Why CFNgin as a subsystem rather than raw CloudFormation

* Dependency-aware stack ordering via DAG
* Template generation via Troposphere (Python DSL)
* Hooks for custom logic (Lambda packaging, Docker builds, SSM parameters)
* Blueprint reuse across projects
* Variable interpolation across stacks

### Why separate context per module

* Modules may override `env_vars`, altering the environment
* Region can differ between parallel deployments
* `os.chdir()` is process-global — isolation requires process-per-module for
  parallel execution

### Why autodetection for module types

* Reduces boilerplate in `runway.yml` — a simple directory listing is often
  sufficient
* Supports mixed-tool repositories without per-module type declarations
* Falls back gracefully: explicit → suffix → file scan → error

### Why `RunwayModuleType` uses import strings

* Decouples module registration from Runway core
* Allows third-party extensions without modifying source
* Deferred imports keep startup fast (only the selected module's dependencies
  load)
