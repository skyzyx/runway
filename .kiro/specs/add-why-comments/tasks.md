# Implementation Plan: Add "Why" Comments to cfngin Subpackage

## Overview

Add rationale-focused "why" comments to all Python files in the `runway/cfngin/` subpackage and corresponding tests. Comments explain design intent, purpose, and rationale — not what the code does.

## Tasks

* [x] 1. Add "why" comments to cfngin core files
  Add rationale-focused comments to the top-level cfngin source files (plan.py, stack.py, cfngin.py, utils.py, environment.py, status.py, exceptions.py, session_cache.py, ui.py, tokenize_userdata.py, awscli_yamlhelper.py, **init**.py). Verify all modified files compile without errors using `python -m py_compile`.
  * [x] 1.1 Add "why" comments to `runway/cfngin/plan.py` (Plan, Step, Graph classes)
  * [x] 1.2 Add "why" comments to `runway/cfngin/stack.py` (Stack abstraction)
  * [x] 1.3 Add "why" comments to `runway/cfngin/cfngin.py` (main entry point)
  * [x] 1.4 Add "why" comments to `runway/cfngin/utils.py` (shared utilities)
  * [x] 1.5 Add "why" comments to `runway/cfngin/environment.py` (environment resolution)
  * [x] 1.6 Add "why" comments to `runway/cfngin/status.py`, `runway/cfngin/exceptions.py`, `runway/cfngin/session_cache.py`
  * [x] 1.7 Add "why" comments to `runway/cfngin/ui.py`, `runway/cfngin/tokenize_userdata.py`, `runway/cfngin/awscli_yamlhelper.py`, `runway/cfngin/__init__.py`
  * [x] 1.8 Verify all modified cfngin core files compile without errors

* [x] 2. Add "why" comments to cfngin actions [depends on: 1]
  Add rationale-focused comments to the action implementations (base.py, deploy.py, destroy.py, diff.py, graph.py, info.py, init.py) explaining why each action exists and how it fits into the deploy/destroy lifecycle.
  * [x] 2.1 Add "why" comments to `runway/cfngin/actions/base.py` and `runway/cfngin/actions/__init__.py`
  * [x] 2.2 Add "why" comments to `runway/cfngin/actions/deploy.py` and `runway/cfngin/actions/destroy.py`
  * [x] 2.3 Add "why" comments to `runway/cfngin/actions/diff.py`, `runway/cfngin/actions/graph.py`, `runway/cfngin/actions/info.py`, `runway/cfngin/actions/init.py`
  * [x] 2.4 Verify all modified action files compile without errors

* [x] 3. Add "why" comments to cfngin providers [depends on: 1]
  Add rationale-focused comments to the provider layer (base.py, aws/default.py) explaining the abstraction boundary between cfngin and AWS APIs.
  * [x] 3.1 Add "why" comments to `runway/cfngin/providers/__init__.py` and `runway/cfngin/providers/base.py`
  * [x] 3.2 Add "why" comments to `runway/cfngin/providers/aws/__init__.py` and `runway/cfngin/providers/aws/default.py`
  * [x] 3.3 Verify all modified provider files compile without errors

* [x] 4. Add "why" comments to cfngin hooks (core) [depends on: 1]
  Add rationale-focused comments to the core hook files: base.py, protocols.py, utils.py, acm.py, aws_lambda.py, cleanup_s3.py, cleanup_ssm.py, command.py, ecs.py, iam.py, keypair.py, route53.py.
  * [x] 4.1 Add "why" comments to `runway/cfngin/hooks/__init__.py`, `runway/cfngin/hooks/base.py`, `runway/cfngin/hooks/protocols.py`, `runway/cfngin/hooks/utils.py`
  * [x] 4.2 Add "why" comments to `runway/cfngin/hooks/acm.py`, `runway/cfngin/hooks/aws_lambda.py`, `runway/cfngin/hooks/cleanup_s3.py`, `runway/cfngin/hooks/cleanup_ssm.py`
  * [x] 4.3 Add "why" comments to `runway/cfngin/hooks/command.py`, `runway/cfngin/hooks/ecs.py`, `runway/cfngin/hooks/iam.py`, `runway/cfngin/hooks/keypair.py`, `runway/cfngin/hooks/route53.py`
  * [x] 4.4 Verify all modified core hook files compile without errors

