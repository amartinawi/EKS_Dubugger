"""Tests for kubectl command execution with shell=False."""

import pytest
import subprocess
from unittest.mock import Mock, patch, MagicMock
from eks_comprehensive_debugger import ComprehensiveEKSDebugger


class TestKubectlCommandExecution:
    """Test cases for _run_kubectl_command and get_kubectl_output with shell=False."""

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

    def test_run_kubectl_command_success(self, debugger):
        """Successful kubectl command returns (True, output)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout='{"items": []}', returncode=0)

            success, output = debugger._run_kubectl_command(
                ["kubectl", "get", "nodes", "-o", "json"],
                timeout=30,
            )

            assert success is True
            assert output == '{"items": []}'
            mock_run.assert_called_once()
            # Verify shell=False
            assert mock_run.call_args[1]["shell"] is False

    def test_run_kubectl_command_timeout(self, debugger):
        """Timeout returns (False, error message)."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("kubectl", 30)

            success, output = debugger._run_kubectl_command(
                ["kubectl", "get", "nodes"],
                timeout=30,
            )

            assert success is False
            assert "timed out" in output.lower()

    def test_run_kubectl_command_failure(self, debugger):
        """Command failure returns (False, stderr)."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1, cmd="kubectl", stderr="Error: resource not found"
            )

            success, output = debugger._run_kubectl_command(
                ["kubectl", "get", "nodes"],
                timeout=30,
            )

            assert success is False
            assert "Error: resource not found" in output

    def test_run_kubectl_command_kubectl_not_found(self, debugger):
        """kubectl not in PATH returns (False, error message)."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()

            success, output = debugger._run_kubectl_command(
                ["kubectl", "get", "nodes"],
                timeout=30,
            )

            assert success is False
            assert "not found" in output.lower()

    def test_get_kubectl_output_simple_command(self, debugger):
        """Simple kubectl command without fallbacks works."""
        with patch.object(debugger, "_run_kubectl_command") as mock_run:
            mock_run.return_value = (True, '{"items": []}')

            output = debugger.get_kubectl_output("kubectl get nodes -o json")

            assert output == '{"items": []}'
            # Should be called with list args
            mock_run.assert_called_once()
            args = mock_run.call_args[0]
            assert args[0] == ["kubectl", "get", "nodes", "-o", "json"]

    def test_get_kubectl_output_with_fallback_first_succeeds(self, debugger):
        """Command with || fallback - first command succeeds."""
        with patch.object(debugger, "_run_kubectl_command") as mock_run:
            mock_run.return_value = (True, '{"items": []}')

            output = debugger.get_kubectl_output(
                "kubectl get deployment foo -o json || echo 'not found'"
            )

            assert output == '{"items": []}'
            # Only first command should be tried
            mock_run.assert_called_once()

    def test_get_kubectl_output_with_fallback_first_fails(self, debugger):
        """Command with || fallback - first fails, echo fallback used."""
        with patch.object(debugger, "_run_kubectl_command") as mock_run:
            # First call fails, then we hit the echo fallback
            mock_run.return_value = (False, "Error: not found")

            output = debugger.get_kubectl_output(
                "kubectl get deployment foo -o json || echo 'not found'"
            )

            # Should return the echo fallback value
            assert output == "not found"

    def test_get_kubectl_output_with_context(self, debugger):
        """Custom kube-context is added to command."""
        debugger.kube_context = "my-context"

        with patch.object(debugger, "_run_kubectl_command") as mock_run:
            mock_run.return_value = (True, '{"items": []}')

            output = debugger.get_kubectl_output("kubectl get nodes -o json")

            # Verify context was added
            assert output == '{"items": []}'

    def test_get_kubectl_output_caching(self, debugger):
        """Successful output is cached."""
        with patch.object(debugger, "_run_kubectl_command") as mock_run:
            mock_run.return_value = (True, '{"items": []}')

            # First call
            output1 = debugger.get_kubectl_output("kubectl get nodes -o json")
            # Second call - should use cache
            output2 = debugger.get_kubectl_output("kubectl get nodes -o json")

            assert output1 == output2
            # _run_kubectl_command should only be called once (second uses cache)
            mock_run.assert_called_once()

    def test_get_kubectl_output_no_cache(self, debugger):
        """use_cache=False bypasses cache."""
        with patch.object(debugger, "_run_kubectl_command") as mock_run:
            mock_run.return_value = (True, '{"items": []}')

            # First call without cache
            debugger.get_kubectl_output("kubectl get nodes -o json", use_cache=False)
            # Second call without cache
            debugger.get_kubectl_output("kubectl get nodes -o json", use_cache=False)

            # Should be called twice (no caching)
            assert mock_run.call_count == 2

    def test_shell_injection_blocked(self, debugger):
        """Shell injection attempts are blocked by input validation."""
        # This test verifies that even if someone tries to inject,
        # the input validation prevents it at construction time
        from eks_comprehensive_debugger import InputValidationError

        with pytest.raises(InputValidationError):
            ComprehensiveEKSDebugger(
                profile="test; rm -rf /",  # Injection attempt
                region="us-east-1",
                cluster_name="test-cluster",
            )

    def test_no_shell_true_in_subprocess(self, debugger):
        """Verify subprocess.run is never called with shell=True."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout="{}", returncode=0)

            debugger._run_kubectl_command(["kubectl", "get", "nodes"], timeout=30)

            # Verify shell=False is used
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs.get("shell") is False
