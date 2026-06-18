"""EKS Debugger MCP Server.

Exposes the EKS Health Check Dashboard's diagnostic capabilities as discoverable,
invocable tools for AI agents (Claude Desktop, AWS DevOps Agent, Copilot, etc.)
via the Model Context Protocol (MCP).

Architecture:
    - Thin wrapper over ``ComprehensiveEKSDebugger`` (no logic duplication)
    - Session-based state: each AI agent session gets its own debugger instance
    - Auto-expiry: sessions expire after 30 minutes of inactivity
    - Structured returns: every tool returns a dict; exceptions never escape

Transports:
    - stdio (default) — for Claude Desktop, works out of the box
    - streamable-http — for remote deployment

Usage:
    # Run as MCP server (stdio transport — for Claude Desktop)
    python eks_mcp_server.py

    # Run with HTTP transport
    python eks_mcp_server.py --transport streamable-http --port 8080

Claude Desktop Configuration (~/Library/Application Support/Claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "eks-debugger": {
          "command": "python",
          "args": ["/path/to/eks_mcp_server.py"],
          "env": {
            "AWS_PROFILE": "production",
            "AWS_REGION": "us-east-1"
          }
        }
      }
    }
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from eks_comprehensive_debugger import (
    VERSION,
    FindingType,
    LLMJSONOutputFormatter,
    ProgressTracker,
    ComprehensiveEKSDebugger,
    get_remediation_commands,
)

# MCP server instance — all @mcp.tool() decorators register against this
mcp = FastMCP("EKS Debugger MCP Server")

# Number of tools exposed by this server (for startup banner / health checks)
TOOL_COUNT = 18

# Sessions auto-expire after this many minutes of inactivity
SESSION_TIMEOUT_MINUTES = 30


# ---------------------------------------------------------------------------
# Session State Management
# ---------------------------------------------------------------------------


@dataclass
class _SessionState:
    """Mutable state for a single MCP client session.

    Each session owns its own ``ComprehensiveEKSDebugger`` instance; there is
    no shared mutable state between sessions (thread isolation by design).
    """

    debugger: ComprehensiveEKSDebugger
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    analysis_complete: bool = False

    def touch(self) -> None:
        """Mark activity on this session (used for expiry)."""
        self.last_activity = datetime.now(timezone.utc)


# In-memory session store. Keyed by opaque session id (``sess_<random>``).
# Not process-persistent: restarting the MCP server drops all sessions.
_sessions: dict[str, _SessionState] = {}


def _get_session(session_id: str) -> _SessionState:
    """Return the active session for ``session_id`` or raise ``ValueError``.

    Touches ``last_activity`` on every access (sliding-window expiry).
    """
    if session_id not in _sessions:
        raise ValueError(f"Session {session_id} not found. Call connect() first to create a session.")
    session = _sessions[session_id]
    session.touch()
    return session


def _cleanup_expired_sessions() -> None:
    """Remove sessions whose ``last_activity`` exceeds ``SESSION_TIMEOUT_MINUTES``."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=SESSION_TIMEOUT_MINUTES)
    expired = [sid for sid, s in _sessions.items() if s.last_activity < cutoff]
    for sid in expired:
        del _sessions[sid]


def _make_session_id() -> str:
    """Generate a fresh, opaque session id."""
    return f"sess_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Internal helpers (not exposed as MCP tools)
# ---------------------------------------------------------------------------


def _category_summary(debugger: ComprehensiveEKSDebugger, categories: list[str]) -> dict[str, int]:
    """Return severity counts across the given finding categories.

    Severity lives inside ``details`` (per project convention), defaulting to
    ``"info"`` when not set.
    """
    critical = warning = info = 0
    for cat in categories:
        for finding in debugger.findings.get(cat, []):
            severity = finding.get("details", {}).get("severity", "info")
            if severity == "critical":
                critical += 1
            elif severity == "warning":
                warning += 1
            else:
                info += 1
    return {"critical": critical, "warning": warning, "info": info}


def _run_analysis_group(
    debugger: ComprehensiveEKSDebugger, methods: list[Callable[[], None]]
) -> tuple[int, list[dict[str, str]]]:
    """Run a list of analysis methods with per-method error isolation.

    Mirrors the existing parallel-analysis pattern: if one method throws, the
    others still run. Errors are recorded on the debugger via ``_add_error``.

    Returns:
        (methods_run, errors) — ``methods_run`` is the count of attempted
        methods (not successful ones); ``errors`` is the last 5 errors seen.
    """
    for method in methods:
        try:
            method()
        except Exception as e:  # noqa: BLE001 — intentional graceful degradation
            debugger._add_error(getattr(method, "__name__", "unknown"), str(e))
    return len(methods), debugger.errors[-5:] if debugger.errors else []


def _error_response(exc: Exception) -> dict[str, str]:
    """Build a uniform error dict for unexpected exceptions."""
    if isinstance(exc, ValueError):
        return {"status": "error", "error": str(exc)}
    return {"status": "error", "error": f"Unexpected error: {exc}"}


# ---------------------------------------------------------------------------
# Tier 1 — Connection & Setup
# ---------------------------------------------------------------------------


