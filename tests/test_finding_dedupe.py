"""Findings are deduplicated, and baseline bookkeeping stays out of finding details."""

import eks_comprehensive_debugger as ekd
from tests.helpers_debugger import make_debugger


def test_identical_summary_in_same_category_is_added_once():
    dbg = make_debugger()
    assert dbg._add_finding("pod_errors", "Pod a restarted", {"severity": "warning"}) is True
    assert dbg._add_finding("pod_errors", "Pod a restarted", {"severity": "warning"}) is False
    assert len(dbg.findings["pod_errors"]) == 1


def test_different_summaries_are_both_kept():
    dbg = make_debugger()
    dbg._add_finding("pod_errors", "Pod a restarted", {"severity": "warning"})
    dbg._add_finding("pod_errors", "Pod b restarted", {"severity": "warning"})
    assert len(dbg.findings["pod_errors"]) == 2


def test_same_summary_in_different_categories_is_kept():
    """Cross-category duplication is a separate problem; dedupe is per category."""
    dbg = make_debugger()
    dbg._add_finding("pod_errors", "same text", {"severity": "warning"})
    dbg._add_finding("addon_issues", "same text", {"severity": "warning"})
    assert len(dbg.findings["pod_errors"]) == 1
    assert len(dbg.findings["addon_issues"]) == 1


def test_baseline_annotation_lives_on_finding_not_details(tmp_path, monkeypatch):
    monkeypatch.setattr(ekd, "CACHE_DIR", str(tmp_path))
    tracker = ekd.BaselineTracker(cluster_name="c", region="r", threshold=1)
    findings = {"pod_errors": [{"summary": "Pod a restarted", "details": {"severity": "warning"}}]}
    tracker.annotate(findings)
    finding = findings["pod_errors"][0]
    assert "is_baseline" not in finding["details"]
    assert "baseline_count" not in finding["details"]
    assert finding["baseline"] == {"count": 0, "is_baseline": False}


def test_baseline_marks_recurring_findings(tmp_path, monkeypatch):
    monkeypatch.setattr(ekd, "CACHE_DIR", str(tmp_path))
    tracker = ekd.BaselineTracker(cluster_name="c", region="r", threshold=1)
    findings = {"pod_errors": [{"summary": "Pod a restarted", "details": {}}]}
    tracker.update_and_save(findings)

    tracker2 = ekd.BaselineTracker(cluster_name="c", region="r", threshold=1)
    findings2 = {"pod_errors": [{"summary": "Pod a restarted", "details": {}}]}
    marked = tracker2.annotate(findings2)
    assert marked == 1
    assert findings2["pod_errors"][0]["baseline"]["is_baseline"] is True
