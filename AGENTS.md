# Agents Guide

This document provides AI agents the context needed to work effectively in this repository. It is structured for minimal token usage — reference specific sections or the linked sub-documents as needed rather than consuming everything at once.

## Overview

Runway is a Python CLI tool that simplifies management of infrastructure deployment tools. It provides a unified interface over AWS CDK, Serverless Framework, CloudFormation (via CFNgin), Terraform, and static website deployments to S3 + CloudFront.

Entry point: `runway._cli.main:cli` (Click-based CLI).

## Repository layout

```text
runway/             # Main Python package (source code)
  _cli/             # Click CLI commands and utilities
  cfngin/           # CloudFormation stack management engine
    hooks/          # Lifecycle hooks (awslambda, docker, staticsite, ssm)
    blueprints/     # Troposphere blueprint definitions
    actions/        # Deploy, destroy, diff actions
    providers/      # AWS CloudFormation provider
  config/           # Configuration models and parsing (Pydantic v2)
  context/          # Runway and CFNgin runtime contexts
  core/             # Core components (Module, Deployment, providers)
    providers/aws/  # AWS provider implementations (s3 helpers)
  module/           # Module handlers (terraform, serverless, cdk, staticsite)
  lookups/          # Variable lookup handlers
  templates/        # Starter project templates (cdk-py, sls-tsc, etc.)
  variables.py      # Variable resolution system
tests/
  unit/             # Unit tests (pytest, moto for AWS mocking)
  integration/      # Integration tests
  functional/       # Functional/end-to-end tests
infrastructure/     # Infrastructure-as-code for the project itself
docs/               # Sphinx documentation source
typings/            # Generated .pyi stubs for troposphere
```

## Technology stack

| Purpose            | Tool                                       |
|--------------------|--------------------------------------------|
| Language           | Python 3.10–3.14                           |
| Package manager    | [uv](https://docs.astral.sh/uv/)           |
| CLI framework      | Click 8.x                                  |
| Data models        | Pydantic v2                                |
| AWS SDK            | boto3/botocore with boto3-stubs            |
| CloudFormation DSL | Troposphere + Awacs                        |
| IaC parsing        | python-hcl2 (Terraform), cfn_flip (CFN)    |
| Linter/formatter   | [Ruff](https://docs.astral.sh/ruff/)       |
| Type checker       | [Zuban](https://zubanls.com) (mypy-compat) |
| Test framework     | pytest + moto + pytest-mock                |
| Git hooks/linting  | [hk](https://github.com/jdx/hk) (hk.pkl)   |
| Docs               | Sphinx + Furo theme + ReadTheDocs          |
| Build system       | poetry-dynamic-versioning                  |
| Markdown lint      | rumdl                                      |
| Code graph         | KiroGraph (MCP server)                     |

## Commands reference

```bash
# Install dependencies
uv sync

# Run all unit tests
uv run pytest tests/unit

# Run a specific test file
uv run pytest tests/unit/path/to/test_file.py -v

# Lint and format
uv tool run ruff check --force-exclude --fix .
uv tool run ruff format --force-exclude .

# Type check (zuban)
uv tool run zuban check runway/path/to/file.py

# Run all hk checks
hk fix --no-fail-fast --all

# Run a single hk step
hk fix --no-fail-fast --all --step python-typechecking
hk fix --no-fail-fast --all --step python-ruff
hk fix --no-fail-fast --all --step python-format
```

## Key architectural concepts

### CFNgin

CFNgin is the CloudFormation management engine. It defines stacks via Blueprints (Troposphere wrappers) and orchestrates them using a DAG-based plan with Actions (deploy, destroy, diff). Hooks run before/after actions.

### Modules

Each deployment tool (Terraform, CDK, Serverless, Static Site) has a module handler in `runway/module/`. Modules inherit from `RunwayModule` and implement `deploy()`, `destroy()`, `plan()`, and `init()`.

### Config system

Configuration uses Pydantic v2 models in `runway/config/models/`. The hierarchy: `RunwayConfigDefinitionModel` → deployments → modules. CFNgin has its own config model tree.

### Variable resolution

Variables support lookup handlers (`${var LOOKUP_NAME QUERY}`) defined in `runway/lookups/handlers/`. The Variable class resolves lookups recursively.

## Configuration files (do not modify)

* **`hk.pkl`** — Git hook and linting pipeline configuration. Never modify.

## Configuration files (may modify)

* **`pyproject.toml`** — All tool config lives here. Modify freely.
* **`.kiro/steering/*.md`** — Agent steering documents. Update when you learn new patterns.

## Agent infrastructure

Detailed documentation on hooks, steering files, agents, and MCP servers lives in [`.kiro/AGENTS-INFRASTRUCTURE.md`](.kiro/AGENTS-INFRASTRUCTURE.md).

## Python conventions

Detailed Python style and type-checking conventions live in the steering file [`.kiro/steering/python-code-conventions.md`](.kiro/steering/python-code-conventions.md).

Key points:

* Zero Zuban diagnostics policy — fix the root cause, suppress as last resort
* Ruff for formatting and linting (replaces black/isort/flake8)
* Google-style docstrings
* Type annotations required on all function signatures
* `from __future__ import annotations` in most files

## Markdown conventions

Markdown style is enforced by `rumdl` (configured in `.rumdl.toml`). Key rules are documented in [`.kiro/steering/markdown-style.md`](.kiro/steering/markdown-style.md).

## Excluded/vendored code

These directories are excluded from linting, type checking, and coverage. Do not modify them:

* `runway/aws_sso_botocore/` — vendored AWS SSO botocore code
* `runway/cfngin/hooks/staticsite/auth_at_edge/templates/` — Lambda@Edge code
* `typings/` — auto-generated pyright stubs for troposphere
* `runway/templates/cdk-py/` — CDK starter template (external deps)