* [x] 5. Add "why" comments to cfngin hooks (awslambda subsystem) [depends on: 4]
  Add rationale-focused comments to the AWS Lambda hook subsystem explaining the packaging and deployment pipeline: base_classes.py, _python_hooks.py, deployment_package.py, docker.py, source_code.py, models/, python_requirements/.
  * [x] 5.1 Add "why" comments to `runway/cfngin/hooks/awslambda/__init__.py`, `base_classes.py`, `_python_hooks.py`
  * [x] 5.2 Add "why" comments to `runway/cfngin/hooks/awslambda/deployment_package.py`, `docker.py`, `source_code.py`
  * [x] 5.3 Add "why" comments to `runway/cfngin/hooks/awslambda/constants.py`, `exceptions.py`, `type_defs.py`
  * [x] 5.4 Add "why" comments to `runway/cfngin/hooks/awslambda/models/` (all files)
  * [x] 5.5 Add "why" comments to `runway/cfngin/hooks/awslambda/python_requirements/` (all files)
  * [x] 5.6 Verify all modified awslambda hook files compile without errors

* [x] 6. Add "why" comments to cfngin hooks (docker, ecr, ssm, staticsite) [depends on: 4]
  Add rationale-focused comments to docker/, ecr/, ssm/, and staticsite/ hook subsystems.
  * [x] 6.1 Add "why" comments to `runway/cfngin/hooks/docker/` (all files including image/ subdir)
  * [x] 6.2 Add "why" comments to `runway/cfngin/hooks/ecr/` and `runway/cfngin/hooks/ssm/` (all files)
  * [x] 6.3 Add "why" comments to `runway/cfngin/hooks/staticsite/` (top-level files)
  * [x] 6.4 Add "why" comments to `runway/cfngin/hooks/staticsite/auth_at_edge/` (all files)
  * [x] 6.5 Verify all modified hook files compile without errors

* [x] 7. Add "why" comments to cfngin lookups [depends on: 1]
  Add rationale-focused comments to the lookup system: registry.py and all handler files (ami.py, awslambda.py, default.py, dynamodb.py, envvar.py, file.py, hook_data.py, kms.py, output.py, rxref.py, split.py, xref.py).
  * [x] 7.1 Add "why" comments to `runway/cfngin/lookups/__init__.py` and `runway/cfngin/lookups/registry.py`
  * [x] 7.2 Add "why" comments to `runway/cfngin/lookups/handlers/__init__.py`, `default.py`, `output.py`, `rxref.py`, `xref.py`
  * [x] 7.3 Add "why" comments to `runway/cfngin/lookups/handlers/ami.py`, `awslambda.py`, `dynamodb.py`, `envvar.py`
  * [x] 7.4 Add "why" comments to `runway/cfngin/lookups/handlers/file.py`, `hook_data.py`, `kms.py`, `split.py`
  * [x] 7.5 Verify all modified lookup files compile without errors

* [x] 8. Add "why" comments to cfngin blueprints and DAG [depends on: 1]
  Add rationale-focused comments to the blueprint system (base.py, cfngin_bucket.py, raw.py, testutil.py, variables/) and DAG implementation.
  * [x] 8.1 Add "why" comments to `runway/cfngin/blueprints/__init__.py`, `base.py`, `cfngin_bucket.py`
  * [x] 8.2 Add "why" comments to `runway/cfngin/blueprints/raw.py`, `testutil.py`, `type_defs.py`
  * [x] 8.3 Add "why" comments to `runway/cfngin/blueprints/variables/__init__.py` and `types.py`
  * [x] 8.4 Add "why" comments to `runway/cfngin/dag/__init__.py` and `runway/cfngin/logger/__init__.py`
  * [x] 8.5 Verify all modified blueprint/DAG files compile without errors

