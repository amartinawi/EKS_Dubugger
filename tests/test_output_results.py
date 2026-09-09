"""Tests for output_results() cluster-name handling."""

from unittest.mock import patch

import pytest

import eks_comprehensive_debugger as ekd

MINIMAL_RESULTS = {"metadata": {}, "findings": {}, "summary": {}}


def _list_report_files(tmp_path):
    return sorted(p.name for p in tmp_path.iterdir())


def test_output_results_with_none_cluster_name_uses_fallback(tmp_path):
    """Interactive cluster selection leaves args.cluster_name as None; must not crash."""
    with patch.object(ekd.HTMLOutputFormatter, "format", return_value="<html></html>"), patch.object(
        ekd.LLMJSONOutputFormatter, "format", return_value="{}"
    ):
        ekd.output_results(MINIMAL_RESULTS, None, "UTC", str(tmp_path))

    files = _list_report_files(tmp_path)
    assert len(files) == 2
    assert all(f.startswith("eks-cluster-") for f in files)


def test_output_results_sanitizes_cluster_name(tmp_path):
    with patch.object(ekd.HTMLOutputFormatter, "format", return_value="<html></html>"), patch.object(
        ekd.LLMJSONOutputFormatter, "format", return_value="{}"
    ):
        ekd.output_results(MINIMAL_RESULTS, "My_Cluster.Prod", "UTC", str(tmp_path))

    files = _list_report_files(tmp_path)
    assert all(f.startswith("my-cluster-prod-") for f in files)


def test_main_passes_resolved_cluster_name_to_output(tmp_path):
    """main() must use the debugger's resolved cluster name, not the raw CLI arg."""
    argv = ["prog", "--profile", "p", "--region", "eu-west-1", "--output-dir", str(tmp_path)]
    fake_results = dict(MINIMAL_RESULTS)

    class FakeDebugger:
        def __init__(self, **kwargs):
            self.cluster_name = kwargs.get("cluster_name")

        def run_comprehensive_analysis(self):
            self.cluster_name = "resolved-cluster"  # simulates interactive selection
            return fake_results

    with patch.object(ekd.sys, "argv", argv), patch.object(ekd, "validate_aws_profile"), patch.object(
        ekd, "ComprehensiveEKSDebugger", FakeDebugger
    ), patch.object(ekd, "output_results") as mock_output, patch.object(
        ekd, "get_exit_code", return_value=0
    ), pytest.raises(SystemExit) as exc:
        ekd.main()

    assert exc.value.code == 0
    mock_output.assert_called_once()
    assert mock_output.call_args.args[1] == "resolved-cluster"
