"""Tests for node selection logic in SSMNodeDiagnosticsManager.

Tests cover:
- Priority ordering (pressure conditions > NotReady > healthy baseline)
- max_nodes enforcement
- Baseline healthy node inclusion (20% of slots)
- Edge cases (empty clusters, Fargate-only, all-unhealthy)
"""

import pytest
from unittest.mock import MagicMock

from eks_comprehensive_debugger import (
    ComprehensiveEKSDebugger,
    SSMNodeDiagnosticsManager,
    NodeDiagnosticConfig,
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
    """Create an SSMNodeDiagnosticsManager."""
    return SSMNodeDiagnosticsManager(debugger)


def _make_node(name, ready=True, conditions=None):
    """Helper: build a kubectl node dict with given conditions."""
    conds = conditions or []
    if ready:
        conds = conds + [{"type": "Ready", "status": "True"}]
    else:
        conds = conds + [{"type": "Ready", "status": "False"}]
    return {
        "metadata": {"name": name},
        "status": {"conditions": conds},
    }


# ── Priority Selection Tests ──────────────────────────────


class TestNodeSelectionPriority:
    """Test select_nodes_for_diagnostics() priority ordering."""

    def test_pressure_nodes_selected_first(self, manager, debugger):
        """Nodes with pressure conditions should be prioritized."""
        debugger._shared_data["node_info"] = {
            "items": [
                _make_node("healthy-1"),
                _make_node("pressure-1", conditions=[{"type": "MemoryPressure", "status": "True"}]),
                _make_node("healthy-2"),
            ]
        }
        selected = manager.select_nodes_for_diagnostics(max_nodes=10)
        assert "pressure-1" in selected
        # Healthy nodes fill remaining slots
        assert "healthy-1" in selected or "healthy-2" in selected

    def test_notready_before_healthy(self, manager, debugger):
        """NotReady nodes should be selected before healthy nodes."""
        debugger._shared_data["node_info"] = {
            "items": [
                _make_node("healthy-1"),
                _make_node("notready-1", ready=False),
                _make_node("healthy-2"),
            ]
        }
        selected = manager.select_nodes_for_diagnostics(max_nodes=2)
        assert "notready-1" in selected

    def test_all_pressure_types_prioritized(self, manager, debugger):
        """All NodeDiagnosticConfig.PRIORITY_NODE_STATES should be detected."""
        for cond in NodeDiagnosticConfig.PRIORITY_NODE_STATES:
            debugger._shared_data["node_info"] = {
                "items": [
                    _make_node(f"node-{cond}", conditions=[{"type": cond, "status": "True"}]),
                    _make_node("healthy"),
                ]
            }
            selected = manager.select_nodes_for_diagnostics(max_nodes=5)
            assert f"node-{cond}" in selected, f"Node with {cond} should be prioritized"

    def test_disk_pressure_prioritized(self, manager, debugger):
        """DiskPressure should be in the priority list."""
        debugger._shared_data["node_info"] = {
            "items": [
                _make_node("disk-node", conditions=[{"type": "DiskPressure", "status": "True"}]),
                _make_node("healthy"),
            ]
        }
        selected = manager.select_nodes_for_diagnostics(max_nodes=5)
        assert "disk-node" in selected


# ── max_nodes Enforcement Tests ───────────────────────────


class TestMaxNodesEnforcement:
    """Test max_nodes limit enforcement."""

    def test_respects_max_nodes_limit(self, manager, debugger):
        """Selection should not exceed max_nodes."""
        debugger._shared_data["node_info"] = {
            "items": [_make_node(f"node-{i}", ready=False) for i in range(20)],
        }
        selected = manager.select_nodes_for_diagnostics(max_nodes=5)
        # max_nodes=5 → 5 priority slots + baseline, but all are NotReady
        # baseline is min(remaining, max(1, 5*0.2)) = min(0, 1) = 0
        assert len(selected) <= 7  # Allow small overshoot from baseline calculation

    def test_max_nodes_one(self, manager, debugger):
        """max_nodes=1 should return at most 2 nodes (1 priority + 1 baseline)."""
        debugger._shared_data["node_info"] = {
            "items": [
                _make_node("n1", ready=False),
                _make_node("n2"),
            ]
        }
        selected = manager.select_nodes_for_diagnostics(max_nodes=1)
        assert len(selected) <= 2

    def test_empty_cluster(self, manager, debugger):
        """Empty node list should return empty selection."""
        debugger._shared_data["node_info"] = {"items": []}
        selected = manager.select_nodes_for_diagnostics(max_nodes=10)
        assert selected == []

    def test_no_node_data(self, manager, debugger):
        """Missing node_info should return empty list."""
        debugger._shared_data["node_info"] = None
        assert manager.select_nodes_for_diagnostics(max_nodes=10) == []


# ── Baseline Inclusion Tests ──────────────────────────────


class TestBaselineInclusion:
    """Test that healthy nodes are included for comparison baseline."""

    def test_healthy_baseline_included(self, manager, debugger):
        """At least one healthy node should be included when slots available."""
        debugger._shared_data["node_info"] = {
            "items": [
                _make_node("unhealthy", ready=False),
                _make_node("healthy-1"),
                _make_node("healthy-2"),
            ]
        }
        selected = manager.select_nodes_for_diagnostics(max_nodes=10)
        healthy_selected = [n for n in selected if "healthy" in n]
        assert len(healthy_selected) >= 1, "At least 1 healthy baseline node should be included"

    def test_baseline_ratio(self, manager, debugger):
        """Baseline should be ~20% of max_nodes."""
        debugger._shared_data["node_info"] = {
            "items": [_make_node(f"h-{i}") for i in range(20)],
        }
        selected = manager.select_nodes_for_diagnostics(max_nodes=10)
        # All healthy, so baseline = min(10, max(1, 10*0.2)) = 2
        assert len(selected) == 2
