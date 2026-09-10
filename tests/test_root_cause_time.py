"""Correlations must report a real time when the findings carry one."""

import json
from datetime import datetime, timedelta, timezone

from tests.helpers_debugger import findings, make_debugger


def _oom_pod(name, finished_at, restarts=40):
    return {
        "metadata": {"name": name, "namespace": "logs"},
        "spec": {"containers": [{"name": "c", "resources": {"limits": {"memory": "128Mi"}}}]},
        "status": {
            "phase": "Running",
            "containerStatuses": [
                {
                    "name": "c",
                    "restartCount": restarts,
                    "state": {"running": {}},
                    "lastState": {
                        "terminated": {"reason": "OOMKilled", "exitCode": 137, "finishedAt": finished_at}
                    },
                }
            ],
        },
    }


def test_oom_finding_exposes_the_kill_time_as_timestamp():
    dbg = make_debugger(
        {"get pods": json.dumps({"items": [_oom_pod("p1", "2026-09-09T09:31:19Z")]}), "get events": ""}
    )
    dbg.check_oom_events()
    detail = findings(dbg, "oom_killed")[0]["details"]
    assert detail["timestamp"] == "2026-09-09T09:31:19Z"


def test_extract_timestamp_understands_termination_and_log_keys():
    dbg = make_debugger()
    assert dbg._extract_timestamp({"finished_at": "2026-09-09T09:31:19Z"}) is not None
    assert dbg._extract_timestamp({"last_seen": "2026-09-09T09:31:19Z"}) is not None
    assert dbg._extract_timestamp({"first_seen": "2026-09-09T09:31:19Z"}) is not None
    assert dbg._extract_timestamp({"nothing": "here"}) is None


def test_oom_correlation_reports_a_real_root_cause_time():
    """The report showed 'Unknown' while every OOM finding carried its kill time."""
    pods = [
        _oom_pod("p1", "2026-09-09T09:31:19Z"),
        _oom_pod("p2", "2026-09-08T22:10:00Z"),
    ]
    dbg = make_debugger({"get pods": json.dumps({"items": pods}), "get events": ""})
    dbg.check_oom_events()
    dbg.correlate_findings()
    oom = next(c for c in dbg.correlations if c["correlation_type"] == "oom_pattern")
    assert oom["root_cause_time"] != "Unknown"
    assert "2026-09-08" in oom["root_cause_time"]  # earliest of the two


def test_timeline_is_limited_to_the_analysis_window():
    """A kill from months ago must not appear in a 24 hour report's timeline."""
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ancient = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    pods = [_oom_pod("recent", recent), _oom_pod("ancient", ancient)]
    dbg = make_debugger({"get pods": json.dumps({"items": pods}), "get events": ""})
    dbg.start_date = now - timedelta(hours=24)
    dbg.end_date = now
    dbg.check_oom_events()
    dbg.correlate_findings()
    buckets = dbg.timeline
    assert buckets, "timeline should not be empty when an in-window event exists"
    joined = " ".join(b["time_bucket"] for b in buckets)
    assert ancient[:7] not in joined
