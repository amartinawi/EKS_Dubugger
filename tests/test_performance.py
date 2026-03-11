"""Tests for performance optimization features."""

import pytest
import time
import json
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor
from eks_comprehensive_debugger import ComprehensiveEKSDebugger, PerformanceTracker


class TestBatchKubectlCalls:
    """Test cases for batch kubectl call optimization."""

    @pytest.fixture
    def debugger(self):
        """Create debugger instance with mocked AWS clients."""
        with patch("eks_comprehensive_debugger.boto3.Session"):
            debugger = ComprehensiveEKSDebugger(
                profile="test",
                region="us-east-1",
                cluster_name="test-cluster",
            )
            debugger.safe_kubectl_call = Mock(return_value='{"items": []}')
            return debugger

    def test_batch_kubectl_calls_executes_all_commands(self, debugger):
        """Batch kubectl calls should execute all provided commands."""
        commands = {
            "pods": "kubectl get pods -o json",
            "nodes": "kubectl get nodes -o json",
            "services": "kubectl get services -o json",
        }

        results = debugger._batch_kubectl_calls(commands)

        assert "pods" in results
        assert "nodes" in results
        assert "services" in results
        assert debugger.safe_kubectl_call.call_count == 3

    def test_batch_kubectl_calls_handles_failures_gracefully(self, debugger):
        """Batch calls should handle individual failures without breaking."""
        call_count = [0]

        def mock_kubectl(cmd):
            call_count[0] += 1
            if "nodes" in cmd:
                return None  # Simulate failure
            return '{"items": [{"metadata": {"name": "test"}}]}'

        debugger.safe_kubectl_call = Mock(side_effect=mock_kubectl)

        commands = {
            "pods": "kubectl get pods -o json",
            "nodes": "kubectl get nodes -o json",
            "services": "kubectl get services -o json",
        }

        results = debugger._batch_kubectl_calls(commands)

        assert results["pods"] is not None
        assert results["nodes"] is None  # Failed call
        assert results["services"] is not None

    def test_batch_kubectl_calls_runs_in_parallel(self, debugger):
        """Batch calls should execute in parallel, not sequentially."""
        call_times = []

        def mock_kubectl(cmd):
            call_times.append(time.time())
            time.sleep(0.1)  # Simulate network delay
            return '{"items": []}'

        debugger.safe_kubectl_call = Mock(side_effect=mock_kubectl)

        commands = {f"resource_{i}": f"kubectl get {f'resource_{i}'} -o json" for i in range(5)}

        start = time.time()
        results = debugger._batch_kubectl_calls(commands)
        elapsed = time.time() - start

        assert len(results) == 5
        assert elapsed < 0.8

    def test_collect_cluster_statistics_uses_batching(self, debugger):
        """collect_cluster_statistics should use batch kubectl calls."""
        debugger._batch_kubectl_calls = Mock(
            return_value={
                "namespaces": '{"items": []}',
                "nodes": '{"items": []}',
                "deployments": '{"items": []}',
                "statefulsets": '{"items": []}',
                "daemonsets": '{"items": []}',
                "jobs": '{"items": []}',
                "cronjobs": '{"items": []}',
                "replicasets": '{"items": []}',
                "pods": '{"items": []}',
                "services": '{"items": []}',
                "ingresses": '{"items": []}',
                "networkpolicies": '{"items": []}',
                "endpoints": '{"items": []}',
                "pvc": '{"items": []}',
                "pv": '{"items": []}',
                "storageclasses": '{"items": []}',
                "configmaps": '{"items": []}',
                "secrets": '{"items": []}',
                "serviceaccounts": '{"items": []}',
                "roles": '{"items": []}',
                "rolebindings": '{"items": []}',
                "clusterroles": '{"items": []}',
                "clusterrolebindings": '{"items": []}',
            }
        )

        statistics = debugger.collect_cluster_statistics()

        debugger._batch_kubectl_calls.assert_called_once()
        assert "workloads" in statistics
        assert "networking" in statistics
        assert "infrastructure" in statistics


class TestParallelControlPlaneLogAnalysis:
    """Test cases for parallel control plane log analysis."""

    @pytest.fixture
    def debugger(self):
        """Create debugger instance with mocked AWS clients."""
        with patch("eks_comprehensive_debugger.boto3.Session") as mock_session:
            mock_logs_client = Mock()
            mock_session.return_value.client.return_value = mock_logs_client

            debugger = ComprehensiveEKSDebugger(
                profile="test",
                region="us-east-1",
                cluster_name="test-cluster",
            )
            debugger.logs_client = mock_logs_client
            return debugger

    def test_analyze_control_plane_logs_fetches_streams_in_parallel(self, debugger):
        """Control plane log analysis should fetch streams in parallel."""
        call_times = []

        def mock_api_call(func, *args, **kwargs):
            call_times.append(time.time())
            if "describe_log_streams" in str(func):
                return True, {
                    "logStreams": [
                        {"logStreamName": "stream-1"},
                        {"logStreamName": "stream-2"},
                        {"logStreamName": "stream-3"},
                    ]
                }
            elif "get_log_events" in str(func):
                time.sleep(0.1)
                return True, {"events": []}
            return True, {}

        debugger.safe_api_call = Mock(side_effect=mock_api_call)
        debugger._get_cached_log_group = Mock(return_value={"logGroups": [{"logGroupName": "/aws/eks/test/cluster"}]})

        start = time.time()
        debugger.analyze_control_plane_logs()
        elapsed = time.time() - start

        assert elapsed < 0.8

    def test_analyze_control_plane_logs_handles_empty_streams(self, debugger):
        """Should handle empty log streams gracefully."""
        debugger.safe_api_call = Mock(return_value=(True, {"logStreams": []}))
        debugger._get_cached_log_group = Mock(return_value={"logGroups": [{"logGroupName": "/aws/eks/test/cluster"}]})

        debugger.analyze_control_plane_logs()

        assert len(debugger.findings["control_plane_issues"]) == 0


