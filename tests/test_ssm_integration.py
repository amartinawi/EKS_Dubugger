"""Tests for SSM-based node OS diagnostics (SSMNodeDiagnosticsManager).

Tests cover:
- Node-to-instance-ID mapping via spec.providerID
- SSM managed instance filtering
- Command polling (Success, InvocationDoesNotExist, InvalidInstanceId, timeout)
- Instance batching (>50 instances split into chunks)
- End-to-end run_diagnostic_commands with {hours} substitution
"""

import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

from eks_comprehensive_debugger import (
    ComprehensiveEKSDebugger,
    SSMNodeDiagnosticsManager,
    NodeDiagnosticConfig,
    FindingType,
)


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def debugger(mocker):
    """Create a debugger instance with mocked AWS clients and progress."""
    mocker.patch("boto3.Session")
    dbg = ComprehensiveEKSDebugger(
        profile="test",
        region="us-east-1",
        cluster_name="test-cluster",
        enable_node_diagnostics=True,
    )
    dbg.progress = MagicMock()
    return dbg


@pytest.fixture
def manager(debugger):
    """Create an SSMNodeDiagnosticsManager with mocked SSM client."""
    return SSMNodeDiagnosticsManager(debugger)


@pytest.fixture
def sample_node_info():
    """Sample kubectl get nodes -o json output."""
    return {
        "items": [
            {
                "metadata": {"name": "ip-10-0-1-50"},
                "spec": {"providerID": "aws:///us-east-1a/i-0abc123def456"},
                "status": {"conditions": [{"type": "Ready", "status": "True"}]},
            },
            {
                "metadata": {"name": "ip-10-0-2-60"},
                "spec": {"providerID": "aws:///us-east-1b/i-0def789ghi012"},
                "status": {"conditions": [{"type": "Ready", "status": "True"}]},
            },
            {
                "metadata": {"name": "fargate-node-1"},
                "spec": {"providerID": "aws:///us-east-1c/abc-notinstance"},
                "status": {"conditions": [{"type": "Ready", "status": "True"}]},
            },
            {
                "metadata": {"name": "node-no-provider"},
                "spec": {},
                "status": {"conditions": [{"type": "Ready", "status": "True"}]},
            },
        ]
    }


# ── Node-to-Instance Mapping Tests ────────────────────────


class TestNodeInstanceMapping:
    """Test get_node_instance_mapping() for node-to-instance-ID mapping."""

    def test_valid_provider_ids(self, manager, debugger, sample_node_info):
        """Valid aws:///az/i-xxx providerIDs should be mapped correctly."""
        debugger._shared_data["node_info"] = sample_node_info
        mapping = manager.get_node_instance_mapping()
        assert mapping == {
            "ip-10-0-1-50": "i-0abc123def456",
            "ip-10-0-2-60": "i-0def789ghi012",
        }

    def test_filters_non_instance_ids(self, manager, debugger, sample_node_info):
        """ProviderIDs without i- prefix should be filtered out."""
        debugger._shared_data["node_info"] = sample_node_info
        mapping = manager.get_node_instance_mapping()
        assert "fargate-node-1" not in mapping
        assert "node-no-provider" not in mapping

    def test_empty_node_info(self, manager, debugger):
        """Empty node_info should return empty mapping."""
        debugger._shared_data["node_info"] = None
        mapping = manager.get_node_instance_mapping()
        assert mapping == {}

    def test_no_node_data_prefetched(self, manager, debugger):
        """Missing node_info (None) should return empty mapping gracefully."""
        debugger._shared_data["node_info"] = None
        assert manager.get_node_instance_mapping() == {}

    def test_malformed_provider_id(self, manager, debugger):
        """Malformed providerIDs should be skipped without error."""
        debugger._shared_data["node_info"] = {
            "items": [
                {"metadata": {"name": "bad-1"}, "spec": {"providerID": "not-a-valid-id"}},
                {"metadata": {"name": "bad-2"}, "spec": {"providerID": ""}},
                {"metadata": {"name": "ok-1"}, "spec": {"providerID": "aws:///us-east-1a/i-valid123"}},
            ]
        }
        mapping = manager.get_node_instance_mapping()
        assert mapping == {"ok-1": "i-valid123"}


