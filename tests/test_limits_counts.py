"""Resource limit counts must be actionable, not inflated by system pods."""

import json

from tests.helpers_debugger import findings, make_debugger


def _pod(ns, name, limits=None, requests=None, init=False, qos="Burstable"):
    container = {"name": "c", "resources": {}}
    if limits:
        container["resources"]["limits"] = limits
    if requests:
        container["resources"]["requests"] = requests
    spec = {"containers": [container]}
    if init:
        spec["initContainers"] = [{"name": "init", "resources": {}}]
    return {"metadata": {"name": name, "namespace": ns}, "spec": spec, "status": {"qosClass": qos}}


BOTH = {"cpu": "1", "memory": "1Gi"}


def _by_summary(dbg, needle):
    for f in findings(dbg, "resource_quota_exceeded"):
        if needle in f["summary"]:
            return f
    raise AssertionError(f"no finding matching {needle!r}")


def test_counts_exclude_system_namespaces_and_init_containers():
    pods = {
        "items": [
            _pod("kube-system", "aws-node"),  # excluded
            _pod("app", "a", limits=BOTH, requests=BOTH, init=True),  # init has none, still fine
            _pod("app", "b", limits={"cpu": "1"}, requests=BOTH),  # cpu-only limit counts as missing
            _pod("app", "c"),  # nothing
        ]
    }
    dbg = make_debugger({"get pods": json.dumps(pods)})
    dbg.analyze_limits_requests()
    limits_f = _by_summary(dbg, "without memory or CPU limits")
    assert limits_f["details"]["pod_count"] == 2
    assert limits_f["details"]["system_namespace_pods_excluded"] == 1
    assert "2 pods" in limits_f["summary"]


def test_requests_counted_the_same_way():
    pods = {
        "items": [
            _pod("app", "a", limits=BOTH, requests=BOTH),
            _pod("app", "b", requests={"cpu": "1"}),
        ]
    }
    dbg = make_debugger({"get pods": json.dumps(pods)})
    dbg.analyze_limits_requests()
    requests_f = _by_summary(dbg, "without memory or CPU requests")
    assert requests_f["details"]["pod_count"] == 1
    assert requests_f["details"]["severity"] == "info"


def test_examples_are_namespaced_names():
    pods = {"items": [_pod("app", "c")]}
    dbg = make_debugger({"get pods": json.dumps(pods)})
    dbg.analyze_limits_requests()
    limits_f = _by_summary(dbg, "without memory or CPU limits")
    assert limits_f["details"]["examples"] == ["app/c"]


def test_fully_specified_cluster_reports_nothing():
    pods = {"items": [_pod("app", "a", limits=BOTH, requests=BOTH, qos="Guaranteed")]}
    dbg = make_debugger({"get pods": json.dumps(pods)})
    dbg.analyze_limits_requests()
    assert [f for f in findings(dbg, "resource_quota_exceeded") if "without memory or CPU" in f["summary"]] == []
