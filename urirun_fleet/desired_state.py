# Author: Tom Sapletta · Part of the ifURI solution.
"""Desired state — the host's source of truth for what each node SHOULD be.

Parsed from a fleet YAML/JSON (see examples/fleet.yaml). This is deliberately the
authority; whatever happens to sit on the node is reconciled toward this, never the
other way around.
"""
from __future__ import annotations

from typing import Any


def _load_text(text: str) -> dict:
    text = text.strip()
    if not text:
        return {}
    if text[0] in "{[":
        import json
        return json.loads(text)
    try:
        import yaml  # optional
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("fleet desired-state is YAML; pip install pyyaml (or use JSON)") from exc
    return yaml.safe_load(text) or {}


def load(path_or_text: str) -> dict[str, dict]:
    """Load the fleet spec → {node_name: desired_dict}. Accepts a path or inline text."""
    from pathlib import Path
    p = Path(path_or_text).expanduser()
    text = p.read_text(encoding="utf-8") if p.is_file() else path_or_text
    doc = _load_text(text)
    nodes = doc.get("nodes") or {}
    return {name: normalize(name, spec) for name, spec in nodes.items()}


def normalize(name: str, spec: dict) -> dict[str, Any]:
    """Flatten a node's desired spec into the fields diff/status compare against."""
    urirun = spec.get("urirun") or {}
    services = (spec.get("services") or {}).get("node") or {}
    registry = spec.get("registry") or {}
    return {
        "node": name,
        "channel": spec.get("channel") or "stable",
        "aliases": list(spec.get("aliases") or []),
        "expected_reported_name": spec.get("expected_reported_name"),
        "connectors": {k: (v or {}) for k, v in (spec.get("connectors") or {}).items()},
        "require_schemes": list(registry.get("require_schemes") or []),
        "required_capabilities": spec.get("required_capabilities") or {},
        "registry_etag": registry.get("etag"),  # optional hard pin
        "allow": list((spec.get("policies") or {}).get("allow") or []),
        **_runtime_fields(urirun),
        **_service_fields(services),
    }


def _runtime_fields(urirun: dict) -> dict[str, Any]:
    return {
        "urirun_source": urirun.get("source") or "pypi",
        "urirun_ref": urirun.get("ref"),
        "min_version": urirun.get("min_version") or urirun.get("version"),
    }


def _service_fields(services: dict) -> dict[str, Any]:
    return {
        "port": services.get("port"),
        "require_run_auth": bool(services.get("require_run_auth")),
        "manage": bool(services.get("manage")),
    }
