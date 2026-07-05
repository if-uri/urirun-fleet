# Author: Tom Sapletta · Part of the ifURI solution.
"""Execute a reconcile plan by calling the node:// remedy URIs, in order, then verify.

The dispatcher is INJECTED (``call(uri, payload) -> envelope``) so the host wires it to
its authenticated node transport (signed POST /run) and the logic stays testable with a
mock. Semantics: run steps in phase order, stop on the first failure, and on a failed
smoke (or any failure after a change was applied) trigger the node's rollback URI — the
node owns the atomic switch (see rollout.py); the host only orchestrates.
"""
from __future__ import annotations

from typing import Any, Callable


def _ok(env: Any) -> bool:
    """A urirun envelope is ok unless it says otherwise (tolerates {value:{ok}} nesting)."""
    if not isinstance(env, dict):
        return False
    if "ok" in env:
        return bool(env["ok"])
    val = env.get("value")
    if isinstance(val, dict) and "ok" in val:
        return bool(val["ok"])
    result = env.get("result")
    if isinstance(result, dict):
        return _ok(result.get("value", result))
    return True  # no explicit ok → treat as success (matches guard://batch convention)


def execute(plan: dict, call: Callable[[str, dict], Any], *,
            on_event: Callable[[dict], None] | None = None,
            rollback_on_fail: bool = True,
            probe: Callable[[], dict] | None = None) -> dict[str, Any]:
    """Run ``plan['steps']`` via ``call``; stop on first failure; roll back if a change
    was already applied. ``probe()`` (optional) is called after each change step so the
    run record carries the node's re-read state. Returns a full run record.

    Hard rule: a ``blocked`` plan (e.g. enrollment needed) is NEVER executed."""
    node = plan.get("node") or "node"

    def emit(ev: dict) -> None:
        if on_event:
            on_event({"node": node, **ev})

    if plan.get("blocked"):
        emit({"event": "blocked", "detail": "plan has human-gated drift; not executing",
              "drift": [d.get("kind") for d in plan.get("blocked") or []]})
        return {"ok": False, "node": node, "blocked": True, "steps": [], "rolledback": False}
    if plan.get("clean"):
        emit({"event": "clean", "detail": "no drift; nothing to reconcile"})
        return {"ok": True, "node": node, "steps": [], "rolledback": False, "clean": True}

    steps_out: list[dict] = []
    applied_change = False
    for step in plan.get("steps", []):
        uri = step["uri"]
        is_smoke = uri.endswith("/smoke/command/run")
        is_change = "/command/" in uri and not is_smoke
        emit({"event": "step.start", "uri": uri, "for": step.get("for")})
        rec, ok = _run_step(call, uri, is_change, probe)
        steps_out.append(rec)
        emit({"event": "step.done", "uri": uri, "ok": ok})
        applied_change = applied_change or is_change
        if not ok:
            rolled = _maybe_rollback(call, node, emit, rollback_on_fail and applied_change)
            status_after = "degraded" if is_smoke else "failed"
            emit({"event": f"node.{status_after}", "failedAt": uri})
            return {"ok": False, "node": node, "steps": steps_out,
                    "failedAt": uri, "rolledback": rolled, "status": status_after}

    emit({"event": "node.ready", "steps": len(steps_out)})
    return {"ok": True, "node": node, "steps": steps_out, "rolledback": False, "status": "ready"}


def _run_step(call, uri, is_change, probe):
    try:
        env = call(uri, {})
        ok = _ok(env)
    except Exception as exc:  # noqa: BLE001
        env, ok = {"error": str(exc)}, False
    rec = {"uri": uri, "ok": ok, "result": env}
    if is_change and probe:  # re-read the node after every change (etag/version/routes)
        try:
            rec["probe"] = probe()
        except Exception:  # noqa: BLE001
            rec["probe"] = None
    return rec, ok


def _maybe_rollback(call, node, emit, do_rollback) -> bool:
    if not do_rollback:
        return False
    emit({"event": "rollback.start", "reason": "a change step failed"})
    try:
        rolled = _ok(call(f"node://{node}/runtime/command/rollback", {}))
    except Exception:  # noqa: BLE001
        rolled = False
    emit({"event": "rollback.done", "ok": rolled})
    return rolled
