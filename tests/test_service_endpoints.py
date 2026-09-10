"""Services with no endpoints must say why, not assume pods are unhealthy."""

import json

from tests.helpers_debugger import findings, make_debugger

EP = {"items": [{"metadata": {"name": "web", "namespace": "app"}, "subsets": []}]}


def _svc(selector):
    return {"items": [{"metadata": {"name": "web", "namespace": "app"}, "spec": {"selector": selector}}]}


def _endpoint_findings(dbg):
    return [f for f in findings(dbg, "network_issues") if "app/web" in f["summary"]]


def test_selector_matching_no_pods_is_info_orphaned():
    dbg = make_debugger(
        {
            "get endpoints": json.dumps(EP),
            "get svc": json.dumps(_svc({"app": "web"})),
            "get pods": json.dumps({"items": []}),
            "get deploy": json.dumps({"items": []}),
        }
    )
    dbg.analyze_service_health()
    f = _endpoint_findings(dbg)
    assert len(f) == 1
    assert f[0]["details"]["severity"] == "info"
    assert "matches no pods" in f[0]["summary"]


def test_backing_deployment_scaled_to_zero_is_info():
    deploy = {
        "items": [
            {
                "metadata": {"name": "web", "namespace": "app"},
                "spec": {"replicas": 0, "template": {"metadata": {"labels": {"app": "web"}}}},
            }
        ]
    }
    dbg = make_debugger(
        {
            "get endpoints": json.dumps(EP),
            "get svc": json.dumps(_svc({"app": "web"})),
            "get pods": json.dumps({"items": []}),
            "get deploy": json.dumps(deploy),
        }
    )
    dbg.analyze_service_health()
    f = _endpoint_findings(dbg)
    assert len(f) == 1
    assert f[0]["details"]["severity"] == "info"
    assert "scaled to zero" in f[0]["summary"]


def test_pods_exist_but_not_ready_stays_warning():
    pods = {
        "items": [
            {
                "metadata": {"name": "web-1", "namespace": "app", "labels": {"app": "web"}},
                "status": {"phase": "Running"},
            }
        ]
    }
    dbg = make_debugger(
        {
            "get endpoints": json.dumps(EP),
            "get svc": json.dumps(_svc({"app": "web"})),
            "get pods": json.dumps(pods),
            "get deploy": json.dumps({"items": []}),
        }
    )
    dbg.analyze_service_health()
    f = _endpoint_findings(dbg)
    assert len(f) == 1
    assert f[0]["details"]["severity"] == "warning"
    assert "not ready" in f[0]["summary"]


def test_service_without_selector_is_skipped():
    """Headless and ExternalName services have no selector and no endpoints by design."""
    dbg = make_debugger(
        {
            "get endpoints": json.dumps(EP),
            "get svc": json.dumps(_svc(None)),
            "get pods": json.dumps({"items": []}),
            "get deploy": json.dumps({"items": []}),
        }
    )
    dbg.analyze_service_health()
    assert _endpoint_findings(dbg) == []
