# Author: Tom Sapletta · Part of the ifURI solution.
"""Execute-mode contract: run the plan safely, verify, roll back on failure, log events,
and NEVER execute a blocked (human-gated) plan. Uses a fake NodeClient — no network."""
from urirun_fleet import capabilities, diff, executor, rollout


class FakeNode:
    """Records calls; returns ok for everything unless a URI is in ``fail``."""
    def __init__(self, fail=(), probe_state=None):
        self.calls = []
        self.fail = set(fail)
        self._probe = probe_state or {"routes_count": 83}

    def call(self, uri, payload=None):
        self.calls.append(uri)
        if uri in self.fail:
            return {"ok": False, "error": "boom", "uri": uri}
        return {"ok": True, "uri": uri}

    def probe(self):
        return dict(self._probe)


def _plan(node="lenovo", steps=None, blocked=None, clean=False):
    return {"node": node, "steps": steps or [], "blocked": blocked or [], "clean": clean,
            "drift": [], "reconcilable": bool(steps)}


AUTO_STEPS = [
    {"phase": 1, "uri": "node://lenovo/runtime/command/upgrade", "for": "runtime_drift"},
    {"phase": 2, "uri": "node://lenovo/connector/command/install", "for": "scheme_missing"},
    {"phase": 4, "uri": "node://lenovo/registry/command/rebuild", "for": "post-change"},
    {"phase": 5, "uri": "node://lenovo/runtime/command/restart", "for": "drop-stale-workers"},
    {"phase": 6, "uri": "node://lenovo/smoke/command/run", "for": "verify"},
]


def test_blocked_plan_is_never_executed():
    node = FakeNode()
    rec = executor.execute(_plan(blocked=[{"kind": "enrollment_drift"}], steps=AUTO_STEPS), node.call)
    assert rec["ok"] is False and rec["blocked"] is True
    assert node.calls == []  # NOTHING ran — the hard rule


def test_happy_path_runs_all_steps_and_reprobes():
    node = FakeNode()
    events = []
    rec = executor.execute(_plan(steps=AUTO_STEPS), node.call, on_event=events.append, probe=node.probe)
    assert rec["ok"] and rec["status"] == "ready"
    assert node.calls == [s["uri"] for s in AUTO_STEPS]
    # a probe rides along each change step (not the smoke step)
    assert any("probe" in s and s["probe"] for s in rec["steps"])
    assert {e["event"] for e in events} >= {"step.start", "step.done", "node.ready"}


def test_failed_step_stops_and_rolls_back():
    node = FakeNode(fail={"node://lenovo/registry/command/rebuild"})
    rec = executor.execute(_plan(steps=AUTO_STEPS), node.call)
    assert rec["ok"] is False and rec["failedAt"].endswith("registry/command/rebuild")
    assert rec["rolledback"] is True
    assert "node://lenovo/runtime/command/rollback" in node.calls
    # steps after the failure did not run
    assert "node://lenovo/runtime/command/restart" not in node.calls


def test_failed_smoke_is_degraded_not_ready():
    node = FakeNode(fail={"node://lenovo/smoke/command/run"})
    rec = executor.execute(_plan(steps=AUTO_STEPS), node.call)
    assert rec["ok"] is False and rec["status"] == "degraded"


def test_clean_plan_is_a_noop():
    node = FakeNode()
    rec = executor.execute(_plan(clean=True), node.call)
    assert rec["ok"] and rec.get("clean") and node.calls == []


# --- capability groups (any_of) -------------------------------------------------
def test_capability_present_via_kvm_even_without_screen_scheme():
    routes = ["kvm://host/screen/query/capture", "kvm://host/input/command/type"]
    req = {"screen_capture": {"any_of": ["screen://*/screen/query/capture",
                                         "kvm://*/screen/query/capture"]}}
    ev = capabilities.evaluate(req, routes)
    assert ev["ok"] and "screen_capture" in ev["met"]


def test_capability_missing_becomes_drift():
    d = diff.compare(
        {"node": "lenovo", "required_capabilities": {
            "browser_control": {"any_of": ["browser://*/page/command/navigate", "cdp://*/page/command/navigate"]}}},
        {"node": "lenovo", "routes": ["kvm://host/screen/query/capture"], "schemes": {"kvm"}})
    kinds = {x["kind"] for x in d}
    assert "capability_missing" in kinds


# --- alias / name drift ---------------------------------------------------------
def test_alias_accepts_reported_name():
    d = diff.compare(
        {"node": "lenovo", "aliases": ["laptop"]},
        {"node": "lenovo", "reported_name": "laptop", "routes": [], "schemes": set()})
    assert not any(x["kind"] == "node_name_drift" for x in d)


def test_unknown_reported_name_is_name_drift():
    d = diff.compare(
        {"node": "lenovo", "aliases": []},
        {"node": "lenovo", "reported_name": "randombox", "routes": [], "schemes": set()})
    nd = [x for x in d if x["kind"] == "node_name_drift"]
    assert nd and nd[0]["severity"] == "blocked"


# --- atomic releases (rollout) --------------------------------------------------
def test_atomic_release_switch_and_rollback(tmp_path):
    mgr = rollout.ReleaseManager(tmp_path)
    r1 = mgr.new_release("20260704-def456"); (r1 / "registry.json").write_text("{}")
    mgr.switch("20260704-def456")
    assert mgr.current_id() == "20260704-def456"
    r2 = mgr.new_release("20260705-abc123"); (r2 / "registry.json").write_text("{}")
    mgr.switch("20260705-abc123")
    assert mgr.current_id() == "20260705-abc123" and mgr.previous_id() == "20260704-def456"
    mgr.rollback()
    assert mgr.current_id() == "20260704-def456"


def test_deploy_release_keeps_current_on_smoke_fail(tmp_path):
    mgr = rollout.ReleaseManager(tmp_path)
    mgr.new_release("v1"); mgr.switch("v1")
    res = rollout.deploy_release(mgr, "v2", build=lambda d: (d / "x").write_text("y"),
                                 smoke=lambda d: False)  # smoke fails
    assert res["ok"] is False and res["switched"] is False
    assert mgr.current_id() == "v1"  # untouched — no half-updated node


def test_deploy_release_switches_on_smoke_pass(tmp_path):
    mgr = rollout.ReleaseManager(tmp_path)
    res = rollout.deploy_release(mgr, "v1", build=lambda d: None, smoke=lambda d: True,
                                 lock={"release_id": "v1"})
    assert res["ok"] and res["switched"] and mgr.current_id() == "v1"
    assert (mgr.releases / "v1" / "manifest.lock.json").is_file()


def test_plan_with_steps_but_no_key_is_management_locked():
    # empirically confirmed: node:// management returns "unauthorized" when keyCount==0
    from urirun_fleet import reconciler
    desired = {"node": "lenovo", "min_version": "0.4.196", "require_run_auth": False}
    actual = {"node": "lenovo", "reachable": True, "urirun_version": "0.4.194",
              "routes_count": 59, "schemes": {"kvm"}, "routes": [], "key_count": 0}
    p = reconciler.plan(desired, actual)
    assert p["steps"] and p["reconcilable"] is False
    assert any(b["kind"] == "management_locked" for b in p["blocked"])
