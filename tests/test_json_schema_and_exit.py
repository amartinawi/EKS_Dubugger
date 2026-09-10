"""JSON output must validate against the shipped schema; exit codes must be distinct."""

import json
import pathlib

import jsonschema

import eks_comprehensive_debugger as ekd

SCHEMA_PATH = pathlib.Path(__file__).resolve().parent.parent / "schemas" / "output_schema.json"


def _results():
    return {
        "metadata": {
            "cluster": "c",
            "region": "eu-west-1",
            "analysis_date": "2026-09-09T08:18:34Z",
            "date_range": {"start": "2026-09-08T08:05:46Z", "end": "2026-09-09T08:05:46Z"},
        },
        "summary": {"total_issues": 1, "critical": 0, "warning": 1, "info": 0},
        "findings": {
            "pod_errors": [
                {
                    "summary": "Pod a restarted",
                    "details": {"severity": "warning", "finding_type": "current_state"},
                }
            ]
        },
        "correlations": [],
        "timeline": [],
        "recommendations": [],
        "errors": [{"step": "analyze_x", "message": "boom"}],
        "delta": {
            "is_first_run": False,
            "new_issues": 1,
            "resolved_issues": 0,
            "new": ["Pod a restarted"],
            "resolved": [],
        },
    }


def test_json_validates_against_schema():
    out = json.loads(ekd.LLMJSONOutputFormatter().format(_results()))
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.validate(out, schema)


def test_json_includes_errors_and_delta():
    out = json.loads(ekd.LLMJSONOutputFormatter().format(_results()))
    assert out["errors"] == [{"step": "analyze_x", "message": "boom"}]
    assert out["delta"]["new_issues"] == 1


def test_exit_code_clean():
    assert ekd.get_exit_code({"summary": {"total_issues": 0}, "errors": []}) == 0


def test_exit_code_issues_found():
    assert ekd.get_exit_code({"summary": {"total_issues": 3}, "errors": []}) == 1


def test_exit_code_partial_run_is_distinct():
    assert ekd.get_exit_code({"summary": {"total_issues": 3}, "errors": [{"step": "x", "message": "y"}]}) == 3


def test_exit_code_fatal_when_no_summary():
    assert ekd.get_exit_code({"errors": [{"step": "x", "message": "y"}]}) == 2


def test_delta_ignores_counter_drift():
    """restart count 987 becoming 989 is the same issue, not one resolved and one new."""
    cache = ekd.IncrementalCache("c", "eu-west-1")
    prev = {"findings": {"pod_errors": [{"summary": "Pod a has high restart count: 987"}]}}
    cur = {"findings": {"pod_errors": [{"summary": "Pod a has high restart count: 989"}]}}
    delta = cache.compute_delta(cur, prev)
    assert delta["new_issues"] == 0
    assert delta["resolved_issues"] == 0