* [x] 9. Add "why" comments to cfngin unit tests (core) [depends on: 1, 2, 3]
  Add rationale-focused comments to the core cfngin test files explaining what behaviors and invariants are being validated and why those scenarios matter.
  * [x] 9.1 Add "why" comments to `tests/unit/cfngin/conftest.py` and `tests/unit/cfngin/factories.py`
  * [x] 9.2 Add "why" comments to `tests/unit/cfngin/test_plan.py` and `tests/unit/cfngin/test_stack.py`
  * [x] 9.3 Add "why" comments to `tests/unit/cfngin/test_cfngin.py` and `tests/unit/cfngin/test_utils.py`
  * [x] 9.4 Add "why" comments to `tests/unit/cfngin/test_environment.py`, `test_exceptions.py`, `test_dag.py`, `test_tokenize_userdata.py`
  * [x] 9.5 Verify all modified test files compile without errors

* [x] 10. Add "why" comments to cfngin unit tests (actions, providers, lookups, blueprints) [depends on: 2, 3, 7, 8]
  Add rationale-focused comments to test files in tests/unit/cfngin/actions/, providers/, lookups/, blueprints/.
  * [x] 10.1 Add "why" comments to all test files in `tests/unit/cfngin/actions/`
  * [x] 10.2 Add "why" comments to all test files in `tests/unit/cfngin/providers/`
  * [x] 10.3 Add "why" comments to all test files in `tests/unit/cfngin/lookups/`
  * [x] 10.4 Add "why" comments to all test files in `tests/unit/cfngin/blueprints/`
  * [x] 10.5 Verify all modified test files compile without errors

* [x] 11. Add "why" comments to cfngin unit tests (hooks) [depends on: 4, 5, 6]
  Add rationale-focused comments to all test files in tests/unit/cfngin/hooks/.
  * [x] 11.1 Add "why" comments to all test files in `tests/unit/cfngin/hooks/`
  * [x] 11.2 Verify all modified hook test files compile without errors

* [x] 12. Final verification [depends on: 9, 10, 11]
  Run the full cfngin test suite to confirm no regressions from added comments.
  * [x] 12.1 Run `python -m pytest tests/unit/cfngin/ -x` and confirm all tests pass
  * [x] 12.2 Spot-check 5 representative files to ensure comments explain "why" not "what"

## Task dependency graph

```json
{
  "waves": [
    { "wave": 1, "tasks": [1] },
    { "wave": 2, "tasks": [2, 3, 4, 7, 8] },
    { "wave": 3, "tasks": [5, 6, 9] },
    { "wave": 4, "tasks": [10, 11] },
    { "wave": 5, "tasks": [12] }
  ],
  "dependencies": {
    "2": [1],
    "3": [1],
    "4": [1],
    "5": [4],
    "6": [4],
    "7": [1],
    "8": [1],
    "9": [1, 2, 3],
    "10": [2, 3, 7, 8],
    "11": [4, 5, 6],
    "12": [9, 10, 11]
  }
}
```

## Notes

* Skip trivial dunder methods (**repr**, **str**, **len**, **hash**, **eq**) and simple property getters with no logic.
* Augment existing docstrings with a "why" sentence appended to the description paragraph. Do not remove or reword existing text.
* Use `#` comments for complex block rationale (placed on the line above the code block).
* Keep all comments to 1-3 sentences maximum.
* When purpose is ambiguous, use hedging language ("Likely handles...", "Appears to guard against...").
* Do NOT modify any executable code, imports, type annotations, or existing docstring content.
