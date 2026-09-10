"""OOM severity must reflect whether the container is looping or was killed once."""

import json

from tests.helpers_debugger import findings, make_debugger


def _pod(name, restarts, limit="128Mi"):
    return {
        "metadata": {"name": name, "namespace": "logs"},
        "spec": {"containers": [{"name": "c", "resources": {"limits": {"memory": limit}}}]},
        "status": {
            "phase": "Running",
            "containerStatuses": [
                {
                    "name": "c",
                    "restartCount": restarts,
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


def _severity(dbg, pod_name):
    for f in findings(dbg, "oom_killed"):
        if pod_name in f["summary"]:
            return f["details"]["severity"]
    raise AssertionError(f"no OOM finding for {pod_name}")


def test_repeatedly_killed_container_is_critical():
    dbg = make_debugger({"get pods": json.dumps({"items": [_pod("looping", 998)]}), "get events": ""})
    dbg.check_oom_events()
    assert _severity(dbg, "looping") == "critical"


def test_single_kill_is_warning():
    dbg = make_debugger({"get pods": json.dumps({"items": [_pod("once", 1)]}), "get events": ""})
    dbg.check_oom_events()
    assert _severity(dbg, "once") == "warning"


def test_threshold_boundary_is_critical():
    dbg = make_debugger({"get pods": json.dumps({"items": [_pod("boundary", 10)]}), "get events": ""})
    dbg.check_oom_events()
    assert _severity(dbg, "boundary") == "critical"


def test_recommendation_names_the_container_either_way():
    dbg = make_debugger({"get pods": json.dumps({"items": [_pod("once", 1)]}), "get events": ""})
    dbg.check_oom_events()
    finding = next(f for f in findings(dbg, "oom_killed") if "once" in f["summary"])
    assert "c" in finding["details"]["recommendation"]
