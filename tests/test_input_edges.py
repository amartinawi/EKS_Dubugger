"""Boundary handling for timezone, lookback windows, and SSM timeout."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import eks_comprehensive_debugger as ekd


def test_bad_timezone_is_date_validation_error():
    with pytest.raises(ekd.DateValidationError):
        ekd.parse_flexible_date("2026-09-09", "Mars/Olympus")


def test_valid_timezone_still_parses():
    parsed = ekd.parse_flexible_date("2026-09-09T08:00:00", "Asia/Dubai")
    assert parsed.year == 2026


def test_hours_zero_rejected():
    parser = ekd.create_argument_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--profile", "p", "--region", "r", "--hours", "0"])


def test_negative_hours_rejected():
    parser = ekd.create_argument_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--profile", "p", "--region", "r", "--hours", "-5"])


def test_hours_and_days_together_rejected():
    args = SimpleNamespace(start_date=None, end_date=None, hours=24, days=3, timezone="UTC")
    with pytest.raises(ekd.DateValidationError):
        ekd.validate_and_parse_dates(args)


def test_hours_alone_is_accepted():
    args = SimpleNamespace(start_date=None, end_date=None, hours=6, days=None, timezone="UTC")
    start, end = ekd.validate_and_parse_dates(args)
    assert round((end - start).total_seconds() / 3600) == 6


def test_ssm_timeout_floor():
    with patch("eks_comprehensive_debugger.boto3.Session"):
        dbg = ekd.ComprehensiveEKSDebugger(profile="p", region="eu-west-1", cluster_name="c", ssm_timeout=0)
    assert dbg.ssm_timeout == ekd.NodeDiagnosticConfig.MIN_SSM_TIMEOUT


def test_ssm_timeout_ceiling_still_applies():
    with patch("eks_comprehensive_debugger.boto3.Session"):
        dbg = ekd.ComprehensiveEKSDebugger(profile="p", region="eu-west-1", cluster_name="c", ssm_timeout=999999)
    assert dbg.ssm_timeout == ekd.NodeDiagnosticConfig.MAX_SSM_TIMEOUT
