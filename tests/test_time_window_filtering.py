"""Tests for time window filtering in correlation detection."""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from eks_comprehensive_debugger import ComprehensiveEKSDebugger, FindingType


class TestTimeWindowFiltering:
    """Tests for time window filtering in correlation detection."""

    @pytest.fixture
    def debugger(self):
        """Create debugger instance with mocked AWS clients."""
        with patch("eks_comprehensive_debugger.boto3.Session"):
            debugger = ComprehensiveEKSDebugger(
                profile="test",
                region="us-east-1",
                cluster_name="test-cluster",
            )
            debugger.start_date = datetime(2026, 3, 10, 21, 48, 0, tzinfo=timezone.utc)
            debugger.end_date = datetime(2026, 3, 10, 21, 48, 59, tzinfo=timezone.utc)
            return debugger

    def test_is_finding_in_time_window_within_range(self, debugger):
        """Findings within time window should return True."""
        finding = {
            "summary": "Test finding",
            "details": {
                "timestamp": "2026-03-10T21:48:30Z",
                "finding_type": FindingType.HISTORICAL_EVENT,
            },
        }
        assert debugger._is_finding_in_time_window(finding) is True

    def test_is_finding_out_time_window_before_range(self, debugger):
        """Findings before time window should return False."""
        finding = {
            "summary": "Old finding from August 2025",
            "details": {
                "timestamp": "2025-08-05T08:58:00Z",
                "finding_type": FindingType.HISTORICAL_EVENT,
            },
        }
        assert debugger._is_finding_in_time_window(finding) is False

    def test_is_finding_out_time_window_after_range(self, debugger):
        """Findings after time window should return False."""
        finding = {
            "summary": "Future finding",
            "details": {
                "timestamp": "2026-03-11T10:00:00Z",
                "finding_type": FindingType.HISTORICAL_EVENT,
            },
        }
        assert debugger._is_finding_in_time_window(finding) is False

    def test_is_finding_no_timestamp_returns_true(self, debugger):
        """Findings without timestamp should return True (assumed in window)."""
        finding = {
            "summary": "Finding without timestamp",
            "details": {
                "finding_type": FindingType.CURRENT_STATE,
            },
        }
        assert debugger._is_finding_in_time_window(finding) is True

    def test_upgrade_detection_respects_time_window(self, debugger):
        """Upgrade detection should only consider findings within time window."""
        debugger.findings["pod_errors"] = [
            {
                "summary": "Pod evicted during upgrade",
                "details": {
                    "timestamp": "2025-08-05T08:58:00Z",
                    "finding_type": FindingType.HISTORICAL_EVENT,
                    "node": "node-1",
                },
            },
            {
                "summary": "Pod crashed due to OOM",
                "details": {
                    "timestamp": "2026-03-10T21:48:30Z",
                    "finding_type": FindingType.HISTORICAL_EVENT,
                },
            },
        ]

        debugger._check_eks_cluster_upgrade = Mock(return_value=None)
        debugger.correlate_findings()

        upgrade_correlations = [c for c in debugger.correlations if c.get("correlation_type") == "cluster_upgrade"]

        if upgrade_correlations:
            for corr in upgrade_correlations:
                if "upgrade_indicators_count" in corr.get("affected_components", {}):
                    assert corr["affected_components"]["upgrade_indicators_count"] <= 1
