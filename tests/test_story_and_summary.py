"""The incident story and executive summary must not invent times or categories."""

import eks_comprehensive_debugger as ekd
from tests.helpers_debugger import make_debugger


def test_story_without_timestamps_has_no_synthetic_events():
    dbg = make_debugger()
    dbg.correlations = [
        {
            "correlation_type": "dns_pattern",
            "severity": "warning",
            "root_cause": "x",
            "impact": "y",
            "recommendation": "z",
            "confidence_tier": "high",
        }
    ]
    story = dbg._generate_incident_story()
    assert story["timeline"] == []
    assert "Affected Areas" not in story["summary"]


def test_story_summary_omits_time_range_when_unknown():
    """With findings but no timestamps, the summary must not print a fabricated window."""
    dbg = make_debugger()
    dbg._add_finding("oom_killed", "Pod a was OOMKilled", {"severity": "critical"})
    dbg.correlations = [
        {
            "correlation_type": "oom_pattern",
            "severity": "critical",
            "root_cause": "memory",
            "impact": "pods killed",
            "recommendation": "raise limits",
            "confidence_tier": "high",
        }
    ]
    story = dbg._generate_incident_story()
    assert "N/A" not in story["summary"]
    assert "Incident Summary" in story["summary"]
    assert "()" not in story["summary"]


def test_quick_wins_pick_high_restart_pod():
    gen = ekd.ExecutiveSummaryGenerator()
    findings = {
        "pod_errors": [
            {
                "summary": "Pod ns/low container c restarted 5 times",
                "details": {"pod": "low", "namespace": "ns", "severity": "warning"},
            },
            {
                "summary": "Pod ns/high container c has high restart count: 989",
                "details": {"pod": "high", "namespace": "ns", "severity": "critical"},
            },
        ]
    }
    wins = gen._classify_quick_wins(findings, [])
    restart = next(w for w in wins if w["title"] == "Investigate Restarting Pod")
    assert restart["affected_pod"] == "high"


def test_recommendation_evidence_excludes_namespaces():
    """A namespace listed among pod names makes the evidence list unreadable."""
    dbg = make_debugger()
    dbg._add_finding(
        "workload_security",
        "DaemonSet ci/runner runs privileged containers",
        {"namespace": "ci", "owner": "runner", "severity": "warning"},
    )
    rec = next(r for r in dbg.generate_recommendations() if r["category"] == "workload_security")
    assert "ci" not in rec["evidence"]["affected_resources"]
    assert "runner" in rec["evidence"]["affected_resources"]