@mcp.tool()
def connect(
    profile: str,
    region: str,
    cluster_name: str,
    hours: int = 24,
    namespace: str | None = None,
    kube_context: str | None = None,
) -> dict[str, Any]:
    """Connect to an EKS cluster for diagnostic analysis.

    Establishes an AWS session, validates credentials, and sets up kubectl.
    Must be called before any analysis tools.

    Args:
        profile: AWS profile name (e.g., 'production')
        region: AWS region (e.g., 'us-east-1')
        cluster_name: EKS cluster name
        hours: Look-back window in hours (default: 24)
        namespace: Optional namespace filter
        kube_context: Optional kubectl context (skips kubeconfig update)

    Returns:
        Connection status with session_id (required for subsequent calls),
        cluster metadata, and node/pod counts from the pre-fetched snapshot.
    """
    try:
        _cleanup_expired_sessions()

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(hours=max(1, hours))

        debugger = ComprehensiveEKSDebugger(
            profile=profile,
            region=region,
            cluster_name=cluster_name,
            start_date=start_date,
            end_date=end_date,
            namespace=namespace,
            progress=ProgressTracker(quiet=True),  # Silent in MCP mode
            kube_context=kube_context,
            # Node OS diagnostics is opt-in per call via collect_node_diagnostics
            enable_node_diagnostics=False,
        )

        # Minimum setup before any analysis method can be called individually
        debugger.validate_aws_access()
        debugger.get_cluster_name()
        debugger.update_kubeconfig()
        debugger._prefetch_shared_data()

        session_id = _make_session_id()
        _sessions[session_id] = _SessionState(debugger=debugger)

        # Pull counts from pre-fetched snapshot (no extra API calls)
        with debugger._shared_data_lock:
            node_info = debugger._shared_data.get("node_info") or {}
            pod_info = debugger._shared_data.get("pod_info") or {}
            node_count = len(node_info.get("items", []))
            pod_count = len(pod_info.get("items", []))

        # Distinct namespaces from pod snapshot (cheap client-side derive)
        namespaces = {(item.get("metadata", {}) or {}).get("namespace", "") for item in pod_info.get("items", [])}
        namespaces.discard("")

        return {
            "status": "connected",
            "session_id": session_id,
            "cluster": debugger.cluster_name,
            "region": debugger.region,
            "nodes": node_count,
            "pods": pod_count,
            "namespaces": len(namespaces),
            "analysis_window_hours": max(1, hours),
            "namespace_filter": namespace or "all",
        }
    except Exception as e:  # noqa: BLE001 — never raise to MCP client
        return _error_response(e)


@mcp.tool()
def cluster_health(session_id: str) -> dict[str, Any]:
    """Quick cluster health overview for initial triage.

    Returns node condition counts (Ready / NotReady / Unknown), pod phase
    breakdown (Running / Pending / Failed / Succeeded), and the count of
    critical findings already detected in this session.

    Faster than full analysis — runs no new analysis methods; only inspects
    the pre-fetched snapshot and any findings collected so far.
    """
    try:
        session = _get_session(session_id)
        debugger = session.debugger

        with debugger._shared_data_lock:
            node_info = debugger._shared_data.get("node_info") or {}
            pod_info = debugger._shared_data.get("pod_info") or {}

        node_conditions = {"Ready": 0, "NotReady": 0, "Unknown": 0}
        for item in node_info.get("items", []):
            ready = False
            conditions = item.get("status", {}).get("conditions", []) or []
            for cond in conditions:
                if cond.get("type") == "Ready":
                    ready = cond.get("status") == "True"
                    break
            if ready:
                node_conditions["Ready"] += 1
            elif conditions:
                node_conditions["NotReady"] += 1
            else:
                node_conditions["Unknown"] += 1

        pod_phases = {"Running": 0, "Pending": 0, "Failed": 0, "Succeeded": 0, "Unknown": 0}
        for item in pod_info.get("items", []):
            phase = (item.get("status", {}) or {}).get("phase", "Unknown")
            pod_phases[phase] = pod_phases.get(phase, 0) + 1

        all_categories = list(debugger.findings.keys())
        severity_counts = _category_summary(debugger, all_categories)

        return {
            "status": "completed",
            "nodes": node_conditions,
            "pods": pod_phases,
            "findings_so_far": severity_counts,
            "analysis_complete": session.analysis_complete,
        }
    except Exception as e:  # noqa: BLE001 — never raise to MCP client
        return _error_response(e)


# ---------------------------------------------------------------------------
# Tier 2 — Analysis (grouped by domain)
# ---------------------------------------------------------------------------

# Category ownership per domain — used to summarize each analyze_* tool's output.
# A domain "owns" the categories its methods primarily populate.
_POD_CATEGORIES = [
    "pod_errors",
    "oom_killed",
    "image_pull_failures",
    "scheduling_failures",
    "memory_pressure",
    "disk_pressure",
]
_NODE_CATEGORIES = ["node_issues"]
_NETWORK_CATEGORIES = ["network_issues", "dns_issues"]
_CONTROL_PLANE_CATEGORIES = ["control_plane_issues"]
_STORAGE_CATEGORIES = ["pvc_issues"]
_IAM_CATEGORIES = ["rbac_issues"]
# Node OS categories populated by Phase 1 SSM diagnostics
_NODE_OS_CATEGORIES = [
    "node_os_iptables",
    "node_os_conntrack",
    "node_os_dmesg",
    "node_os_kubelet",
    "node_os_containerd",
    "node_os_ipamd",
    "node_os_routes",
    "node_os_cni_config",
    "node_os_sysctl",
    "node_os_eni",
]


