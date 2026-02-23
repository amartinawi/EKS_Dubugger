"""Shared fixtures for EKS Debugger tests."""

import pytest
import sys
import os

# Add parent directory to path to import the main module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sample_pod_eviction_event():
    """Sample pod eviction event for testing."""
    return {
        "metadata": {"namespace": "default", "name": "test-pod-123"},
        "reason": "Evicted",
        "message": "The node was low on resource: ephemeral-storage.",
        "lastTimestamp": "2026-02-20T10:30:00Z",
        "involvedObject": {"name": "test-pod", "namespace": "default"},
    }


@pytest.fixture
def sample_node_condition():
    """Sample node condition for testing."""
    return {
        "type": "MemoryPressure",
        "status": "True",
        "message": "Node has insufficient memory",
    }
