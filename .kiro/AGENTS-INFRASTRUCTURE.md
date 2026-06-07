# Agent Infrastructure

This document describes the hooks, steering files, custom agents, and MCP servers configured in this workspace. Reference this when you need to understand how automated behaviors work or how to extend them.

## Steering files

Steering files live in `.kiro/steering/` and inject context into agent sessions. They use front matter to control when they activate.

| File                         | Inclusion | Purpose                                |
|------------------------------|-----------|----------------------------------------|
| `core-premises.md`           | always    | Four cardinal rules for all work       |
| `python-code-conventions.md` | fileMatch | Python style + Zuban type checking     |
| `markdown-style.md`          | fileMatch | Markdown lint rules from `.rumdl.toml` |
| `kirograph.md`               | always    | Kirograph tool reference               |
| `kirograph-review.md`        | manual    | Code review workflow                   |
| `kirograph-debug.md`         | manual    | Debugging workflow                     |
| `kirograph-onboard.md`       | manual    | Codebase onboarding workflow           |
| `kirograph-refactor.md`      | manual    | Safe refactoring workflow              |
| `kirograph-architecture.md`  | manual    | Architecture analysis workflow         |
| `kirograph-security.md`      | manual    | Security audit workflow                |

### Inclusion modes

* **always** — injected into every agent session automatically.
* **fileMatch** — injected when a file matching the `fileMatchPattern` glob is read into context (e.g., `**/*.py` triggers `python-code-conventions.md`).
* **manual** — only injected when a user explicitly provides it via `#` context key or the agent reads it directly.

### Core premises (always active)

1. Don't assume. Don't hide confusion. Surface tradeoffs.
2. Minimum code that solves the problem. Nothing speculative.
3. Touch only what you must. Clean up only your own mess.
4. Define success criteria. Loop until verified.

## Hooks

Hooks live in `.kiro/hooks/` and trigger automated agent behaviors on IDE events.

| Hook file                           | Event      | Action     | Purpose                        |
|-------------------------------------|------------|------------|--------------------------------|
| `kirograph-compress-hint.kiro.hook` | preToolUse | askAgent   | Remind to use `kirograph_exec` |
| `kirograph-mem-capture.kiro.hook`   | agentStop  | askAgent   | Store session learnings        |
| `kirograph-sync-if-dirty.kiro.hook` | agentStop  | runCommand | Sync Kirograph index           |

### Compression hint hook

Fires before any `shell` tool use. Reminds the agent to use `kirograph_exec` instead of raw bash for git, test, lint, build, and similar commands. This saves 60–90% of output tokens via intelligent compression.

> [!IMPORTANT]
> This hook intercepts tool calls but does NOT block them. The agent should evaluate whether `kirograph_exec` is appropriate and proceed accordingly. For commands where you need full uncompressed output (e.g., writing results to a file), the raw shell tool is still valid.

### Memory capture hook

Fires when the agent stops. Prompts the agent to store important observations (decisions, errors, patterns, architecture insights) using `kirograph_mem_store`. This builds persistent project memory across sessions.

### Sync hook

Fires when the agent stops. Runs `kirograph sync --quiet` to update the Kirograph index with any file changes made during the session.

## Custom agents

Defined in `.kiro/agents/`.

### Kirograph agent (`kirograph.json`)

A Kirograph-aware agent with access to all Kirograph MCP tools. It registers the steering workflow files as resources and syncs the index on spawn, prompt submit, and stop.

Activate workflow modes by reading the corresponding steering file:

* `/kirograph-review` — code review workflow
* `/kirograph-debug` — debugging/root-cause workflow
* `/kirograph-architecture` — architecture analysis
* `/kirograph-onboard` — codebase onboarding
* `/kirograph-refactor` — safe refactoring
* `/kirograph-security` — security audit (requires `enableSecurity` in config)

## MCP servers

Configured in `.kiro/settings/mcp.json`.

### Kirograph (`kirograph serve --mcp`)

A semantic code knowledge graph. Provides 50+ tools for symbol search, call graphs, impact analysis, architecture metrics, dead code detection, security scanning, data querying, documentation search, and persistent memory.

All Kirograph tools are auto-approved (no confirmation needed).

Key tools for daily work:

| Task                          | Tool                   |
|-------------------------------|------------------------|
| Start any code task           | `kirograph_context`    |
| Find a symbol                 | `kirograph_search`     |
| Read a symbol's code          | `kirograph_node`       |
| Who calls X?                  | `kirograph_callers`    |
| What does X call?             | `kirograph_callees`    |
| Blast radius of changing X    | `kirograph_impact`     |
| Run commands with compression | `kirograph_exec`       |
| Recall past decisions         | `kirograph_mem_search` |
| Store a learning              | `kirograph_mem_store`  |

## Creating new hooks

To add a new hook, create a `.kiro.hook` file in `.kiro/hooks/` following this schema:

```json
{
  "name": "Hook Name",
  "version": "1.0.0",
  "description": "What this hook does",
  "when": {
    "type": "eventType",
    "patterns": ["*.ts"],
    "toolTypes": ["write"]
  },
  "then": {
    "type": "askAgent | runCommand",
    "prompt": "For askAgent",
    "command": "For runCommand"
  }
}
```

Valid event types: `fileEdited`, `fileCreated`, `fileDeleted`, `userTriggered`, `promptSubmit`, `agentStop`, `preToolUse`, `postToolUse`, `preTaskExecution`, `postTaskExecution`.

## Creating new steering files

Add a `.md` file to `.kiro/steering/` with appropriate front matter:

```markdown
---
inclusion: always | fileMatch | manual
fileMatchPattern: "**/*.py"
---

# Your Steering Content
```

Use `always` sparingly — it consumes tokens on every session. Prefer `fileMatch` for language-specific guidance or `manual` for workflow guides.