def _analyze_domain(
    session_id: str, domain: str, methods: list[Callable[[], None]], categories: list[str]
) -> dict[str, Any]:
    """Shared body for the per-domain analyze_* tools.

    Runs each method with per-method error isolation, runs correlation on
    whatever findings exist, and returns a uniform summary.
    """
    try:
        session = _get_session(session_id)
        debugger = session.debugger
        methods_run, recent_errors = _run_analysis_group(debugger, methods)
        # Correlate against whatever we have so far (safe on partial data)
        try:
            debugger.correlate_findings()
        except Exception as e:  # noqa: BLE001 — correlation must not abort the tool
            debugger._add_error("correlate_findings", str(e))
        findings_count = sum(len(debugger.findings.get(c, [])) for c in categories)
        categories_with_findings = [c for c in categories if debugger.findings.get(c)]
        return {
            "status": "completed",
            "domain": domain,
            "methods_run": methods_run,
            "findings_count": findings_count,
            "categories_with_findings": categories_with_findings,
            "summary": _category_summary(debugger, categories),
            "recent_errors": recent_errors,
        }
    except Exception as e:  # noqa: BLE001 — never raise to MCP client
        return _error_response(e)


@mcp.tool()
def analyze_pods(session_id: str) -> dict[str, Any]:
    """Analyze pod health: CrashLoopBackOff, OOMKilled, ImagePullBackOff,
    evictions, probe failures, init containers, sidecars, PDB violations,
    stuck terminations, deployment rollouts, Jobs/CronJobs, StatefulSets,
    and ephemeral containers.

    Runs 13 pod-related analysis methods. Duration: ~30-60 seconds.
    Use get_findings(category=..., severity="critical") to drill into results.
    """
    try:
        session = _get_session(session_id)
    except Exception as e:
        return _error_response(e)
    debugger = session.debugger
    methods = [
        debugger.analyze_pod_evictions,
        debugger.check_oom_events,
        debugger.analyze_pod_health_deep,
        debugger.analyze_probe_failures,
        debugger.analyze_image_pull_failures,
        debugger.analyze_init_container_failures,
        debugger.analyze_sidecar_health,
        debugger.analyze_pdb_violations,
        debugger.analyze_pods_terminating,
        debugger.analyze_deployment_rollouts,
        debugger.analyze_jobs_cronjobs,
        debugger.analyze_statefulset_issues,
        debugger.analyze_ephemeral_containers,
    ]
    return _analyze_domain(session_id, "pods", methods, _POD_CATEGORIES)


@mcp.tool()
def analyze_nodes(session_id: str) -> dict[str, Any]:
    """Analyze node health: conditions (NotReady, DiskPressure, MemoryPressure),
    resource saturation, AMI age, version skew, certificate expiry, PLEG,
    container runtime, pause image, managed node groups, Windows nodes,
    workload security posture, topology spread, and Karpenter drift.

    Runs 13 node-related analysis methods. Duration: ~20-40 seconds.
    Node OS-level diagnostics (iptables, conntrack, dmesg) are opt-in via
    collect_node_diagnostics (Phase 1 SSM integration).
    """
    try:
        session = _get_session(session_id)
    except Exception as e:
        return _error_response(e)
    debugger = session.debugger
    methods = [
        debugger.analyze_node_conditions,
        debugger.analyze_eks_nodegroup_health,
        debugger.analyze_certificate_expiry,
        debugger.analyze_windows_nodes,
        debugger.analyze_pleg_health,
        debugger.analyze_container_runtime,
        debugger.analyze_pause_image_issues,
        debugger.analyze_node_resource_saturation,
        debugger.analyze_version_skew,
        debugger.analyze_node_ami_age,
        debugger.analyze_topology_spread,
        debugger.analyze_workload_security_posture,
        debugger.analyze_karpenter_drift,
    ]
    # Node analysis also benefits from any Phase 1 SSM findings already collected
    categories = _NODE_CATEGORIES + _NODE_OS_CATEGORIES
    return _analyze_domain(session_id, "nodes", methods, categories)


@mcp.tool()
def analyze_networking(session_id: str) -> dict[str, Any]:
    """Analyze networking: VPC CNI health, CoreDNS, DNS configuration,
    services, EndpointSlices, ingress, NetworkPolicies, ALB health,
    conntrack, subnets, security groups, and general connectivity issues.

    Runs 12 networking analysis methods. Duration: ~30-50 seconds.
    """
    try:
        session = _get_session(session_id)
    except Exception as e:
        return _error_response(e)
    debugger = session.debugger
    methods = [
        debugger.analyze_network_issues,
        debugger.analyze_vpc_cni_health,
        debugger.analyze_coredns_health,
        debugger.analyze_service_health,
        debugger.analyze_subnet_health,
        debugger.analyze_security_groups,
        debugger.analyze_network_policies,
        debugger.analyze_alb_health,
        debugger.analyze_conntrack_health,
        debugger.analyze_ingress_health,
        debugger.analyze_dns_configuration,
        debugger.analyze_endpointslice_health,
    ]
    return _analyze_domain(session_id, "networking", methods, _NETWORK_CATEGORIES)


@mcp.tool()
def analyze_control_plane(session_id: str) -> dict[str, Any]:
    """Analyze control plane: API server latency, rate limiting, inflight
    requests, etcd health (quota, leader changes), controller manager,
    scheduler, admission webhooks, and CloudWatch control-plane log errors.

    Runs 8 control-plane analysis methods. Duration: ~30-60 seconds
    (depends on CloudWatch log volume).
    """
    try:
        session = _get_session(session_id)
    except Exception as e:
        return _error_response(e)
    debugger = session.debugger
    methods = [
        debugger.analyze_control_plane_logs,
        debugger.analyze_apiserver_latency,
        debugger.analyze_apiserver_rate_limiting,
        debugger.analyze_apiserver_inflight,
        debugger.analyze_etcd_health,
        debugger.analyze_controller_manager,
        debugger.analyze_scheduler_health,
        debugger.analyze_admission_webhooks,
    ]
    return _analyze_domain(session_id, "control_plane", methods, _CONTROL_PLANE_CATEGORIES)


