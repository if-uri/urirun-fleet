# Author: Tom Sapletta · Part of the ifURI solution.
"""Drift = desired − actual. Each entry carries the node:// remedy that would fix it.

Severity: ``auto`` (a node:// command can fix it) vs ``blocked`` (needs a human, e.g.
enrollment). The reconciler acts on ``auto`` drift; ``blocked`` drift stops the node at
``blocked`` in the readiness ladder.
"""
from __future__ import annotations

from typing import Any

from . import capabilities as _caps


def _ver_tuple(v: str | None) -> tuple:
    if not v:
        return ()
    out = []
    for part in str(v).split("."):
        num = "".join(c for c in part if c.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


def _drift(kind: str, detail: str, severity: str, remedy: str | None) -> dict[str, Any]:
    return {"kind": kind, "detail": detail, "severity": severity, "remedy_uri": remedy}


def compare(desired: dict, actual: dict) -> list[dict[str, Any]]:
    """Return the ordered drift list (name → runtime → connectors → registry → enrollment).

    Each check is its own function returning zero or more drift entries; compare() just
    concatenates them in order."""
    node = desired.get("node") or actual.get("node") or "node"
    out: list[dict] = []
    for check in (_name_drift, _runtime_drift, _scheme_drift, _connector_drift,
                  _capability_drift, _registry_drift, _enrollment_drift):
        out.extend(check(node, desired, actual))
    return out


def _name_drift(node: str, desired: dict, actual: dict) -> list[dict]:
    reported = actual.get("reported_name") or actual.get("name")
    if not reported or reported == node:
        return []
    if reported in (desired.get("aliases") or []) or reported == desired.get("expected_reported_name"):
        return []  # accepted alias — same object under a different --name
    return [_drift("node_name_drift",
                   f"reported name '{reported}' != desired id '{node}' (add it to aliases?)",
                   "blocked", f"node://{node}/runtime/command/rename")]


def _runtime_drift(node: str, desired: dict, actual: dict) -> list[dict]:
    minv = desired.get("min_version")
    if minv and _ver_tuple(actual.get("urirun_version")) < _ver_tuple(minv):
        return [_drift("runtime_drift", f"urirun {actual.get('urirun_version')} < required {minv}",
                       "auto", f"node://{node}/runtime/command/upgrade")]
    return []


def _scheme_drift(node: str, desired: dict, actual: dict) -> list[dict]:
    have = set(actual.get("schemes") or [])
    return [_drift("scheme_missing",
                   f"required scheme '{s}://' not served (connector missing/stale)",
                   "auto", f"node://{node}/connector/command/install")
            for s in desired.get("require_schemes") or [] if s not in have]


def _connector_drift(node: str, desired: dict, actual: dict) -> list[dict]:
    have = set(actual.get("schemes") or [])
    req_schemes = set(desired.get("require_schemes") or [])
    out = []
    for cname in desired.get("connectors") or {}:
        cscheme = _CONNECTOR_SCHEME.get(cname, cname)
        if cscheme not in have and cscheme not in req_schemes:
            out.append(_drift("connector_drift",
                              f"connector '{cname}' declared but its scheme is not served",
                              "auto", f"node://{node}/connector/command/install"))
    return out


def _capability_drift(node: str, desired: dict, actual: dict) -> list[dict]:
    ev = _caps.evaluate(desired.get("required_capabilities") or {}, actual.get("routes") or [])
    return [_drift("capability_missing", f"capability '{name}' unmet (none of {any_of} served)",
                   "auto", f"node://{node}/connector/command/install")
            for name, any_of in ev["missing"].items()]


def _registry_drift(node: str, desired: dict, actual: dict) -> list[dict]:
    want = desired.get("registry_etag")
    if want and actual.get("registry_etag") and want != actual.get("registry_etag"):
        return [_drift("registry_drift",
                       f"registry etag {actual.get('registry_etag')} != pinned {want}",
                       "auto", f"node://{node}/registry/command/rebuild")]
    return []


def _enrollment_drift(node: str, desired: dict, actual: dict) -> list[dict]:
    if desired.get("require_run_auth") and int(actual.get("key_count") or 0) == 0:
        return [_drift("enrollment_drift", "run-auth required but no key enrolled (needs console token)",
                       "blocked", f"node://{node}/enroll")]
    return []


# connector id → the URI scheme it serves (for connector_drift detection)
_CONNECTOR_SCHEME = {
    "urivision-runtime": "runtime",
    "browser-control": "browser",
}
