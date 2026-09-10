"""Recommendation priority must follow the evidence, not a static per-category literal."""

from tests.helpers_debugger import make_debugger


def _priorities(dbg):
    return {r["category"]: r["priority"] for r in dbg.generate_recommendations()}


def test_priority_follows_highest_finding_severity():
    dbg = make_debugger()
    dbg._add_finding("node_issues", "Node n1 kubelet one minor behind", {"severity": "info"})
    dbg._add_finding("pvc_issues", "PV x is Released", {"severity": "warning"})
    dbg._add_finding("pod_errors", "Pod a was OOMKilled", {"severity": "critical"})
    priorities = _priorities(dbg)
    assert priorities["node_issues"] == "low"
    assert priorities["pvc_issues"] == "high"
    assert priorities["pod_errors"] == "critical"


def test_node_warnings_do_not_produce_a_critical_recommendation():
    dbg = make_debugger()
    dbg._add_finding("node_issues", "Node group web AMI is 40 days behind", {"severity": "warning"})
    assert _priorities(dbg)["node_issues"] == "high"


def test_all_priorities_are_known_sort_values():
    dbg = make_debugger()
    for category in ("node_issues", "pod_errors", "pvc_issues", "rbac_issues", "workload_security"):
        dbg._add_finding(category, f"{category} finding", {"severity": "warning"})
    valid = {"critical", "high", "medium", "low", "info"}
    for rec in dbg.generate_recommendations():
        assert rec["priority"] in valid, f"{rec['category']} has priority {rec['priority']}"