@mcp.tool()
def analyze_storage(session_id: str) -> dict[str, Any]:
    """Analyze storage: PVC issues (Pending, ProvisioningFailed), EBS CSI
    driver health (attachment failures, AZ mismatch), EFS CSI health
    (mount failures), and volume snapshot operations.

    Runs 4 storage analysis methods.
    """
    try:
        session = _get_session(session_id)
    except Exception as e:
        return _error_response(e)
    debugger = session.debugger
    methods = [
        debugger.analyze_pvc_issues,
        debugger.analyze_ebs_csi_health,
        debugger.analyze_efs_csi_health,
        debugger.analyze_volume_snapshots,
    ]
    return _analyze_domain(session_id, "storage", methods, _STORAGE_CATEGORIES)


@mcp.tool()
def analyze_iam(session_id: str) -> dict[str, Any]:
    """Analyze IAM/RBAC: RBAC errors (Forbidden, Unauthorized), IRSA and
    Pod Identity credential failures, Pod Security Admission violations,
    missing ConfigMaps/Secrets, and deprecated API usage (upgrade readiness).

    Runs 5 IAM/security analysis methods.
    """
    try:
        session = _get_session(session_id)
    except Exception as e:
        return _error_response(e)
    debugger = session.debugger
    methods = [
        debugger.analyze_rbac_issues,
        debugger.analyze_iam_pod_identity,
        debugger.analyze_psa_violations,
        debugger.analyze_missing_config_resources,
        debugger.analyze_deprecated_apis,
    ]
    return _analyze_domain(session_id, "iam", methods, _IAM_CATEGORIES)


@mcp.tool()
def run_full_analysis(session_id: str) -> dict[str, Any]:
    """Run ALL analysis methods (pods, nodes, networking, control plane,
    storage, IAM, autoscaling, observability, addons) and return a
    comprehensive summary including correlations and recommendations.

    This is the most thorough option but takes 2-10 minutes depending on
    cluster size and CloudWatch log volume. Use the targeted analyze_*
    tools (analyze_pods, analyze_nodes, etc.) for faster domain-specific
    investigation.

    Returns severity counts across all categories plus a top-correlations
    preview. Use get_findings / get_correlations / get_recommendations
    for detailed drill-down.
    """
    try:
        session = _get_session(session_id)
        debugger = session.debugger

        # Delegate to the debugger's own orchestrator. It handles parallel
        # execution, correlation, recommendation generation, and graceful
        # per-method error isolation. Setup calls inside are no-ops when
        # already done (validate_aws_access, get_cluster_name, etc. are cached).
        results = debugger.run_comprehensive_analysis()
        session.analysis_complete = True

        # Build a compact summary for the AI agent — full results are queried
        # via the dedicated Tier 3 tools (get_findings, get_correlations, etc.).
        summary = results.get("summary", {})
        correlations = results.get("correlations", []) or []
        recommendations = results.get("recommendations", []) or []

        # Top 5 correlations by composite confidence (already sorted upstream,
        # but we re-sort defensively in case of upstream changes).
        def _corr_score(c: dict) -> float:
            return float(c.get("composite_confidence") or 0.0)

        top_correlations = sorted(correlations, key=_corr_score, reverse=True)[:5]
        top_correlations_compact = [
            {
                "correlation_type": c.get("correlation_type", ""),
                "severity": c.get("severity", "info"),
                "root_cause": c.get("root_cause", ""),
                "confidence_tier": c.get("confidence_tier", "low"),
                "composite_confidence": c.get("composite_confidence", 0.0),
            }
            for c in top_correlations
        ]

        return {
            "status": "completed",
            "domain": "full",
            "summary": summary,
            "categories_with_findings": [cat for cat, items in debugger.findings.items() if items],
            "correlations_count": len(correlations),
            "recommendations_count": len(recommendations),
            "top_correlations": top_correlations_compact,
            "errors": (results.get("errors") or [])[-5:],
        }
    except Exception as e:  # noqa: BLE001 — never raise to MCP client
        return _error_response(e)


# ---------------------------------------------------------------------------
# Tier 3 — Results & Query
# ---------------------------------------------------------------------------


def _ensure_correlated(debugger: ComprehensiveEKSDebugger) -> None:
    """Run correlation if it hasn't been run yet (idempotent, safe on partial)."""
    # correlate_findings() is safe to call multiple times — it rebuilds from
    # the current findings dict. We treat the absence of any correlation
    # artifacts as a signal that it hasn't run.
    if not getattr(debugger, "correlations", None):
        try:
            debugger.correlate_findings()
        except Exception as e:  # noqa: BLE001
            debugger._add_error("correlate_findings", str(e))


