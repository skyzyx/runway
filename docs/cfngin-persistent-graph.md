# CFNgin Persistent Graph

## Overview

The Persistent Graph is a state-tracking mechanism that allows CFNgin to
remember which CloudFormation stacks it has deployed across invocations. By
storing a JSON representation of the dependency graph in S3, CFNgin can detect
stacks that have been removed from configuration and automatically destroy them
during the next deploy, keeping deployed infrastructure in sync with the
declared configuration.

Without a persistent graph, removing a stack definition from your config file
leaves the CloudFormation stack orphaned in AWS. With the persistent graph
enabled, CFNgin compares the stored graph against the current config, identifies
removed stacks, and schedules their destruction in the correct dependency order.

## Enabling the feature

Add the `persistent_graph_key` option to your CFNgin configuration file:

```yaml
namespace: my-app
cfngin_bucket: my-cfngin-bucket
persistent_graph_key: my-app-graph

stacks:
  - name: vpc
    template_path: templates/vpc.yaml
  - name: database
    template_path: templates/database.yaml
    requires:
      - vpc
```

### Configuration requirements

* **`namespace`** (required): The namespace isolates graph storage so multiple
  CFNgin configurations can share the same S3 bucket without collisions.
* **`cfngin_bucket`** (required): The S3 bucket where CFNgin stores compiled
  templates and persistent graph state. If set to an empty string, S3 upload
  and persistent graph functionality are disabled.
* **`persistent_graph_key`** (required): The key name for the S3 object. A
  `.json` extension is appended automatically if not provided.

## How it works

### S3 storage format

The persistent graph is stored as a JSON object in S3 at:

```text
s3://{cfngin_bucket}/persistent_graphs/{namespace}/{persistent_graph_key}.json
```

The JSON structure maps each stack name to an array of its dependency names:

```json
{
  "vpc": [],
  "database": ["vpc"],
  "app-server": ["vpc", "database"]
}
```

When the graph is empty (all stacks destroyed), the S3 object is deleted
rather than storing an empty JSON object.

### Bucket requirements

When persistent graph is enabled, CFNgin checks the S3 bucket for recommended
settings:

* **Versioning** should be enabled. CFNgin logs a warning if versioning is
  disabled, since versioned objects provide a recovery path if the graph state
  is corrupted.
* **MFADelete** must be disabled. CFNgin needs to modify and delete the graph
  object without MFA challenges.

If the bucket does not exist and CFNgin is allowed to create it, versioning is
automatically enabled on the new bucket.

## Locking mechanism

The persistent graph uses S3 object tagging as a distributed lock to prevent
concurrent CFNgin runs from corrupting shared state.

### How locking works

1. Before executing a plan, CFNgin generates a UUID (the plan ID) as the lock
   code.
2. It writes a tag (`cfngin_lock_code={uuid}`) to the S3 object.
3. During execution, any updates to the graph require the lock code to match.
4. After execution completes (or fails), the tag is removed to unlock the
   graph.

### Lock enforcement rules

* **Deploy and Destroy** actions lock the graph before execution and unlock it
  in a `finally` block, ensuring the lock is always released.
* **Diff and Graph** actions pass `require_unlocked=False` because they are
  read-only operations that should not be blocked by another session's lock.
* If a plan attempts to execute while the graph is locked by a different
  session, a `PersistentGraphLocked` exception is raised.

### Lock-related exceptions

| Exception                         | Meaning                                                            |
|-----------------------------------|--------------------------------------------------------------------|
| `PersistentGraphLocked`           | The graph is locked by another session; cannot proceed             |
| `PersistentGraphUnlocked`         | Attempted to update the graph without holding the lock             |
| `PersistentGraphCannotLock`       | The S3 object does not exist; locking impossible                   |
| `PersistentGraphCannotUnlock`     | Cannot unlock (not locked, or code mismatch)                       |
| `PersistentGraphLockCodeMismatch` | The provided lock code does not match the one stored on the object |

### Manual recovery

If a CFNgin run is interrupted (process killed, network failure) without
releasing the lock, subsequent runs will fail with `PersistentGraphLocked`.
To recover, manually remove the `cfngin_lock_code` tag from the S3 object:

```bash
aws s3api delete-object-tagging \
  --bucket my-cfngin-bucket \
  --key persistent_graphs/my-app/my-app-graph.json
```

## Deploy action behavior

When the persistent graph is enabled, the deploy action performs additional
reconciliation logic:

1. **Load the persistent graph** from S3 (or create an empty one if the object
   does not exist).
2. **Compare** stacks in the persistent graph against stacks in the current
   configuration.
3. **Identify removed stacks**: any stack present in the persistent graph but
   absent from the current config is scheduled for destruction.
4. **Build a merged plan** containing both deploy steps (for current stacks)
   and destroy steps (for removed stacks), with correct dependency ordering.
5. **Lock** the persistent graph.
6. **Execute** the plan. After each step completes:
   * If a stack was successfully launched → add it to the persistent graph.
   * If a stack was successfully destroyed → remove it from the persistent
     graph.
   * Upload the updated graph to S3 after each mutation.
7. **Unlock** the persistent graph.

### Dependency ordering for removals

