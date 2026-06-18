"""Tests for EKS Debugger MCP Server (Phase 2).

Covers all 18 MCP tools, session lifecycle, error handling, and the core
invariants:
    - Every tool returns a dict; no tool ever raises to the caller.
    - Session ids are opaque and unique.
    - Sessions auto-expire after SESSION_TIMEOUT_MINUTES of inactivity.
    - Finding severity lives inside ``details`` (per project convention).

The ComprehensiveEKSDebugger is mocked throughout — these tests validate the
MCP layer, not the underlying analysis (which has its own test suite).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import eks_mcp_server
from eks_mcp_server import (
    SESSION_TIMEOUT_MINUTES,
    _SessionState,
    _cleanup_expired_sessions,
    _get_session,
    _make_session_id,
    analyze_control_plane,
    analyze_iam,
    analyze_networking,
    analyze_nodes,
    analyze_pods,
    analyze_storage,
    cluster_health,
    collect_node_diagnostics,
    connect,
    format_for_llm,
    get_correlations,
    get_findings,
    get_recommendations,
    get_remediation,
    get_summary,
    get_timeline,
    run_full_analysis,
    search_findings,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_sessions():
    """Clear the global session store before and after every test.

    Without this, sessions created in one test would leak into the next.
    """
    eks_mcp_server._sessions.clear()
    yield
    eks_mcp_server._sessions.clear()


def _build_mock_debugger(
    *,
    findings: dict | None = None,
    correlations: list | None = None,
    timeline: list | None = None,
    errors: list | None = None,
    cluster_name: str = "test-cluster",
    region: str = "us-east-1",
    namespace: str | None = None,
) -> MagicMock:
    """Build a MagicMock debugger with realistic default state.

    The debugger's findings dict drives most tool behavior; the default
    fixture data includes one critical finding in each of three categories
    so filtering/pagination/severity tests have something to chew on.
    """
    dbg = MagicMock(name="ComprehensiveEKSDebugger")
    dbg.cluster_name = cluster_name
    dbg.region = region
    dbg.namespace = namespace
    dbg.start_date = datetime.now(timezone.utc) - timedelta(hours=24)
    dbg.end_date = datetime.now(timezone.utc)
    dbg.findings = (
        findings
        if findings is not None
        else {
            "pod_errors": [
                {
                    "summary": "Pod app-x in CrashLoopBackOff",
                    "details": {
                        "severity": "critical",
                        "finding_type": "current_state",
                        "namespace": "default",
                        "pod": "app-x",
                    },
                },
                {
                    "summary": "Pod worker-y high restart count",
                    "details": {
                        "severity": "warning",
                        "finding_type": "current_state",
                        "namespace": "default",
                        "pod": "worker-y",
                    },
                },
            ],
            "node_issues": [
                {
                    "summary": "Node ip-10-0-1-50 is NotReady",
                    "details": {
                        "severity": "critical",
                        "finding_type": "current_state",
                        "node": "ip-10-0-1-50",
                    },
                },
            ],
            "oom_killed": [
                {
                    "summary": "Container OOMKilled in namespace prod",
                    "details": {
                        "severity": "critical",
                        "finding_type": "historical_event",
                        "timestamp": "2026-06-18T10:00:00Z",
                        "namespace": "prod",
                    },
                },
            ],
            "control_plane_issues": [],
            "network_issues": [],
            "dns_issues": [],
            "rbac_issues": [],
            "pvc_issues": [],
            "image_pull_failures": [],
            "scheduling_failures": [],
            "memory_pressure": [],
            "disk_pressure": [],
            "addon_issues": [],
            # Phase 1 node OS categories
            "node_os_iptables": [],
            "node_os_conntrack": [],
            "node_os_dmesg": [],
            "node_os_kubelet": [],
            "node_os_containerd": [],
            "node_os_ipamd": [],
            "node_os_routes": [],
            "node_os_cni_config": [],
            "node_os_sysctl": [],
            "node_os_eni": [],
        }
    )
    dbg.correlations = correlations if correlations is not None else []
    dbg.timeline = timeline if timeline is not None else []
    dbg.first_issue = None
    dbg.errors = errors if errors is not None else []

    # Shared data lock — needed because some tools acquire it
    import threading

    dbg._shared_data_lock = threading.Lock()
    dbg._shared_data = {
        "node_info": {"items": []},
        "pod_info": {"items": []},
    }

    # generate_recommendations returns a list by default
    dbg.generate_recommendations = MagicMock(return_value=[])
    # correlate_findings is a no-op by default (mock)
    dbg.correlate_findings = MagicMock()
    # _add_error captures error calls
    dbg._add_error = MagicMock()
    return dbg


@pytest.fixture
def mock_debugger():
    """Default mock debugger with mixed findings."""
    return _build_mock_debugger()


@pytest.fixture
def session_id(mock_debugger):
    """Inject ``mock_debugger`` into the session store; return its id."""
    sid = "sess_test_fixture"
    eks_mcp_server._sessions[sid] = _SessionState(debugger=mock_debugger)
    return sid


# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------


class TestSessionManagement:
    def test_make_session_id_has_prefix_and_length(self):
        sid = _make_session_id()
        assert sid.startswith("sess_")
        # sess_ + 12 hex chars
        assert len(sid) == len("sess_") + 12

    def test_make_session_id_is_unique(self):
        ids = {_make_session_id() for _ in range(200)}
        # Probabilistic uniqueness — collisions are astronomically unlikely
        assert len(ids) == 200

    def test_get_session_returns_state_and_touches_activity(self, mock_debugger):
        sid = "sess_xyz"
        state = _SessionState(debugger=mock_debugger)
        old_activity = state.last_activity - timedelta(minutes=5)
        state.last_activity = old_activity
        eks_mcp_server._sessions[sid] = state

        fetched = _get_session(sid)
        assert fetched is state
        assert fetched.last_activity > old_activity

    def test_get_session_raises_for_unknown_id(self):
        with pytest.raises(ValueError, match="not found"):
            _get_session("sess_does_not_exist")

    def test_cleanup_removes_expired_sessions(self, mock_debugger):
        expired_state = _SessionState(debugger=mock_debugger)
        expired_state.last_activity = datetime.now(timezone.utc) - timedelta(minutes=SESSION_TIMEOUT_MINUTES + 1)
        fresh_state = _SessionState(debugger=mock_debugger)

        eks_mcp_server._sessions["sess_old"] = expired_state
        eks_mcp_server._sessions["sess_new"] = fresh_state

        _cleanup_expired_sessions()

        assert "sess_old" not in eks_mcp_server._sessions
        assert "sess_new" in eks_mcp_server._sessions

    def test_cleanup_keeps_active_sessions(self, mock_debugger):
        state = _SessionState(debugger=mock_debugger)
        eks_mcp_server._sessions["sess_active"] = state
        _cleanup_expired_sessions()
        assert "sess_active" in eks_mcp_server._sessions


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------


class TestConnect:
    @patch("eks_mcp_server.ComprehensiveEKSDebugger")
    def test_connect_success_returns_session_id(self, mock_cls):
        mock_dbg = mock_cls.return_value
        mock_dbg.cluster_name = "prod-cluster"
        mock_dbg.region = "us-east-1"
        mock_dbg._shared_data_lock.__enter__ = MagicMock(return_value=None)
        mock_dbg._shared_data_lock.__exit__ = MagicMock(return_value=False)
        mock_dbg._shared_data = {
            "node_info": {"items": [{"metadata": {"name": "n1"}}]},
            "pod_info": {
                "items": [
                    {"metadata": {"namespace": "default"}},
                    {"metadata": {"namespace": "kube-system"}},
                    {"metadata": {"namespace": "default"}},
                ]
            },
        }

        result = connect("prod", "us-east-1", "prod-cluster")

        assert result["status"] == "connected"
        assert result["session_id"].startswith("sess_")
        assert result["cluster"] == "prod-cluster"
        assert result["region"] == "us-east-1"
        assert result["nodes"] == 1
        assert result["pods"] == 3
        assert result["namespaces"] == 2  # default + kube-system
        # Session is registered
        assert result["session_id"] in eks_mcp_server._sessions

    @patch("eks_mcp_server.ComprehensiveEKSDebugger")
    def test_connect_failure_returns_error_dict(self, mock_cls):
        mock_cls.side_effect = ValueError("Invalid AWS profile")

        result = connect("bad", "us-east-1", "c")

        assert result["status"] == "error"
        assert "Invalid AWS profile" in result["error"]
        # Crucially, did not register a session
        assert not eks_mcp_server._sessions

    @patch("eks_mcp_server.ComprehensiveEKSDebugger")
    def test_connect_calls_setup_methods(self, mock_cls):
        mock_dbg = mock_cls.return_value
        mock_dbg._shared_data_lock.__enter__ = MagicMock(return_value=None)
        mock_dbg._shared_data_lock.__exit__ = MagicMock(return_value=False)
        mock_dbg._shared_data = {"node_info": {"items": []}, "pod_info": {"items": []}}

        connect("p", "us-east-1", "c", hours=12, namespace="default")

        mock_dbg.validate_aws_access.assert_called_once()
        mock_dbg.get_cluster_name.assert_called_once()
        mock_dbg.update_kubeconfig.assert_called_once()
        mock_dbg._prefetch_shared_data.assert_called_once()


# ---------------------------------------------------------------------------
# cluster_health()
# ---------------------------------------------------------------------------


class TestClusterHealth:
    def test_returns_node_and_pod_breakdowns(self, mock_debugger):
        mock_debugger._shared_data = {
            "node_info": {
                "items": [
                    {"status": {"conditions": [{"type": "Ready", "status": "True"}]}},
                    {"status": {"conditions": [{"type": "Ready", "status": "False"}]}},
                ]
            },
            "pod_info": {
                "items": [
                    {"status": {"phase": "Running"}},
                    {"status": {"phase": "Pending"}},
                    {"status": {"phase": "Failed"}},
                ]
            },
        }
        eks_mcp_server._sessions["s1"] = _SessionState(debugger=mock_debugger)

        result = cluster_health("s1")

        assert result["status"] == "completed"
        assert result["nodes"] == {"Ready": 1, "NotReady": 1, "Unknown": 0}
        assert result["pods"]["Running"] == 1
        assert result["pods"]["Pending"] == 1
        assert result["pods"]["Failed"] == 1

    def test_invalid_session_returns_error(self):
        result = cluster_health("sess_unknown")
        assert result["status"] == "error"
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# Tier 2 — analyze_* tools
# ---------------------------------------------------------------------------


class TestAnalyzeTools:
    """Each analyze_* tool should: fetch session, run methods, correlate,
    return a structured summary. We verify the shape, not the analysis."""

    def test_analyze_pods_returns_completed(self, session_id, mock_debugger):
        result = analyze_pods(session_id)
        assert result["status"] == "completed"
        assert result["domain"] == "pods"
        assert result["methods_run"] == 13
        # 13 pod analysis methods should have been called
        assert mock_debugger.analyze_pod_evictions.called
        assert mock_debugger.analyze_ephemeral_containers.called
        assert mock_debugger.correlate_findings.called

    def test_analyze_nodes_returns_completed(self, session_id, mock_debugger):
        result = analyze_nodes(session_id)
        assert result["status"] == "completed"
        assert result["domain"] == "nodes"
        assert result["methods_run"] == 13
        assert mock_debugger.analyze_node_conditions.called

    def test_analyze_networking_returns_completed(self, session_id, mock_debugger):
        result = analyze_networking(session_id)
        assert result["status"] == "completed"
        assert result["methods_run"] == 12

    def test_analyze_control_plane_returns_completed(self, session_id, mock_debugger):
        result = analyze_control_plane(session_id)
        assert result["status"] == "completed"
        assert result["methods_run"] == 8

    def test_analyze_storage_returns_completed(self, session_id, mock_debugger):
        result = analyze_storage(session_id)
        assert result["status"] == "completed"
        assert result["methods_run"] == 4

    def test_analyze_iam_returns_completed(self, session_id, mock_debugger):
        result = analyze_iam(session_id)
        assert result["status"] == "completed"
        assert result["methods_run"] == 5

    def test_analyze_invalid_session_returns_error(self):
        result = analyze_pods("sess_unknown")
        assert result["status"] == "error"
        assert "not found" in result["error"]

    def test_analyze_continues_on_method_failure(self, session_id, mock_debugger):
        """A throwing method should not abort the whole tool."""
        mock_debugger.analyze_pod_health_deep.side_effect = RuntimeError("boom")
        result = analyze_pods(session_id)
        # Other methods still ran, error was captured
        assert result["status"] == "completed"
        mock_debugger._add_error.assert_called()


# ---------------------------------------------------------------------------
# run_full_analysis()
# ---------------------------------------------------------------------------


class TestRunFullAnalysis:
    def test_delegates_to_run_comprehensive_analysis(self, session_id, mock_debugger):
        mock_debugger.run_comprehensive_analysis.return_value = {
            "summary": {"critical": 2, "warning": 1, "info": 0, "total_issues": 3},
            "correlations": [
                {
                    "correlation_type": "node_pressure_cascade",
                    "severity": "critical",
                    "root_cause": "Memory pressure",
                    "confidence_tier": "high",
                    "composite_confidence": 0.9,
                }
            ],
            "recommendations": [{"title": "Fix memory", "priority": "critical"}],
            "errors": [],
        }

        result = run_full_analysis(session_id)

        assert result["status"] == "completed"
        assert result["summary"]["total_issues"] == 3
        assert result["correlations_count"] == 1
        assert result["recommendations_count"] == 1
        assert len(result["top_correlations"]) == 1
        assert result["top_correlations"][0]["confidence_tier"] == "high"

    def test_marks_session_analysis_complete(self, session_id, mock_debugger):
        mock_debugger.run_comprehensive_analysis.return_value = {
            "summary": {},
            "correlations": [],
            "recommendations": [],
            "errors": [],
        }
        run_full_analysis(session_id)
        assert eks_mcp_server._sessions[session_id].analysis_complete is True


# ---------------------------------------------------------------------------
# get_findings()
# ---------------------------------------------------------------------------


class TestGetFindings:
    def test_returns_all_findings_sorted_by_severity(self, session_id):
        result = get_findings(session_id)
        assert result["status"] == "completed"
        assert result["total"] == 4  # 2 + 1 + 1 from fixture
        # Critical first
        severities = [f["severity"] for f in result["findings"]]
        assert severities == sorted(
            severities,
            key=lambda s: {"critical": 0, "warning": 1, "info": 2}.get(s, 3),
        )

    def test_filter_by_severity_critical(self, session_id):
        result = get_findings(session_id, severity="critical")
        assert result["status"] == "completed"
        assert result["total"] == 3
        assert all(f["severity"] == "critical" for f in result["findings"])

    def test_filter_by_category(self, session_id):
        result = get_findings(session_id, category="node_issues")
        assert result["total"] == 1
        assert all(f["category"] == "node_issues" for f in result["findings"])

    def test_pagination_limit_and_offset(self, session_id):
        page1 = get_findings(session_id, limit=2, offset=0)
        assert page1["returned"] == 2
        assert page1["has_more"] is True

        page2 = get_findings(session_id, limit=2, offset=2)
        assert page2["returned"] == 2
        assert page2["has_more"] is False

        # Pages don't overlap
        page1_ids = {f["id"] for f in page1["findings"]}
        page2_ids = {f["id"] for f in page2["findings"]}
        assert not (page1_ids & page2_ids)

    def test_invalid_category_returns_error(self, session_id):
        result = get_findings(session_id, category="not_a_category")
        assert result["status"] == "error"
        assert "Unknown category" in result["error"]

    def test_invalid_severity_returns_error(self, session_id):
        result = get_findings(session_id, severity="urgent")
        assert result["status"] == "error"
        assert "severity must be one of" in result["error"]

    def test_limit_is_capped_at_500(self, session_id):
        result = get_findings(session_id, limit=99999)
        # Internal cap applied; returned field reflects it
        assert result["limit"] == 500

    def test_finding_ids_are_stable_and_formatted(self, session_id):
        result = get_findings(session_id)
        ids = [f["id"] for f in result["findings"]]
        assert all(i.startswith("F-") and len(i) == 6 for i in ids)
        assert len(set(ids)) == len(ids)  # unique


# ---------------------------------------------------------------------------
# get_correlations()
# ---------------------------------------------------------------------------


class TestGetCorrelations:
    def test_returns_all_when_no_filter(self, session_id, mock_debugger):
        mock_debugger.correlations = [
            {
                "correlation_type": "node_pressure_cascade",
                "severity": "critical",
                "root_cause": "Memory pressure",
                "confidence_tier": "high",
                "composite_confidence": 0.9,
            },
            {
                "correlation_type": "dns_pattern",
                "severity": "warning",
                "root_cause": "CoreDNS down",
                "confidence_tier": "low",
                "composite_confidence": 0.3,
            },
        ]

        result = get_correlations(session_id)

        assert result["status"] == "completed"
        assert result["total"] == 2
        assert result["counts_by_tier"]["high"] == 1
        assert result["counts_by_tier"]["low"] == 1
        assert result["top_root_cause"]["confidence_tier"] == "high"

    def test_filter_by_confidence_tier(self, session_id, mock_debugger):
        mock_debugger.correlations = [
            {"confidence_tier": "high", "composite_confidence": 0.9, "root_cause": "A"},
            {"confidence_tier": "low", "composite_confidence": 0.2, "root_cause": "B"},
        ]

        result = get_correlations(session_id, confidence_tier="high")

        assert result["total"] == 1
        assert result["correlations"][0]["root_cause"] == "A"

    def test_invalid_tier_returns_error(self, session_id):
        result = get_correlations(session_id, confidence_tier="definite")
        assert result["status"] == "error"
        assert "confidence_tier must be one of" in result["error"]


# ---------------------------------------------------------------------------
# get_summary()
# ---------------------------------------------------------------------------


class TestGetSummary:
    def test_summary_counts_match_findings(self, session_id):
        result = get_summary(session_id)
        assert result["status"] == "completed"
        # fixture has 3 critical, 1 warning, 0 info
        assert result["critical"] == 3
        assert result["warning"] == 1
        assert result["info"] == 0
        assert result["total_issues"] == 4

    def test_category_breakdown_skips_empty(self, session_id):
        result = get_summary(session_id)
        # control_plane_issues is empty in the fixture; should not appear
        categories = [c["category"] for c in result["category_breakdown"]]
        assert "control_plane_issues" not in categories
        assert "pod_errors" in categories


# ---------------------------------------------------------------------------
# search_findings()
# ---------------------------------------------------------------------------


class TestSearchFindings:
    def test_finds_by_summary_substring(self, session_id):
        result = search_findings(session_id, "CrashLoopBackOff")
        assert result["status"] == "completed"
        assert result["total"] == 1
        assert "CrashLoopBackOff" in result["matches"][0]["summary"]

    def test_finds_by_details_value(self, session_id):
        # The node name ip-10-0-1-50 lives in details, not summary
        result = search_findings(session_id, "ip-10-0-1-50")
        assert result["total"] == 1
        assert result["matches"][0]["category"] == "node_issues"

    def test_case_insensitive(self, session_id):
        result = search_findings(session_id, "oomkilled")
        assert result["total"] == 1

    def test_no_matches_returns_empty(self, session_id):
        result = search_findings(session_id, "definitely_not_present_xyz")
        assert result["total"] == 0
        assert result["matches"] == []

    def test_empty_query_returns_error(self, session_id):
        result = search_findings(session_id, "")
        assert result["status"] == "error"
        assert "non-empty" in result["error"]


# ---------------------------------------------------------------------------
# get_timeline()
# ---------------------------------------------------------------------------


class TestGetTimeline:
    def test_returns_timeline_buckets(self, session_id, mock_debugger):
        mock_debugger.timeline = [
            {"time_bucket": "2026-06-18 10:00", "event_count": 5},
            {"time_bucket": "2026-06-18 11:00", "event_count": 2},
        ]
        result = get_timeline(session_id, hours=168)  # wide window
        assert result["status"] == "completed"
        assert result["buckets"] == 2
        assert result["total_events"] == 7

    def test_filter_by_hours(self, session_id, mock_debugger):
        # Bucket far in the past + bucket recent
        mock_debugger.timeline = [
            {"time_bucket": "2020-01-01 00:00", "event_count": 99},
            {
                "time_bucket": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "event_count": 1,
            },
        ]
        result = get_timeline(session_id, hours=24)
        # Only the recent bucket passes the filter
        assert result["buckets"] == 1
        assert result["total_events"] == 1


# ---------------------------------------------------------------------------
# get_remediation()
# ---------------------------------------------------------------------------


class TestGetRemediation:
    def test_requires_finding_id_or_category(self, session_id):
        result = get_remediation(session_id)
        assert result["status"] == "error"
        assert "Either finding_id or category" in result["error"]

    def test_by_finding_id_returns_remediation(self, session_id, mocker):
        # F-0001 is the first finding (pod_errors CrashLoopBackOff)
        mocker.patch(
            "eks_mcp_server.get_remediation_commands",
            return_value={
                "diagnostic": ["kubectl logs ..."],
                "fix": ["kubectl rollout restart ..."],
                "aws_doc": "https://example.com/doc",
            },
        )
        result = get_remediation(session_id, finding_id="F-0001")
        assert result["status"] == "completed"
        assert result["finding_id"] == "F-0001"
        assert result["remediation"]["aws_doc"].startswith("https://")

    def test_unknown_finding_id_returns_error(self, session_id):
        result = get_remediation(session_id, finding_id="F-9999")
        assert result["status"] == "error"
        assert "not found" in result["error"]

    def test_by_category_returns_entries(self, session_id, mocker):
        mocker.patch(
            "eks_mcp_server.get_remediation_commands",
            return_value={"diagnostic": [], "fix": [], "aws_doc": None},
        )
        result = get_remediation(session_id, category="pod_errors")
        assert result["status"] == "completed"
        # fixture has 2 pod_errors findings
        assert result["findings_with_remediation"] == 2


# ---------------------------------------------------------------------------
# get_recommendations()
# ---------------------------------------------------------------------------


class TestGetRecommendations:
    def test_returns_sorted_recommendations(self, session_id, mock_debugger):
        mock_debugger.generate_recommendations.return_value = [
            {"title": "A", "priority": "info"},
            {"title": "B", "priority": "critical"},
            {"title": "C", "priority": "warning"},
        ]
        result = get_recommendations(session_id)
        assert result["status"] == "completed"
        assert result["total"] == 3
        assert result["critical_count"] == 1
        # Sorted: critical → warning → info
        priorities = [r["priority"] for r in result["recommendations"]]
        assert priorities == ["critical", "warning", "info"]

    def test_handles_generation_failure(self, session_id, mock_debugger):
        mock_debugger.generate_recommendations.side_effect = RuntimeError("nope")
        result = get_recommendations(session_id)
        # Tool must not raise; falls back to empty list
        assert result["status"] == "completed"
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# collect_node_diagnostics()
# ---------------------------------------------------------------------------


class TestCollectNodeDiagnostics:
    def test_enables_node_diagnostics_flag(self, session_id, mock_debugger):
        result = collect_node_diagnostics(session_id, max_nodes=5)
        assert result["status"] == "completed"
        assert mock_debugger.enable_node_diagnostics is True
        assert mock_debugger.ssm_max_nodes == 5
        mock_debugger._run_node_os_diagnostics.assert_called_once()

    def test_caps_max_nodes_at_50(self, session_id, mock_debugger):
        collect_node_diagnostics(session_id, max_nodes=9999)
        assert mock_debugger.ssm_max_nodes == 50

    def test_ssm_failure_does_not_abort_tool(self, session_id, mock_debugger):
        mock_debugger._run_node_os_diagnostics.side_effect = RuntimeError("SSM down")
        result = collect_node_diagnostics(session_id)
        assert result["status"] == "completed"
        mock_debugger._add_error.assert_called()


# ---------------------------------------------------------------------------
# format_for_llm()
# ---------------------------------------------------------------------------


class TestFormatForLLM:
    def test_returns_llm_json_string(self, session_id, mock_debugger, mocker):
        # The formatter returns a JSON string; mock it to avoid depending
        # on the full LLMJSONOutputFormatter implementation.
        mocker.patch(
            "eks_mcp_server.LLMJSONOutputFormatter.format",
            return_value='{"summary": {"critical": 3}}',
        )
        result = format_for_llm(session_id)
        assert result["status"] == "completed"
        assert isinstance(result["llm_json"], str)
        assert "critical" in result["llm_json"]
        assert result["metadata"]["cluster"] == "test-cluster"

    def test_include_findings_false_passes_empty_dict(self, session_id, mock_debugger, mocker):
        captured: dict = {}
        real_format = MagicMock(return_value="{}")

        def spy(self, results):
            captured["findings"] = results.get("findings")
            return real_format.return_value

        mocker.patch("eks_mcp_server.LLMJSONOutputFormatter.format", spy)

        format_for_llm(session_id, include_findings=False)

        assert captured["findings"] == {}


# ---------------------------------------------------------------------------
# Error handling — the core MCP invariant
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Every tool must return an error dict for an unknown session — never raise."""

    @pytest.mark.parametrize(
        "tool",
        [
            cluster_health,
            analyze_pods,
            analyze_nodes,
            analyze_networking,
            analyze_control_plane,
            analyze_storage,
            analyze_iam,
            run_full_analysis,
            get_summary,
            get_timeline,
            get_recommendations,
            collect_node_diagnostics,
            format_for_llm,
        ],
    )
    def test_invalid_session_returns_error_dict(self, tool):
        result = tool("sess_invalid")
        assert result["status"] == "error"
        assert isinstance(result["error"], str)

    def test_get_findings_invalid_session_returns_error_dict(self):
        result = get_findings("sess_invalid")
        assert result["status"] == "error"

    def test_search_findings_invalid_session_returns_error_dict(self):
        result = search_findings("sess_invalid", "anything")
        assert result["status"] == "error"

    def test_get_correlations_invalid_session_returns_error_dict(self):
        result = get_correlations("sess_invalid")
        assert result["status"] == "error"

    def test_get_remediation_invalid_session_returns_error_dict(self):
        result = get_remediation("sess_invalid", category="pod_errors")
        assert result["status"] == "error"
