"""OOMKilled detection from container status, and OOM reason on restart findings."""

import json

from tests.helpers_debugger import findings, make_debugger

OOM_POD = {
    "metadata": {"name": "logger-abc", "namespace": "logs"},
    "spec": {"containers": [{"name": "fluent", "resources": {"limits": {"memory": "128Mi"}}}]},
    "status": {
        "phase": "Running",
        "containerStatuses": [
            {
                "name": "fluent",
                "restartCount": 992,
                "ready": True,
                "state": {"running": {}},
                "lastState": {
                    "terminated": {
                        "reason": "OOMKilled",
                        "exitCode": 137,
                        "finishedAt": "2026-09-09T09:31:19Z",
                    }
                },
            }
        ],
    },
}


def test_oom_detected_from_last_state_without_events():
    dbg = make_debugger({"get pods": json.dumps({"items": [OOM_POD]}), "get events": ""})
    dbg.check_oom_events()
    oom = findings(dbg, "oom_killed")
    assert len(oom) == 1
    assert "OOMKilled" in oom[0]["summary"]
    assert oom[0]["details"]["memory_limit"] == "128Mi"
    assert oom[0]["details"]["severity"] == "critical"
    assert oom[0]["details"]["finding_type"] == "current_state"


def test_restart_finding_names_oom_reason():
    dbg = make_debugger({"get pods": json.dumps({"items": [OOM_POD]})})
    dbg.analyze_pod_health_deep()
    restarts = [f for f in findings(dbg, "pod_errors") if "restart" in f["summary"].lower()]
    assert restarts, "restart finding missing"
    assert restarts[0]["details"]["last_termination_reason"] == "OOMKilled"
    assert "OOMKilled" in restarts[0]["summary"]


def test_healthy_pod_produces_no_oom_finding():
    healthy = {
        "metadata": {"name": "web-1", "namespace": "app"},
        "spec": {"containers": [{"name": "web", "resources": {}}]},
        "status": {"phase": "Running", "containerStatuses": [{"name": "web", "restartCount": 0, "ready": True}]},
    }
    dbg = make_debugger({"get pods": json.dumps({"items": [healthy]}), "get events": ""})
    dbg.check_oom_events()
    assert findings(dbg, "oom_killed") == []
