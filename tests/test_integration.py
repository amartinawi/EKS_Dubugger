"""
Integration tests for EKS Comprehensive Debugger.

Tests the main debugger class with mocked AWS services and kubectl commands.
"""

import json
import pytest
from unittest.mock import Mock, MagicMock, patch
from eks_comprehensive_debugger import (
    validate_input,
    ComprehensiveEKSDebugger,
    InputValidationError,
)


class TestInputValidation:
    """Test input validation for security."""

    def test_valid_inputs_pass_validation(self):
        """Valid inputs should pass validation."""
        valid_inputs = [
            ("profile", "prod-profile"),
            ("cluster_name", "my-cluster-1"),
            ("namespace", "kube-system"),
            ("region", "us-east-1"),
            ("kube_context", "arn:aws:eks:us-east-1:123:cluster/test"),
        ]

        for input_name, valid_value in valid_inputs:
            # Should not raise
            result = validate_input(input_name, valid_value)
            assert result == valid_value

    def test_shell_injection_blocked(self):
        """Shell injection attempts should be blocked."""
        malicious_inputs = [
            ("profile", "prod; rm -rf /"),
            ("cluster_name", "cluster$(whoami)"),
            ("namespace", "default`id`"),
            ("region", "us-east-1 && cat /etc/passwd"),
        ]

        for input_name, malicious_value in malicious_inputs:
            with pytest.raises(InputValidationError):
                validate_input(input_name, malicious_value)


class TestRemediationCommands:
    """Test remediation command generation."""

    def test_crashloopbackoff_remediation(self):
        """CrashLoopBackOff should generate remediation commands."""
        from eks_comprehensive_debugger import get_remediation_commands

        summary = "Pod test-pod is in CrashLoopBackOff"
        details = {
            "namespace": "default",
            "pod": "test-pod",
            "container": "app",
        }

        commands = get_remediation_commands(summary, details)

        assert commands is not None
        assert "diagnostic" in commands
        assert "fix" in commands
        assert any("logs" in cmd for cmd in commands["diagnostic"])

    def test_oomkilled_remediation(self):
        """OOMKilled should generate memory-related remediation."""
        from eks_comprehensive_debugger import get_remediation_commands

        summary = "Container was OOMKilled"
        details = {
            "namespace": "default",
            "pod": "test-pod",
            "container": "app",
            "exit_code": 137,
        }

        commands = get_remediation_commands(summary, details)

        assert commands is not None
        assert any("memory" in cmd.lower() for cmd in commands["fix"])


