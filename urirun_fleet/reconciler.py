# Author: Tom Sapletta · Part of the ifURI solution.
"""Reconcile: desired − actual → an ORDERED plan of node:// commands, then verify.

The plan is pure data (dry-run by default) so it can be reviewed before anything runs.
Execution is deterministic and ends in a smoke test; a failed smoke means the caller
must roll back (the atomic-release switch lives in the node, not here). The preflight
gate — ``run_allowed`` — is the whole point: a task never runs on a non-ready node.
"""
from __future__ import annotations

from typing import Any, Callable

from . import actual_state as _actual
from . import diff as _diff
from . import smoke as _smoke
from . import status as _status

# drift kind → the phase it belongs to (ordered: fix code, then registry, then process)
_PHASE = {
    "runtime_drift": 1, "scheme_missing": 2, "connector_drift": 2, "capability_missing": 2,
    "registry_drift": 3, "enrollment_drift": 0, "node_name_drift": 0,
}


def plan(desired: dict, actual: dict) -> dict[str, Any]:
    """Dry-run: the drift and the ordered node:// commands that would reconcile it.

    Always appends a registry rebuild + restart + smoke after any code change, because a
    warm worker keeps stale imports until the process restarts (the #8 failure mode).

    The remedy URIs are all ``node://`` MANAGEMENT routes, which the node gates behind an
    enrolled key. So a plan with steps but no enrolled key (``key_count == 0``) is NOT
    executable — surfaced as a blocked ``management_locked`` entry so --execute refuses."""
    node = desired.get("node") or actual.get("node") or "node"
    drift = _diff.compare(desired, actual)
    auto = [d for d in drift if d.get("severity") == "auto"]
    blocked = [d for d in drift if d.get("severity") == "blocked"]

    steps: list[dict] = []
    seen: set = set()
    for d in sorted(auto, key=lambda x: _PHASE.get(x["kind"], 9)):
        uri = d["remedy_uri"]
        if uri in seen:  # dedupe identical remedies (e.g. two drifts → one connector install)
            continue
        seen.add(uri)
        steps.append({"phase": _PHASE.get(d["kind"], 9), "uri": uri, "for": d["kind"]})
    if auto:  # any code/registry change → rebuild, restart (drop stale imports), smoke
        steps.append({"phase": 4, "uri": f"node://{node}/registry/command/rebuild", "for": "post-change"})
        steps.append({"phase": 5, "uri": f"node://{node}/runtime/command/restart", "for": "drop-stale-workers"})
        steps.append({"phase": 6, "uri": f"node://{node}/smoke/command/run", "for": "verify"})

    blocked = _add_management_lock(node, steps, actual, blocked)

    return {
        "node": node,
        "drift": drift,
        "blocked": blocked,
        "steps": steps,
        "reconcilable": bool(auto) and not blocked,
        "clean": not drift,
    }


def _add_management_lock(node: str, steps: list, actual: dict, blocked: list) -> list:
    """node:// management needs an enrolled key — a plan we can't run is blocked, not runnable."""
    needs_key = bool(steps) and int(actual.get("key_count") or 0) == 0 and actual.get("reachable")
    if needs_key and not any(b.get("kind") == "enrollment_drift" for b in blocked):
        return [*blocked, _diff._drift(
            "management_locked",
            "reconcile needs node:// management, but no key is enrolled (keyCount=0) — enroll first",
            "blocked", f"node://{node}/enroll")]
    return blocked


def run_allowed(readiness: _status.Readiness) -> tuple[bool, str]:
    """The preflight gate. Returns (allowed, reason). A task runs ONLY on a ready node."""
    if readiness.runnable:
        return True, "ready"
    return False, f"node is '{readiness.status}': " + "; ".join(readiness.reasons or ["not ready"])


def assess(desired: dict, actual: dict, *, required_routes: list[str] | None = None,
           smoke_call: Callable[[str], dict] | None = None,
           live_checks: list | None = None) -> dict[str, Any]:
    """One call: drift + smoke + readiness + reconcile plan + the preflight verdict.

    smoke runs only when the node is otherwise compatible (no point smoking a stale node)."""
    drift = _diff.compare(desired, actual)
    smoke_report = None
    smoke_ok: bool | None = None
    if not drift and (required_routes or live_checks):
        smoke_report = _smoke.run(actual, required_routes, live_checks, smoke_call)
        smoke_ok = smoke_report["ok"]
    readiness = _status.classify(actual, desired, drift, smoke_ok)
    allowed, reason = run_allowed(readiness)
    return {
        "node": desired.get("node") or actual.get("node"),
        "readiness": readiness.to_dict(),
        "drift": drift,
        "smoke": smoke_report,
        "plan": plan(desired, actual),
        "run_allowed": allowed,
        "run_reason": reason,
    }


def auto_reconcile_before_ask(desired: dict, actual: dict, *,
                              execute_fn: Callable[[dict], dict],
                              required_routes: list[str] | None = None,
                              smoke_call: Callable[[str], dict] | None = None) -> dict[str, Any]:
    """IFURI-031: don't ask the host/human first — try to heal automatically.

    When a node is not ready, attempt an automatic reconcile IF the plan is safe and
    actionable (no human-gated/blocked steps). Only escalate to the host when there is no
    safe automatic remedy, or the auto-reconcile ran but did not make the node ready.
    ``execute_fn(plan)`` applies the plan and returns its result; it is injectable for tests."""
    assessment = assess(desired, actual, required_routes=required_routes, smoke_call=smoke_call)
    if assessment["run_allowed"]:
        return {"action": "none", "reason": "already ready", "assessment": assessment}

    plan_steps = assessment["plan"]
    if plan_steps.get("blocked"):
        return {"action": "ask_host", "reason": "reconcile blocked (needs human): "
                + "; ".join(str(b) for b in plan_steps["blocked"]), "assessment": assessment}
    if not plan_steps.get("steps"):
        return {"action": "ask_host", "reason": "no automatic remedy for this drift",
                "assessment": assessment}

    # safe, actionable plan → heal automatically, then verify it actually became ready
    exec_result = execute_fn(plan_steps)
    healed = bool(exec_result.get("ok")) and bool(exec_result.get("verified", True))
    if healed:
        return {"action": "auto_reconciled", "reason": "healed without asking the host",
                "execution": exec_result, "assessment": assessment}
    return {"action": "ask_host", "reason": "auto-reconcile ran but node still not ready",
            "execution": exec_result, "assessment": assessment}


def assess_live(desired: dict, base_url: str, *, required_routes: list[str] | None = None,
                timeout: float = 6.0) -> dict[str, Any]:
    """assess() against a live node: probe /health + /routes, then evaluate."""
    actual = _actual.probe(base_url, desired.get("node") or "node", timeout=timeout)
    return assess(desired, actual, required_routes=required_routes)
