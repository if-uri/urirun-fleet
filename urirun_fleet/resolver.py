# Author: Tom Sapletta · Part of the ifURI solution.
"""Capability resolver — the LLM reasoning loop that satisfies a NEED without giving up.

When a node lacks a capability (e.g. "no text editor"), don't report failure — reason
about it. A text editor is a MEANS, not the END; the end is "a document with content",
reachable headlessly (generate the file), by installing a connector, or by a GUI app.
This loop asks an LLM for ranked strategies, keeps the ones that are AVAILABLE or
INSTALLABLE, and — when all are blocked — feeds the blockers back and asks for an
alternative that AVOIDS them (the reframing). The LLM is injected, so it is testable
with a fake; a rule-based fallback covers the common "author a document" intent offline.

    resolve(need, available_capabilities, installable_catalog, llm) -> resolution + plan
"""
from __future__ import annotations

import json
from typing import Any, Callable

Completer = Callable[[str], str]


def _provides(catalog: dict, cap: str) -> str | None:
    """Which installable connector provides capability ``cap`` (by any_of route glob match)?"""
    from . import capabilities as _caps
    for cid, spec in (catalog or {}).items():
        for group in (spec.get("capabilities") or {}).values():
            if cap in (group.get("any_of") or []) or cap == group.get("id"):
                return cid
        if cap in (spec.get("provides") or []):
            return cid
    return None


def feasibility(strategy: dict, available: list[str], catalog: dict) -> str:
    """available (a served route matches) > installable (a connector provides it) > blocked."""
    from . import capabilities as _caps
    needs = strategy.get("needs") or []
    if not needs:
        return "available"  # a pure reframing that uses nothing new
    missing = [n for n in needs if not _caps.present(available, [n])]
    if not missing:
        return "available"
    if all(_provides(catalog, n) for n in missing):
        return "installable"
    return "blocked"


def _plan(node: str, strategy: dict, available: list[str], catalog: dict) -> list[dict]:
    """Turn a chosen strategy into ordered URI steps: install missing connectors, then act."""
    from . import capabilities as _caps
    steps: list[dict] = []
    seen: set = set()
    for n in strategy.get("needs") or []:
        if not _caps.present(available, [n]):
            cid = _provides(catalog, n)
            if cid and cid not in seen:
                seen.add(cid)
                steps.append({"uri": f"node://{node}/connector/command/install",
                              "payload": {"id": cid}, "for": f"provides:{n}"})
    for step in strategy.get("steps") or []:
        steps.append(step if isinstance(step, dict) else {"uri": step})
    return steps


_PROMPT = """You resolve a capability NEED into a URI-process plan for an ifURI node.
A missing GUI tool is never the end — reframe to the underlying goal when needed
(e.g. "text editor" → generate the document file headlessly).

NEED: {need}
CAPABILITIES AVAILABLE NOW (served routes): {available}
INSTALLABLE CONNECTORS (id → provides): {catalog}
STRATEGIES ALREADY FOUND BLOCKED (do not repeat, find an alternative): {blocked}

Return JSON: {{"strategies":[{{"id":"short-id","summary":"...","needs":["<route-glob>",...],
"steps":[{{"uri":"scheme://{node}/...","payload":{{}}}}],"reframes":true|false}}]}}
Rank strategies best-first. Prefer ones whose `needs` are already available, then ones a
listed connector provides, then a reframing that needs nothing missing."""


def _ask_llm(need, available, catalog, blocked, node, llm: Completer) -> list[dict]:
    prompt = _PROMPT.format(need=need, available=json.dumps(available[:40]),
                            catalog=json.dumps({k: (v.get("provides") or list((v.get("capabilities") or {})))
                                                for k, v in (catalog or {}).items()}),
                            blocked=json.dumps(blocked), node=node)
    try:
        raw = llm(prompt)
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        return data.get("strategies") or []
    except Exception:  # noqa: BLE001 - a malformed LLM reply yields no strategies this round
        return []


def resolve(need: str, available_capabilities: list[str], installable_catalog: dict,
            llm: Completer, *, node: str = "host", max_rounds: int = 3) -> dict[str, Any]:
    """The reasoning loop: ask → rank by feasibility → keep first feasible → else feed the
    blockers back and reframe. Returns the chosen strategy + an executable URI plan, or an
    honest 'unresolved' with everything tried."""
    blocked_ids: list[str] = []
    considered: list[dict] = []
    for _ in range(max_rounds):
        strategies = _ask_llm(need, available_capabilities, installable_catalog, blocked_ids, node, llm)
        if not strategies:
            break
        for s in strategies:
            feas = feasibility(s, available_capabilities, installable_catalog)
            considered.append({"id": s.get("id"), "feasibility": feas})
            if feas in ("available", "installable"):
                return {"resolved": True, "strategy": s, "feasibility": feas,
                        "plan": _plan(node, s, available_capabilities, installable_catalog),
                        "considered": considered}
        blocked_ids += [s.get("id") for s in strategies if s.get("id")]
    return {"resolved": False, "considered": considered, "tried": blocked_ids,
            "reason": "no available/installable strategy; a human capability may be required"}
