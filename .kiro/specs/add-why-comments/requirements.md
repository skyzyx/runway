# Requirements: Add "Why" Comments to Python Codebase (Phase 1: cfngin)

## Overview

Add rationale-focused comments ("why" comments) to the `runway/cfngin/` subpackage and its corresponding tests. These comments explain the purpose, intent, and design rationale behind functions, methods, classes, and complex code blocks — not what the code does, but why it exists and why it takes the approach it does.

This is Phase 1 of a multi-phase effort. The cfngin subpackage is the largest and most complex module (109 source files), making it the highest-value target.

## Scope

* **In scope**: All `.py` files under `runway/cfngin/` and their corresponding tests under `tests/unit/cfngin/`.
* **Out of scope**: All other `runway/` subpackages, non-Python files, documentation, configuration files, and `typings/`. These will be covered in future phases.

## Functional requirements

### REQ-1: Function/Method-Level "Why" comments

**MUST** add rationale to every non-trivial function and method explaining **why** it exists — its purpose in the system, the problem it solves, or the design decision it represents.

* Trivial methods (e.g., `__repr__`, `__str__`, `__len__`, `__hash__`, `__eq__`, simple property getters that return a stored value with no logic) **SHOULD** be skipped.
* Existing docstrings that already describe "what" **MUST** be augmented with an additional "why" sentence appended to the description paragraph. The existing description text must not be removed or reworded.
* For functions without a docstring, add a docstring with the "why" rationale.

### REQ-2: Class-Level "Why" comments

**MUST** add a rationale comment to every class explaining why this abstraction exists, what design pattern it implements (if applicable), and how it fits into the broader architecture.

### REQ-3: complex block comments

**MUST** add inline `#` comments before or within complex code blocks (3+ lines of non-obvious logic) explaining **why** that approach was chosen. Examples:

* Workarounds for library bugs or API quirks
* Performance-motivated patterns (e.g., caching, batching)
* Security considerations (e.g., input validation, escaping)
* Order-dependent operations where reordering would break something
* Regex patterns and their purpose
* Try/except blocks that handle specific edge cases

### REQ-4: test file comments

**MUST** add comments to test functions and test classes explaining:

* What behavior or invariant the test validates
* Why this particular scenario is important to test (edge case, regression, etc.)
* For parameterized tests: why these specific parameter combinations matter

### REQ-5: comment style consistency

**MUST** follow these conventions:

* Use `#` comments for block-level rationale (placed on the line above the code)
* Use docstring additions for function/class-level rationale
* Keep comments concise: 1-3 sentences max per comment
* Write in present tense, active voice
* Do NOT describe what the code does — only why

### REQ-6: preserve existing code

**MUST NOT** modify any executable code, imports, type annotations, or existing docstring content. Only additions of comments are permitted.

## Non-Functional requirements

### REQ-7: subpackage ordering within cfngin

Work should proceed in this order within `runway/cfngin/`:

1. Top-level cfngin files (`plan.py`, `stack.py`, `cfngin.py`, `utils.py`, `environment.py`, etc.)
2. `runway/cfngin/actions/` — action implementations
3. `runway/cfngin/providers/` — AWS provider layer
4. `runway/cfngin/hooks/` — lifecycle hooks
5. `runway/cfngin/lookups/` — lookup handlers
6. `runway/cfngin/blueprints/` — CloudFormation blueprints
7. `runway/cfngin/dag/` — DAG implementation
8. `runway/cfngin/logger/` — logging utilities
9. Corresponding test files in `tests/unit/cfngin/`

### REQ-8: accuracy of rationale

Comments **MUST** accurately reflect the code's actual purpose. When the rationale is uncertain, the comment should note the most likely intent based on context (e.g., "Likely handles the case where..." or "Appears to guard against...") rather than guessing definitively.

### REQ-9: no breaking changes

All existing tests must continue to pass after comments are added. Comments must not introduce syntax errors or change program behavior.
