---
inclusion: manual
---

# KiroGraph: Code Review Workflow

Follow these steps for a structured, risk-aware code review using the knowledge graph.

## Steps

1. **Understand the change scope**
   ```
   kirograph_context(task: "<describe what changed>")
   ```

2. **Analyze blast radius**
   For each key symbol that was modified:
   ```
   kirograph_impact(symbol: "<changed symbol>", depth: 2)
   ```

3. **Check test coverage**
   ```
   kirograph_callers(symbol: "<changed symbol>")
   ```
   Look for test files among the callers. Flag untested changes.

4. **Look for surprising coupling**
   ```
   kirograph_surprising(limit: 10)
   ```

5. **Produce findings** grouped by risk level (high/medium/low) with:
   - What changed and why it matters
   - Test coverage status
   - Suggested improvements
   - Overall merge recommendation
