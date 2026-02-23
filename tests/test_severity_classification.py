"""Tests for severity classification logic."""

import pytest
from eks_comprehensive_debugger import classify_severity


class TestClassifySeverity:
    """Test cases for classify_severity function."""

    # === Critical Severity Tests ===

    @pytest.mark.parametrize(
        "summary",
        [
            "Pod was OOM killed",
            "Container OOMKilled with exit code 137",
            "Node has OOM issues",
        ],
    )
    def test_oom_keywords_return_critical(self, summary: str):
        """OOM-related keywords should return critical."""
        assert classify_severity(summary) == "critical"

    @pytest.mark.parametrize(
        "summary",
        [
            "Container in CrashLoopBackOff",
            "Application crashed unexpectedly",
            "Process crash detected",
        ],
    )
    def test_crash_keywords_return_critical(self, summary: str):
        """Crash-related keywords should return critical."""
        assert classify_severity(summary) == "critical"

    @pytest.mark.parametrize(
        "summary",
        [
            "Node is unhealthy",
            "Service critical failure",
            "System down",
        ],
    )
    def test_critical_keywords_return_critical(self, summary: str):
        """Critical/unhealthy/down keywords should return critical."""
        assert classify_severity(summary) == "critical"

    # === Warning Severity Tests ===

    @pytest.mark.parametrize(
        "summary",
        [
            "Warning: high CPU usage",
            "Disk pressure detected",
            "Memory pressure on node",
        ],
    )
    def test_warning_keywords_return_warning(self, summary: str):
        """Warning/pressure keywords should return warning."""
        assert classify_severity(summary) == "warning"

    @pytest.mark.parametrize(
        "summary",
        [
            "Pod evicted due to resource constraints",
            "Deployment degraded",
            "Service timeout occurred",
        ],
    )
    def test_degraded_keywords_return_warning(self, summary: str):
        """Evicted/degraded/timeout keywords should return warning."""
        assert classify_severity(summary) == "warning"

    @pytest.mark.parametrize(
        "summary",
        [
            "Failed to pull image",
            "Error connecting to database",
            "Request failed",
        ],
    )
    def test_error_keywords_return_warning(self, summary: str):
        """Failed/error keywords should return warning."""
        assert classify_severity(summary) == "warning"

    @pytest.mark.parametrize(
        "summary",
        [
            "Pod pending for 5 minutes",
            "PVC in pending state",
        ],
    )
    def test_pending_keywords_return_warning(self, summary: str):
        """Pending keywords should return warning."""
        assert classify_severity(summary) == "warning"

    # === Info Severity Tests ===

    @pytest.mark.parametrize(
        "summary",
        [
            "Info: scheduled backup",
            "Notice: maintenance window",
            "Using fallback configuration",
        ],
    )
    def test_info_keywords_return_info(self, summary: str):
        """Info/notice/fallback keywords should return info."""
        assert classify_severity(summary) == "info"

    def test_network_not_ready_returns_info(self):
        """Network not ready should return info."""
        assert classify_severity("Container network not ready") == "info"

    # === Default Fallback Tests ===

    def test_unknown_summary_returns_info(self):
        """Unknown summaries should default to info."""
        assert classify_severity("Some random message") == "info"

    def test_empty_summary_returns_info(self):
        """Empty summaries should return info."""
        assert classify_severity("") == "info"

    # === Explicit Severity in Details Tests ===

    def test_explicit_critical_severity(self):
        """Explicit severity in details should override keyword matching."""
        details = {"severity": "critical"}
        assert classify_severity("Info message", details) == "critical"

    def test_explicit_warning_severity(self):
        """Explicit severity in details should override keyword matching."""
        details = {"severity": "warning"}
        assert classify_severity("Critical error", details) == "warning"

    def test_explicit_info_severity(self):
        """Explicit severity in details should override keyword matching."""
        details = {"severity": "info"}
        assert classify_severity("OOM killed", details) == "info"

    def test_invalid_explicit_severity_ignored(self):
        """Invalid explicit severity should be ignored, fall back to keywords."""
        details = {"severity": "invalid"}
        assert classify_severity("OOM killed", details) == "critical"

    # === Case Insensitivity Tests ===

    @pytest.mark.parametrize(
        "summary",
        [
            "OOM KILLED",
            "oom killed",
            "Oom Killed",
        ],
    )
    def test_case_insensitive_matching(self, summary: str):
        """Keyword matching should be case insensitive."""
        assert classify_severity(summary) == "critical"

    # === Priority Tests ===

    def test_critical_takes_priority_over_warning(self):
        """Critical keywords should take priority over warning keywords."""
        # "error" is warning, "crash" is critical - critical wins
        assert classify_severity("Error: application crash") == "critical"

    def test_warning_takes_priority_over_info(self):
        """Warning keywords should take priority over info keywords."""
        # "info" is info, "error" is warning - warning wins
        assert classify_severity("Info: connection error") == "warning"
