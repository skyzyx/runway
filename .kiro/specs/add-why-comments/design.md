# Design: Add "Why" Comments to cfngin Subpackage

## Approach

### Comment placement strategy

**Function/Method-level rationale** — augment existing docstrings by appending a "why" sentence after the existing description line(s), before Args/Returns/Raises sections:

```python
def resolve(self, context, provider=None, variables=None, **kwargs):
    """Resolve the variable value.

    This enables late-binding of configuration values so that cross-stack
    references and dynamic lookups can be evaluated at deploy time rather
    than parse time.

    Args:
        context: The current context object.
        ...
    """
```

**Class-level rationale** — augment the class docstring with architectural context:

```python
class Step:
    """State machine for executing generic actions related to stacks.

    Encapsulates the lifecycle of a single stack operation (create/update/delete)
    as a state machine, allowing the DAG-based plan executor to poll for completion
    without blocking other independent stack operations.

    Attributes:
        ...
    """
```

**Complex block rationale** — use `#` comments on the line(s) above:

```python
# Guard against transitive dependency failures: if any upstream stack
# failed, this stack cannot proceed since its inputs may be invalid.
for dep in self.graph.downstream(step.name):
    if not dep.ok:
        step.set_status(FailedStatus("dependency has failed"))
        return step.ok
```

### What qualifies as "Non-Trivial"

A function/method is non-trivial if any of:

* It contains conditional logic, loops, or exception handling
* It coordinates multiple operations
* It implements a design pattern or architectural boundary
* Its name alone doesn't explain why it exists in the architecture
* It's a public API method

A function IS trivial (skip commenting) if ALL of:

* It's a dunder method that's a standard Python protocol (`__repr__`, `__str__`, `__len__`, `__hash__`, `__eq__`, `__iter__`)
* It contains a single return/yield statement with no logic
* Its behavior is obvious from the method signature alone

### What qualifies as a "Complex block"

A code block warrants a "why" comment if:

* It's 3+ lines of related logic that aren't self-documenting
* It uses regex patterns
* It contains workarounds (try/except for known issues, API quirks)
* It has order-dependent operations
* It implements non-obvious algorithms or optimizations
* It contains nested conditionals or loops

## File processing order

### Batch 1: core cfngin files (top-level)

* `runway/cfngin/plan.py` — Plan/Step/Graph orchestration
* `runway/cfngin/stack.py` — Stack abstraction
* `runway/cfngin/cfngin.py` — Main entry point
* `runway/cfngin/utils.py` — Shared utilities
* `runway/cfngin/environment.py` — Environment resolution
* `runway/cfngin/status.py` — Status codes
* `runway/cfngin/exceptions.py` — Exception definitions
* `runway/cfngin/session_cache.py` — AWS session caching
* `runway/cfngin/ui.py` — User interface output
* `runway/cfngin/tokenize_userdata.py` — EC2 userdata tokenization
* `runway/cfngin/awscli_yamlhelper.py` — YAML helper

### Batch 2: actions

* All files in `runway/cfngin/actions/`

### Batch 3: providers

* All files in `runway/cfngin/providers/`

### Batch 4: hooks

* All files in `runway/cfngin/hooks/`

### Batch 5: lookups

* All files in `runway/cfngin/lookups/`

### Batch 6: blueprints, DAG, logger

* All files in `runway/cfngin/blueprints/`
* All files in `runway/cfngin/dag/`
* All files in `runway/cfngin/logger/`

### Batch 7: corresponding tests

* All files in `tests/unit/cfngin/` that correspond to modified source files

## Verification strategy

After each batch:

1. Run `python -m py_compile` on modified files to ensure no syntax errors
2. Run existing tests for the modified module to confirm no breakage
3. Spot-check that comments explain "why" not "what"

## Risks and mitigations

| Risk                                               | Mitigation                                                                             |
|----------------------------------------------------|----------------------------------------------------------------------------------------|
| Incorrect rationale when code purpose is ambiguous | Use hedging language ("Likely...", "Appears to...") and note uncertainty               |
| Breaking syntax with malformed docstrings          | Compile-check every modified file                                                      |
| Overly verbose comments that reduce readability    | Enforce 1-3 sentence limit per comment                                                 |
| Comments that just restate the code                | Review checklist: does this comment add information beyond what the code already says? |
