"""Control plane logs are analyzed across the whole window, aggregated by pattern."""

from tests.helpers_debugger import findings, make_debugger


def test_insights_rows_become_aggregated_findings():
    dbg = make_debugger()
    rows = [
        {
            "comp": "kube-controller-manager",
            "pattern": "Evict",
            "n": "7",
            "first": "2026-09-08 12:04:00.000",
            "last": "2026-09-09 02:31:00.000",
        },
        {
            "comp": "kube-apiserver",
            "pattern": "context deadline exceeded",
            "n": "3",
            "first": "2026-09-08 20:00:00.000",
            "last": "2026-09-08 20:05:00.000",
        },
    ]
    dbg._run_logs_insights = lambda query, limit=100: rows
    dbg.analyze_control_plane_logs()
    f = findings(dbg, "control_plane_issues")
    assert len(f) == 2
    apiserver = next(x for x in f if "kube-apiserver" in x["summary"])
    assert apiserver["details"]["count"] == 3
    assert apiserver["details"]["severity"] == "critical"
    assert apiserver["details"]["finding_type"] == "historical_event"
    assert apiserver["details"]["timestamp"].startswith("2026-09-08T20:00")


def test_non_critical_pattern_is_warning():
    dbg = make_debugger()
    dbg._run_logs_insights = lambda query, limit=100: [
        {"comp": "kube-scheduler", "pattern": "Evict", "n": "2", "first": "2026-09-08 12:00:00.000", "last": ""}
    ]
    dbg.analyze_control_plane_logs()
    f = findings(dbg, "control_plane_issues")
    assert len(f) == 1
    assert f[0]["details"]["severity"] == "warning"


def test_falls_back_to_stream_sampling_when_insights_unavailable():
    dbg = make_debugger()
    dbg._run_logs_insights = lambda query, limit=100: None
    dbg._sample_control_plane_streams = lambda: dbg._add_finding(
        "control_plane_issues", "sampled", {"severity": "warning"}
    )
    dbg.analyze_control_plane_logs()
    assert [x["summary"] for x in findings(dbg, "control_plane_issues")] == ["sampled"]


def test_empty_result_produces_no_findings():
    dbg = make_debugger()
    dbg._run_logs_insights = lambda query, limit=100: []
    dbg.analyze_control_plane_logs()
    assert findings(dbg, "control_plane_issues") == []
