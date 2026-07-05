# Author: Tom Sapletta · Part of the ifURI solution.
"""Capability groups — require an ABILITY, satisfiable by any of several routes.

``scheme_missing`` is too blunt: a node with no ``screen://`` can still capture the
screen via ``kvm://.../screen/query/capture``. So the desired state can declare
capabilities as ``any_of`` route globs; a capability is present if the node serves any
matching route. Missing ones become ``capability_missing`` drift.
"""
from __future__ import annotations

import fnmatch
from typing import Any


def _matches(pattern: str, route: str) -> bool:
    # match on the path part so host↔node target names don't matter; '*' spans a segment
    return fnmatch.fnmatch(route, pattern) or fnmatch.fnmatch(
        route.split("://", 1)[-1], pattern.split("://", 1)[-1])


def present(routes: list[str], any_of: list[str]) -> bool:
    return any(_matches(p, r) for p in any_of for r in routes)


def evaluate(required: dict[str, dict], routes: list[str]) -> dict[str, Any]:
    """required = {cap_name: {any_of: [glob, ...]}}. Returns which capabilities are met/missing."""
    met, missing = {}, {}
    for name, spec in (required or {}).items():
        any_of = spec.get("any_of") or spec.get("anyOf") or []
        (met if present(routes, any_of) else missing)[name] = any_of
    return {"met": met, "missing": missing, "ok": not missing}
