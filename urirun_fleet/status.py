# Author: Tom Sapletta · Part of the ifURI solution.
"""The readiness ladder — the core insight: a stale node must NOT count as usable.

A node climbs rungs: offline → online → enrolled → routable → compatible → ready.
Two off-ladder states capture "reachable but not usable": ``stale`` (online but a
version/scheme/registry drift) and ``blocked`` (needs a human, e.g. enrollment). The
host runs tasks ONLY on ``ready`` — never on ``online``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ordered rungs (index = height); classify() returns the highest one reached
LADDER = ["offline", "online", "enrolled", "routable", "compatible", "ready"]
OFF_LADDER = ["stale", "blocked", "degraded"]


@dataclass
class Readiness:
    node: str
    status: str
    reasons: list[str] = field(default_factory=list)
    reached: list[str] = field(default_factory=list)  # rungs climbed before stopping

    @property
    def runnable(self) -> bool:
        """The gate: only a fully-ready node may receive tasks."""
        return self.status == "ready"

    def to_dict(self) -> dict[str, Any]:
        return {"node": self.node, "status": self.status, "runnable": self.runnable,
                "reasons": self.reasons, "reached": self.reached}


def classify(actual: dict, desired: dict | None, drift: list | None = None,
             smoke_ok: bool | None = None) -> Readiness:
    """Map (actual state, desired state, drift, smoke result) → a single Readiness.

    ``actual`` is a normalized actual-state dict (see actual_state.normalize).
    ``drift`` is the list from diff.compare (empty = compatible). ``smoke_ok`` is the
    capability smoke result (None = not run yet → cannot be ``ready``)."""
    node = str(actual.get("node") or (desired or {}).get("node") or "?")
    reached: list[str] = []
    for rung, verdict in _rungs(node, actual, desired or {}, drift or [], smoke_ok):
        if verdict is not None:
            return verdict
        reached.append(rung)
    return Readiness(node, "ready", [], reached)


def _rungs(node, actual, desired, drift, smoke_ok):
    """Yield (rung_name, off-ladder Readiness or None). A non-None verdict stops the climb."""
    yield "online", (Readiness(node, "offline", ["node not reachable on its endpoint"])
                     if not actual.get("reachable") else None)

    needs_auth = bool(desired.get("require_run_auth") or actual.get("require_run_auth"))
    blocked_enroll = needs_auth and int(actual.get("key_count") or 0) == 0
    yield "enrolled", (Readiness(node, "blocked",
                                 ["auth required but no key enrolled — run uri-copy-id with the console token"])
                       if blocked_enroll else None)

    yield "routable", (Readiness(node, "stale", ["node online but serves no routes (registry not built?)"])
                       if int(actual.get("routes_count") or 0) <= 0 else None)

    yield "compatible", _drift_verdict(node, drift)

    yield "ready", _smoke_verdict(node, smoke_ok)


def _drift_verdict(node, drift):
    if not drift:
        return None
    reasons = [f"{d.get('kind')}: {d.get('detail')}" for d in drift]
    # a drift needing a human (blocked severity) is blocked, not merely stale
    status = "blocked" if any(d.get("severity") == "blocked" for d in drift) else "stale"
    return Readiness(node, status, reasons)


def _smoke_verdict(node, smoke_ok):
    if smoke_ok is None:
        return Readiness(node, "compatible", ["compatible; smoke test not run yet"])
    if not smoke_ok:
        return Readiness(node, "degraded", ["compatible but smoke test failed"])
    return None  # passed → climb to ready
