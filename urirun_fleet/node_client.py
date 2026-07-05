# Author: Tom Sapletta · Part of the ifURI solution.
"""NodeClient — the host's authenticated transport to a node's HTTP surface.

``probe()`` reads /health + /routes (unauthenticated). ``call(uri, payload)`` POSTs to
/run; the admin-gated node:// management URIs need auth, supplied as a token header or a
``sign(body)`` callable (SSH-key signing). The client is a thin, injectable seam so the
executor stays testable with a fake in place of real HTTP.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from . import actual_state


class NodeClient:
    def __init__(self, base_url: str, node: str, *, token: str | None = None,
                 sign: Callable[[bytes], dict] | None = None, timeout: float = 20.0) -> None:
        self.base = base_url.rstrip("/")
        self.node = node
        self.token = token
        self.sign = sign
        self.timeout = timeout

    def probe(self) -> dict[str, Any]:
        return actual_state.probe(self.base, self.node, timeout=min(self.timeout, 6.0))

    def call(self, uri: str, payload: dict | None = None) -> dict[str, Any]:
        """POST /run {uri, payload}. Admin routes get the token header / signature headers."""
        from urllib.request import Request, urlopen
        body = json.dumps({"uri": uri, "payload": payload or {}}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Urirun-Token"] = self.token
        if self.sign:
            headers.update(self.sign(body))  # e.g. {"X-Urirun-Signature": "...", "X-Urirun-Key": "..."}
        req = Request(self.base + "/run", data=body, headers=headers)
        try:
            with urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - a transport error is a failed step, not a crash
            return {"ok": False, "error": str(exc), "uri": uri}
