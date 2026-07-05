# Author: Tom Sapletta · Part of the ifURI solution.
"""The fleet contract: a stale/blocked node is NOT ready, and drift maps to node:// fixes."""
from urirun_fleet import actual_state, desired_state, diff, reconciler, smoke, status

# real /health shape captured from lenovo (.201:8766)
LENOVO_HEALTH = {
    "name": "laptop", "version": "0.4.194", "routeCount": 59,
    "registryEtag": "6d3826ba34fe60bc", "registryGeneration": 1,
    "deploy": True, "keyAuth": True, "keyCount": 0, "kind": "node",
}
LENOVO_ROUTES = ["env://laptop/runtime/query/health", "node://laptop/connector/command/install",
                 "kvm://host/screen/query/capture", "shell://laptop/command/uname"]

DESIRED = desired_state.normalize("laptop", {
    "channel": "dev",
    "urirun": {"source": "git", "ref": "main", "min_version": "0.4.196"},
    "connectors": {"kvm": {}, "urivision": {}},
    "registry": {"require_schemes": ["env", "node", "kvm", "screen", "browser", "urivision"]},
    "services": {"node": {"port": 8766, "require_run_auth": True, "manage": True}},
})


def _actual(**over):
    a = actual_state.normalize("laptop", True, LENOVO_HEALTH, LENOVO_ROUTES)
    a.update(over)
    return a


def test_offline_node_is_offline_and_not_runnable():
    a = actual_state.normalize("laptop", False, None)
    r = status.classify(a, DESIRED)
    assert r.status == "offline" and not r.runnable


def test_lenovo_drift_detected_version_and_missing_schemes():
    d = diff.compare(DESIRED, _actual())
    kinds = {x["kind"] for x in d}
    assert "runtime_drift" in kinds          # 0.4.194 < 0.4.196
    assert "scheme_missing" in kinds         # browser://, urivision://, screen:// absent
    # every auto drift carries a node:// remedy
    assert all(x["remedy_uri"].startswith("node://") for x in d if x["severity"] == "auto")


def test_lenovo_full_desired_is_blocked_on_enrollment():
    # the REAL lenovo state: require_run_auth + keyCount 0 → blocked (human must enroll)
    r = status.classify(_actual(require_run_auth=True), DESIRED, diff.compare(DESIRED, _actual()))
    assert r.status == "blocked" and not r.runnable


def test_version_drift_alone_makes_node_stale_not_ready():
    # isolate version/scheme drift from enrollment: node has a key, auth not required
    d = dict(DESIRED, require_run_auth=False)
    a = _actual(key_count=1)
    r = status.classify(a, d, diff.compare(d, a))
    assert r.status == "stale" and not r.runnable


def test_enrollment_drift_is_blocked_needs_human():
    # require_run_auth + keyCount 0 → blocked (a human must enroll), not merely stale
    d = diff.compare(DESIRED, _actual(key_count=0))
    enroll = [x for x in d if x["kind"] == "enrollment_drift"]
    assert enroll and enroll[0]["severity"] == "blocked"
    r = status.classify(_actual(require_run_auth=True, key_count=0), DESIRED, d)
    assert r.status == "blocked"


def test_compatible_then_ready_only_after_smoke():
    # a node meeting version + all schemes, with a key, no auth requirement
    good_desired = dict(DESIRED, min_version="0.4.190", require_schemes=["env", "node", "kvm"],
                        require_run_auth=False, connectors={})
    good = _actual(urirun_version="0.4.194",
                   schemes={"env", "node", "kvm", "shell"}, key_count=1)
    d = diff.compare(good_desired, good)
    assert d == []
    assert status.classify(good, good_desired, d, smoke_ok=None).status == "compatible"
    assert status.classify(good, good_desired, d, smoke_ok=True).status == "ready"
    assert status.classify(good, good_desired, d, smoke_ok=False).status == "degraded"


def test_reconcile_plan_orders_fixes_and_appends_rebuild_restart_smoke():
    p = reconciler.plan(DESIRED, _actual())
    phases = [s["phase"] for s in p["steps"]]
    assert phases == sorted(phases)                    # ordered
    uris = " ".join(s["uri"] for s in p["steps"])
    assert "runtime/command/upgrade" in uris
    assert "registry/command/rebuild" in uris and "runtime/command/restart" in uris
    assert uris.strip().endswith("smoke/command/run")  # verify is always last


def test_preflight_gate_blocks_task_on_non_ready_node():
    d = dict(DESIRED, require_run_auth=False)
    a = _actual(key_count=1)
    r = status.classify(a, d, diff.compare(d, a))
    allowed, reason = reconciler.run_allowed(r)
    assert allowed is False and "stale" in reason


def test_smoke_static_missing_routes():
    a = _actual()
    rep = smoke.required_routes_present(a, ["kvm://laptop/screen/query/capture", "browser://laptop/x"])
    assert rep["ok"] is False and "browser://laptop/x" in rep["missing"]


def test_assess_end_to_end_shape():
    out = reconciler.assess(DESIRED, _actual(require_run_auth=True),
                            required_routes=["kvm://laptop/screen/query/capture"])
    assert out["run_allowed"] is False
    # real lenovo: blocked on enrollment; the plan still lists the auto fixes
    assert out["readiness"]["status"] == "blocked"
    assert out["plan"]["steps"]


def test_normalize_extracts_schemes_from_route_dicts():
    # the real /routes list shape: [{"uri": "...", "kind": "..."}, ...]
    routes = [{"uri": "env://laptop/runtime/query/health"}, {"uri": "kvm://host/screen/query/capture"}]
    a = actual_state.normalize("laptop", True, LENOVO_HEALTH, routes)
    assert {"env", "kvm"} <= a["schemes"]
