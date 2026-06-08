# User Guide

Runway is a CLI tool that deploys infrastructure-as-code modules (Terraform,
CloudFormation, AWS CDK, Serverless Framework, and static websites) from a
single configuration file. This guide walks you through installation, project
setup, and deploying each supported module type.

## Prerequisites

* Python 3.10 or newer
* AWS CLI configured with valid credentials (`aws configure`)
* Git (for environment detection from branch names)

## Installation

Add Runway to your project…

```bash
uv add runway
```

…or run Runway directly…

```bash
uvx runway
```

Verify installation:

```bash
runway --version
```

## Core concepts

### Deploy environment

Runway determines the current _deploy environment_ using this priority:

1. `--deploy-environment` CLI flag
2. `DEPLOY_ENVIRONMENT` environment variable
3. Git branch name (strips `ENV-` prefix; `master` maps to `common`)
4. Name of the current working directory

The deploy environment controls which configuration values apply (e.g.,
different AWS accounts for `dev` vs `prod`).

### Modules

A module is a directory containing infrastructure code. Runway detects the type
automatically:

| Directory suffix | Tool                   | Example directory |
|------------------|------------------------|-------------------|
| `.tf`            | Terraform              | `networking.tf`   |
| `.cfn`           | CloudFormation/CFNgin  | `sampleapp.cfn`   |
| `.cdk`           | AWS CDK                | `myapp.cdk`       |
| `.sls`           | Serverless Framework   | `backend.sls`     |
| `.web`           | Static website (S3+CF) | `frontend.web`    |

You can also set `type:` explicitly in the config or let Runway autodetect
by scanning files (e.g., presence of `*.tf` files).

### Deployments

A deployment groups modules together with shared settings: AWS regions, IAM
role assumption, environment variables, and account verification.

## Project structure

```text
my-project/
├── runway.yml          # Runway configuration
├── networking.tf/      # Terraform module
│   ├── main.tf
│   └── variables.tf
├── backend.sls/        # Serverless module
│   ├── serverless.yml
│   └── handler.py
└── frontend/           # Static site (autodetected)
    ├── package.json
    └── src/
```

## Configuration file

Create `runway.yml` at the project root (or run `runway new` to generate one):

```yaml
deployments:
  - name: my-infrastructure
    modules:
      - networking.tf
      - backend.sls
      - frontend
    regions:
      - us-east-1
    environments:
      dev: "123456789012"
      prod: "234567890123"
```

### Configuration options

```yaml
deployments:
  - name: production-stack
    modules:
      - path: networking.tf
        parameters:
          vpc_cidr: "10.0.0.0/16"
        environments:
          dev: true
          prod: true
      - backend.sls

    regions:
      - us-east-1
      - us-west-2

    # Or deploy regions in parallel:
    # parallel_regions:
    #   - us-east-1
    #   - us-west-2

    # Assume a role before deploying
    assume_role:
      arn: arn:aws:iam::123456789012:role/deploy-role
      session_name: runway

    # Verify correct account
    account_id: "123456789012"

    # Inject environment variables
    env_vars:
      APP_ENV: ${env DEPLOY_ENVIRONMENT}

    # Pass parameters to all modules in this deployment
    parameters:
      namespace: myapp-${env DEPLOY_ENVIRONMENT}

# Variables available for lookup resolution
variables:
  vpc_cidr:
    dev: "10.0.0.0/16"
    prod: "10.1.0.0/16"
```

### Lookups

Runway supports variable interpolation using lookup syntax:

| Lookup        | Description               | Example                   |
|---------------|---------------------------|---------------------------|
| `${env NAME}` | Environment variable      | `${env AWS_REGION}`       |
| `${var name}` | From `variables:` section | `${var vpc_cidr.dev}`     |
| `${ssm path}` | AWS SSM Parameter Store   | `${ssm /app/db-password}` |

Lookups can be nested: `${var account_id.${env DEPLOY_ENVIRONMENT}}`

## Commands

### Deploy

Deploy all modules in order:

```bash
runway deploy
```

In CI (non-interactive, deploys everything):

```bash
runway deploy --ci
```

Deploy specific modules:

```bash
runway deploy --module networking.tf
```

Deploy with tags:

```bash
runway deploy --tag tier:data --tag tier:app
```

### Destroy

Tear down infrastructure (reverse order):

```bash
runway destroy
```

### Plan

Preview changes without applying:

```bash
runway plan
```

### Init

Initialize modules (e.g., `terraform init`):

```bash
runway init
```

### Generate samples

Scaffold a starter module:

```bash
runway gen-sample tf         # Terraform
runway gen-sample cfn        # CloudFormation (CFNgin)
runway gen-sample cdk-py     # AWS CDK (Python)
runway gen-sample cdk-tsc    # AWS CDK (TypeScript)
runway gen-sample sls-py     # Serverless (Python)
runway gen-sample sls-tsc    # Serverless (TypeScript)
runway gen-sample static-react   # React static site
runway gen-sample static-angular # Angular static site
```

### Terraform version management

