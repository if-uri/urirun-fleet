# Author: Tom Sapletta · Part of the ifURI solution.
"""Actual state — what a node REPORTS about itself, normalized for comparison.

Pure normalize() (testable with fixtures) is separated from probe() (network). Built
from the node's ``/health`` plus ``/routes``; richer fields (git sha, connector
versions) are read from a runtime-state URI when the node exposes one, and degrade
gracefully when it does not.
"""
from __future__ import annotations

from typing import Any


def scheme_of(uri: str) -> str:
    return str(uri).split("://", 1)[0] if "://" in str(uri) else ""


def _route_keys(routes: list | dict | None) -> list[str]:
    if isinstance(routes, dict):
        return list(routes.keys())
    if isinstance(routes, list):
        return [r.get("uri") if isinstance(r, dict) else str(r) for r in routes]
    return []


def normalize(node: str, reachable: bool, health: dict | None,
              routes: list | dict | None = None, state: dict | None = None) -> dict[str, Any]:
    """Fold /health + /routes (+ optional runtime state) into a flat actual-state dict."""
    health = health or {}
    route_keys = _route_keys(routes)
    schemes = {s for s in (scheme_of(k) for k in route_keys) if s}
    st = state or {}
    return {
        "node": node,
        "reported_name": health.get("name"),   # the node's own --name (for alias drift)
        "reachable": bool(reachable),
        "urirun_version": st.get("urirun_version") or health.get("version"),
        "urirun_source": st.get("urirun_source"),
        "git_sha": st.get("git_sha"),
        "routes_count": health.get("routeCount") if health.get("routeCount") is not None else len(route_keys),
        "registry_etag": health.get("registryEtag") or st.get("registry_etag"),
        "registry_generation": health.get("registryGeneration"),
        "key_count": health.get("keyCount"),
        "require_run_auth": bool(health.get("requireRunAuth") or (health.get("policy") or {}).get("requireRunAuth")),
        "deploy": health.get("deploy"),
        "schemes": schemes,
        "routes": route_keys,
        "connectors": st.get("connectors") or {},
        "capabilities": st.get("capabilities") or {},
    }


def probe(base_url: str, node: str, timeout: float = 6.0) -> dict[str, Any]:
    """Network probe: GET /health + /routes, return a normalized actual-state dict.
    Unreachable → reachable:false (never raises — a dead node is a valid actual state)."""
    import json
    from urllib.request import urlopen

    def _get(path):
        with urlopen(base_url.rstrip("/") + path, timeout=timeout) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))

    try:
        health = _get("/health")
    except Exception:  # noqa: BLE001
        return normalize(node, reachable=False, health=None)
    routes = None
    try:
        raw = _get("/routes")
        # /routes is an envelope {ok, name, routes:[...], etag}; unwrap the list
        routes = raw.get("routes") if isinstance(raw, dict) and "routes" in raw else raw
    except Exception:  # noqa: BLE001
        pass
    return normalize(node, reachable=True, health=health, routes=routes)