When stacks are removed from config, their destruction must happen in reverse
dependency order (dependents are destroyed before their dependencies). The
deploy action transposes the persistent graph to determine this ordering,
ensuring that a stack like `app-server` (which depends on `database`) is
destroyed before `database`.

### Example scenario

Given the persistent graph contains:

```json
{
  "vpc": [],
  "database": ["vpc"],
  "app-server": ["vpc", "database"]
}
```

And the current config only defines `vpc` and `database`, CFNgin will:

1. Detect that `app-server` is missing from the config.
2. Schedule `app-server` for destruction.
3. Deploy/update `vpc` and `database` as normal.
4. Destroy `app-server` in CloudFormation.
5. Remove `app-server` from the persistent graph and upload the updated state.

## Destroy action behavior

The destroy action includes the persistent graph in its plan by merging it
with the local graph. This ensures that stacks tracked remotely (which may
no longer appear in the local config) are included in the destruction plan.

The destroy action:

1. Generates a plan with `include_persistent_graph=True` and `reverse=True`.
2. Merges stacks from the persistent graph into the plan.
3. Locks the persistent graph.
4. Executes the plan in reverse-dependency order (dependents first).
5. Unlocks the persistent graph.

## Diff action behavior

The diff action includes the persistent graph for completeness but operates
in read-only mode:

* It passes `require_unlocked=False` so it is never blocked by a lock held
  by a concurrent deploy or destroy.
* Stacks in the persistent graph that do not exist in CloudFormation are
  reported with a "will be removed" skip status.
* Stacks scheduled for destruction (no blueprint class) are reported with a
  "will be destroyed" skip status.

## Graph action behavior

The graph visualization action merges the persistent graph with the local
graph to show the complete picture of managed stacks. It supports output in
DOT (graphviz) and JSON formats and optionally performs transitive reduction
for cleaner visual output.

## Step lifecycle and persistent graph updates

The `Plan.walk` method handles updating the persistent graph after each step
completes:

```text
For each step in the DAG (topological order):
  1. Check if any upstream dependency failed → fail this step
  2. Execute the step function (poll until terminal status)
  3. If step completed successfully:
     - If step function was _destroy_stack → remove from persistent graph
     - If step function was _launch_stack → add to persistent graph
     - Upload updated graph to S3
```

This per-step update strategy ensures that even if a plan fails partway
through, the persistent graph accurately reflects which stacks exist in AWS.

## Architecture summary

### Key components

| Component                                 | Role                                                      |
|-------------------------------------------|-----------------------------------------------------------|
| `CfnginConfig.persistent_graph_key`       | Config option enabling the feature                        |
| `CfnginContext.persistent_graph`          | Property that fetches/creates the graph from S3           |
| `CfnginContext.persistent_graph_location` | Computes the S3 bucket and key path                       |
| `CfnginContext.lock_persistent_graph`     | Acquires the distributed lock via S3 tagging              |
| `CfnginContext.unlock_persistent_graph`   | Releases the lock                                         |
| `CfnginContext.put_persistent_graph`      | Uploads the current graph state to S3                     |
| `Graph`                                   | DAG wrapper with serialization (`dumps`, `from_dict`)     |
| `Graph.add_step_if_not_exists`            | Safe merge for persistent graph entries                   |
| `Step.from_persistent_graph`              | Creates Step objects from serialized graph dict           |
| `Step.from_stack_name`                    | Creates a lightweight "fake" Stack for graph-only entries |
| `merge_graphs`                            | Combines local and persistent graphs                      |
| `Plan.walk`                               | Executes steps and updates persistent graph per-step      |
| `Plan.lock_code`                          | Plan UUID used as the lock/unlock credential              |

### Data flow

```text
┌──────────────────────┐
│   CFNgin Config      │
│ persistent_graph_key │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐       ┌─────────────────────────────────┐
│   CfnginContext      │◄─────►│  S3 Bucket                      │
│                      │       │  persistent_graphs/{ns}/{key}    │
│  .persistent_graph   │       │                                  │
│  .lock_persistent_   │       │  Tags: cfngin_lock_code={uuid}   │
│   graph()            │       └─────────────────────────────────┘
│  .put_persistent_    │
│   graph()            │
│  .unlock_persistent_ │
│   graph()            │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│      Plan            │
│                      │
│  .execute() / .walk()│──► Updates graph after each step
│  .lock_code          │
└──────────────────────┘
```

## Limitations and considerations

* **Single-writer**: The locking mechanism serializes graph modifications but
  does not support multi-writer concurrency. Only one deploy or destroy action
  can modify the graph at a time.
* **Stale locks**: If a process is killed without unlocking, manual tag removal
  is required. There is no TTL or automatic expiration.
* **S3 eventual consistency**: While S3 now provides strong read-after-write
  consistency, the tagging-based lock is not a true distributed lock primitive.
  It is sufficient for preventing accidental concurrent runs but should not be
  relied upon for strict mutual exclusion in high-contention environments.
* **No cross-config awareness**: Each CFNgin config file has its own persistent
  graph scoped by namespace and key. There is no built-in mechanism to track
  dependencies across separate config files.
* **Empty graph cleanup**: When all stacks are destroyed, the S3 object is
  deleted rather than left as an empty JSON file. The next deploy will
  recreate it.
