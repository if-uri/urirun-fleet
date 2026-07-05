# Author: Tom Sapletta · Part of the ifURI solution.
"""JSONL event log for fleet runs — so "what happened to the node, and when?" is answerable.

Every reconcile writes an append-only stream: reconcile.started → drift_detected →
step.start/done → smoke → node.ready|blocked|degraded. A run_id ties them together.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable


def default_log_path() -> Path:
    d = Path(os.environ.get("URIRUN_FLEET_EVENTS") or "~/.urirun/fleet/events.jsonl").expanduser()
    d.parent.mkdir(parents=True, exist_ok=True)
    return d


class EventLog:
    """Append-only JSONL sink. ``ts`` is injected (scripts/replays stay deterministic)."""

    def __init__(self, run_id: str, path: str | Path | None = None,
                 clock: Callable[[], float] | None = None,
                 also: Callable[[dict], None] | None = None) -> None:
        self.run_id = run_id
        self.path = Path(path).expanduser() if path else default_log_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._also = also
        self.events: list[dict] = []

    def emit(self, event: str, **fields: Any) -> dict:
        rec = {"event": event, "runId": self.run_id, **fields}
        if self._clock:
            rec["ts"] = self._clock()
        self.events.append(rec)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
        if self._also:
            self._also(rec)
        return rec

    def sink(self) -> Callable[[dict], None]:
        """An on_event callback for executor.execute — forwards its events into this log."""
        def _on(ev: dict) -> None:
            name = ev.pop("event", "fleet.event")
            self.emit(f"fleet.{name}" if not name.startswith("fleet.") else name, **ev)
        return _on