class TestPodAnalysisMethods:
    """Test pod analysis methods with mocked kubectl."""

    @pytest.fixture
    def debugger(self):
        """Create debugger instance with mocked AWS clients."""
        with patch("eks_comprehensive_debugger.boto3.Session") as mock_session:
            mock_session.return_value.client.return_value = Mock()
            from datetime import datetime, timezone

            # Set date range to include test data from 2024-01-15
            debugger = ComprehensiveEKSDebugger(
                cluster_name="test-cluster",
                region="us-east-1",
                profile=None,
                namespace=None,
                start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2024, 1, 31, tzinfo=timezone.utc),
            )
            debugger.progress = Mock()
            return debugger

    def test_analyze_pod_evictions(self, debugger):
        """Test pod eviction analysis."""
        mock_events = {
            "items": [
                {
                    "metadata": {"namespace": "default", "name": "pod-1.abc123"},
                    "reason": "Evicted",
                    "message": "Pod was evicted due to memory pressure",
                    "involvedObject": {"name": "pod-1", "kind": "Pod"},
                    "count": 1,
                    "lastTimestamp": "2024-01-15T10:00:00Z",
                }
            ]
        }

        with patch.object(debugger, "safe_kubectl_call", return_value=json.dumps(mock_events)):
            debugger.analyze_pod_evictions()

        assert len(debugger.findings["memory_pressure"]) > 0
        finding = debugger.findings["memory_pressure"][0]
        assert "evicted" in finding["summary"].lower()
        # Memory information is in details["reason"], not in summary
        assert "memory" in finding["details"]["reason"].lower()

    def test_check_oom_events(self, debugger):
        """Test OOM event detection."""
        mock_events = {
            "items": [
                {
                    "metadata": {"namespace": "default", "name": "pod-1.abc123"},
                    "reason": "OOMKilled",
                    "message": "Container app was OOMKilled",
                    "involvedObject": {"name": "pod-1", "kind": "Pod"},
                    "count": 1,
                    "lastTimestamp": "2024-01-15T10:00:00Z",
                }
            ]
        }

        with patch.object(debugger, "safe_kubectl_call", return_value=json.dumps(mock_events)):
            debugger.check_oom_events()

        assert len(debugger.findings["oom_killed"]) > 0
        finding = debugger.findings["oom_killed"][0]
        assert "oom" in finding["summary"].lower()

    def test_analyze_pod_health_deep_crashloopbackoff(self, debugger):
        """Test CrashLoopBackOff detection in pod health analysis."""
        mock_pods = {
            "items": [
                {
                    "metadata": {
                        "namespace": "default",
                        "name": "crashloop-pod",
                    },
                    "status": {
                        "phase": "Running",
                        "containerStatuses": [
                            {
                                "name": "app",
                                "restartCount": 5,
                                "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                            }
                        ],
                    },
                }
            ]
        }

        with patch.object(debugger, "safe_kubectl_call", return_value=json.dumps(mock_pods)):
            debugger.analyze_pod_health_deep()

        assert len(debugger.findings["pod_errors"]) > 0
        finding = debugger.findings["pod_errors"][0]
        assert "crashloopbackoff" in finding["summary"].lower()


class TestNodeAnalysisMethods:
    """Test node analysis methods with mocked kubectl."""

    @pytest.fixture
    def debugger(self):
        """Create debugger instance with mocked AWS clients."""
        with patch("eks_comprehensive_debugger.boto3.Session") as mock_session:
            mock_session.return_value.client.return_value = Mock()
            debugger = ComprehensiveEKSDebugger(
                cluster_name="test-cluster",
                region="us-east-1",
                profile=None,
                namespace=None,
            )
            debugger.progress = Mock()
            return debugger

    def test_analyze_node_conditions_notready(self, debugger):
        """Test NotReady node detection."""
        mock_nodes = {
            "items": [
                {
                    "metadata": {"name": "ip-10-0-1-50.ec2.internal"},
                    "status": {
                        "conditions": [
                            {
                                "type": "Ready",
                                "status": "False",
                                "lastTransitionTime": "2024-01-15T10:00:00Z",
                                "reason": "KubeletNotReady",
                            }
                        ]
                    },
                }
            ]
        }

        with patch.object(debugger, "safe_kubectl_call", return_value=json.dumps(mock_nodes)):
            debugger.analyze_node_conditions()

        assert len(debugger.findings["node_issues"]) > 0
        finding = debugger.findings["node_issues"][0]
        assert "not ready" in finding["summary"].lower() or "notready" in finding["summary"].lower()

    def test_analyze_node_conditions_memory_pressure(self, debugger):
        """Test MemoryPressure node detection."""
        mock_nodes = {
            "items": [
                {
                    "metadata": {"name": "ip-10-0-1-50.ec2.internal"},
                    "status": {
                        "conditions": [
                            {
                                "type": "Ready",
                                "status": "True",
                            },
                            {
                                "type": "MemoryPressure",
                                "status": "True",
                                "lastTransitionTime": "2024-01-15T10:00:00Z",
                            },
                        ]
                    },
                }
            ]
        }

        with patch.object(debugger, "safe_kubectl_call", return_value=json.dumps(mock_nodes)):
            debugger.analyze_node_conditions()

        # MemoryPressure findings go to both memory_pressure and node_issues
        total_findings = len(debugger.findings["node_issues"]) + len(debugger.findings.get("memory_pressure", []))
        assert total_findings > 0

        # Check either category
        if debugger.findings.get("memory_pressure"):
            finding = debugger.findings["memory_pressure"][0]
        else:
            finding = debugger.findings["node_issues"][0]
        assert "memory" in finding["summary"].lower()


class TestControlPlaneAnalysis:
    """Test control plane log analysis with mocked CloudWatch."""

    @pytest.fixture
    def debugger(self):
        """Create debugger instance with mocked AWS clients."""
        with patch("eks_comprehensive_debugger.boto3.Session") as mock_session:
            mock_logs_client = Mock()
            mock_session.return_value.client.return_value = mock_logs_client
            debugger = ComprehensiveEKSDebugger(
                cluster_name="test-cluster",
                region="us-east-1",
                profile=None,
                namespace=None,
            )
            debugger.progress = Mock()
            return debugger

    def test_analyze_control_plane_logs_errors(self, debugger):
        """Test control plane error detection."""
        # Mock describe_log_groups (for _get_cached_log_group)
        debugger.logs_client.describe_log_groups.return_value = {
            "logGroups": [{"logGroupName": "/aws/eks/test-cluster/cluster", "retentionInDays": 7}]
        }

        # Mock describe_log_streams
        debugger.logs_client.describe_log_streams.return_value = {
            "logStreams": [{"logStreamName": "kube-apiserver-123", "lastEventTimestamp": 1705312800000}]
        }

        # Mock get_log_events (not filter_log_events)
        debugger.logs_client.get_log_events.return_value = {
            "events": [
                {
                    "message": json.dumps(
                        {
                            "level": "error",
                            "msg": "etcdserver: leader changed",
                            "time": "2024-01-15T10:00:00Z",
                        }
                    ),
                    "timestamp": 1705312800000,
                }
            ]
        }

        debugger.analyze_control_plane_logs()

        assert len(debugger.findings["control_plane_issues"]) > 0
        finding = debugger.findings["control_plane_issues"][0]
        # Summary is "Control plane error in {stream_name}", check details for actual message
        details = finding.get("details", {})
        message = details.get("message", "")
        assert "etcdserver" in message.lower() or "leader" in message.lower()


class TestKubectlCacheTTL:
    """Test kubectl cache TTL functionality."""

    @pytest.fixture
    def debugger(self):
        """Create debugger instance with mocked AWS clients."""
        with patch("eks_comprehensive_debugger.boto3.Session") as mock_session:
            mock_session.return_value.client.return_value = Mock()
            debugger = ComprehensiveEKSDebugger(
                cluster_name="test-cluster",
                region="us-east-1",
                profile=None,
                namespace=None,
            )
            debugger.progress = Mock()
            return debugger

    def test_kubectl_cache_stores_with_timestamp(self, debugger):
        """Test that kubectl cache stores entries with timestamps."""
        import time

        cmd = "kubectl get pods"
        output = "pod output data"

        debugger._set_kubectl_cache(cmd, output)

        # Verify cache entry exists with timestamp
        with debugger._shared_data_lock:
            cache = debugger._shared_data["kubectl_cache"]
            assert cmd in cache
            cached_output, timestamp = cache[cmd]
            assert cached_output == output
            assert isinstance(timestamp, float)
            assert time.time() - timestamp < 1  # Should be recent

    def test_kubectl_cache_returns_cached_data(self, debugger):
        """Test that kubectl cache returns cached data when not expired."""
        cmd = "kubectl get pods"
        output = "pod output data"

        debugger._set_kubectl_cache(cmd, output)

        cached = debugger._get_kubectl_cache(cmd)
        assert cached == output

    def test_kubectl_cache_expiration(self, debugger):
        """Test that kubectl cache expires old entries."""
        import time

        cmd = "kubectl get pods"
        output = "pod output data"

        # Manually insert expired entry
        with debugger._shared_data_lock:
            cache = debugger._shared_data["kubectl_cache"]
            # Set timestamp to 11 minutes ago (beyond 10-minute TTL)
            cache[cmd] = (output, time.time() - 661)

        # Should return None for expired entry
        cached = debugger._get_kubectl_cache(cmd)
        assert cached is None

        # Entry should be removed from cache
        with debugger._shared_data_lock:
            assert cmd not in debugger._shared_data["kubectl_cache"]


class TestSeverityClassification:
    """Test severity classification integration."""

    def test_critical_keywords_trigger_critical_severity(self):
        """Test that critical keywords result in critical severity."""
        from eks_comprehensive_debugger import classify_severity

        summary = "Pod was OOMKilled due to memory limit"
        severity = classify_severity(summary)
        assert severity == "critical"

    def test_warning_keywords_trigger_warning_severity(self):
        """Test that warning keywords result in warning severity."""
        from eks_comprehensive_debugger import classify_severity

        summary = "Pod has high restart count"
        severity = classify_severity(summary)
        assert severity == "warning"

    def test_info_keywords_trigger_info_severity(self):
        """Test that info keywords result in info severity."""
        from eks_comprehensive_debugger import classify_severity

        summary = "Pod is running normally"
        severity = classify_severity(summary)
        assert severity == "info"