# ── Instance Batching Tests ───────────────────────────────


class TestInstanceBatching:
    """Test _chunk_instances() for SSM API limit compliance."""

    def test_single_batch_under_limit(self):
        """50 instances should produce a single chunk."""
        ids = [f"i-{i:012d}" for i in range(50)]
        chunks = SSMNodeDiagnosticsManager._chunk_instances(ids, 50)
        assert len(chunks) == 1
        assert len(chunks[0]) == 50

    def test_two_batches_over_limit(self):
        """51 instances should produce two chunks (50 + 1)."""
        ids = [f"i-{i:012d}" for i in range(51)]
        chunks = SSMNodeDiagnosticsManager._chunk_instances(ids, 50)
        assert len(chunks) == 2
        assert len(chunks[0]) == 50
        assert len(chunks[1]) == 1

    def test_large_batch(self):
        """150 instances should produce 3 chunks of 50."""
        ids = [f"i-{i:012d}" for i in range(150)]
        chunks = SSMNodeDiagnosticsManager._chunk_instances(ids, 50)
        assert len(chunks) == 3
        assert all(len(c) == 50 for c in chunks)

    def test_empty_list(self):
        """Empty list should produce no chunks."""
        assert SSMNodeDiagnosticsManager._chunk_instances([], 50) == []

    def test_single_instance(self):
        """Single instance should produce one chunk."""
        chunks = SSMNodeDiagnosticsManager._chunk_instances(["i-0abc123"], 50)
        assert len(chunks) == 1
        assert chunks[0] == ["i-0abc123"]


# ── SSM Managed Check Tests ───────────────────────────────


class TestSSMManagedCheck:
    """Test check_ssm_managed() for filtering SSM Online instances."""

    def test_filters_to_online_only(self, manager, mocker):
        """Only Online instances should be returned."""
        manager.ssm_client.describe_instance_information.return_value = {
            "InstanceInformationList": [
                {"InstanceId": "i-0abc123"},
                {"InstanceId": "i-0def456"},
            ]
        }
        managed = manager.check_ssm_managed(["i-0abc123", "i-0def456", "i-0unmanaged"])
        assert managed == {"i-0abc123", "i-0def456"}
        assert "i-0unmanaged" not in managed

    def test_empty_input(self, manager):
        """Empty input should return empty set."""
        assert manager.check_ssm_managed([]) == set()

    def test_api_error_logged(self, manager, mocker):
        """API errors should be logged, not crash."""
        manager.debugger.safe_api_call = MagicMock(return_value=(False, "AccessDenied"))
        managed = manager.check_ssm_managed(["i-0abc123"])
        assert managed == set()
        assert any("check_ssm_managed" in e.get("step", "") for e in manager.debugger.errors)


# ── Command Polling Tests ─────────────────────────────────


