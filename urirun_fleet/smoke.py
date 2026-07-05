# Author: Tom Sapletta · Part of the ifURI solution.
"""Smoke tests — does the node ACTUALLY have the capabilities a task needs?

Two levels: static (required routes present in the served surface — cheap, no execution)
and live (call a read-only route and check the envelope). A node passes smoke only when
every required capability is present; that gate is what turns ``compatible`` into
``ready``.
"""
from __future__ import annotations

from typing import Any, Callable


def required_routes_present(actual: dict, required_routes: list[str]) -> dict[str, Any]:
    """Static smoke: every required route URI is in the node's served surface."""
    have = set(actual.get("routes") or [])
    # match by suffix so host↔node target names don't cause false misses
    def _present(req: str) -> bool:
        if req in have:
            return True
        tail = req.split("://", 1)[-1]
        return any(r.split("://", 1)[-1] == tail for r in have)
    missing = [r for r in required_routes if not _present(r)]
    return {"ok": not missing, "checked": len(required_routes), "missing": missing}


def run(actual: dict, required_routes: list[str] | None = None,
        live_checks: list[tuple[str, Callable[[dict], bool]]] | None = None,
        call: Callable[[str], dict] | None = None) -> dict[str, Any]:
    """Full smoke: static route presence + optional live read-only calls.

    ``live_checks`` is a list of (uri, verify) — ``call(uri)`` runs it, ``verify(result)``
    decides pass/fail. ``call`` is injected (a dispatcher), so the pure logic stays
    testable. Any failure → ok:false with the details."""
    report: dict[str, Any] = {"ok": True, "static": None, "live": []}
    if required_routes:
        st = required_routes_present(actual, required_routes)
        report["static"] = st
        if not st["ok"]:
            report["ok"] = False
    if live_checks and call:
        for uri, verify in live_checks:
            try:
                res = call(uri)
                passed = bool(verify(res))
            except Exception as exc:  # noqa: BLE001
                res, passed = {"error": str(exc)}, False
            report["live"].append({"uri": uri, "ok": passed})
            if not passed:
                report["ok"] = False
    return report
