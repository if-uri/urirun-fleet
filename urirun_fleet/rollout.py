# Author: Tom Sapletta · Part of the ifURI solution.
"""Atomic releases for a node install — eliminates half-updated nodes.

An upgrade builds a NEW release dir (fresh venv, compiled registry, lock file), smoke-
tests it OFF to the side, and only then flips the ``current`` symlink — atomically, via
``os.replace`` on a temp link (rename is atomic on POSIX). A failed smoke never touches
``current``; ``rollback()`` swaps ``current`` back to ``previous``. This runs ON the node
(filesystem ops); the host triggers it through the node:// upgrade/rollback URIs.

    ~/.urirun-node/
      current  -> releases/20260705-abc123
      previous -> releases/20260704-def456
      releases/<id>/{.venv, registry.json, node.json, manifest.lock.json}
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable


class ReleaseManager:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.releases = self.root / "releases"
        self.current = self.root / "current"
        self.previous = self.root / "previous"
        self.releases.mkdir(parents=True, exist_ok=True)

    # -- inspection -------------------------------------------------------------
    def current_id(self) -> str | None:
        return self.current.resolve().name if self.current.is_symlink() or self.current.exists() else None

    def previous_id(self) -> str | None:
        return self.previous.resolve().name if self.previous.is_symlink() or self.previous.exists() else None

    def list_releases(self) -> list[str]:
        return sorted((p.name for p in self.releases.iterdir() if p.is_dir()), reverse=True)

    # -- build & switch ---------------------------------------------------------
    def new_release(self, release_id: str) -> Path:
        """Create (or reuse) releases/<id>/ and return its path — build the venv here."""
        d = self.releases / release_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_lock(self, release_id: str, lock: dict) -> Path:
        p = self.releases / release_id / "manifest.lock.json"
        p.write_text(json.dumps(lock, indent=1, default=str), encoding="utf-8")
        return p

    def _atomic_symlink(self, link: Path, target: Path) -> None:
        """Point ``link`` at ``target`` atomically (write a temp link, then rename over)."""
        tmp = link.with_name(link.name + ".tmp")
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()
        os.symlink(target, tmp)
        os.replace(tmp, link)  # atomic on POSIX

    def switch(self, release_id: str) -> dict[str, Any]:
        """Flip current→release_id, keeping the old current as previous (for rollback)."""
        target = self.releases / release_id
        if not target.is_dir():
            raise FileNotFoundError(f"no such release: {release_id}")
        old = self.current_id()
        if old and old != release_id:
            self._atomic_symlink(self.previous, self.releases / old)
        self._atomic_symlink(self.current, target)
        return {"current": release_id, "previous": self.previous_id()}

    def rollback(self) -> dict[str, Any]:
        """Swap current ↔ previous. Returns the new current (or raises if no previous)."""
        prev = self.previous_id()
        if not prev:
            raise RuntimeError("no previous release to roll back to")
        cur = self.current_id()
        self._atomic_symlink(self.current, self.releases / prev)
        if cur:
            self._atomic_symlink(self.previous, self.releases / cur)
        return {"current": prev, "previous": cur}

    def prune(self, keep: int = 3) -> list[str]:
        """Delete old releases beyond ``keep``, never touching current/previous."""
        import shutil
        protected = {self.current_id(), self.previous_id()}
        removed = []
        for rid in self.list_releases()[keep:]:
            if rid in protected:
                continue
            shutil.rmtree(self.releases / rid, ignore_errors=True)
            removed.append(rid)
        return removed


def deploy_release(mgr: ReleaseManager, release_id: str, *, build: Callable[[Path], None],
                   smoke: Callable[[Path], bool], lock: dict | None = None) -> dict[str, Any]:
    """The atomic upgrade: build the release OFF to the side, smoke it, switch ONLY on pass.

    ``build(dir)`` populates releases/<id> (venv + registry). ``smoke(dir)`` returns True if
    the freshly-built release is healthy (run it on a temp port). A failed build/smoke
    leaves ``current`` untouched — no half-updated node."""
    d = mgr.new_release(release_id)
    try:
        build(d)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "phase": "build", "error": str(exc), "switched": False}
    if lock is not None:
        mgr.write_lock(release_id, lock)
    try:
        healthy = bool(smoke(d))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "phase": "smoke", "error": str(exc), "switched": False}
    if not healthy:
        return {"ok": False, "phase": "smoke", "error": "smoke failed", "switched": False,
                "kept_current": mgr.current_id()}
    res = mgr.switch(release_id)
    return {"ok": True, "switched": True, **res}
