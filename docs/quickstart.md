# Quick Flow Summary

## Entry point

```text
runway._cli.main:cli
```

The CLI is a Click application registered via `pyproject.toml`
(`[project.scripts] runway = "runway._cli.main:cli"`). The `cli` function is a
`click.Group` decorated with global options (`--debug`, `--verbose`,
`--no-color`, `--ci`, `--deploy-environment`). Subcommands are auto-registered
from `runway._cli.commands.__all__`.

## Primary flow

A `runway deploy` (or `destroy`/`plan`/`init`) executes this call chain:

```text
cli (Click group)
 └─ deploy command (runway/_cli/commands/_deploy.py)
     ├─ Load RunwayConfig from runway.yml
     ├─ Create RunwayContext (env, region, credentials)
     ├─ Select deployments (interactive prompt, --tag, or --module filters)
     └─ Runway(config, context).deploy(selected_deployments)
         └─ Deployment.run_list(action, deployments)
             └─ For each deployment:
                 ├─ Resolve variables and env_vars
                 ├─ Assume IAM role (if configured)
                 ├─ Validate account credentials
                 └─ Module.run_list(action, modules)
                     └─ For each module:
                         ├─ Determine module type (explicit → suffix → autodetect)
                         ├─ Dynamically load handler class
                         ├─ cd into module directory
                         └─ handler.deploy() / .destroy() / .plan() / .init()
```

### Environment detection order

1. `--deploy-environment` CLI flag
2. `DEPLOY_ENVIRONMENT` environment variable
3. Git branch name (strips `ENV-` prefix; `master` → `common`)
4. Current working directory name

### Module type detection order

1. Explicit `type:` field in module definition
2. Directory suffix (`.tf`, `.sls`, `.cdk`, `.cfn`, `.web`)
3. File-based autodetection (presence of `*.tf`, `serverless.yml`, `cdk.json`,
   `*.yaml`)

## Module roles

| Module class          | File                                  | IaC tool                |
|-----------------------|---------------------------------------|-------------------------|
| `Terraform`           | `runway/module/terraform.py`          | Terraform/OpenTofu      |
| `CloudFormation`      | `runway/module/cloudformation.py`     | CFNgin (CloudFormation) |
| `CloudDevelopmentKit` | `runway/module/cdk.py`                | AWS CDK                 |
| `Serverless`          | `runway/module/serverless.py`         | Serverless Framework    |
| `StaticSite`          | `runway/module/staticsite/handler.py` | S3 + CloudFront         |

All inherit from `RunwayModule` (base class in `runway/module/base.py`) which
defines the `deploy()`, `destroy()`, `init()`, `plan()` interface.

### CFNgin subsystem

`CloudFormation` delegates to the `CFNgin` class (`runway/cfngin/cfngin.py`),
which:

1. Finds `.yaml` config files in the module directory
2. Renders templates with Jinja2 (variable interpolation)
3. Builds a DAG of stacks based on dependencies
4. Executes Actions (`deploy`, `destroy`, `diff`, `init`) via a Provider
   (`runway/cfngin/providers/aws/default.py`)
5. Runs pre/post hooks around stack operations

Stacks are defined using Blueprints (Troposphere wrappers) that produce
CloudFormation templates programmatically.

## Design decisions

### Why a unified CLI over multiple tools

Infrastructure projects often mix Terraform, CDK, Serverless, and
CloudFormation in the same repository. Without Runway, teams maintain bespoke
shell scripts or Makefiles that:

* Are environment-specific and fragile
* Don't work identically on local workstations and CI
* Can't easily enforce deployment ordering

Runway provides a single `runway.yml` config that declares deployment ordering,
environment mappings, and IAM roles — making GitOps reproducible.

### Why dynamic module loading

The `RunwayModuleType` class uses Python's import system to load module handler
classes at runtime. This allows:

* Third-party modules via `class_path` in config
* Auto-detection without explicit configuration for simple projects
* Extension without modifying Runway core

### Why use pydantic v2 for config

* Strict validation with clear error messages
* Automatic coercion (e.g., string → Path)
* Model inheritance for deployment/module variants
* JSON Schema generation for editor autocomplete

### Why separate contexts per module

Each `Module` receives a `.copy()` of the `RunwayContext`. This isolates
module-level env_vars, region overrides, and working directory changes from
affecting sibling modules.

## Risks and unknowns

* **Parallel module execution uses `fork`** — this can cause issues with
  libraries that hold open connections or locks before fork. Not compatible
  with `spawn`-only platforms.
* **Variable resolution is recursive** — deeply nested lookups can be hard to
  debug. Failed lookups surface as `UnresolvedVariable` exceptions.
* **CFNgin's Action DAG depends on stack `requires` declarations** — missing
  or circular dependencies cause silent hangs or errors at plan time.
* **Static site module is deprecated** — marked for removal in the next major
  release. Tests have known pre-existing failures.
* **Terraform version management** — `TFEnvManager` downloads and caches
  Terraform binaries. Network failures during download can leave partial state.
* **Vendored `aws_sso_botocore`** — frozen copy of AWS SSO credential
  resolution. Will diverge from upstream over time.