class TestCommandPolling:
    """Test _poll_command() for terminal state detection and error handling."""

    def test_success_status(self, manager):
        """Success status should return immediately with stdout."""
        manager.ssm_client.get_command_invocation.return_value = {
            "Status": "Success",
            "StandardOutputContent": "iptables output",
            "StandardErrorContent": "",
            "StandardOutputUrl": "",
            "ResponseCode": 0,
        }
        result = manager._poll_command("cmd-1", "i-0abc", timeout=30)
        assert result["status"] == "Success"
        assert result["stdout"] == "iptables output"

    def test_failed_status(self, manager):
        """Failed status should return with stderr."""
        manager.ssm_client.get_command_invocation.return_value = {
            "Status": "Failed",
            "StandardOutputContent": "",
            "StandardErrorContent": "command not found",
            "StandardOutputUrl": "",
            "ResponseCode": 127,
        }
        result = manager._poll_command("cmd-2", "i-0abc", timeout=30)
        assert result["status"] == "Failed"
        assert "command not found" in result["stderr"]

    def test_invocation_does_not_exist_retry(self, manager):
        """InvocationDoesNotExist should retry then succeed."""
        call_count = [0]

        def mock_poll(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise ClientError(
                    {"Error": {"Code": "InvocationDoesNotExist", "Message": "not yet"}},
                    "GetCommandInvocation",
                )
            return {
                "Status": "Success",
                "StandardOutputContent": "ok",
                "StandardErrorContent": "",
                "StandardOutputUrl": "",
                "ResponseCode": 0,
            }

        manager.ssm_client.get_command_invocation.side_effect = mock_poll
        result = manager._poll_command("cmd-3", "i-0abc", timeout=30)
        assert result["status"] == "Success"
        assert call_count[0] >= 3  # Retried before succeeding

    def test_invalid_instance_id(self, manager):
        """InvalidInstanceId should return error immediately."""
        manager.ssm_client.get_command_invocation.side_effect = ClientError(
            {"Error": {"Code": "InvalidInstanceId", "Message": "not managed"}},
            "GetCommandInvocation",
        )
        result = manager._poll_command("cmd-4", "i-0xxx", timeout=10)
        assert result["status"] == "error"
        assert "not managed" in result["stderr"]

    def test_timeout(self, manager):
        """Non-terminal status should eventually time out."""
        manager.ssm_client.get_command_invocation.return_value = {
            "Status": "InProgress",
            "StandardOutputContent": "",
            "StandardErrorContent": "",
            "StandardOutputUrl": "",
            "ResponseCode": -1,
        }
        result = manager._poll_command("cmd-5", "i-0abc", timeout=3)
        assert result["status"] == "timeout"


# ── Run Diagnostic Commands Tests ─────────────────────────


class TestRunDiagnosticCommands:
    """Test run_diagnostic_commands() end-to-end with mocks."""

    def test_successful_execution(self, manager):
        """All instances should get results for each diagnostic type."""
        manager.ssm_client.send_command.return_value = {"Command": {"CommandId": "test-cmd"}}
        manager.ssm_client.get_command_invocation.return_value = {
            "Status": "Success",
            "StandardOutputContent": "output data",
            "StandardErrorContent": "",
            "StandardOutputUrl": "",
            "ResponseCode": 0,
        }
        results = manager.run_diagnostic_commands(
            ["i-0abc", "i-0def"],
            {"iptables": ["iptables-save"], "conntrack": ["conntrack -S"]},
            hours=24,
        )
        assert "i-0abc" in results and "i-0def" in results
        assert "iptables" in results["i-0abc"]
        assert results["i-0abc"]["iptables"]["status"] == "Success"

    def test_hours_substitution(self, manager):
        """{hours} placeholder should be substituted in commands."""
        manager.ssm_client.send_command.return_value = {"Command": {"CommandId": "cmd-h"}}
        manager.ssm_client.get_command_invocation.return_value = {
            "Status": "Success",
            "StandardOutputContent": "",
            "StandardErrorContent": "",
            "StandardOutputUrl": "",
            "ResponseCode": 0,
        }
        manager.run_diagnostic_commands(
            ["i-0abc"],
            {"kubelet": ["journalctl -u kubelet --since '{hours} hours ago'"]},
            hours=48,
        )
        sent_cmds = manager.ssm_client.send_command.call_args.kwargs["Parameters"]["commands"]
        assert "48 hours ago" in sent_cmds[0]

    def test_send_command_failure_marks_error(self, manager):
        """Failed send_command should mark instances as error for that type."""
        manager.debugger.safe_api_call = MagicMock(return_value=(False, "AccessDenied"))
        results = manager.run_diagnostic_commands(
            ["i-0abc"],
            {"iptables": ["iptables-save"]},
            hours=24,
        )
        assert results["i-0abc"]["iptables"]["status"] == "error"


# ── Send Command Batch Tests ──────────────────────────────


class TestSendCommandBatch:
    """Test _send_command_batch() for correct SSM API parameters."""

    def test_returns_command_id(self, manager):
        """Should return the CommandId from send_command response."""
        manager.ssm_client.send_command.return_value = {"Command": {"CommandId": "abc-123"}}
        cmd_id = manager._send_command_batch(["i-0abc"], ["iptables-save"], "iptables")
        assert cmd_id == "abc-123"

    def test_correct_document_name(self, manager):
        """Should use AWS-RunShellScript document."""
        manager.ssm_client.send_command.return_value = {"Command": {"CommandId": "x"}}
        manager._send_command_batch(["i-0abc"], ["test"], "test")
        kwargs = manager.ssm_client.send_command.call_args.kwargs
        assert kwargs["DocumentName"] == "AWS-RunShellScript"

    def test_failure_returns_none(self, manager):
        """API failure should return None and log error."""
        manager.debugger.safe_api_call = MagicMock(return_value=(False, "ThrottlingException"))
        cmd_id = manager._send_command_batch(["i-0abc"], ["test"], "iptables")
        assert cmd_id is None


# ── Real Command Format Regression Tests ─────────────────


class TestRealCommandFormat:
    """Regression tests using the real NODE_DIAGNOSTIC_COMMANDS constant.

    These ensure .format(hours=) does not crash on shell brace constructs
    like awk '{print $2}' in the eni_metadata command.
    """

    def test_all_ten_types_format_without_error(self):
        """Every diagnostic type in NODE_DIAGNOSTIC_COMMANDS must survive .format(hours=)."""
        from eks_comprehensive_debugger import NODE_DIAGNOSTIC_COMMANDS

        hours = 48
        for diag_type, commands in NODE_DIAGNOSTIC_COMMANDS.items():
            for cmd in commands:
                # This must not raise KeyError or ValueError
                formatted = cmd.format(hours=hours) if "{hours}" in cmd else cmd
                assert isinstance(formatted, str)

    def test_eni_metadata_awk_braces_survive(self):
        """eni_metadata command contains awk '{print $2}' — must not crash on .format()."""
        from eks_comprehensive_debugger import NODE_DIAGNOSTIC_COMMANDS

        eni_cmds = NODE_DIAGNOSTIC_COMMANDS["eni_metadata"]
        hours = 24
        for cmd in eni_cmds:
            # The guarded format must succeed even with awk braces
            formatted = cmd.format(hours=hours) if "{hours}" in cmd else cmd
            assert isinstance(formatted, str)
            if "awk" in cmd:
                assert "{print $2}" in formatted or "print" in formatted

    def test_hours_substituted_in_kubelet_command(self):
        """kubelet command has {hours} placeholder — must be substituted."""
        from eks_comprehensive_debugger import NODE_DIAGNOSTIC_COMMANDS

        kubelet_cmds = NODE_DIAGNOSTIC_COMMANDS["kubelet"]
        hours = 72
        for cmd in kubelet_cmds:
            formatted = cmd.format(hours=hours) if "{hours}" in cmd else cmd
            if "{hours}" in cmd:
                assert str(hours) in formatted
                assert "{hours}" not in formatted

    def test_run_diagnostic_commands_with_real_constant(self, manager):
        """Full run_diagnostic_commands must not crash with the real command set."""
        from eks_comprehensive_debugger import NODE_DIAGNOSTIC_COMMANDS

        manager.ssm_client.send_command.return_value = {"Command": {"CommandId": "test"}}
        manager.ssm_client.get_command_invocation.return_value = {
            "Status": "Success",
            "StandardOutputContent": "",
            "StandardErrorContent": "",
            "StandardOutputUrl": "",
            "ResponseCode": 0,
        }
        # This must complete without KeyError from eni_metadata awk braces
        results = manager.run_diagnostic_commands(
            ["i-0abc"],
            NODE_DIAGNOSTIC_COMMANDS,
            hours=24,
        )
        assert "i-0abc" in results
        # All 10 diagnostic types should have results
        assert len(results["i-0abc"]) == len(NODE_DIAGNOSTIC_COMMANDS)