```bash
runway tfenv install 1.5.7   # Install a specific version
runway tfenv list             # List installed versions
runway tfenv run -- plan      # Run terraform via runway
```

## Deploying Terraform

### Directory structure

```text
networking.tf/
├── main.tf
├── variables.tf
├── outputs.tf
├── backend.hcl             # Backend config (optional)
└── dev-us-east-1.tfvars    # Per-environment variables
```

### Environment-specific variables

Runway automatically includes `.tfvars` files matching the pattern:

```text
{environment}-{region}.tfvars
```

For example, `dev-us-east-1.tfvars` is used when deploying to `dev` in
`us-east-1`.

### Backend configuration

Place backend config files matching:

```text
backend-{environment}-{region}.hcl
backend-{environment}.hcl
backend-{region}.hcl
backend.hcl
```

Runway passes the most specific match to `terraform init -backend-config=`.

### Workspace management

Runway automatically creates and selects Terraform workspaces matching the
deploy environment name.

### Module options

```yaml
modules:
  - path: networking.tf
    options:
      terraform_backend_config:
        bucket: my-state-bucket
        region: us-east-1
      terraform_version: "1.5.7"
      args:
        apply:
          - "-parallelism=20"
```

## Deploying CloudFormation (CFNgin)

### Directory structure

```text
sampleapp.cfn/
├── dev-us-east-1.env       # Environment variables
├── cfngin.yaml             # CFNgin config (stack definitions)
└── blueprints/
    └── my_stack.py         # Troposphere blueprint
```

### CFNgin config

```yaml
namespace: ${namespace}
cfngin_bucket: my-cfngin-bucket-${region}

stacks:
  vpc:
    class_path: blueprints.vpc.VPC
    variables:
      CidrBlock: "10.0.0.0/16"

  app:
    class_path: blueprints.app.Application
    requires:
      - vpc
    variables:
      VpcId: ${output vpc.VpcId}
```

### Environment file

The `.env` file (e.g., `dev-us-east-1.env`) provides values:

```text
namespace: myapp-dev
region: us-east-1
cfngin_bucket_name: myapp-cfngin-us-east-1
```

## Deploying AWS CDK

### Directory structure

```text
myapp.cdk/
├── package.json
├── cdk.json
├── tsconfig.json
└── lib/
    └── my-stack.ts
```

### Requirements

* Node.js and npm installed
* `aws-cdk` in `package.json` devDependencies

Runway runs `npm install` automatically, then invokes `npx cdk deploy` (or
`destroy`/`diff`/`synth` depending on the command).

### Module options

```yaml
modules:
  - path: myapp.cdk
    options:
      build_steps:
        - npx tsc
      skip_npm_ci: false
```

## Deploying with serverless framework

### Directory structure

```text
backend.sls/
├── package.json
├── serverless.yml
└── handler.py
```

### Requirements

* Node.js and npm installed
* `serverless` in `package.json` devDependencies

Runway runs `npm install` then invokes `npx sls deploy` (or `remove`/`print`).

### Module options

```yaml
modules:
  - path: backend.sls
    options:
      args:
        - "--verbose"
      skip_npm_ci: false
      promotezip:
        bucketname: my-artifact-bucket
```

## Deploying static websites

### Directory structure

```text
frontend.web/
├── package.json
└── src/
    └── index.html
```

Static site modules deploy to S3 and optionally configure CloudFront. They use
CFNgin under the hood to manage the infrastructure (S3 bucket, CloudFront
distribution, Route53 records).

### Parameters

```yaml
modules:
  - path: frontend.web
    parameters:
      namespace: myapp-${env DEPLOY_ENVIRONMENT}
      staticsite_aliases: www.example.com
      staticsite_acmcert_arn: arn:aws:acm:us-east-1:...
```

## Tips for CI/CD

### Non-interactive mode

Set the `CI` environment variable or pass `--ci`:

```bash
CI=1 runway deploy
# or
runway deploy --ci
```

This skips interactive prompts and deploys all modules.

### Environment detection

In CI, set `DEPLOY_ENVIRONMENT` explicitly to avoid git branch detection:

```bash
export DEPLOY_ENVIRONMENT=prod
runway deploy --ci
```

### Parallel regions

For faster multi-region deploys in CI:

```yaml
deployments:
  - modules:
      - networking.tf
    parallel_regions:
      - us-east-1
      - eu-west-1
      - ap-southeast-1
```

## Troubleshooting

### Enable debug logging

```bash
runway deploy --debug
```

Or set `DEBUG=1` in the environment.

### Verbose output

```bash
runway deploy --verbose
```

### Common issues

* **"Config not found"** — ensure `runway.yml` or `runway.yaml` exists at
  the project root (or the directory you ran the command from).
* **"Account ID mismatch"** — your AWS credentials don't match the
  `account_id` defined in the deployment. Check `aws sts get-caller-identity`.
* **"Module class could not be determined"** — Runway can't detect the module
  type. Add a suffix to the directory name (`.tf`, `.cfn`, etc.) or set
  `type:` in the module definition.
* **Terraform version issues** — use `runway tfenv install <version>` or set
  `terraform_version` in module options.
