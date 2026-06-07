---
inclusion: manual
---

# KiroGraph: Debug Workflow

Follow these steps to systematically trace and debug issues using the knowledge graph.

## Steps

1. **Find related code**
   ```
   kirograph_search(query: "<error message or symptom keywords>")
   ```

2. **Get full context**
   ```
   kirograph_context(task: "<describe the bug>")
   ```

3. **Trace the call chain**
   ```
   kirograph_callers(symbol: "<suspected function>")
   kirograph_callees(symbol: "<suspected function>")
   ```

4. **Check what changed recently**
   ```
   kirograph_diff()
   ```

5. **Understand blast radius**
   ```
   kirograph_impact(symbol: "<root cause symbol>", depth: 3)
   ```

## Tips
- Check both callers and callees to understand the full context
- Recent changes (via diff) are the most common source of new issues
- Use `kirograph_path` to trace how two symbols are connected
