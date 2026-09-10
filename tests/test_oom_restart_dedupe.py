"""An OOM-killed container is reported once, by the analyzer that explains it."""

import json

from tests.helpers_debugger import findings, make_debugger


def _pod(reason):
    last_state = {"terminated": {"reason": reason, "exitCode": 137 if reason == "OOMKilled" else 1}} if reason else {}
    return {
        "metadata": {"name": "logger", "namespace": "logs"},
        "spec": {"containers": [{"name": "c", "resources": {"limits": {"memory": "128Mi"}}}]},
        "status": {
            "phase": "Running",
            "containerStatuses": [
                {"name": "c", "restartCount": 40, "state": {"running": {}}, "lastState": last_state}
            ],
        },
    }


def test_oom_restart_is_not_also_a_pod_error():
    """The OOM finding names the limit and the cause, so the bare restart count adds nothing."""
    pods = json.dumps({"items": [_pod("OOMKilled")]})
    dbg = make_debugger({"get pods": pods, "get events": ""})
    dbg.analyze_pod_health_deep()
    dbg.check_oom_events()
    restart_findings = [f for f in findings(dbg, "pod_errors") if "restart" in f["summary"].lower()]
    oom_findings = findings(dbg, "oom_killed")
    assert restart_findings == []
    assert len(oom_findings) == 1
    assert "128Mi" in oom_findings[0]["summary"]


def test_non_oom_restart_is_still_reported():
    pods = json.dumps({"items": [_pod("Error")]})
    dbg = make_debugger({"get pods": pods, "get events": ""})
    dbg.analyze_pod_health_deep()
    restart_findings = [f for f in findings(dbg, "pod_errors") if "restart" in f["summary"].lower()]
    assert len(restart_findings) == 1
    assert restart_findings[0]["details"]["last_termination_reason"] == "Error"


def test_restart_without_last_state_is_still_reported():
    pods = json.dumps({"items": [_pod(None)]})
    dbg = make_debugger({"get pods": pods, "get events": ""})
    dbg.analyze_pod_health_deep()
    restart_findings = [f for f in findings(dbg, "pod_errors") if "restart" in f["summary"].lower()]
    assert len(restart_findings) == 1
