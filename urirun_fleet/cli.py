# Author: Tom Sapletta · Part of the ifURI solution.
"""`urirun-fleet` CLI — status / diff / reconcile (dry-run) over a fleet desired-state.

    urirun-fleet status  --fleet fleet.yaml --nodes nodes.json
    urirun-fleet diff    --fleet fleet.yaml --nodes nodes.json
    urirun-fleet reconcile --fleet fleet.yaml --nodes nodes.json [--node lenovo]

``nodes.json`` maps node name → base URL (the host's ~/.urirun/nodes.json shape). The
reconcile subcommand prints the ordered plan; it does NOT execute yet (that lands when
the node:// upgrade/rebuild/restart URIs are wired end-to-end).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import desired_state, reconciler


def _node_urls(path: str) -> dict[str, str]:
    d = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    nodes = d.get("nodes") if isinstance(d, dict) and "nodes" in d else d
    out = {}
    for k, v in (nodes or {}).items():
        out[k] = v if isinstance(v, str) else (v or {}).get("url", "")
    return out


def _required_routes(desired: dict) -> list[str]:
    node = desired["node"]
    return [f"{s}://{node}/" for s in desired.get("require_schemes") or []]  # presence-by-scheme


def _execute(desired: dict, url: str, plan: dict, args) -> dict:
    """Run the reconcile plan via a NodeClient, logging a JSONL event trace. Hard rules:
    a blocked plan refuses; the executor re-probes after each change and rolls back on fail."""
    from . import events, executor, node_client
    if plan.get("blocked"):
        return {"ok": False, "refused": "plan is blocked (human action needed) — not executing"}
    node = desired["node"]
    run_id = "fleet-run-" + node
    log = events.EventLog(run_id, path=args.trace_out)
    log.emit("fleet.reconcile.started", node=node, drift=[d["kind"] for d in plan.get("drift") or []])
    client = node_client.NodeClient(url, node, token=args.token)
    rec = executor.execute(plan, client.call, on_event=log.sink(), probe=client.probe)
    log.emit("fleet.reconcile.finished", node=node, ok=rec["ok"], status=rec.get("status"))
    rec["trace"] = str(log.path)
    return rec


def _enroll(fleet: dict, urls: dict, targets: list) -> int:
    """Print the exact enrollment steps for each blocked node (human-in-the-loop flow)."""
    for name in targets:
        url = urls.get(name, "http://<node-ip>:8766")
        print(f"== enroll {name} ({url}) ==")
        print(f"  1. on the NODE, read the console token:  grep -i token ~/.urirun-node/node.log | tail -1")
        print(f"  2. on the HOST, enroll your key:         uri-copy-id {url} -t <TOKEN>")
        print(f"  3. then reconcile:                       urirun-fleet reconcile --node {name} --execute")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="urirun-fleet")
    ap.add_argument("cmd", choices=["status", "diff", "reconcile", "enroll"])
    ap.add_argument("--fleet", required=True, help="desired-state YAML/JSON")
    ap.add_argument("--nodes", required=True, help="node name → base URL map (nodes.json)")
    ap.add_argument("--node", help="limit to one node")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--execute", action="store_true",
                    help="reconcile: actually run the plan (needs an enrolled key/token; blocked plans refuse)")
    ap.add_argument("--token", help="admin token for node:// management routes")
    ap.add_argument("--trace-out", help="write the run's JSONL event log here")
    args = ap.parse_args(argv)

    fleet = desired_state.load(args.fleet)
    urls = _node_urls(args.nodes)
    targets = [args.node] if args.node else list(fleet)

    if args.cmd == "enroll":
        return _enroll(fleet, urls, targets)

    results = {name: _assess_one(fleet, urls, name, args) for name in targets}

    if args.json:
        print(json.dumps(results, indent=1, default=str))
        return 0 if all("error" not in r and r.get("run_allowed") for r in results.values()) else 1

    rc = 0
    for name, r in results.items():
        if not _print_node(name, r, args.cmd):
            rc = 1
    return rc


def _assess_one(fleet: dict, urls: dict, name: str, args) -> dict:
    desired = fleet.get(name)
    if not desired:
        return {"error": "not in desired-state"}
    url = urls.get(name)
    if not url:
        return {"error": "no URL in nodes map"}
    assessment = reconciler.assess_live(desired, url, required_routes=_required_routes(desired))
    if args.cmd == "reconcile" and args.execute:
        assessment["execution"] = _execute(desired, url, assessment["plan"], args)
    return assessment


def _print_node(name: str, r: dict, cmd: str) -> bool:
    """Print one node's result; return True if it is run-allowed (for the exit code)."""
    if "error" in r:
        print(f"  {name}: ERROR — {r['error']}")
        return False
    mark = "✓" if r["run_allowed"] else "✗"
    print(f"  {mark} {name}: {r['readiness']['status']}"
          + (f" ({r['run_reason']})" if not r["run_allowed"] else ""))
    if cmd in ("diff", "reconcile"):
        for d in r["drift"]:
            print(f"      drift [{d['severity']}] {d['kind']}: {d['detail']}  → {d['remedy_uri']}")
    if cmd == "reconcile":
        for s in r["plan"]["steps"]:
            print(f"      step {s['phase']}: {s['uri']}  ({s['for']})")
        if r["plan"]["blocked"]:
            print("      BLOCKED — needs a human before reconcile can proceed")
        _print_execution(r.get("execution"))
    return bool(r["run_allowed"])


def _print_execution(ex: dict | None) -> None:
    if not ex:
        return
    if ex.get("refused"):
        print(f"      execute: refused — {ex['refused']}")
        return
    print(f"      execute: {'ok' if ex.get('ok') else 'FAILED'} "
          f"status={ex.get('status')} rolledback={ex.get('rolledback')} trace={ex.get('trace')}")


if __name__ == "__main__":
    raise SystemExit(main())