class TestPerformanceTrackerWithParallelism:
    """Test PerformanceTracker with parallel execution."""

    def test_tracker_records_parallel_method_timings(self):
        """PerformanceTracker should accurately record timings from parallel execution."""
        tracker = PerformanceTracker()

        def simulate_analysis(method_name, duration):
            start = time.time()
            time.sleep(duration)
            tracker.record(method_name, time.time() - start)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for i in range(5):
                futures.append(executor.submit(simulate_analysis, f"method_{i % 3}", 0.05))

            for future in futures:
                future.result()

        summary = tracker.get_summary()
        assert len(summary) == 3
        for method_stats in summary.values():
            assert method_stats["calls"] > 0

    def test_get_slowest_methods_with_concurrent_recording(self):
        """get_slowest should work correctly with concurrent recordings."""
        tracker = PerformanceTracker()

        def record_many():
            for i in range(100):
                tracker.record(f"method_{i % 10}", 0.001 * (i + 1))

        threads = []
        for _ in range(5):
            t = MagicMock()
            t.start = lambda: record_many()
            threads.append(t)

        for t in threads:
            t.start()

        slowest = tracker.get_slowest(limit=5)
        assert len(slowest) <= 5
        if len(slowest) > 1:
            for i in range(len(slowest) - 1):
                assert slowest[i][1] >= slowest[i + 1][1]


class TestStatisticsCollectionPerformance:
    """Test statistics collection performance improvements."""

    @pytest.fixture
    def debugger(self):
        """Create debugger with mocked components."""
        with patch("eks_comprehensive_debugger.boto3.Session"):
            debugger = ComprehensiveEKSDebugger(
                profile="test",
                region="us-east-1",
                cluster_name="test-cluster",
            )
            return debugger

    def test_statistics_collection_with_large_cluster(self, debugger):
        """Statistics collection should handle large clusters efficiently."""
        large_response = json.dumps(
            {
                "items": [
                    {
                        "metadata": {"name": f"resource-{i}", "namespace": "default"},
                        "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
                    }
                    for i in range(1000)
                ]
            }
        )

        debugger._batch_kubectl_calls = Mock(
            return_value={
                key: large_response
                for key in [
                    "namespaces",
                    "nodes",
                    "deployments",
                    "statefulsets",
                    "daemonsets",
                    "jobs",
                    "cronjobs",
                    "replicasets",
                    "pods",
                    "services",
                    "ingresses",
                    "networkpolicies",
                    "endpoints",
                    "pvc",
                    "pv",
                    "storageclasses",
                    "configmaps",
                    "secrets",
                    "serviceaccounts",
                    "roles",
                    "rolebindings",
                    "clusterroles",
                    "clusterrolebindings",
                ]
            }
        )

        start = time.time()
        statistics = debugger.collect_cluster_statistics()
        elapsed = time.time() - start

        assert elapsed < 2.0
        assert statistics["workloads"]["pods"] == 1000


class TestParallelExecutionSafety:
    """Test thread safety of parallel execution."""

    @pytest.fixture
    def debugger(self):
        """Create debugger with thread-safe structures."""
        with patch("eks_comprehensive_debugger.boto3.Session"):
            debugger = ComprehensiveEKSDebugger(
                profile="test",
                region="us-east-1",
                cluster_name="test-cluster",
            )
            return debugger

    def test_concurrent_finding_additions(self, debugger):
        """Adding findings concurrently should be thread-safe."""

        def add_findings(category, count):
            for i in range(count):
                debugger._add_finding_dict(
                    category,
                    {
                        "summary": f"Finding {i}",
                        "details": {"index": i},
                    },
                )

        threads = []
        for _ in range(5):
            t = MagicMock()
            t.start = lambda: add_findings("test_category", 100)
            threads.append(t)

        for t in threads:
            t.start()

        total = sum(len(v) for v in debugger.findings.values())
        assert total <= 500

    def test_concurrent_error_additions(self, debugger):
        """Adding errors concurrently should be thread-safe."""

        def add_errors(count):
            for i in range(count):
                debugger._add_error("test_step", f"Error {i}")

        import threading

        threads = []
        for _ in range(5):
            t = threading.Thread(target=add_errors, args=(50,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(debugger.errors) == 250
