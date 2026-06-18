"""Tests for BaselineTracker — finding frequency tracking across analysis runs.

Covers fingerprint normalization, load/save/update cycle, annotation logic,
file permissions (0o600), and edge cases.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from eks_comprehensive_debugger import BaselineTracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_cache_dir(tmp_path, monkeypatch):
    """Redirect CACHE_DIR to a temp directory so tests don't touch real cache."""
    cache_dir = tmp_path / ".eks-debugger-cache"
    cache_dir.mkdir()
    # Patch the module-level CACHE_DIR used by BaselineTracker
    import eks_comprehensive_debugger as mod

    monkeypatch.setattr(mod, "CACHE_DIR", str(cache_dir))
    return cache_dir


@pytest.fixture
def tracker(temp_cache_dir):
    """A BaselineTracker with threshold=3 (low for fast testing)."""
    return BaselineTracker("test-cluster", "us-east-1", threshold=3)


@pytest.fixture
def sample_findings():
    """Realistic findings dict matching the debugger's self.findings shape."""
    return {
        "pod_errors": [
            {
                "summary": "Pod app-x-abc123 in CrashLoopBackOff",
                "details": {"severity": "critical", "namespace": "default"},
            },
            {
                "summary": "Pod app-y in CrashLoopBackOff",
                "details": {"severity": "critical", "namespace": "default"},
            },
        ],
        "node_issues": [
            {
                "summary": "Node ip-10-0-1-50 is NotReady",
                "details": {"severity": "critical", "node": "ip-10-0-1-50"},
            },
        ],
        "control_plane_issues": [],
    }


# ---------------------------------------------------------------------------
# Fingerprint Normalization
# ---------------------------------------------------------------------------


class TestFingerprintNormalization:
    def test_same_summary_same_fingerprint(self, tracker):
        """Identical summaries produce identical fingerprints."""
        fp1 = tracker._fingerprint("pod_errors", "Pod crash")
        fp2 = tracker._fingerprint("pod_errors", "Pod crash")
        assert fp1 == fp2

    def test_different_category_different_fingerprint(self, tracker):
        """Same summary but different category = different fingerprint."""
        fp1 = tracker._fingerprint("pod_errors", "Node down")
        fp2 = tracker._fingerprint("node_issues", "Node down")
        assert fp1 != fp2

    def test_timestamps_normalized(self, tracker):
        """ISO timestamps are stripped so they don't affect the fingerprint."""
        fp1 = tracker._fingerprint("oom_killed", "OOM at 2026-06-18T10:30:00Z")
        fp2 = tracker._fingerprint("oom_killed", "OOM at 2026-06-19T11:00:00Z")
        assert fp1 == fp2

    def test_instance_ids_normalized(self, tracker):
        """EC2 instance IDs are stripped."""
        fp1 = tracker._fingerprint("node_issues", "Node i-0abc123def456 not ready")
        fp2 = tracker._fingerprint("node_issues", "Node i-0abc789def012 not ready")
        assert fp1 == fp2

    def test_ip_addresses_normalized(self, tracker):
        """IP addresses are stripped."""
        fp1 = tracker._fingerprint("network_issues", "DNS timeout from 10.0.1.50")
        fp2 = tracker._fingerprint("network_issues", "DNS timeout from 10.0.2.99")
        assert fp1 == fp2

    def test_pod_hashes_normalized(self, tracker):
        """Kubernetes pod hash suffixes are stripped."""
        fp1 = tracker._fingerprint("pod_errors", "Pod app-x-a1b2c3d4e in CrashLoopBackOff")
        fp2 = tracker._fingerprint("pod_errors", "Pod app-x-f9e8d7c6b in CrashLoopBackOff")
        assert fp1 == fp2

    def test_case_insensitive(self, tracker):
        """Summary is lowercased before fingerprinting."""
        fp1 = tracker._fingerprint("pod_errors", "Pod Crash")
        fp2 = tracker._fingerprint("pod_errors", "pod crash")
        assert fp1 == fp2


# ---------------------------------------------------------------------------
# Load / Save / Update Cycle
# ---------------------------------------------------------------------------


class TestLoadSaveUpdate:
    def test_first_load_returns_empty(self, tracker):
        """No cache file = empty fingerprints."""
        tracker.load()
        assert tracker._fingerprints == {}
        assert tracker._total_runs == 0

    def test_update_increments_counts(self, tracker, sample_findings):
        """update_and_save should increment fingerprint counts."""
        tracker.update_and_save(sample_findings)
        # 3 unique findings (2 pod_errors + 1 node_issues; control_plane is empty)
        assert len(tracker._fingerprints) == 3
        assert all(c == 1 for c in tracker._fingerprints.values())
        assert tracker._total_runs == 1

    def test_multiple_runs_accumulate(self, tracker, sample_findings):
        """Running update twice should double counts for same findings."""
        tracker.update_and_save(sample_findings)
        tracker.update_and_save(sample_findings)
        assert all(c == 2 for c in tracker._fingerprints.values())
        assert tracker._total_runs == 2

    def test_persistence_across_instances(self, tracker, sample_findings):
        """A new BaselineTracker for the same cluster should load saved data."""
        tracker.update_and_save(sample_findings)

        # Create a new tracker for the same cluster
        tracker2 = BaselineTracker("test-cluster", "us-east-1", threshold=3)
        tracker2.load()
        assert tracker2._fingerprints == tracker._fingerprints
        assert tracker2._total_runs == 1

    def test_different_cluster_separate_cache(self, tracker, sample_findings):
        """Different cluster = different cache file."""
        tracker.update_and_save(sample_findings)

        tracker2 = BaselineTracker("other-cluster", "us-east-1", threshold=3)
        tracker2.load()
        assert tracker2._fingerprints == {}
        assert tracker2._total_runs == 0

    def test_file_permissions_0600(self, tracker, sample_findings):
        """Cache file must be owner-only (0o600)."""
        tracker.update_and_save(sample_findings)
        mode = stat.S_IMODE(os.stat(tracker.cache_file).st_mode)
        assert mode == 0o600

    def test_corrupt_cache_handled_gracefully(self, tracker, temp_cache_dir):
        """Corrupt JSON in cache file should not crash — start fresh."""
        # Write garbage to the cache file
        tracker.cache_file  # ensure path is set
        with open(tracker.cache_file, "w") as f:
            f.write("{corrupt json!!!")

        tracker.load()
        assert tracker._fingerprints == {}
        assert tracker._total_runs == 0

    def test_wrong_version_cache_ignored(self, tracker, sample_findings, temp_cache_dir):
        """Cache with wrong version number should be ignored."""
        # Manually write a cache with wrong version
        with open(tracker.cache_file, "w") as f:
            json.dump(
                {"version": 999, "total_runs": 50, "fingerprints": {"abc": 99}},
                f,
            )

        tracker.load()
        assert tracker._fingerprints == {}
        assert tracker._total_runs == 0


# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------


class TestAnnotation:
    def test_no_baseline_on_first_run(self, tracker, sample_findings):
        """First run: nothing should be baseline (all counts are 0)."""
        count = tracker.annotate(sample_findings)
        assert count == 0
        for items in sample_findings.values():
            for item in items:
                assert item["details"]["is_baseline"] is False
                assert item["details"]["baseline_count"] == 0

    def test_baseline_after_threshold_runs(self, tracker, sample_findings):
        """After threshold runs, findings should be marked baseline."""
        # Simulate 3 prior runs (threshold=3)
        for _ in range(3):
            tracker.update_and_save(sample_findings)

        # Now annotate — these findings have been seen 3 times
        count = tracker.annotate(sample_findings)
        assert count == 3  # all 3 findings are baseline
        for items in sample_findings.values():
            for item in items:
                assert item["details"]["is_baseline"] is True
                assert item["details"]["baseline_count"] == 3

    def test_below_threshold_not_baseline(self, tracker, sample_findings):
        """Findings seen fewer times than threshold should NOT be baseline."""
        # 2 prior runs (threshold=3)
        tracker.update_and_save(sample_findings)
        tracker.update_and_save(sample_findings)

        count = tracker.annotate(sample_findings)
        assert count == 0  # none are baseline yet (count=2, threshold=3)
        for items in sample_findings.values():
            for item in items:
                assert item["details"]["is_baseline"] is False
                assert item["details"]["baseline_count"] == 2

    def test_threshold_zero_disables_baseline(self, temp_cache_dir):
        """threshold=0 means baseline tracking is disabled."""
        tracker = BaselineTracker("test", "us-east-1", threshold=0)
        findings = {
            "cat": [{"summary": "x", "details": {}}],
        }
        # Simulate many runs
        for _ in range(20):
            tracker.update_and_save(findings)

        count = tracker.annotate(findings)
        assert count == 0  # disabled, nothing is baseline
        assert findings["cat"][0]["details"]["is_baseline"] is False

    def test_annotate_then_update_order(self, tracker, sample_findings):
        """annotate() should reflect PREVIOUS runs, not current.

        Call order: annotate → update_and_save.
        After 2 prior runs + annotate + update: count should be 2 (from annotate),
        then 3 (after update). But annotate showed 2, so not baseline yet.
        """
        # 2 prior runs
        tracker.update_and_save(sample_findings)
        tracker.update_and_save(sample_findings)

        # Annotate (should see count=2, below threshold=3)
        count = tracker.annotate(sample_findings)
        assert count == 0
        assert sample_findings["pod_errors"][0]["details"]["baseline_count"] == 2

        # Now update (increment to 3)
        tracker.update_and_save(sample_findings)

        # Next run's annotate would see count=3 (baseline)
        count = tracker.annotate(sample_findings)
        assert count == 3

    def test_empty_findings_no_crash(self, tracker):
        """Empty findings dict should not crash."""
        count = tracker.annotate({})
        assert count == 0
        tracker.update_and_save({})

    def test_malformed_findings_no_crash(self, tracker):
        """Malformed finding items should be skipped gracefully."""
        findings = {
            "cat": [
                {"summary": "good", "details": {}},
                "not a proper finding",  # string instead of dict
                {"no_summary": True},  # missing summary
                {"summary": "also good", "details": "not_a_dict"},  # bad details
            ],
        }
        # Should not raise
        count = tracker.annotate(findings)
        tracker.update_and_save(findings)
        # The two "good" findings should have been processed
        assert findings["cat"][0]["details"].get("baseline_count") is not None


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_structure(self, tracker, sample_findings):
        """get_summary should return expected fields."""
        tracker.update_and_save(sample_findings)
        summary = tracker.get_summary()
        assert summary["enabled"] is True
        assert summary["total_runs"] == 1
        assert summary["threshold"] == 3
        assert summary["unique_fingerprints_tracked"] == 3
        assert summary["fingerprints_at_or_above_threshold"] == 0

    def test_summary_disabled(self, temp_cache_dir):
        """Disabled tracker (threshold=0) should report enabled=False."""
        tracker = BaselineTracker("test", "us-east-1", threshold=0)
        summary = tracker.get_summary()
        assert summary["enabled"] is False
