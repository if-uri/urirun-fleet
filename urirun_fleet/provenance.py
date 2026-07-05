# Author: Tom Sapletta · Part of the ifURI solution.
"""Provenance — the metadata every response should carry: WHERE this code came from.

The whole "stale node" class of bug (a process serving old bindings while the disk has a
new version) is invisible until each response says: which module ran, its version, its
source (git repo + sha when available), when the file was last updated, and on which
host/node. Stamp this on every dispatch result (HTTP or CLI) and drift is self-evident.

    {"module": "urirun_connector_kvm.core", "version": "0.3.1",
     "source": "git+https://github.com/if-uri/urirun-connector-kvm.git",
     "sha": "abc1234", "file": "/…/core.py", "updatedAt": 1751… ,
     "ranOn": "laptop", "python": "3.14.6"}
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def _dist_version(module: str) -> str | None:
    import importlib.metadata as m
    # map top-level module → distribution name best-effort
    top = module.split(".", 1)[0]
    for name in (top, top.replace("_", "-")):
        try:
            return m.version(name)
        except Exception:  # noqa: BLE001
            continue
    return None


def _module_file(module: str) -> str | None:
    mod = sys.modules.get(module)
    f = getattr(mod, "__file__", None)
    if f:
        return f
    try:
        import importlib.util
        spec = importlib.util.find_spec(module)
        return spec.origin if spec else None
    except Exception:  # noqa: BLE001
        return None


def _git_source(path: str) -> dict[str, Any]:
    """git repo + short sha for a file, if it lives in a checkout. Best-effort, no raise."""
    import subprocess
    p = Path(path).parent
    try:
        sha = subprocess.run(["git", "-C", str(p), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=3).stdout.strip()
        url = subprocess.run(["git", "-C", str(p), "config", "--get", "remote.origin.url"],
                             capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, Any] = {}
    if sha:
        out["sha"] = sha
    if url:
        out["source"] = f"git+{url}" if not url.startswith("git+") else url
    return out


def of(module: str, *, ran_on: str | None = None) -> dict[str, Any]:
    """Build the provenance block for a module — safe, never raises."""
    prov: dict[str, Any] = {"module": module}
    try:
        prov["version"] = _dist_version(module)
        f = _module_file(module)
        if f:
            prov["file"] = f
            try:
                prov["updatedAt"] = int(Path(f).stat().st_mtime)
            except OSError:
                pass
            prov.update(_git_source(f))
        prov["ranOn"] = ran_on or os.environ.get("URIRUN_NODE_NAME") or _hostname()
        prov["python"] = ".".join(str(v) for v in sys.version_info[:3])
    except Exception as exc:  # noqa: BLE001 - provenance must never break a response
        prov["provenanceError"] = str(exc)
    return prov


def _hostname() -> str:
    try:
        import socket
        return socket.gethostname()
    except Exception:  # noqa: BLE001
        return "?"


def stamp(result: dict, module: str, *, uri: str | None = None, ran_on: str | None = None) -> dict:
    """Attach a ``_meta`` provenance block to a result envelope (idempotent, non-destructive).

    This is what a dispatch layer calls before returning: the caller always learns where the
    code came from, its version, and when it was last updated — over HTTP or CLI alike."""
    if not isinstance(result, dict):
        result = {"value": result}
    meta = of(module, ran_on=ran_on)
    if uri:
        meta["invokedUri"] = uri
    result.setdefault("_meta", meta)
    return result
