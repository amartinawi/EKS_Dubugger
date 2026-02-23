"""Tests for findings management (limits, thread safety)."""

import pytest
import threading
from eks_comprehensive_debugger import ComprehensiveEKSDebugger, MAX_FINDINGS_PER_CATEGORY


class TestAddFinding:
    """Test cases for _add_finding method."""

    @pytest.fixture
    def debugger(self, mocker):
        """Create a debugger instance with mocked AWS clients."""
        mocker.patch("boto3.Session")
        debugger = ComprehensiveEKSDebugger(
            profile="test",
            region="us-east-1",
            cluster_name="test-cluster",
        )
        return debugger

    def test_add_finding_basic(self, debugger):
        """Basic finding addition should work."""
        result = debugger._add_finding(
            "pod_errors",
            "Test finding",
            {"key": "value"},
        )
        assert result is True
        assert len(debugger.findings["pod_errors"]) == 1
        assert debugger.findings["pod_errors"][0]["summary"] == "Test finding"
        assert debugger.findings["pod_errors"][0]["details"]["key"] == "value"
        assert debugger.findings["pod_errors"][0]["details"]["finding_type"] == "current_state"

    def test_add_finding_with_type(self, debugger):
        """Finding with explicit type should preserve it."""
        from eks_comprehensive_debugger import FindingType

        result = debugger._add_finding(
            "node_issues",
            "Historical finding",
            finding_type=FindingType.HISTORICAL_EVENT,
        )
        assert result is True
        assert debugger.findings["node_issues"][0]["details"]["finding_type"] == "historical_event"

    def test_add_finding_default_details(self, debugger):
        """Finding without details should get empty dict."""
        result = debugger._add_finding("pod_errors", "No details")
        assert result is True
        assert debugger.findings["pod_errors"][0]["details"] == {"finding_type": "current_state"}

    def test_add_finding_respects_limit(self, debugger):
        """Adding findings should respect max_findings limit."""
        debugger.max_findings = 3

        # First 3 should succeed
        assert debugger._add_finding("pod_errors", "Finding 1") is True
        assert debugger._add_finding("pod_errors", "Finding 2") is True
        assert debugger._add_finding("pod_errors", "Finding 3") is True

        # 4th should fail (limit reached)
        assert debugger._add_finding("pod_errors", "Finding 4") is False

        # Should only have 3 findings
        assert len(debugger.findings["pod_errors"]) == 3

    def test_add_finding_separate_limits_per_category(self, debugger):
        """Each category should have its own limit."""
        debugger.max_findings = 2

        # Add 2 to each category
        debugger._add_finding("pod_errors", "P1")
        debugger._add_finding("pod_errors", "P2")
        debugger._add_finding("node_issues", "N1")
        debugger._add_finding("node_issues", "N2")

        # Both should be at limit
        assert debugger._add_finding("pod_errors", "P3") is False
        assert debugger._add_finding("node_issues", "N3") is False

        # But new category should work
        assert debugger._add_finding("network_issues", "NW1") is True


class TestAddFindingDict:
    """Test cases for _add_finding_dict method."""

    @pytest.fixture
    def debugger(self, mocker):
        """Create a debugger instance with mocked AWS clients."""
        mocker.patch("boto3.Session")
        debugger = ComprehensiveEKSDebugger(
            profile="test",
            region="us-east-1",
            cluster_name="test-cluster",
        )
        return debugger

    def test_add_finding_dict_basic(self, debugger):
        """Adding finding via dict should work."""
        finding = {
            "summary": "Dict finding",
            "details": {"key": "value"},
        }
        result = debugger._add_finding_dict("pod_errors", finding)
        assert result is True
        assert len(debugger.findings["pod_errors"]) == 1

    def test_add_finding_dict_extracts_finding_type(self, debugger):
        """Finding type should be extracted from details."""
        from eks_comprehensive_debugger import FindingType

        finding = {
            "summary": "Historical finding",
            "details": {"finding_type": FindingType.HISTORICAL_EVENT},
        }
        debugger._add_finding_dict("pod_errors", finding)
        assert debugger.findings["pod_errors"][0]["details"]["finding_type"] == "historical_event"

    def test_add_finding_dict_respects_limit(self, debugger):
        """_add_finding_dict should also respect limits."""
        debugger.max_findings = 1

        assert debugger._add_finding_dict("pod_errors", {"summary": "F1"}) is True
        assert debugger._add_finding_dict("pod_errors", {"summary": "F2"}) is False


class TestThreadSafety:
    """Test thread safety of findings collection."""

    @pytest.fixture
    def debugger(self, mocker):
        """Create a debugger instance with mocked AWS clients."""
        mocker.patch("boto3.Session")
        debugger = ComprehensiveEKSDebugger(
            profile="test",
            region="us-east-1",
            cluster_name="test-cluster",
        )
        debugger.max_findings = 10000  # High limit for concurrency test
        return debugger

    def test_concurrent_add_finding(self, debugger):
        """Concurrent _add_finding calls should not lose data."""
        num_threads = 10
        findings_per_thread = 100
        threads = []

        def add_findings(thread_id):
            for i in range(findings_per_thread):
                debugger._add_finding(
                    "pod_errors",
                    f"Thread {thread_id} finding {i}",
                )

        for i in range(num_threads):
            t = threading.Thread(target=add_findings, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Should have all findings (no lost writes)
        assert len(debugger.findings["pod_errors"]) == num_threads * findings_per_thread

    def test_concurrent_add_finding_dict(self, debugger):
        """Concurrent _add_finding_dict calls should not lose data."""
        num_threads = 10
        findings_per_thread = 100
        threads = []

        def add_findings(thread_id):
            for i in range(findings_per_thread):
                debugger._add_finding_dict(
                    "pod_errors",
                    {"summary": f"Thread {thread_id} finding {i}"},
                )

        for i in range(num_threads):
            t = threading.Thread(target=add_findings, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Should have all findings (no lost writes)
        assert len(debugger.findings["pod_errors"]) == num_threads * findings_per_thread