@mcp.tool()
def get_findings(
    session_id: str,
    category: str | None = None,
    severity: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Get diagnostic findings with optional category and severity filtering.

    Findings are sorted by severity (critical first) and paginated.
    Each finding includes a stable ``id`` (F-0001…) for cross-reference
    with get_remediation.

    Args:
        category: Filter by category (e.g., 'pod_errors', 'node_issues',
            'oom_killed', 'control_plane_issues', 'network_issues',
            'image_pull_failures', 'scheduling_failures', 'rbac_issues',
            'pvc_issues', 'dns_issues', or any 'node_os_*' category).
        severity: Filter by severity — 'critical', 'warning', or 'info'.
        limit: Max findings to return (default: 50, capped at 500).
        offset: Pagination offset for paging through large result sets.

    Returns:
        Paginated findings list with total count and has_more flag.
    """
    try:
        session = _get_session(session_id)
        debugger = session.debugger

        # Clamp limit to a sane upper bound
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        if severity is not None:
            severity = severity.lower()
            if severity not in ("critical", "warning", "info"):
                return {
                    "status": "error",
                    "error": (f"severity must be one of: 'critical', 'warning', 'info' (got {severity!r})"),
                }

        categories = [category] if category else list(debugger.findings.keys())
        # Validate requested category exists (case sensitive — these are dict keys)
        if category is not None and category not in debugger.findings:
            available = sorted(debugger.findings.keys())
            return {
                "status": "error",
                "error": (f"Unknown category {category!r}. Available: {available}"),
            }

        all_findings: list[dict[str, Any]] = []
        finding_counter = 0
        for cat in categories:
            for item in debugger.findings.get(cat, []):
                finding_counter += 1
                details = item.get("details", {}) or {}
                item_severity = details.get("severity", "info")
                if severity and item_severity != severity:
                    continue
                finding_entry = {
                    "id": f"F-{finding_counter:04d}",
                    "category": cat,
                    "severity": item_severity,
                    "finding_type": details.get("finding_type", FindingType.CURRENT_STATE),
                    "summary": item.get("summary", ""),
                    "details": {k: v for k, v in details.items() if k != "finding_type"},
                }
                timestamp = details.get("timestamp") or details.get("event_time")
                if timestamp:
                    finding_entry["timestamp"] = str(timestamp)
                all_findings.append(finding_entry)

        severity_order = {"critical": 0, "warning": 1, "info": 2}
        all_findings.sort(key=lambda f: severity_order.get(f["severity"], 3))

        total = len(all_findings)
        paginated = all_findings[offset : offset + limit]

        return {
            "status": "completed",
            "findings": paginated,
            "total": total,
            "returned": len(paginated),
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total,
            "filter": {
                "category": category,
                "severity": severity,
            },
        }
    except Exception as e:  # noqa: BLE001 — never raise to MCP client
        return _error_response(e)


@mcp.tool()
def get_correlations(
    session_id: str,
    confidence_tier: str | None = None,
) -> dict[str, Any]:
    """Get root cause correlations with 5D confidence scoring.

    Correlations are produced by ``correlate_findings()`` from the current
    findings set. They link findings across data sources (e.g., node memory
    pressure → pod evictions) and rank root causes using five dimensions:
    temporal, spatial, mechanism, exclusivity, reproducibility.

    Args:
        confidence_tier: Optional filter — 'high' (≥0.75), 'medium' (≥0.50),
            or 'low' (<0.50). Omit to return all correlations.

    Returns:
        Correlations list (filtered), counts by tier, and the highest-confidence
        root cause identified.
    """
    try:
        session = _get_session(session_id)
        debugger = session.debugger

        if confidence_tier is not None:
            confidence_tier = confidence_tier.lower()
            if confidence_tier not in ("high", "medium", "low"):
                return {
                    "status": "error",
                    "error": (f"confidence_tier must be one of: 'high', 'medium', 'low' (got {confidence_tier!r})"),
                }

        _ensure_correlated(debugger)
        correlations = list(getattr(debugger, "correlations", []) or [])

        # Group by tier for the counts (defensive against missing field)
        by_tier: dict[str, list[dict[str, Any]]] = {"high": [], "medium": [], "low": []}
        for corr in correlations:
            tier = corr.get("confidence_tier", "low")
            by_tier.setdefault(tier, []).append(corr)

        if confidence_tier:
            returned = by_tier.get(confidence_tier, [])
        else:
            returned = correlations

        # Compact representation for the AI agent
        compact = [
            {
                "correlation_type": c.get("correlation_type", ""),
                "severity": c.get("severity", "info"),
                "root_cause": c.get("root_cause", ""),
                "impact": c.get("impact", ""),
                "confidence_tier": c.get("confidence_tier", "low"),
                "composite_confidence": c.get("composite_confidence", 0.0),
                "recommendation": c.get("recommendation", ""),
                "aws_doc": c.get("aws_doc", ""),
            }
            for c in returned
        ]

        # Highest-confidence root cause (if any) — quick signal for triage
        top_root_cause = None
        if correlations:
            sorted_corrs = sorted(
                correlations,
                key=lambda c: float(c.get("composite_confidence") or 0.0),
                reverse=True,
            )
            best = sorted_corrs[0]
            top_root_cause = {
                "correlation_type": best.get("correlation_type", ""),
                "root_cause": best.get("root_cause", ""),
                "confidence_tier": best.get("confidence_tier", "low"),
                "composite_confidence": best.get("composite_confidence", 0.0),
            }

        return {
            "status": "completed",
            "correlations": compact,
            "total": len(compact),
            "counts_by_tier": {k: len(v) for k, v in by_tier.items()},
            "top_root_cause": top_root_cause,
            "filter": {"confidence_tier": confidence_tier},
        }
    except Exception as e:  # noqa: BLE001 — never raise to MCP client
        return _error_response(e)


@mcp.tool()
def get_summary(session_id: str) -> dict[str, Any]:
    """Get analysis summary: issue counts by severity, affected categories,
    and finding-type breakdown (historical_event vs current_state).

    Reflects whatever analysis has run so far in this session. Call
    run_full_analysis() first for complete coverage.
    """
    try:
        session = _get_session(session_id)
        debugger = session.debugger

        all_categories = list(debugger.findings.keys())
        severity_counts = _category_summary(debugger, all_categories)

        # Per-category breakdown (skip empty)
        category_breakdown: list[dict[str, Any]] = []
        historical_count = 0
        current_state_count = 0
        for cat in all_categories:
            items = debugger.findings.get(cat, []) or []
            if not items:
                continue
            cat_sev = _category_summary(debugger, [cat])
            category_breakdown.append(
                {
                    "category": cat,
                    "total": len(items),
                    **cat_sev,
                }
            )
            for item in items:
                ft = (item.get("details", {}) or {}).get("finding_type", FindingType.CURRENT_STATE)
                if ft == FindingType.HISTORICAL_EVENT:
                    historical_count += 1
                else:
                    current_state_count += 1

        # Sort categories by critical count desc, then total desc
        category_breakdown.sort(key=lambda c: (c["critical"], c["total"]), reverse=True)

        return {
            "status": "completed",
            "total_issues": severity_counts["critical"] + severity_counts["warning"] + severity_counts["info"],
            "critical": severity_counts["critical"],
            "warning": severity_counts["warning"],
            "info": severity_counts["info"],
            "historical_events": historical_count,
            "current_state_issues": current_state_count,
            "categories_affected": len(category_breakdown),
            "category_breakdown": category_breakdown,
            "analysis_complete": session.analysis_complete,
            "errors_count": len(debugger.errors),
        }
    except Exception as e:  # noqa: BLE001 — never raise to MCP client
        return _error_response(e)


@mcp.tool()
def search_findings(
    session_id: str,
    query: str,
    category: str | None = None,
) -> dict[str, Any]:
    """Full-text search across all findings (summaries and details).

    Case-insensitive substring match against finding summaries and the
    string-form of every value in details. Useful for ad-hoc queries like
    'OOMKilled', 'ip-10-0-1-50', 'CrashLoopBackOff', or a namespace name.

    Args:
        query: Search query (matches summary and all details values).
        category: Optional category filter to narrow the search scope.

    Returns:
        Matching findings (sorted by severity) with total count.
    """
    try:
        session = _get_session(session_id)
        debugger = session.debugger

        if not query or not query.strip():
            return {
                "status": "error",
                "error": "query must be a non-empty string",
            }
        needle = query.lower()

        if category is not None and category not in debugger.findings:
            return {
                "status": "error",
                "error": (f"Unknown category {category!r}. Available: {sorted(debugger.findings.keys())}"),
            }

        categories = [category] if category else list(debugger.findings.keys())
        matches: list[dict[str, Any]] = []
        finding_counter = 0
        for cat in categories:
            for item in debugger.findings.get(cat, []):
                finding_counter += 1
                summary = item.get("summary", "") or ""
                details = item.get("details", {}) or {}

                # Build a searchable blob: summary + all stringified detail values
                values = [summary]
                for v in details.values():
                    if v is None:
                        continue
                    values.append(str(v))
                blob = " ".join(values).lower()

                if needle not in blob:
                    continue

                severity = details.get("severity", "info")
                matches.append(
                    {
                        "id": f"F-{finding_counter:04d}",
                        "category": cat,
                        "severity": severity,
                        "finding_type": details.get("finding_type", FindingType.CURRENT_STATE),
                        "summary": summary,
                        "details": {k: v for k, v in details.items() if k != "finding_type"},
                    }
                )

        severity_order = {"critical": 0, "warning": 1, "info": 2}
        matches.sort(key=lambda f: severity_order.get(f["severity"], 3))

        return {
            "status": "completed",
            "query": query,
            "matches": matches,
            "total": len(matches),
            "filter": {"category": category},
        }
    except Exception as e:  # noqa: BLE001 — never raise to MCP client
        return _error_response(e)


@mcp.tool()
def get_timeline(session_id: str, hours: int = 24) -> dict[str, Any]:
    """Get chronological event timeline bucketed by hour.

    Useful for understanding incident progression — when issues started,
    peaked, and resolved. Each bucket includes event count, contributing
    categories, and a bucket-level severity.

    Args:
        hours: Restrict timeline to the most recent N hours (default: 24).
            Set to a large value (e.g., 168) to see the full analysis window.

    Returns:
        Timeline buckets (newest first), total event count, and the
        earliest bucket timestamp (likely the incident start).
    """
    try:
        session = _get_session(session_id)
        debugger = session.debugger

        _ensure_correlated(debugger)
        timeline = list(getattr(debugger, "timeline", []) or [])

        # Filter by hours if buckets carry timestamps we can compare against.
        # Timeline buckets use a 'time_bucket' field like '2026-02-20 10:00'.
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))
        filtered: list[dict[str, Any]] = []
        for bucket in timeline:
            ts_str = bucket.get("time_bucket") or bucket.get("timestamp")
            if not ts_str:
                filtered.append(bucket)
                continue
            try:
                # time_bucket format is naive UTC 'YYYY-MM-DD HH:MM'
                ts = datetime.strptime(str(ts_str)[:16], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    filtered.append(bucket)
            except (ValueError, TypeError):
                # If we can't parse, keep the bucket rather than dropping it
                filtered.append(bucket)

        total_events = sum(b.get("event_count", 0) for b in filtered)
        earliest = filtered[0].get("time_bucket") if filtered else None
        latest = filtered[-1].get("time_bucket") if filtered else None

        return {
            "status": "completed",
            "timeline": filtered,
            "buckets": len(filtered),
            "total_events": total_events,
            "earliest_bucket": earliest,
            "latest_bucket": latest,
            "filter": {"hours": hours},
        }
    except Exception as e:  # noqa: BLE001 — never raise to MCP client
        return _error_response(e)


# ---------------------------------------------------------------------------
# Tier 4 — Remediation
# ---------------------------------------------------------------------------


@mcp.tool()
def get_remediation(
    session_id: str,
    finding_id: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """Get remediation commands for specific findings or a whole category.

    Uses the project's REMEDIATION_COMMANDS pattern library (45+ patterns)
    to return diagnostic commands, fix commands, and AWS documentation links
    tailored to each finding.

    Args:
        finding_id: Specific finding id (e.g., 'F-0007' from get_findings).
            Returns remediation for that single finding.
        category: Get remediation for all findings in a category (e.g.,
            'pod_errors'). Returns a list, one entry per finding with a
            matching remediation pattern.

    Either finding_id or category must be provided. If both are given,
    finding_id takes precedence.

    Returns:
        For finding_id: a single remediation entry with diagnostic, fix,
        and aws_doc fields. For category: a list of entries.
    """
    try:
        session = _get_session(session_id)
        debugger = session.debugger

        if not finding_id and not category:
            return {
                "status": "error",
                "error": "Either finding_id or category must be provided.",
            }

        if category is not None and category not in debugger.findings:
            return {
                "status": "error",
                "error": (f"Unknown category {category!r}. Available: {sorted(debugger.findings.keys())}"),
            }

        # Build a flat, indexed list of findings so we can resolve finding_id
        flat: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
        counter = 0
        for cat, items in debugger.findings.items():
            for item in items:
                counter += 1
                fid = f"F-{counter:04d}"
                flat.append((fid, cat, item.get("details", {}) or {}, item))

        if finding_id:
            match = next((t for t in flat if t[0] == finding_id), None)
            if not match:
                return {
                    "status": "error",
                    "error": (f"finding_id {finding_id!r} not found. Use get_findings() to list valid ids."),
                }
            _fid, cat, details, item = match
            remediation = get_remediation_commands(item.get("summary", ""), details)
            return {
                "status": "completed",
                "finding_id": finding_id,
                "category": cat,
                "summary": item.get("summary", ""),
                "remediation": remediation
                or {
                    "diagnostic": [],
                    "fix": [],
                    "aws_doc": None,
                    "note": "No matching remediation pattern for this finding.",
                },
            }

        # category branch
        entries: list[dict[str, Any]] = []
        for fid, cat, details, item in flat:
            if cat != category:
                continue
            remediation = get_remediation_commands(item.get("summary", ""), details)
            if not remediation:
                continue
            entries.append(
                {
                    "finding_id": fid,
                    "summary": item.get("summary", ""),
                    "severity": details.get("severity", "info"),
                    "remediation": remediation,
                }
            )
        return {
            "status": "completed",
            "category": category,
            "findings_with_remediation": len(entries),
            "entries": entries,
        }
    except Exception as e:  # noqa: BLE001 — never raise to MCP client
        return _error_response(e)


@mcp.tool()
def get_recommendations(session_id: str) -> dict[str, Any]:
    """Get evidence-based remediation recommendations.

    Each recommendation includes priority (critical/warning/info), an action
    description, diagnostic steps, AWS documentation links, and evidence
    (affected resources, first_seen, last_seen, example findings).

    Recommendations are generated from the current findings set; call
    run_full_analysis() (or the domain-specific analyze_* tools) first.
    """
    try:
        session = _get_session(session_id)
        debugger = session.debugger

        try:
            recommendations = debugger.generate_recommendations() or []
        except Exception as e:  # noqa: BLE001 — must still return something useful
            debugger._add_error("generate_recommendations", str(e))
            recommendations = []

        # Compact representation: drop very large evidence examples arrays
        # to keep the payload LLM-friendly
        compact: list[dict[str, Any]] = []
        for rec in recommendations:
            evidence = rec.get("evidence", {}) or {}
            compact.append(
                {
                    "title": rec.get("title", ""),
                    "category": rec.get("category", ""),
                    "priority": rec.get("priority", "info"),
                    "action": rec.get("action", ""),
                    "aws_doc": rec.get("aws_doc"),
                    "diagnostic_steps": rec.get("diagnostic_steps", []),
                    "evidence_summary": {
                        "total_count": evidence.get("total_count", 0),
                        "critical_count": evidence.get("critical_count", 0),
                        "warning_count": evidence.get("warning_count", 0),
                        "info_count": evidence.get("info_count", 0),
                        "affected_resources": (evidence.get("affected_resources", [])[:10]),
                        "first_seen": evidence.get("first_seen"),
                        "last_seen": evidence.get("last_seen"),
                    },
                }
            )

        # Sort by priority (critical first)
        priority_order = {"critical": 0, "warning": 1, "info": 2}
        compact.sort(key=lambda r: priority_order.get(r["priority"], 3))

        return {
            "status": "completed",
            "recommendations": compact,
            "total": len(compact),
            "critical_count": sum(1 for r in compact if r["priority"] == "critical"),
            "warning_count": sum(1 for r in compact if r["priority"] == "warning"),
            "info_count": sum(1 for r in compact if r["priority"] == "info"),
        }
    except Exception as e:  # noqa: BLE001 — never raise to MCP client
        return _error_response(e)


# ---------------------------------------------------------------------------
# Tier 5 — Advanced (Phase 1 SSM integration + LLM export)
# ---------------------------------------------------------------------------


@mcp.tool()
def collect_node_diagnostics(
    session_id: str,
    node_name: str | None = None,
    max_nodes: int = 10,
) -> dict[str, Any]:
    """Collect node OS-level diagnostics via AWS SSM Run Command (Phase 1).

    Runs read-only diagnostic commands on EKS worker nodes to collect:
    iptables rules, conntrack state, kernel messages (dmesg), kubelet
    journal, containerd logs, IPAMD state, route tables, CNI config,
    sysctl parameters, and ENI metadata.

    Requires:
        - SSM Agent running on target nodes
        - ``AmazonSSMManagedInstanceCore`` policy on the node IAM role
        - Nodes must be managed instances in SSM (managed-instance-role)

    Duration: 1-5 minutes depending on node count and SSM responsiveness.

    Args:
        node_name: Specific node to diagnose (kubectl node name). If
            omitted, the debugger selects up to ``max_nodes`` priority
            nodes (e.g., NotReady nodes, nodes with issues).
        max_nodes: Maximum number of nodes to diagnose (default: 10).
            Capped at 50 per SSM limits.

    Returns:
        Summary of node_os_* findings collected, per-category counts, and
        any errors encountered during SSM execution.
    """
    try:
        session = _get_session(session_id)
        debugger = session.debugger

        # Opt-in to SSM diagnostics on the existing debugger instance
        debugger.enable_node_diagnostics = True
        debugger.ssm_max_nodes = max(1, min(int(max_nodes), 50))

        # If a specific node was requested, hint it via shared_data so the
        # existing prioritization logic can prefer it. The Phase 1 selector
        # already includes any NotReady / issue-bearing node; this is a
        # convenience override for ad-hoc investigation.
        if node_name:
            with debugger._shared_data_lock:
                debugger._shared_data.setdefault("node_diagnostics_target", node_name)

        try:
            debugger._run_node_os_diagnostics()
        except Exception as e:  # noqa: BLE001 — SSM failures must not abort the tool
            debugger._add_error("collect_node_diagnostics", str(e))

        # Tally the Phase 1 node_os_* categories
        category_counts: dict[str, int] = {}
        for cat in _NODE_OS_CATEGORIES:
            items = debugger.findings.get(cat, []) or []
            if items:
                category_counts[cat] = len(items)

        total_findings = sum(category_counts.values())
        severity = _category_summary(debugger, _NODE_OS_CATEGORIES)

        return {
            "status": "completed",
            "nodes_targeted": debugger.ssm_max_nodes,
            "target_node": node_name,
            "total_findings": total_findings,
            "findings_by_category": category_counts,
            "severity_breakdown": severity,
            "recent_errors": debugger.errors[-5:] if debugger.errors else [],
        }
    except Exception as e:  # noqa: BLE001 — never raise to MCP client
        return _error_response(e)


@mcp.tool()
def format_for_llm(
    session_id: str,
    include_findings: bool = True,
) -> dict[str, Any]:
    """Export all results as LLM-optimized JSON for external analysis.

    Uses the project's ``LLMJSONOutputFormatter`` to produce structured JSON
    with finding-type classification (historical_event vs current_state),
    correlations grouped by 5D confidence tier, and ranked potential root
    causes.

    Useful for:
        - Passing the cluster state to an external LLM (e.g., a different
          Claude session, GPT, or a custom analysis pipeline).
        - Saving a snapshot for later comparison.
        - Feeding into automated remediation systems.

    Args:
        include_findings: If True (default), include the full findings list
            in the output. Set to False for a compact summary-only export
            (much smaller payload, useful for quick status checks).

    Returns:
        LLM-optimized JSON as a string under the ``llm_json`` key, plus a
        ``metadata`` block describing the export (counts, schema version).
    """
    try:
        session = _get_session(session_id)
        debugger = session.debugger

        _ensure_correlated(debugger)
        try:
            recommendations = debugger.generate_recommendations() or []
        except Exception as e:  # noqa: BLE001
            debugger._add_error("generate_recommendations", str(e))
            recommendations = []

        # Build a minimal results dict in the shape LLMJSONOutputFormatter expects
        results = {
            "metadata": {
                "cluster": debugger.cluster_name,
                "region": debugger.region,
                "analysis_date": datetime.now(timezone.utc).isoformat(),
                "date_range": {
                    "start": debugger.start_date.isoformat() if debugger.start_date else None,
                    "end": debugger.end_date.isoformat() if debugger.end_date else None,
                },
                "namespace": debugger.namespace or "all",
            },
            "summary": _category_summary(debugger, list(debugger.findings.keys())),
            "findings": debugger.findings if include_findings else {},
            "correlations": getattr(debugger, "correlations", []) or [],
            "timeline": getattr(debugger, "timeline", []) or [],
            "first_issue": getattr(debugger, "first_issue", None),
            "recommendations": recommendations,
        }

        formatter = LLMJSONOutputFormatter()
        llm_json = formatter.format(results)

        # Parse the JSON string back so we can return structured metadata
        # alongside the raw string (caller can use either form).
        try:
            parsed = json.loads(llm_json)
        except (json.JSONDecodeError, TypeError):
            parsed = None

        return {
            "status": "completed",
            "llm_json": llm_json,
            "metadata": {
                "cluster": debugger.cluster_name,
                "region": debugger.region,
                "include_findings": include_findings,
                "findings_count": sum(len(v) for v in debugger.findings.values() if isinstance(v, list)),
                "correlations_count": len(getattr(debugger, "correlations", []) or []),
                "recommendations_count": len(recommendations),
                "parsed_preview": (
                    {
                        "summary": parsed.get("summary"),
                        "potential_root_causes_count": len(parsed.get("potential_root_causes", []) or []),
                    }
                    if parsed
                    else None
                ),
            },
        }
    except Exception as e:  # noqa: BLE001 — never raise to MCP client
        return _error_response(e)


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the EKS Debugger MCP server."""
    parser = argparse.ArgumentParser(description="EKS Debugger MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport type (default: stdio for Claude Desktop)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for streamable-http transport (default: 8000)",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        help="Log level (default: WARNING)",
    )
    args = parser.parse_args()

    # Banner to stderr — stdout is reserved for the MCP protocol frames
    print(f"EKS Debugger MCP Server v{VERSION}", file=sys.stderr)
    print(f"Transport: {args.transport}", file=sys.stderr)
    print(f"Tools available: {TOOL_COUNT}", file=sys.stderr)

    if args.transport == "streamable-http":
        # FastMCP accepts port via run() kwargs for HTTP transport
        mcp.run(transport=args.transport, port=args.port)
    else:
        mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
