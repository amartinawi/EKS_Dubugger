"""Every CLI flag the parser accepts must reach the debugger."""

from unittest.mock import patch

import pytest

import eks_comprehensive_debugger as ekd


def _run_main(argv):
    captured = {}

    class FakeDebugger:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.cluster_name = "c"

        def run_comprehensive_analysis(self):
            return {"metadata": {}, "summary": {"total_issues": 0}, "findings": {}}

    with (
        patch.object(ekd.sys, "argv", ["prog", *argv]),
        patch.object(ekd, "validate_aws_profile"),
        patch.object(ekd, "ComprehensiveEKSDebugger", FakeDebugger),
        patch.object(ekd, "output_results"),
        patch.object(ekd, "get_exit_code", return_value=0),
        pytest.raises(SystemExit),
    ):
        ekd.main()
    return captured


def test_flags_are_forwarded():
    kw = _run_main(
        [
            "--profile",
            "p",
            "--region",
            "r",
            "--no-parallel",
            "--no-cache",
            "--no-incremental",
            "--max-findings",
            "7",
        ]
    )
    assert kw["parallel"] is False
    assert kw["enable_cache"] is False
    assert kw["enable_incremental"] is False
    assert kw["max_findings"] == 7


def test_defaults_are_on():
    kw = _run_main(["--profile", "p", "--region", "r"])
    assert kw["parallel"] is True
    assert kw["enable_cache"] is True
    assert kw["enable_incremental"] is True


def test_constructor_honours_flags():
    with patch("eks_comprehensive_debugger.boto3.Session"):
        dbg = ekd.ComprehensiveEKSDebugger(
            profile="p",
            region="eu-west-1",
            cluster_name="c",
            parallel=False,
            enable_cache=False,
            enable_incremental=False,
            max_findings=3,
        )
    assert dbg.parallel is False
    assert dbg.enable_cache is False
    assert dbg.enable_incremental is False
    assert dbg.max_findings == 3


def test_config_file_sets_defaults(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text('{"region": "eu-west-1", "max_findings": 5}')
    kw = _run_main(["--profile", "p", "--config", str(cfg)])
    assert kw["region"] == "eu-west-1"
    assert kw["max_findings"] == 5


def test_explicit_flag_beats_config_file(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text('{"region": "eu-west-1"}')
    kw = _run_main(["--profile", "p", "--region", "us-east-1", "--config", str(cfg)])
    assert kw["region"] == "us-east-1"
