# Author: Tom Sapletta · Part of the ifURI solution.
"""urirun-fleet — desired/actual/diff/reconcile/verify for a fleet of URI nodes.

A stale node must not count as usable. This package gives the host a lightweight
control loop: know the desired state, read each node's actual state, compute drift,
classify readiness, and gate task execution on ``ready`` — never ``online``.
"""
from __future__ import annotations

from . import (
    actual_state, capabilities, desired_state, diff, events, executor,
    node_client, reconciler, rollout, smoke, status,
)
from .status import Readiness, classify

__all__ = [
    "actual_state", "capabilities", "desired_state", "diff", "events", "executor",
    "node_client", "reconciler", "rollout", "smoke", "status", "Readiness", "classify",
]
