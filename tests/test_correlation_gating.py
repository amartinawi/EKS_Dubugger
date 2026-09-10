"""Correlations need actionable evidence; low-confidence ones are not root causes."""

import json

import eks_comprehensive_debugger as ekd
from tests.helpers_debugger import make_debugger


def test_info_only_dns_finding_does_not_create_correlation():
    """A count of pods using default ndots is a config observation, not an incident."""
    dbg = make_debugger()
    dbg._add_finding("dns_issues", "113 pods using default ndots:5", {"severity": "info"})
    dbg.correlate_findings()
    assert dbg.correlations == []


def test_dns_correlation_requires_coredns_evidence():
    dbg = make_debugger()
    dbg._add_finding("dns_issues", "Service lookup failures in ns app", {"severity": "warning"})
    dbg.correlate_findings()
    assert [c["correlation_type"] for c in dbg.correlations if c["correlation_type"] == "dns_pattern"] == []


def test_coredns_warning_creates_correlation():
    dbg = make_debugger()
    dbg._add_finding("dns_issues", "CoreDNS pod coredns-1 restarting", {"severity": "warning"})
    dbg._add_finding("dns_issues", "Service lookup failures in ns app", {"severity": "warning"})
    dbg.correlate_findings()
    assert "dns_pattern" in [c["correlation_type"] for c in dbg.correlations]


def test_actionable_helper_filters_info():
    dbg = make_debugger()
    dbg._add_finding("dns_issues", "info thing", {"severity": "info"})
    dbg._add_finding("dns_issues", "warning thing", {"severity": "warning"})
    dbg._add_finding("dns_issues", "critical thing", {"severity": "critical"})
    actionable = dbg._actionable("dns_issues")
    assert [f["summary"] for f in actionable] == ["warning thing", "critical thing"]


def test_low_tier_correlation_excluded_from_recommendations():
    dbg = make_debugger()
    dbg.correlations = [
        {
            "correlation_type": "dns_pattern",
            "severity": "warning",
            "root_cause": "x",
            "impact": "y",
            "recommendation": "z",
            "confidence_tier": "low",
            "composite_confidence": 0.4,
        }
    ]
    recs = dbg.generate_recommendations()
    assert not any(r.get("is_correlation") for r in recs)


def test_low_tier_correlation_excluded_from_root_causes():
    results = {
        "metadata": {},
        "summary": {"total_issues": 0, "critical": 0, "warning": 0, "info": 0},
        "findings": {},
        "correlations": [
            {
                "correlation_type": "dns_pattern",
                "severity": "warning",
                "root_cause": "x",
                "impact": "y",
                "recommendation": "z",
                "confidence_tier": "low",
                "composite_confidence": 0.4,
            }
        ],
        "timeline": [],
        "recommendations": [],
    }
    out = json.loads(ekd.LLMJSONOutputFormatter().format(results))
    assert out["potential_root_causes"] == []


def test_high_tier_correlation_is_kept():
    results = {
        "metadata": {},
        "summary": {"total_issues": 0, "critical": 0, "warning": 0, "info": 0},
        "findings": {},
        "correlations": [
            {
                "correlation_type": "oom_pattern",
                "severity": "critical",
                "root_cause": "memory exhaustion",
                "impact": "pods killed",
                "recommendation": "raise limits",
                "confidence_tier": "high",
                "composite_confidence": 0.9,
            }
        ],
        "timeline": [],
        "recommendations": [],
    }
    out = json.loads(ekd.LLMJSONOutputFormatter().format(results))
    assert len(out["potential_root_causes"]) == 1
