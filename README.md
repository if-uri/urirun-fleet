# urirun-fleet

Fleet reconciliation for URI nodes — a lightweight control loop so **a stale node never
counts as usable**. The host knows the *desired* state; each node reports its *actual*
state; the fleet computes drift, classifies readiness, and **gates task execution on
`ready`**, never on `online`.

```
desired state  →  actual state  →  diff  →  reconcile plan  →  smoke  →  ready?  →  run task
   (host)          (node/health)   (drift)   (node:// URIs)    (verify)   (gate)
```

## The readiness ladder (`status.py`)

A node climbs: `offline → online → enrolled → routable → compatible → ready`. Two
off-ladder states capture "reachable but not usable": **`stale`** (version/scheme/registry
drift) and **`blocked`** (needs a human, e.g. enrollment). The host runs tasks **only on
`ready`**.

## Modules

| module | role |
|--------|------|
| `desired_state.py` | parse the fleet spec (YAML/JSON) → per-node desired dict |
| `actual_state.py`  | normalize a node's `/health` + `/routes` (+ optional runtime state); `probe()` fetches it live |
| `diff.py`          | desired − actual → typed drift, each with its `node://` remedy; `auto` vs `blocked` severity |
| `status.py`        | classify (actual, desired, drift, smoke) → one `Readiness` with a `runnable` gate |
| `smoke.py`         | required-route presence + optional live read-only checks — turns `compatible` into `ready` |
| `reconciler.py`    | ordered dry-run `plan()` (deduped), the `run_allowed()` preflight gate, and `assess()`/`assess_live()` |
| `capabilities.py`  | capability groups (`any_of` route globs) — require an ability, not a bare scheme |
| `executor.py`      | run the plan via an injected `call`, re-probe after each change, roll back on failure; **never runs a blocked plan** |
| `node_client.py`   | authenticated HTTP transport to a node (`probe`, `call` /run with token/signature) |
| `events.py`        | append-only JSONL event log (`fleet.reconcile.started` … `node.ready|degraded`) |
| `rollout.py`       | atomic releases: build off to the side, smoke, then flip `current` symlink; `rollback()` |
| `cli.py`           | `urirun-fleet status|diff|reconcile|enroll` (+ `--execute`, `--json`, `--trace-out`) |

## Use

```bash
urirun-fleet diff      --fleet examples/fleet.yaml --nodes ~/.urirun/nodes.json
urirun-fleet reconcile --fleet examples/fleet.yaml --nodes ~/.urirun/nodes.json --node lenovo
urirun-fleet reconcile --fleet examples/fleet.yaml --nodes ~/.urirun/nodes.json --node lenovo --execute
urirun-fleet enroll    --fleet examples/fleet.yaml --nodes ~/.urirun/nodes.json --node lenovo
```

Reconcile prints the ordered plan (`upgrade → connector install → registry rebuild →
restart → smoke`) — a code change **always** appends restart + smoke, because a warm
worker keeps stale imports until the process restarts.

`--execute` runs the plan through a `NodeClient`, logging a JSONL trace. Hard rules:
default is dry-run; a **blocked** plan (e.g. enrollment needed) is refused; the executor
re-probes after each change and rolls back on failure. Enroll first, then reconcile.

## Status

Implemented and tested (23 tests, all functions ≤15 cyclomatic): desired/actual/diff/
status/smoke/capabilities/reconcile-plan + preflight gate + **execute mode** (executor,
node_client, events, aliases, capability groups) + **atomic releases** (rollout: switch/
rollback/deploy-with-smoke). Live `diff`/`reconcile`/`--execute` verified against lenovo
(correctly **blocked** on enrollment → execution refused). **Next:** the node-side backend
for the `node://` management URIs (upgrade/install/rebuild/restart/smoke) that this
orchestrates — `node.sh --doctor` already implements most of that logic locally.

Part of the ifURI solution · Author: Tom Sapletta · Apache-2.0
