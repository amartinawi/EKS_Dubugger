#!/usr/bin/env python3
"""
Comprehensive EKS Debugging Tool v3.0.0

A production-grade diagnostic tool for Amazon EKS cluster troubleshooting that provides
systematic analysis of cluster health, workload issues, networking, storage, and control plane.

================================================================================
FEATURES
================================================================================

📊 Comprehensive Issue Detection (56 Analysis Methods)
   • Pod & Workload: CrashLoopBackOff, ImagePullBackOff, OOMKilled, evictions, probes
   • Node Health: NotReady, DiskPressure, MemoryPressure, PIDPressure, PLEG, runtime
   • Networking: VPC CNI, CoreDNS, service endpoints, connectivity, NetworkPolicy
   • Storage: PVC issues, EBS/EFS CSI, volume attachment failures
   • Control Plane: API latency, rate limiting, etcd health, webhooks
   • IAM/RBAC: Permission errors, IRSA/Pod Identity, CloudTrail correlation
   • Autoscaling: Cluster Autoscaler, Karpenter, HPA/VPA, Fargate

📈 Interactive HTML Reports
   • Modern dashboard with sidebar navigation
   • Real-time search and filtering
   • Severity classification with color coding
   • Data source badges (kubectl, CloudWatch, EKS API)
   • Evidence-based recommendations with diagnostic steps

🔗 Smart Correlation Engine
   • Root cause identification across data sources
   • Timeline of events by hour
   • Cascading failure analysis
   • First issue detection

================================================================================
OUTPUT FORMATS
================================================================================

   • html      - Interactive dashboard (recommended)
   • json      - Structured output for automation
   • markdown  - Documentation-friendly format
   • yaml      - Human-readable structured output
   • console   - Text output with colors

================================================================================
USAGE
================================================================================

Basic usage (generates HTML + LLM-JSON reports):
    python eks_comprehensive_debugger.py --profile prod --region eu-west-1

With specific cluster and time range:
    python eks_comprehensive_debugger.py \\
        --profile prod \\
        --region eu-west-1 \\
        --cluster-name my-cluster \\
        --days 2

With custom kubectl context (SSM tunnel/VPN):
    python eks_comprehensive_debugger.py \\
        --profile prod \\
        --region eu-west-1 \\
        --cluster-name my-cluster \\
        --kube-context my-cluster-ssm-tunnel \\
        --days 1

Historical analysis with specific timezone:
    python eks_comprehensive_debugger.py \\
        --profile prod \\
        --region eu-west-1 \\
        --cluster-name my-cluster \\
        --start-date "2026-02-15T08:00:00" \\
        --end-date "2026-02-16T18:00:00" \\
        --timezone "Asia/Dubai"

================================================================================
CLI ARGUMENTS
================================================================================

Required:
    --profile       AWS profile from ~/.aws/credentials
    --region        AWS region (e.g., eu-west-1, us-east-1)

Optional:
    --cluster-name  EKS cluster name (prompts if not provided)
    --kube-context  Kubernetes context (skips kubeconfig update)
    --hours         Look back N hours from now
    --days          Look back N days from now (default: 1)
    --start-date    Start date (ISO 8601 or YYYY-MM-DD, supports time)
    --end-date      End date (ISO 8601 or YYYY-MM-DD, supports time)
    --timezone      Timezone for date parsing (default: UTC, e.g., "Asia/Dubai")
    --namespace     Focus on specific namespace
    --verbose       Enable verbose output
    --quiet         Suppress progress messages

Output:
    Always generates two files:
    - {cluster}-eks-report-{timestamp}.html      - Interactive HTML dashboard
    - {cluster}-eks-findings-{timestamp}.json    - LLM-ready JSON for AI analysis

================================================================================
EXIT CODES
================================================================================

    0   - Success, no issues found
    1   - Success, issues found in cluster
    2   - Error during analysis
    130 - Interrupted by user (Ctrl+C)

================================================================================
IAM PERMISSIONS REQUIRED
================================================================================

EKS:
    eks:ListClusters, eks:DescribeCluster
    eks:ListAddons, eks:DescribeAddon
    eks:ListNodegroups, eks:DescribeNodegroup

CloudWatch:
    cloudwatch:GetMetricStatistics, cloudwatch:ListMetrics
    logs:DescribeLogGroups, logs:DescribeLogStreams, logs:GetLogEvents

EC2:
    ec2:DescribeInstances, ec2:DescribeInstanceStatus
    ec2:DescribeSubnets, ec2:DescribeSecurityGroups

Other:
    service-quotas:ListServiceQuotas
    cloudtrail:LookupEvents (optional, for IAM correlation)
    sts:GetCallerIdentity

================================================================================
CATALOG COVERAGE
================================================================================

This tool implements 100% coverage of three comprehensive EKS troubleshooting catalogs:

    • EKS Issue Patterns Catalog: 49 issues (100%)
    • High-Value Kubernetes Issues: 21 issues (100%)
    • Common Kubernetes Issues: 9 issues (100%)
    • Total: 79 issues (100%)

================================================================================
REFERENCES
================================================================================

    • EKS Troubleshooting: https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html
    • EKS Disk Pressure: https://repost.aws/knowledge-center/eks-resolve-disk-pressure
    • CloudWatch Container Insights: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/ContainerInsights.html
    • EKS Best Practices: https://docs.aws.amazon.com/prescriptive-guidance/latest/amazon-eks-observability-best-practices/
    • EKS Control Plane Logs: https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html
    • IRSA: https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html
    • EKS Pod Identity: https://docs.aws.amazon.com/eks/latest/userguide/pod-identity.html

================================================================================
"""

# === SECTION 1: IMPORTS & CONSTANTS ===

import argparse
import boto3
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from dateutil import parser as date_parser
import pytz

VERSION = "3.0.0"
DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_TIMEOUT = 30
MAX_API_RETRIES = 3
RETRY_DELAY_SECONDS = 1
MAX_LOG_STREAMS = 5
MAX_EVENTS_PER_STREAM = 50
MAX_CONSOLE_DISPLAY = 10
MAX_HTML_DISPLAY = 50
DATE_RANGE_WARNING_DAYS = 7


class Thresholds:
    """Threshold configuration for alerts"""

    MEMORY_WARNING = 85
    MEMORY_CRITICAL = 95
    CPU_WARNING = 80
    CPU_CRITICAL = 90
    DISK_WARNING = 85
    DISK_CRITICAL = 95
    QUOTA_WARNING_RATIO = 0.9
    RESTART_WARNING = 5
    RESTART_CRITICAL = 10
    PENDING_POD_WARNING = 5
    PENDING_POD_CRITICAL = 10


class FindingType:
    """Classification of finding data source and time sensitivity"""

    CURRENT_STATE = "current_state"
    HISTORICAL_EVENT = "historical_event"

    @classmethod
    def get_label(cls, finding_type: str) -> str:
        labels = {
            cls.CURRENT_STATE: "Current State",
            cls.HISTORICAL_EVENT: "Historical Event",
        }
        return labels.get(finding_type, "Unknown")

    @classmethod
    def get_description(cls, finding_type: str) -> str:
        descriptions = {
            cls.CURRENT_STATE: "Reflects current cluster state (not filtered by date range)",
            cls.HISTORICAL_EVENT: "Event occurred within the specified date range",
        }
        return descriptions.get(finding_type, "")


EKS_ISSUE_PATTERNS = {
    "pod_issues": {
        "CrashLoopBackOff": {
            "root_causes": [
                "Application crash due to unhandled exception",
                "Missing environment variables or ConfigMaps",
                "Missing Secrets or invalid credentials",
                "Resource limits too low (OOM before crash)",
                "Liveness probe failing incorrectly",
                "Application startup dependency not ready",
            ],
            "detection": {"event_reason": "BackOff", "container_state": "waiting"},
            "severity": "critical",
            "aws_doc": "https://repost.aws/knowledge-center/eks-crashloopbackoff-cloudwatch-pod-identity",
        },
        "ImagePullBackOff": {
            "root_causes": [
                "Image does not exist in registry",
                "Incorrect image name or tag",
                "Missing ECR repository permissions",
                "ECR public rate limiting",
                "Network connectivity to registry",
                "Invalid or expired credentials",
            ],
            "detection": {"event_reason": ["ImagePullBackOff", "ErrImagePull"]},
            "severity": "critical",
            "aws_doc": "https://repost.aws/knowledge-center/eks-troubleshoot-kubernetes-pods",
        },
        "CreateContainerConfigError": {
            "root_causes": [
                "Referenced ConfigMap does not exist",
                "Referenced Secret does not exist",
                "Invalid volume mount configuration",
                "Missing service account token",
            ],
            "detection": {"event_reason": "Failed"},
            "severity": "critical",
            "aws_doc": "https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/",
        },
        "Evicted": {
            "root_causes": [
                "Node disk pressure threshold exceeded",
                "Node memory pressure threshold exceeded",
                "Pod exceeding ephemeral storage limit",
                "Node resource cleanup required",
            ],
            "detection": {"event_reason": "Evicted"},
            "severity": "warning",
            "aws_doc": "https://repost.aws/knowledge-center/eks-resolve-disk-pressure",
        },
        "OOMKilled": {
            "root_causes": [
                "Memory limit too low for workload",
                "Memory leak in application",
                "JVM heap not configured correctly",
                "Application memory usage spike",
            ],
            "detection": {"event_reason": "OOMKilling", "exit_code": 137},
            "severity": "critical",
            "aws_doc": "https://docs.aws.amazon.com/eks/latest/best-practices/windows-oom.html",
        },
    },
    "node_issues": {
        "NotReady": {
            "root_causes": [
                "Kubelet not running or crashed",
                "Network plugin not ready (CNI)",
                "API server unreachable",
                "Certificate expiration",
                "Insufficient node resources",
            ],
            "detection": {"condition": "Ready", "status": "False"},
            "severity": "critical",
            "aws_doc": "https://repost.aws/knowledge-center/eks-nodes-fail-cluster-join",
        },
        "DiskPressure": {
            "root_causes": [
                "Container images not garbage collected",
                "Log files filling disk",
                "Container runtime logs not rotated",
                "Ephemeral storage exhausted",
            ],
            "detection": {"condition": "DiskPressure", "status": "True"},
            "severity": "critical",
            "aws_doc": "https://repost.aws/knowledge-center/eks-resolve-disk-pressure",
        },
        "MemoryPressure": {
            "root_causes": [
                "Too many pods on node",
                "Memory leak in system processes",
                "Insufficient instance type",
                "Memory limits not enforced",
            ],
            "detection": {"condition": "MemoryPressure", "status": "True"},
            "severity": "critical",
            "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html",
        },
        "NetworkUnavailable": {
            "root_causes": [
                "VPC CNI not initialized",
                "aws-node DaemonSet not running",
                "Subnet IP exhaustion",
                "Security group blocking traffic",
            ],
            "detection": {"condition": "NetworkUnavailable", "status": "True"},
            "severity": "critical",
            "aws_doc": "https://repost.aws/knowledge-center/eks-troubleshoot-vpc-cni-add-on",
        },
    },
    "network_issues": {
        "IPExhaustion": {
            "root_causes": [
                "Subnet CIDR too small",
                "Too many pods per node",
                "Prefix delegation not enabled",
                "Warm IP pool too large",
            ],
            "detection": {
                "patterns": [
                    "failed to allocate",
                    "no available ip",
                    "insufficient free addresses",
                ]
            },
            "severity": "critical",
            "aws_doc": "https://repost.aws/knowledge-center/eks-resolve-cluster-ip-address-issues",
        },
        "CNINotReady": {
            "root_causes": [
                "aws-node pod not running",
                "VPC CNI addon degraded",
                "IAM permissions missing for CNI",
                "Security group blocking ENI attachment",
            ],
            "detection": {"patterns": ["cni plugin not initialized", "NetworkPluginNotReady"]},
            "severity": "warning",
            "aws_doc": "https://repost.aws/knowledge-center/eks-troubleshoot-vpc-cni-add-on",
        },
        "DNSResolutionFailure": {
            "root_causes": [
                "CoreDNS pods not running",
                "CoreDNS overloaded",
                "VPC DNS limits exceeded",
                "Network policy blocking DNS",
            ],
            "detection": {"patterns": ["nslookup", "dns", "name resolution", "coredns"]},
            "severity": "warning",
            "aws_doc": "https://repost.aws/knowledge-center/eks-install-nodelocaldns-troubleshoot",
        },
    },
    "iam_issues": {
        "AccessDenied": {
            "root_causes": [
                "Missing IAM policy permissions",
                "Service account not annotated",
                "IRSA not configured correctly",
                "Pod Identity agent not running",
            ],
            "detection": {"patterns": ["AccessDenied", "Unauthorized", "403"]},
            "severity": "critical",
            "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/security-iam-troubleshoot.html",
        },
        "UnableToFetchCredentials": {
            "root_causes": [
                "EKS Pod Identity agent not installed",
                "eks-auth endpoint not accessible",
                "IAM role trust policy incorrect",
                "Service account mismatch",
            ],
            "detection": {
                "patterns": [
                    "unable to fetch credentials",
                    "credentials from container-role",
                ]
            },
            "severity": "critical",
            "aws_doc": "https://repost.aws/knowledge-center/eks-unable-to-fetch-credentials-errors",
        },
    },
    "storage_issues": {
        "PVCPending": {
            "root_causes": [
                "No PersistentVolume available",
                "StorageClass not defined",
                "Volume size exceeds quota",
                "Availability zone mismatch",
            ],
            "detection": {"patterns": ["pending", "volume binding", "no persistent volumes"]},
            "severity": "warning",
            "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/ebs-csi.html",
        },
        "VolumeAttachmentFailed": {
            "root_causes": [
                "EBS CSI driver not installed",
                "IAM permissions for CSI missing",
                "Volume already attached elsewhere",
                "Zone mismatch between PV and node",
            ],
            "detection": {"patterns": ["attach", "mount", "volume", "failed"]},
            "severity": "critical",
            "aws_doc": "https://docs.aws.amazon.com/systems-manager-automation-runbooks/latest/userguide/automation-awssupport-troubleshoot-ebs-csi-drivers-for-eks.html",
        },
    },
    "scheduling_issues": {
        "InsufficientResources": {
            "root_causes": [
                "Node capacity exhausted",
                "Resource requests too high",
                "No nodes match node selector",
                "Taints without tolerations",
            ],
            "detection": {
                "patterns": [
                    "Insufficient cpu",
                    "Insufficient memory",
                    "Insufficient ephemeral-storage",
                ]
            },
            "severity": "warning",
            "aws_doc": "https://repost.aws/knowledge-center/eks-pod-scheduling-node-availability",
        },
        "AffinityConflict": {
            "root_causes": [
                "Node affinity no nodes match",
                "Pod anti-affinity too strict",
                "Topology spread constraints",
                "Zone availability issues",
            ],
            "detection": {
                "patterns": [
                    "node affinity",
                    "pod affinity",
                    "topology spread",
                    "anti-affinity",
                ]
            },
            "severity": "warning",
            "aws_doc": "https://repost.aws/knowledge-center/eks-pod-scheduling-cluster-autoscaler",
        },
    },
}

ERROR_PATTERNS = ["error", "fail", "denied", "forbidden", "unauthorized"]
NETWORK_EVENT_REASONS = ["FailedCreatePodSandBox", "FailedSync", "NetworkNotReady"]
IMAGE_PULL_REASONS = ["Failed", "BackOff", "ErrImagePull"]
CRITICAL_CATEGORIES = [
    "oom_killed",
    "disk_pressure",
    "memory_pressure",
    "node_issues",
]

CONTROL_PLANE_BENIGN_PATTERNS = [
    "required revision has been compacted",
    "falling back to the standard LIST semantics",
    "watchlist request.*ended with an error",
    "etcdserver: mvcc",
    "resourceVersion.*is invalid",
]

CONTROL_PLANE_ERROR_PATTERNS = [
    "etcdserver: leader changed",
    "connection refused",
    "context deadline exceeded",
    "internal error",
    "admission denied",
    "authentication failed",
]

# === SECTION 2: EXCEPTION CLASSES ===


class EKSDebuggerError(Exception):
    """Base exception for EKS debugger"""

    pass


class AWSAuthenticationError(EKSDebuggerError):
    """AWS authentication failed"""

    pass


class ClusterNotFoundError(EKSDebuggerError):
    """EKS cluster not found"""

    pass


class KubectlNotAvailableError(EKSDebuggerError):
    """kubectl not available in PATH"""

    pass


class DateValidationError(EKSDebuggerError):
    """Invalid date format or range"""

    pass


class InsufficientPermissionsError(EKSDebuggerError):
    """Missing required IAM permissions"""

    pass


# === SECTION 3: UTILITY CLASSES ===


class ProgressTracker:
    """Track progress of analysis steps"""

    def __init__(self, verbose=False, quiet=False):
        self.verbose = verbose
        self.quiet = quiet
        self.steps_completed = 0
        self.total_steps = 0

    def set_total_steps(self, total):
        self.total_steps = total

    def step(self, message):
        """Show progress for current step"""
        if not self.quiet:
            self.steps_completed += 1
            prefix = f"[{self.steps_completed}/{self.total_steps}]" if self.total_steps > 0 else ""
            print(f"{prefix} {message}")

    def info(self, message):
        """Show info message"""
        if self.verbose and not self.quiet:
            print(f"ℹ️  {message}")

    def warning(self, message):
        """Show warning message"""
        if not self.quiet:
            print(f"⚠️  {message}")

    def error(self, message):
        """Show error message"""
        print(f"✗ {message}", file=sys.stderr)


class DateFilterMixin:
    """Mixin for filtering kubectl events and CloudWatch data by date"""

    def filter_kubectl_events_by_date(self, events_json, start_date, end_date):
        """Filter kubectl events by date range"""
        if not events_json or not isinstance(events_json, dict):
            return events_json

        filtered_items = []
        for event in events_json.get("items", []):
            # Get timestamp from event (lastTimestamp or eventTime)
            timestamp_str = event.get("lastTimestamp") or event.get("eventTime")
            if not timestamp_str:
                continue

            try:
                event_time = date_parser.parse(timestamp_str)
                # Ensure timezone aware
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=timezone.utc)

                if start_date <= event_time <= end_date:
                    filtered_items.append(event)
            except Exception:
                # If parsing fails, include the event to avoid data loss
                filtered_items.append(event)

        return {"items": filtered_items}

    def get_cloudwatch_time_params(self, start_date, end_date):
        """Get CloudWatch API time parameters"""
        return {"StartTime": start_date, "EndTime": end_date}

    def filter_log_events_by_date(self, log_events, start_date, end_date):
        """Filter CloudWatch log events by date range"""
        if not log_events:
            return log_events

        filtered = []
        for event in log_events:
            timestamp = event.get("timestamp")
            if timestamp:
                # CloudWatch timestamps are in milliseconds
                event_time = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
                if start_date <= event_time <= end_date:
                    filtered.append(event)

        return filtered


# === SECTION 4: OUTPUT FORMATTERS ===


class OutputFormatter:
    """Base class for output formatters"""

    def format(self, results):
        """Format results for output"""
        raise NotImplementedError


class ConsoleOutputFormatter(OutputFormatter):
    """Human-readable console output with colors"""

    def format(self, results):
        """Format results for console output"""
        output = []

        # Header
        output.append("=" * 70)
        output.append("COMPREHENSIVE EKS CLUSTER ANALYSIS REPORT")
        output.append("=" * 70)
        output.append(f"Cluster:    {results['metadata']['cluster']}")
        output.append(f"Region:     {results['metadata']['region']}")
        output.append(f"Analysis:   {results['metadata']['analysis_date']}")
        output.append(
            f"Date Range: {results['metadata']['date_range']['start']} to {results['metadata']['date_range']['end']}"
        )
        output.append("=" * 70)

        # Summary
        output.append("\n📊 SUMMARY")
        output.append("-" * 70)
        output.append(f"Total Issues Found: {results['summary']['total_issues']}")
        output.append(f"  Critical: {results['summary']['critical']}")
        output.append(f"  Warning:  {results['summary']['warning']}")

        if results["summary"]["categories"]:
            output.append(f"\nIssue Categories: {', '.join(results['summary']['categories'])}")

        # Detailed findings by category
        if results.get("findings"):
            output.append("\n\n🔍 DETAILED FINDINGS")
            output.append("=" * 70)

            for category, items in results["findings"].items():
                if items:
                    category_title = category.replace("_", " ").title()
                    output.append(f"\n{category_title} ({len(items)} items)")
                    output.append("-" * 70)

                    for idx, item in enumerate(items[:10], 1):  # Show first 10
                        output.append(f"\n  {idx}. {item.get('summary', 'N/A')}")
                        if item.get("details"):
                            for key, value in item["details"].items():
                                output.append(f"     {key}: {value}")

                    if len(items) > 10:
                        output.append(f"\n  ... and {len(items) - 10} more")

        # Recommendations
        if results.get("recommendations"):
            output.append("\n\n💡 RECOMMENDATIONS")
            output.append("=" * 70)
            for idx, rec in enumerate(results["recommendations"], 1):
                output.append(f"\n{idx}. {rec['title']}")
                output.append(f"   Category: {rec['category']}")
                output.append(f"   Priority: {rec['priority']}")
                output.append(f"   Action: {rec['action']}")
                if rec.get("aws_doc"):
                    output.append(f"   AWS Doc: {rec['aws_doc']}")

        # Errors
        if results.get("errors"):
            output.append("\n\n⚠️  ANALYSIS ERRORS")
            output.append("=" * 70)
            for error in results["errors"]:
                output.append(f"  • {error['step']}: {error['message']}")

        # Footer
        output.append("\n" + "=" * 70)
        output.append(f"✓ Analysis completed at {results['metadata']['analysis_date']}")
        output.append("=" * 70)

        return "\n".join(output)


class JSONOutputFormatter(OutputFormatter):
    """JSON output for automation"""

    def format(self, results):
        """Format results as JSON"""
        return json.dumps(results, indent=2, default=str)


class MarkdownOutputFormatter(OutputFormatter):
    """Markdown output for reports"""

    def format(self, results):
        """Format results as Markdown"""
        output = []

        # Header
        output.append("# EKS Cluster Analysis Report\n")
        output.append(f"**Cluster:** {results['metadata']['cluster']}")
        output.append(f"**Region:** {results['metadata']['region']}")
        output.append(f"**Analysis Date:** {results['metadata']['analysis_date']}")
        output.append(
            f"**Date Range:** {results['metadata']['date_range']['start']} to {results['metadata']['date_range']['end']}\n"
        )

        # Summary
        output.append("## Executive Summary\n")
        output.append(f"- **Total Issues:** {results['summary']['total_issues']}")
        output.append(f"- **Critical:** {results['summary']['critical']}")
        output.append(f"- **Warning:** {results['summary']['warning']}")

        if results["summary"]["categories"]:
            output.append(f"- **Categories:** {', '.join(results['summary']['categories'])}\n")

        # Detailed findings
        if results.get("findings"):
            output.append("## Detailed Findings\n")

            for category, items in results["findings"].items():
                if items:
                    category_title = category.replace("_", " ").title()
                    output.append(f"### {category_title} ({len(items)} instances)\n")

                    for idx, item in enumerate(items, 1):
                        output.append(f"{idx}. **{item.get('summary', 'N/A')}**")
                        if item.get("details"):
                            for key, value in item["details"].items():
                                output.append(f"   - {key}: `{value}`")
                        output.append("")

        # Recommendations
        if results.get("recommendations"):
            output.append("## Recommendations\n")
            for idx, rec in enumerate(results["recommendations"], 1):
                output.append(f"### {idx}. {rec['title']}")
                output.append(f"- **Category:** {rec['category']}")
                output.append(f"- **Priority:** {rec['priority']}")
                output.append(f"- **Action:** {rec['action']}")
                if rec.get("aws_doc"):
                    output.append(f"- **AWS Documentation:** [{rec['aws_doc']}]({rec['aws_doc']})")
                output.append("")

        # Errors
        if results.get("errors"):
            output.append("## Analysis Errors\n")
            for error in results["errors"]:
                output.append(f"- **{error['step']}:** {error['message']}")

        # Footer
        output.append(f"\n---\n*Generated with EKS Comprehensive Debugger v{VERSION}*")

        return "\n".join(output)


class YAMLOutputFormatter(OutputFormatter):
    """YAML output for GitOps workflows"""

    def format(self, results):
        """Format results as YAML"""
        try:
            import yaml

            return yaml.dump(results, default_flow_style=False, sort_keys=False)
        except ImportError:
            # Fallback to simple YAML-like formatting if pyyaml not available
            return self._simple_yaml_format(results)

    def _simple_yaml_format(self, obj, indent=0):
        """Simple YAML-like formatting without pyyaml"""
        output = []
        indent_str = "  " * indent

        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, (dict, list)):
                    output.append(f"{indent_str}{key}:")
                    output.append(self._simple_yaml_format(value, indent + 1))
                else:
                    output.append(f"{indent_str}{key}: {value}")
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    output.append(f"{indent_str}-")
                    output.append(self._simple_yaml_format(item, indent + 1))
                else:
                    output.append(f"{indent_str}- {item}")

        return "\n".join(output)


class LLMJSONOutputFormatter(OutputFormatter):
    """LLM-optimized JSON output for AI analysis"""

    def format(self, results):
        """Format results as LLM-ready JSON with finding type classification"""
        import uuid

        metadata = results["metadata"]
        summary = results["summary"]
        findings = results.get("findings", {})
        correlations = results.get("correlations", [])
        timeline = results.get("timeline", [])
        recommendations = results.get("recommendations", [])
        first_issue = results.get("first_issue")

        historical_count = 0
        current_state_count = 0

        llm_findings = []
        for category, items in findings.items():
            for item in items:
                details = item.get("details", {})
                finding_type = details.get("finding_type", FindingType.CURRENT_STATE)
                if finding_type == FindingType.HISTORICAL_EVENT:
                    historical_count += 1
                else:
                    current_state_count += 1

                severity = details.get("severity", "info")
                if severity not in ("critical", "warning", "info"):
                    if "critical" in item.get("summary", "").lower():
                        severity = "critical"
                    elif "warning" in item.get("summary", "").lower():
                        severity = "warning"
                    else:
                        severity = "info"

                llm_finding = {
                    "id": str(uuid.uuid4())[:8],
                    "category": category,
                    "severity": severity,
                    "finding_type": finding_type,
                    "summary": item.get("summary", ""),
                    "details": {k: v for k, v in details.items() if k != "finding_type"},
                }

                timestamp = details.get("timestamp") or details.get("event_time")
                if timestamp:
                    llm_finding["timestamp"] = str(timestamp)

                llm_findings.append(llm_finding)

        potential_root_causes = []
        if first_issue:
            potential_root_causes.append(
                {
                    "timestamp": first_issue.get("timestamp"),
                    "category": first_issue.get("category"),
                    "summary": first_issue.get("summary"),
                    "is_potential_root_cause": first_issue.get("potential_root_cause", False),
                }
            )

        for corr in correlations:
            if corr.get("root_cause"):
                potential_root_causes.append(
                    {
                        "correlation_type": corr.get("correlation_type"),
                        "severity": corr.get("severity"),
                        "root_cause": corr.get("root_cause"),
                        "impact": corr.get("impact"),
                        "recommendation": corr.get("recommendation"),
                        "aws_doc": corr.get("aws_doc"),
                    }
                )

        llm_output = {
            "analysis_context": {
                "cluster": metadata.get("cluster"),
                "region": metadata.get("region"),
                "analysis_date": metadata.get("analysis_date"),
                "date_range": metadata.get("date_range"),
                "timezone": metadata.get("timezone", "UTC"),
                "namespace": metadata.get("namespace"),
            },
            "summary": {
                "total_issues": summary.get("total_issues", 0),
                "critical": summary.get("critical", 0),
                "warning": summary.get("warning", 0),
                "info": summary.get("info", 0),
                "historical_events": historical_count,
                "current_state_issues": current_state_count,
                "categories": summary.get("categories", []),
            },
            "findings": llm_findings,
            "correlations": correlations,
            "timeline": timeline,
            "potential_root_causes": potential_root_causes,
            "recommendations": [
                {
                    "title": rec.get("title"),
                    "category": rec.get("category"),
                    "priority": rec.get("priority"),
                    "action": rec.get("action"),
                    "aws_doc": rec.get("aws_doc"),
                }
                for rec in recommendations
            ],
        }

        return json.dumps(llm_output, indent=2, default=str)


class ExecutiveSummaryGenerator:
    """Generate executive summary from analysis results"""

    def generate(self, results: dict) -> dict:
        """
        Generate executive summary from analysis results.

        Returns a dict with:
        - health_status: overall health assessment
        - key_findings: top critical issues
        - root_cause_analysis: from correlations
        - timeline_insights: when issues occurred
        - priority_actions: recommended actions prioritized
        - affected_resources: summary of impacted components
        """
        summary = results.get("summary", {})
        findings = results.get("findings", {})
        correlations = results.get("correlations", [])
        timeline = results.get("timeline", [])
        first_issue = results.get("first_issue")
        recommendations = results.get("recommendations", [])
        metadata = results.get("metadata", {})

        # Determine overall health status
        health_status = self._determine_health_status(summary)

        # Get top critical issues
        key_findings = self._extract_key_findings(findings, limit=5)

        # Analyze root causes
        root_cause_analysis = self._analyze_root_causes(correlations, first_issue)

        # Timeline insights
        timeline_insights = self._analyze_timeline(timeline, metadata)

        # Prioritized actions
        priority_actions = self._prioritize_actions(recommendations, findings, correlations)

        # Affected resources summary
        affected_resources = self._summarize_affected_resources(findings)

        # Category breakdown
        category_breakdown = self._category_breakdown(findings)

        # Healthy components for balanced view
        healthy_components = self._get_healthy_components(findings, summary)

        # First issue for prominent display
        first_issue_prominent = None
        if first_issue:
            first_issue_prominent = {
                "timestamp": first_issue.get("timestamp"),
                "category": first_issue.get("category", "").replace("_", " ").title(),
                "summary": first_issue.get("summary"),
                "is_potential_root_cause": first_issue.get("potential_root_cause", False),
            }

        # Phase 2 enhancements
        # Most common error types
        common_errors = self._get_most_common_error_types(findings)

        # External service impact
        external_impact = self._get_external_service_impact(findings)

        # Phase 3 enhancements
        # Correlation-based narrative
        narrative = self._generate_correlation_narrative(correlations, first_issue, findings)

        # Quick wins classification
        quick_wins = self._classify_quick_wins(findings, recommendations)

        return {
            "health_status": health_status,
            "first_issue": first_issue_prominent,
            "key_findings": key_findings,
            "root_cause_analysis": root_cause_analysis,
            "timeline_insights": timeline_insights,
            "priority_actions": priority_actions,
            "affected_resources": affected_resources,
            "category_breakdown": category_breakdown,
            "healthy_components": healthy_components,
            # Phase 2 additions
            "trend": timeline_insights.get("trend"),
            "common_errors": common_errors,
            "external_impact": external_impact,
            # Phase 3 additions
            "narrative": narrative,
            "quick_wins": quick_wins,
        }

    def _determine_health_status(self, summary: dict) -> dict:
        """Determine overall cluster health status"""
        critical = summary.get("critical", 0)
        warning = summary.get("warning", 0)
        total = summary.get("total_issues", 0)
        historical = summary.get("historical_event_count", 0)
        current = summary.get("current_state_count", 0)

        if critical >= 3:
            status = "critical"
            message = f"Cluster is in CRITICAL state with {critical} critical issues requiring immediate attention"
            icon = "🔴"
        elif critical >= 1:
            status = "critical"
            message = f"Cluster has {critical} critical issue(s) that need immediate attention"
            icon = "🔴"
        elif warning >= 5:
            status = "warning"
            message = f"Cluster is in WARNING state with {warning} issues detected"
            icon = "⚠️"
        elif warning >= 1:
            status = "warning"
            message = f"Cluster has {warning} warning(s) that should be reviewed"
            icon = "⚠️"
        else:
            status = "healthy"
            message = "Cluster is healthy with no significant issues detected"
            icon = "✅"

        return {
            "status": status,
            "icon": icon,
            "message": message,
            "critical_count": critical,
            "warning_count": warning,
            "total_issues": total,
            "historical_events": historical,
            "current_state_issues": current,
        }

    def _extract_key_findings(self, findings: dict, limit: int = 5) -> list:
        """Extract top critical findings"""
        all_findings = []

        for category, items in findings.items():
            for item in items:
                details = item.get("details", {})
                finding_type = details.get("finding_type", FindingType.CURRENT_STATE)

                # Determine severity
                severity = details.get("severity", "info")
                if severity not in ("critical", "warning", "info"):
                    severity = self._classify_severity(item.get("summary", ""))

                all_findings.append(
                    {
                        "category": category,
                        "summary": item.get("summary", ""),
                        "severity": severity,
                        "finding_type": finding_type,
                        "timestamp": details.get("timestamp"),
                        "pod": details.get("pod"),
                        "node": details.get("node"),
                        "namespace": details.get("namespace"),
                    }
                )

        # Sort by severity (critical first), then by timestamp
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        all_findings.sort(
            key=lambda x: (severity_order.get(x["severity"], 2), x["timestamp"] or "")
        )

        return all_findings[:limit]

    def _analyze_root_causes(self, correlations: list, first_issue: dict | None) -> dict:
        """Analyze root causes from correlations and first issue"""
        root_causes = []

        for corr in correlations:
            if corr.get("root_cause"):
                root_causes.append(
                    {
                        "type": corr.get("correlation_type", "unknown"),
                        "severity": corr.get("severity", "warning"),
                        "root_cause": corr.get("root_cause"),
                        "impact": corr.get("impact"),
                        "recommendation": corr.get("recommendation"),
                        "aws_doc": corr.get("aws_doc"),
                    }
                )

        # Add first issue as potential root cause
        first_issue_info = None
        if first_issue and first_issue.get("potential_root_cause"):
            first_issue_info = {
                "timestamp": first_issue.get("timestamp"),
                "category": first_issue.get("category"),
                "summary": first_issue.get("summary"),
            }

        return {
            "identified_root_causes": root_causes,
            "first_issue": first_issue_info,
            "has_root_cause": len(root_causes) > 0 or first_issue_info is not None,
        }

    def _analyze_timeline(self, timeline: list, metadata: dict) -> dict:
        """Analyze timeline for insights including trend calculation"""
        if not timeline:
            return {
                "has_timeline": False,
                "insights": "No historical events in the specified date range",
                "trend": None,
            }

        # Find peak issue time
        peak_bucket = max(timeline, key=lambda x: x.get("event_count", 0))

        # Find most severe bucket
        critical_buckets = [t for t in timeline if t.get("severity") == "critical"]

        # Get time range
        if timeline:
            start_time = timeline[0].get("time_bucket", "")
            end_time = timeline[-1].get("time_bucket", "")
        else:
            start_time = end_time = ""

        # Calculate trend from last 2 buckets (Phase 2 - #1)
        trend = self._calculate_trend(timeline)

        insights = []
        if critical_buckets:
            insights.append(
                f"Issues peaked at {critical_buckets[0].get('time_bucket', 'unknown')} with critical severity"
            )
        if peak_bucket.get("event_count", 0) > 10:
            insights.append(
                f"High activity period at {peak_bucket.get('time_bucket', 'unknown')} with {peak_bucket.get('event_count')} events"
            )

        return {
            "has_timeline": True,
            "start_time": start_time,
            "end_time": end_time,
            "total_buckets": len(timeline),
            "peak_time": peak_bucket.get("time_bucket"),
            "peak_event_count": peak_bucket.get("event_count", 0),
            "critical_periods": len(critical_buckets),
            "insights": insights if insights else ["Events distributed across the time range"],
            "trend": trend,
        }

    def _calculate_trend(self, timeline: list) -> dict | None:
        """
        Calculate trend from last 2 time buckets.

        Returns trend with:
        - direction: "increasing", "decreasing", "stable"
        - percentage: change percentage
        - icon: visual indicator
        - message: human-readable description
        """
        if len(timeline) < 2:
            return None

        # Get last 2 buckets
        last_bucket = timeline[-1]
        second_last_bucket = timeline[-2]

        last_count = last_bucket.get("event_count", 0)
        second_last_count = second_last_bucket.get("event_count", 0)
        last_time = last_bucket.get("time_bucket", "")
        second_last_time = second_last_bucket.get("time_bucket", "")

        # Calculate percentage change
        if second_last_count == 0:
            if last_count == 0:
                percentage = 0
                direction = "stable"
            else:
                percentage = 100  # New issues appeared
                direction = "increasing"
        else:
            percentage = ((last_count - second_last_count) / second_last_count) * 100
            # Determine direction with 10% threshold for "stable"
            if percentage > 10:
                direction = "increasing"
            elif percentage < -10:
                direction = "decreasing"
            else:
                direction = "stable"

        # Set icon and color based on direction
        if direction == "increasing":
            icon = "📈"
            color = "#ef4444"  # red
            message = f"Issues increased by {abs(percentage):.0f}% in the last hour"
        elif direction == "decreasing":
            icon = "📉"
            color = "#22c55e"  # green
            message = f"Issues decreased by {abs(percentage):.0f}% in the last hour"
        else:
            icon = "➡️"
            color = "#6b7280"  # gray
            message = "Issue rate is stable"

        return {
            "direction": direction,
            "percentage": round(percentage, 1),
            "icon": icon,
            "color": color,
            "message": message,
            "last_count": last_count,
            "previous_count": second_last_count,
            "last_time": last_time,
            "previous_time": second_last_time,
        }

    def _get_most_common_error_types(self, findings: dict) -> list:
        """
        Extract and count the most common error types (Phase 2 - #4).

        Looks for patterns like:
        - CrashLoopBackOff
        - ImagePullBackOff
        - OOMKilled
        - Evicted
        - FailedScheduling
        - etc.
        """
        error_counts: dict[str, dict] = {}

        # Known error patterns to extract
        error_patterns = [
            "CrashLoopBackOff",
            "ImagePullBackOff",
            "ErrImagePull",
            "OOMKilled",
            "Evicted",
            "FailedScheduling",
            "FailedMount",
            "FailedAttachVolume",
            "FailedCreate",
            "FailedGetResourceMetric",
            "NodeNotReady",
            "DiskPressure",
            "MemoryPressure",
            "PIDPressure",
            "NetworkUnavailable",
            "ContainerCreating",
            "CreateContainerConfigError",
            "RunContainerError",
            "PostStartHookError",
            "PreStopHookError",
        ]

        for category, items in findings.items():
            for item in items:
                summary = item.get("summary", "").lower()
                details = item.get("details", {})
                reason = details.get("reason", "").lower() if isinstance(details, dict) else ""

                # Check for known error patterns
                for pattern in error_patterns:
                    pattern_lower = pattern.lower()
                    if pattern_lower in summary or pattern_lower in reason:
                        if pattern not in error_counts:
                            error_counts[pattern] = {
                                "error_type": pattern,
                                "count": 0,
                                "category": category,
                                "examples": [],
                            }
                        error_counts[pattern]["count"] += 1

                        # Store up to 2 examples
                        if len(error_counts[pattern]["examples"]) < 2:
                            example = {
                                "summary": item.get("summary", ""),
                                "namespace": details.get("namespace", ""),
                                "pod": details.get("pod", ""),
                            }
                            if example not in error_counts[pattern]["examples"]:
                                error_counts[pattern]["examples"].append(example)
                        break

        # Sort by count and return top 5
        sorted_errors = sorted(error_counts.values(), key=lambda x: x["count"], reverse=True)
        return sorted_errors[:5]

    def _get_external_service_impact(self, findings: dict) -> dict:
        """
        Analyze impact on external services (Phase 2 - #6).

        Counts:
        - Services with no endpoints (offline)
        - Ingress/ALB issues
        - DNS resolution failures
        """
        services_offline = []
        dns_failures = []
        ingress_issues = []

        # Check network issues for services with no endpoints
        for item in findings.get("network_issues", []):
            summary = item.get("summary", "").lower()
            details = item.get("details", {})

            if "no endpoints" in summary or "no ready endpoints" in summary:
                services_offline.append(
                    {
                        "service": details.get("service", "unknown"),
                        "namespace": details.get("namespace", "unknown"),
                        "summary": item.get("summary", ""),
                    }
                )

        # Check DNS issues
        for item in findings.get("dns_issues", []):
            details = item.get("details", {})
            dns_failures.append(
                {
                    "summary": item.get("summary", ""),
                    "namespace": details.get("namespace", ""),
                }
            )

        # Calculate business impact level
        total_offline = len(services_offline)
        if total_offline >= 5:
            impact_level = "critical"
            impact_message = f"{total_offline} services are offline - likely impacting user traffic"
        elif total_offline >= 2:
            impact_level = "warning"
            impact_message = f"{total_offline} services have no endpoints - may be impacting users"
        elif total_offline == 1:
            impact_level = "warning"
            impact_message = "1 service has no endpoints"
        else:
            impact_level = "healthy"
            impact_message = "All services have available endpoints"

        return {
            "impact_level": impact_level,
            "impact_message": impact_message,
            "services_offline_count": total_offline,
            "services_offline": services_offline[:5],  # Top 5
            "dns_failures_count": len(dns_failures),
            "dns_failures": dns_failures[:3],
            "has_external_impact": total_offline > 0 or len(dns_failures) > 0,
        }

    def _prioritize_actions(
        self, recommendations: list, findings: dict, correlations: list
    ) -> list:
        """Prioritize recommended actions"""
        actions = []

        # First, add actions from correlations (these are root cause based)
        for corr in correlations:
            if corr.get("recommendation"):
                actions.append(
                    {
                        "priority": "high" if corr.get("severity") == "critical" else "medium",
                        "action": corr.get("recommendation"),
                        "category": corr.get("correlation_type", "correlation"),
                        "source": "Root Cause Analysis",
                        "aws_doc": corr.get("aws_doc"),
                    }
                )

        # Then add top recommendations
        for rec in recommendations[:5]:
            priority = rec.get("priority", "medium")
            if rec.get("critical_count", 0) > 0:
                priority = "high"

            actions.append(
                {
                    "priority": priority,
                    "action": rec.get("action"),
                    "category": rec.get("category"),
                    "source": "Recommendation",
                    "aws_doc": rec.get("aws_doc"),
                }
            )

        # Sort by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        actions.sort(key=lambda x: priority_order.get(x["priority"], 2))

        return actions[:10]  # Top 10 actions

    def _generate_correlation_narrative(
        self, correlations: list, first_issue: dict | None, findings: dict
    ) -> dict:
        """
        Generate a human-readable narrative from correlations (Phase 3 - #5).

        Creates a story like:
        "Memory pressure on node X caused eviction of 5 pods, leading to
        cascading failures in dependent services."
        """
        if not correlations and not first_issue:
            return {
                "has_narrative": False,
                "narrative": "",
                "short_summary": "",
            }

        narrative_parts = []
        short_summary = ""

        # Process correlations to build narrative
        for corr in correlations:
            corr_type = corr.get("correlation_type", "")
            root_cause = corr.get("root_cause", "")
            impact = corr.get("impact", "")
            severity = corr.get("severity", "warning")

            if corr_type == "node_pressure_cascade":
                # Extract node and pod count from impact
                node_match = ""
                pod_count = 0
                if "node" in impact.lower():
                    # Try to extract details
                    narrative_parts.append(
                        f"📊 **Memory/Disk Pressure Cascade**: {root_cause}. "
                        f"This triggered a cascade where {impact}."
                    )
                    short_summary = f"Node pressure caused cascading failures"

            elif corr_type == "cni_cascade":
                narrative_parts.append(
                    f"🔌 **CNI Cascade**: {root_cause}. "
                    f"Network connectivity issues followed: {impact}."
                )
                short_summary = "VPC CNI issues caused network failures"

            elif corr_type == "oom_pattern":
                narrative_parts.append(
                    f"💾 **OOM Pattern**: {root_cause}. Memory exhaustion led to: {impact}."
                )
                short_summary = "OOM kills indicate memory issues"

            elif corr_type == "control_plane_impact":
                narrative_parts.append(
                    f"⚙️ **Control Plane Impact**: {root_cause}. "
                    f"Control plane instability affected: {impact}."
                )
                short_summary = "Control plane issues impacting workloads"

            elif corr_type == "image_pull_pattern":
                narrative_parts.append(
                    f"📦 **Image Pull Issues**: {root_cause}. Container startup failures: {impact}."
                )
                short_summary = "Image pull failures detected"

            elif corr_type == "scheduling_pattern":
                narrative_parts.append(
                    f"📋 **Scheduling Issues**: {root_cause}. "
                    f"Pods could not be scheduled: {impact}."
                )
                short_summary = "Scheduling failures detected"

            elif corr_type == "dns_pattern":
                narrative_parts.append(
                    f"🔍 **DNS Issues**: {root_cause}. Service discovery problems: {impact}."
                )
                short_summary = "DNS resolution issues detected"

            else:
                # Generic correlation
                if root_cause and impact:
                    narrative_parts.append(
                        f"🔗 **{corr_type.replace('_', ' ').title()}**: {root_cause}. Impact: {impact}"
                    )

        # Add first issue context if available
        if first_issue and first_issue.get("potential_root_cause"):
            first_timestamp = first_issue.get("timestamp", "Unknown time")
            first_summary = first_issue.get("summary", "Unknown issue")
            narrative_parts.insert(
                0,
                f"🎯 **First Detected Issue** (at {first_timestamp}): {first_summary}. "
                f"This appears to be the initial trigger for subsequent failures.",
            )

        # Generate overall narrative
        if narrative_parts:
            full_narrative = "\n\n".join(narrative_parts)

            # Add a summary sentence
            if len(narrative_parts) > 1:
                overall_summary = (
                    f"Analysis identified {len(narrative_parts)} correlated event chains. "
                    f"The issues appear interconnected, suggesting a common root cause."
                )
            else:
                overall_summary = (
                    short_summary if short_summary else "A single correlation pattern was detected."
                )

            return {
                "has_narrative": True,
                "narrative": full_narrative,
                "short_summary": overall_summary,
                "correlation_count": len(correlations),
                "has_first_issue": first_issue is not None,
            }

        return {
            "has_narrative": False,
            "narrative": "",
            "short_summary": "No clear correlation patterns detected.",
        }

    def _classify_quick_wins(self, findings: dict, recommendations: list) -> list:
        """
        Identify quick wins - simple fixes that can be done in < 15 minutes (Phase 3 - #2).

        Quick win categories:
        - Missing ConfigMaps/Secrets
        - Resource limit adjustments
        - Image tag fixes
        - Label/annotation updates
        - Simple restart operations
        """
        quick_wins = []

        # Define quick win patterns with estimated time
        quick_win_patterns = {
            "missing_configmap": {
                "keywords": [
                    "missing configmap",
                    "configmap not found",
                    'configmap "',
                    "could not find configmap",
                ],
                "title": "Fix Missing ConfigMap",
                "solution": "Create the missing ConfigMap",
                "time": "2 min",
                "category": "configuration",
            },
            "missing_secret": {
                "keywords": [
                    "missing secret",
                    "secret not found",
                    'secret "',
                    "could not find secret",
                ],
                "title": "Fix Missing Secret",
                "solution": "Create the missing Secret",
                "time": "2 min",
                "category": "configuration",
            },
            "resource_limit": {
                "keywords": [
                    "insufficient cpu",
                    "insufficient memory",
                    "resource quota",
                    "exceeded quota",
                ],
                "title": "Adjust Resource Limits",
                "solution": "Update pod resource requests/limits",
                "time": "5 min",
                "category": "resources",
            },
            "image_tag": {
                "keywords": [
                    "imagepullbackoff",
                    "errimagepull",
                    "image not found",
                    "manifest unknown",
                ],
                "title": "Fix Image Reference",
                "solution": "Verify image exists and update tag",
                "time": "5 min",
                "category": "images",
            },
            "image_pull_secret": {
                "keywords": ["failed to pull image", "authentication required", "unauthorized"],
                "title": "Add Image Pull Secret",
                "solution": "Configure imagePullSecrets for private registry",
                "time": "5 min",
                "category": "images",
            },
            "pending_pvc": {
                "keywords": ["pvc pending", "waiting for volume", "storageclass not found"],
                "title": "Fix PVC Configuration",
                "solution": "Verify StorageClass exists or update PVC",
                "time": "10 min",
                "category": "storage",
            },
            "node_taint": {
                "keywords": ["node affinity", "taint", "toleration", "no nodes available"],
                "title": "Adjust Node Affinity/Taints",
                "solution": "Add tolerations or update node affinity",
                "time": "5 min",
                "category": "scheduling",
            },
            "probe_failure": {
                "keywords": ["liveness probe", "readiness probe", "probe failed"],
                "title": "Adjust Probe Configuration",
                "solution": "Increase probe timeout or adjust thresholds",
                "time": "5 min",
                "category": "health",
            },
            "restart_policy": {
                "keywords": ["crashloopbackoff", "back-off restarting", "restarted"],
                "title": "Investigate Restarting Pod",
                "solution": "Check logs and fix application error",
                "time": "10 min",
                "category": "troubleshooting",
            },
        }

        # Scan findings for quick win opportunities
        detected_issues = set()

        for category, items in findings.items():
            for item in items:
                summary = item.get("summary", "").lower()
                details = item.get("details", {})

                for pattern_key, pattern_info in quick_win_patterns.items():
                    for keyword in pattern_info["keywords"]:
                        if keyword in summary and pattern_key not in detected_issues:
                            detected_issues.add(pattern_key)

                            # Extract affected resources
                            affected_pod = details.get("pod", "")
                            affected_namespace = details.get("namespace", "")

                            quick_wins.append(
                                {
                                    "title": pattern_info["title"],
                                    "solution": pattern_info["solution"],
                                    "time": pattern_info["time"],
                                    "category": pattern_info["category"],
                                    "affected_pod": affected_pod,
                                    "affected_namespace": affected_namespace,
                                    "evidence": item.get("summary", ""),
                                }
                            )
                            break

        # Also check recommendations for quick wins
        for rec in recommendations:
            category = rec.get("category", "")
            action = rec.get("action", "").lower()

            # Resource quota quick wins
            if "quota" in category or "limit" in action or "request" in action:
                if "quota" not in detected_issues and "resource" not in detected_issues:
                    quick_wins.append(
                        {
                            "title": "Adjust Resource Quotas",
                            "solution": rec.get("action", "Update resource quotas"),
                            "time": "5 min",
                            "category": "resources",
                            "affected_pod": "",
                            "affected_namespace": "",
                            "evidence": "Resource quota recommendation",
                        }
                    )
                    detected_issues.add("quota")

        # Sort by time (quickest first)
        time_order = {"2 min": 0, "5 min": 1, "10 min": 2, "15 min": 3}
        quick_wins.sort(key=lambda x: time_order.get(x.get("time", "15 min"), 3))

        return quick_wins[:6]  # Return top 6 quick wins

    def _summarize_affected_resources(self, findings: dict) -> dict:
        """Summarize affected resources including namespace breakdown"""
        pods = set()
        nodes = set()
        namespace_counts: dict[str, int] = {}
        services_offline = 0

        for category, items in findings.items():
            for item in items:
                details = item.get("details", {})
                if details.get("pod"):
                    pods.add(details["pod"])
                if details.get("node"):
                    nodes.add(details["node"])
                if details.get("namespace"):
                    ns = details["namespace"]
                    namespace_counts[ns] = namespace_counts.get(ns, 0) + 1

        # Count services with no endpoints (offline services)
        for item in findings.get("network_issues", []):
            details = item.get("details", {})
            if "no endpoints" in item.get("summary", "").lower():
                services_offline += 1

        # Sort namespaces by issue count
        top_namespaces = sorted(namespace_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "pods_affected": len(pods),
            "nodes_affected": len(nodes),
            "namespaces_affected": len(namespace_counts),
            "services_offline": services_offline,
            "pod_list": sorted(list(pods))[:10],
            "node_list": sorted(list(nodes))[:10],
            "namespace_list": sorted(list(namespace_counts.keys())),
            "top_namespaces": [{"name": ns, "count": count} for ns, count in top_namespaces],
        }

    def _get_healthy_components(self, findings: dict, summary: dict) -> list:
        """Get list of healthy components for balanced view"""
        healthy = []

        # Check for categories with no issues
        categories_with_issues = set(findings.keys())

        # Define healthy checks based on missing findings
        healthy_checks = {
            "memory_pressure": ("Memory", "No memory pressure detected"),
            "disk_pressure": ("Disk", "No disk pressure detected"),
            "oom_killed": ("OOM", "No OOM kills in the analysis window"),
            "node_issues": ("Nodes", "All nodes healthy"),
            "control_plane_issues": ("Control Plane", "No critical control plane errors"),
            "scheduling_failures": ("Scheduler", "No scheduling failures"),
            "network_issues": ("Network", "No network issues detected"),
            "rbac_issues": ("RBAC/IAM", "No authorization failures"),
            "image_pull_failures": ("Images", "All images pulling successfully"),
            "pvc_issues": ("Storage", "No PVC issues detected"),
            "dns_issues": ("DNS", "CoreDNS operating normally"),
            "addon_issues": ("Addons", "EKS addons healthy"),
        }

        for category, (name, message) in healthy_checks.items():
            if category not in categories_with_issues:
                healthy.append({"name": name, "message": message})

        # Add healthy checks count from summary
        healthy_checks_count = summary.get("healthy_checks", 0)
        if healthy_checks_count > len(healthy):
            healthy.append(
                {"name": "Health Checks", "message": f"{healthy_checks_count} checks passed"}
            )

        return healthy[:6]  # Limit to 6 items

    def _category_breakdown(self, findings: dict) -> list:
        """Get breakdown of issues by category"""
        breakdown = []

        category_names = {
            "memory_pressure": "Memory Pressure",
            "disk_pressure": "Disk Pressure",
            "pod_errors": "Pod Errors",
            "node_issues": "Node Issues",
            "oom_killed": "OOM Killed",
            "control_plane_issues": "Control Plane",
            "scheduling_failures": "Scheduling",
            "network_issues": "Network",
            "rbac_issues": "RBAC/IAM",
            "image_pull_failures": "Image Pull",
            "resource_quota_exceeded": "Resource Quotas",
            "pvc_issues": "Storage/PVC",
            "dns_issues": "DNS",
            "addon_issues": "EKS Addons",
        }

        for category, items in findings.items():
            if not items:
                continue

            critical = sum(
                1 for item in items if item.get("details", {}).get("severity") == "critical"
            )
            warning = sum(
                1 for item in items if item.get("details", {}).get("severity") == "warning"
            )

            breakdown.append(
                {
                    "category": category,
                    "display_name": category_names.get(
                        category, category.replace("_", " ").title()
                    ),
                    "count": len(items),
                    "critical": critical,
                    "warning": warning,
                }
            )

        # Sort by count descending
        breakdown.sort(key=lambda x: x["count"], reverse=True)
        return breakdown

    def _classify_severity(self, summary_text: str) -> str:
        """Classify severity from summary text"""
        summary_lower = summary_text.lower()

        critical_keywords = ["oom", "killed", "crash", "critical", "down", "unhealthy", "notready"]
        warning_keywords = [
            "warning",
            "warn",
            "degraded",
            "pressure",
            "evicted",
            "pending",
            "timeout",
            "error",
            "failed",
        ]

        for kw in critical_keywords:
            if kw in summary_lower:
                return "critical"
        for kw in warning_keywords:
            if kw in summary_lower:
                return "warning"
        return "info"


class HTMLOutputFormatter(OutputFormatter):
    """Modern HTML output with interactive features"""

    def _classify_severity(self, summary_text, details):
        """Classify finding severity based on content"""
        if details and isinstance(details, dict):
            explicit_severity = details.get("severity")
            if explicit_severity in ("critical", "warning", "info"):
                return explicit_severity

        summary_lower = summary_text.lower()

        critical_keywords = [
            "oom",
            "killed",
            "crash",
            "critical",
            "down",
            "unhealthy",
        ]
        warning_keywords = [
            "warning",
            "warn",
            "degraded",
            "pressure",
            "evicted",
            "pending",
            "timeout",
            "error",
            "failed",
        ]
        info_keywords = ["info", "notice", "fallback", "network not ready"]

        for kw in critical_keywords:
            if kw in summary_lower:
                return "critical"
        for kw in warning_keywords:
            if kw in summary_lower:
                return "warning"
        for kw in info_keywords:
            if kw in summary_lower:
                return "info"

        if details:
            msg = str(details.get("message", "")).lower()
            if msg.startswith("e"):
                return "critical"
            elif msg.startswith("w"):
                return "warning"

        return "info"

    def _get_source_icon(self, details):
        """Get data source indicator"""
        if "log_stream" in details:
            return '<span class="source-badge cw-logs" title="CloudWatch Logs">📋 CW Logs</span>'
        elif "metric" in str(details).lower():
            return '<span class="source-badge cw-metrics" title="CloudWatch Metrics">📊 CW Metrics</span>'
        elif "pod" in details or "namespace" in details:
            return '<span class="source-badge kubectl" title="Kubernetes API">⚙️ kubectl</span>'
        elif "addon" in details:
            return '<span class="source-badge eks" title="EKS API">🔵 EKS API</span>'
        return '<span class="source-badge auto" title="Auto-detected">🔍 Auto</span>'

    def _get_finding_type_badge(self, details):
        """Get finding type badge (current state vs historical event)"""
        finding_type = details.get("finding_type", FindingType.CURRENT_STATE)
        if finding_type == FindingType.HISTORICAL_EVENT:
            return '<span class="finding-type-badge historical" title="Event occurred within date range">📅 Historical</span>'
        else:
            return '<span class="finding-type-badge current" title="Current cluster state (not filtered by date)">🔄 Current</span>'

    def _generate_executive_summary_html(self, exec_summary: dict) -> str:
        """Generate HTML for the Executive Summary section with Phase 1 & 2 enhancements"""
        health = exec_summary.get("health_status", {})
        first_issue = exec_summary.get("first_issue")
        key_findings = exec_summary.get("key_findings", [])
        root_cause = exec_summary.get("root_cause_analysis", {})
        timeline = exec_summary.get("timeline_insights", {})
        actions = exec_summary.get("priority_actions", [])
        affected = exec_summary.get("affected_resources", {})
        categories = exec_summary.get("category_breakdown", [])
        healthy_components = exec_summary.get("healthy_components", [])

        # Phase 2 additions
        trend = exec_summary.get("trend")
        common_errors = exec_summary.get("common_errors", [])
        external_impact = exec_summary.get("external_impact", {})

        status_class = health.get("status", "healthy")

        html = f"""
            <!-- Executive Summary -->
            <section class="executive-summary" id="executive-summary">
                <div class="executive-summary-header">
                    <div class="executive-summary-title">
                        <span>📋</span>
                        <span>Executive Summary</span>
                    </div>
                    <div class="executive-summary-subtitle">AI-Generated Analysis Overview</div>
                </div>
                <div class="executive-summary-content">
                    <!-- Health Assessment with Trend -->
                    <div class="health-assessment {status_class}">
                        <div class="health-icon">{health.get("icon", "✅")}</div>
                        <div class="health-message">
                            <h3>Cluster Status: {health.get("status", "Unknown").upper()}</h3>
                            <p>{health.get("message", "No status available")}</p>
                        </div>
                    </div>

                    <!-- Trend Indicator (Phase 2 - #1) -->
        """

        if trend:
            trend_color = trend.get("color", "#6b7280")
            html += f"""
                    <div class="trend-indicator" style="background: linear-gradient(135deg, {trend_color}15 0%, {trend_color}30 100%); border-left: 4px solid {trend_color};">
                        <span class="trend-icon">{trend.get("icon", "➡️")}</span>
                        <div class="trend-content">
                            <span class="trend-label">Trend</span>
                            <span class="trend-message">{trend.get("message", "No trend data")}</span>
                        </div>
                        <div class="trend-details">
                            <span class="trend-current">{trend.get("last_count", 0)} events</span>
                            <span class="trend-previous">vs {trend.get("previous_count", 0)} in previous hour</span>
                        </div>
                    </div>
            """

        html += f"""
                    <!-- At a Glance Stats -->
                    <div class="at-a-glance">
                        <div class="glance-stat">
                            <div class="glance-value">{health.get("critical_count", 0)}</div>
                            <div class="glance-label">Critical</div>
                        </div>
                        <div class="glance-stat">
                            <div class="glance-value">{health.get("warning_count", 0)}</div>
                            <div class="glance-label">Warnings</div>
                        </div>
                        <div class="glance-stat">
                            <div class="glance-value">{affected.get("pods_affected", 0)}</div>
                            <div class="glance-label">Pods</div>
                        </div>
                        <div class="glance-stat">
                            <div class="glance-value">{affected.get("nodes_affected", 0)}</div>
                            <div class="glance-label">Nodes</div>
                        </div>
                        <div class="glance-stat">
                            <div class="glance-value">{affected.get("namespaces_affected", 0)}</div>
                            <div class="glance-label">Namespaces</div>
                        </div>
                        <div class="glance-stat">
                            <div class="glance-value">{external_impact.get("services_offline_count", 0)}</div>
                            <div class="glance-label">Services Offline</div>
                        </div>
                    </div>
        """

        # First Issue Prominent (Phase 1 - #9)
        if first_issue:
            html += f"""
                    <!-- First Detected Issue - Prominent -->
                    <div class="first-issue-callout" onclick="this.classList.toggle('expanded')">
                        <div class="first-issue-header">
                            <span class="first-issue-icon">🎯</span>
                            <span class="first-issue-title">First Detected Issue</span>
                            <span class="first-issue-toggle">▼</span>
                        </div>
                        <div class="first-issue-content">
                            <div class="first-issue-time">⏰ {first_issue.get("timestamp", "Unknown")}</div>
                            <div class="first-issue-summary">{first_issue.get("summary", "Unknown")}</div>
                            <div class="first-issue-category">Category: {first_issue.get("category", "Unknown")}</div>
                            {"<div class='first-issue-badge'>⚠️ Potential Root Cause</div>" if first_issue.get("is_potential_root_cause") else ""}
                        </div>
                    </div>
            """

        # Collapsible Key Findings (Phase 1 - #10)
        html += f"""
                    <!-- Key Findings - Collapsible -->
                    <div class="summary-block collapsible">
                        <div class="summary-block-header" onclick="toggleSummaryBlock(this)">
                            <div class="summary-block-title">
                                <span>🔍</span> Key Findings
                            </div>
                            <span class="block-toggle">▼</span>
                        </div>
                        <div class="summary-block-content">
        """

        if not key_findings:
            html += """<p style='color: var(--text-secondary); font-size: 0.9rem;'>No critical issues detected</p>"""
        else:
            for finding in key_findings[:5]:
                severity_class = finding.get("severity", "info")
                meta_parts = []
                if finding.get("namespace"):
                    meta_parts.append(f"ns: {finding['namespace']}")
                if finding.get("pod"):
                    meta_parts.append(f"pod: {finding['pod']}")
                if finding.get("node"):
                    meta_parts.append(f"node: {finding['node']}")
                meta_str = (
                    " | ".join(meta_parts)
                    if meta_parts
                    else finding.get("category", "").replace("_", " ").title()
                )
                html += f"""
                            <div class="key-finding-item {severity_class}">
                                <div class="key-finding-summary">{finding.get("summary", "Unknown")}</div>
                                <div class="key-finding-meta">{meta_str}</div>
                            </div>
                """

        html += """
                        </div>
                    </div>
        """

        # Top Impacted Namespaces (Phase 1 - #3)
        top_namespaces = affected.get("top_namespaces", [])
        if top_namespaces:
            html += """
                    <!-- Top Impacted Namespaces -->
                    <div class="summary-block collapsible">
                        <div class="summary-block-header" onclick="toggleSummaryBlock(this)">
                            <div class="summary-block-title">
                                <span>📍</span> Most Impacted Namespaces
                            </div>
                            <span class="block-toggle">▼</span>
                        </div>
                        <div class="summary-block-content">
                            <div class="namespace-list">
            """
            for ns in top_namespaces[:5]:
                html += f"""
                                <div class="namespace-item">
                                    <span class="namespace-name">{ns.get("name", "unknown")}</span>
                                    <span class="namespace-count">{ns.get("count", 0)} issues</span>
                                </div>
                """
            html += """
                            </div>
                        </div>
                    </div>
            """

        # Most Common Error Types (Phase 2 - #4)
        if common_errors:
            html += """
                    <!-- Most Common Error Types -->
                    <div class="summary-block collapsible">
                        <div class="summary-block-header" onclick="toggleSummaryBlock(this)">
                            <div class="summary-block-title">
                                <span>🔥</span> Most Common Errors
                            </div>
                            <span class="block-toggle">▼</span>
                        </div>
                        <div class="summary-block-content">
                            <div class="error-type-list">
            """
            for err in common_errors[:5]:
                # Determine severity color based on error type
                error_type = err.get("error_type", "")
                if error_type in ["CrashLoopBackOff", "OOMKilled", "OOMKilled"]:
                    severity_color = "#ef4444"  # red
                elif error_type in ["ImagePullBackOff", "Evicted", "FailedScheduling"]:
                    severity_color = "#f59e0b"  # amber
                else:
                    severity_color = "#6b7280"  # gray

                html += f"""
                                <div class="error-type-item">
                                    <div class="error-type-header">
                                        <span class="error-type-name" style="border-left: 3px solid {severity_color};">{error_type}</span>
                                        <span class="error-type-count">{err.get("count", 0)}</span>
                                    </div>
                """
                # Add examples
                examples = err.get("examples", [])
                if examples:
                    for ex in examples[:2]:
                        example_text = ex.get("pod", "") or ex.get("summary", "")
                        if example_text:
                            html += f"""
                                    <div class="error-example">• {example_text}</div>
                            """
                html += """
                                </div>
                """
            html += """
                            </div>
                        </div>
                    </div>
            """

        # External Service Impact (Phase 2 - #6)
        if external_impact.get("has_external_impact"):
            impact_level = external_impact.get("impact_level", "healthy")
            impact_message = external_impact.get("impact_message", "")
            services_offline = external_impact.get("services_offline", [])

            impact_color = "#ef4444" if impact_level == "critical" else "#f59e0b"

            html += f"""
                    <!-- External Service Impact -->
                    <div class="summary-block impact-block" style="border-left: 4px solid {impact_color};">
                        <div class="summary-block-header" onclick="toggleSummaryBlock(this)">
                            <div class="summary-block-title">
                                <span>🌐</span> Business Impact
                            </div>
                            <span class="block-toggle">▼</span>
                        </div>
                        <div class="summary-block-content">
                            <div class="impact-alert" style="background: {impact_color}15; border-radius: 8px; padding: 1rem; margin-bottom: 1rem;">
                                <strong>⚠️ {impact_message}</strong>
                            </div>
            """

            if services_offline:
                html += """
                            <div class="impact-services">
                                <strong>Offline Services:</strong>
                """
                for svc in services_offline[:5]:
                    html += f"""
                                <div class="impact-service-item">
                                    <span class="service-name">{svc.get("service", "unknown")}</span>
                                    <span class="service-namespace">{svc.get("namespace", "")}</span>
                                </div>
                """
                html += """
                            </div>
                """

            html += """
                        </div>
                    </div>
            """

        # Phase 3: Correlation-Based Narrative
        narrative = exec_summary.get("narrative", {})
        if narrative.get("has_narrative"):
            narrative_text = narrative.get("narrative", "")
            short_summary = narrative.get("short_summary", "")

            # Convert markdown-style bold to HTML
            narrative_html = narrative_text.replace("**", "<strong>").replace(
                "</strong><strong>", ""
            )
            narrative_html = (
                narrative_html.replace("<strong>", "</strong>", 1)
                if "</strong>" in narrative_html
                else narrative_html
            )

            html += f"""
                    <!-- What Happened - Narrative (Phase 3 - #5) -->
                    <div class="summary-block narrative-block">
                        <div class="summary-block-header" onclick="toggleSummaryBlock(this)">
                            <div class="summary-block-title">
                                <span>📖</span> What Happened
                            </div>
                            <span class="block-toggle">▼</span>
                        </div>
                        <div class="summary-block-content">
                            <div class="narrative-summary">{short_summary}</div>
                            <div class="narrative-details">
                                {narrative_html.replace(chr(10), "<br>")}
                            </div>
                        </div>
                    </div>
            """

        # Phase 3: Quick Wins
        quick_wins = exec_summary.get("quick_wins", [])
        if quick_wins:
            html += (
                """
                    <!-- Quick Wins (Phase 3 - #2) -->
                    <div class="summary-block quick-wins-block">
                        <div class="summary-block-header" onclick="toggleSummaryBlock(this)">
                            <div class="summary-block-title">
                                <span>🚀</span> Quick Wins
                            </div>
                            <span class="quick-wins-count">"""
                + str(len(quick_wins))
                + """ fixes < 15 min</span>
                            <span class="block-toggle">▼</span>
                        </div>
                        <div class="summary-block-content">
                            <div class="quick-wins-grid">
            """
            )
            for qw in quick_wins:
                time_badge_color = "#22c55e" if "2 min" in qw.get("time", "") else "#3b82f6"
                html += f"""
                                <div class="quick-win-item">
                                    <div class="quick-win-header">
                                        <span class="quick-win-title">{qw.get("title", "Quick Fix")}</span>
                                        <span class="quick-win-time" style="background: {time_badge_color};">{qw.get("time", "5 min")}</span>
                                    </div>
                                    <div class="quick-win-solution">{qw.get("solution", "")}</div>
                """
                if qw.get("affected_pod") or qw.get("affected_namespace"):
                    affected = []
                    if qw.get("affected_namespace"):
                        affected.append(f"ns: {qw['affected_namespace']}")
                    if qw.get("affected_pod"):
                        affected.append(f"pod: {qw['affected_pod']}")
                    html += f"""
                                    <div class="quick-win-affected">Affects: {" | ".join(affected)}</div>
                    """
                html += """
                                </div>
                """
            html += """
                            </div>
                        </div>
                    </div>
            """

        # Root Cause Analysis
        html += """
                    <!-- Root Cause Analysis - Collapsible -->
                    <div class="summary-block collapsible collapsed">
                        <div class="summary-block-header" onclick="toggleSummaryBlock(this)">
                            <div class="summary-block-title">
                                <span>🔗</span> Root Cause Analysis
                            </div>
                            <span class="block-toggle">▼</span>
                        </div>
                        <div class="summary-block-content">
        """

        if root_cause.get("has_root_cause"):
            for rc in root_cause.get("identified_root_causes", [])[:3]:
                html += f"""
                            <div class="root-cause-item">
                                <div class="root-cause-text">{rc.get("root_cause", "Unknown")}</div>
                                <div class="root-cause-impact">Impact: {rc.get("impact", "N/A")}</div>
                            </div>
                """
        else:
            html += """<p style='color: var(--text-secondary); font-size: 0.9rem;'>No root cause correlations identified</p>"""

        html += """
                        </div>
                    </div>
        """

        # Priority Actions
        html += """
                    <!-- Priority Actions - Collapsible -->
                    <div class="summary-block collapsible">
                        <div class="summary-block-header" onclick="toggleSummaryBlock(this)">
                            <div class="summary-block-title">
                                <span>⚡</span> Priority Actions
                            </div>
                            <span class="block-toggle">▼</span>
                        </div>
                        <div class="summary-block-content">
        """

        if actions:
            for action in actions[:5]:
                priority = action.get("priority", "medium")
                html += f"""
                            <div class="action-item">
                                <span class="action-priority {priority}">{priority}</span>
                                <div class="action-text">{action.get("action", "No action specified")}</div>
                            </div>
                """
        else:
            html += """<p style='color: var(--text-secondary); font-size: 0.9rem;'>No priority actions identified</p>"""

        html += """
                        </div>
                    </div>
        """

        # Healthy Components (Phase 1 - #7)
        if healthy_components:
            html += """
                    <!-- Healthy Components -->
                    <div class="summary-block healthy-block collapsible collapsed">
                        <div class="summary-block-header" onclick="toggleSummaryBlock(this)">
                            <div class="summary-block-title">
                                <span>✅</span> Healthy Components
                            </div>
                            <span class="block-toggle">▼</span>
                        </div>
                        <div class="summary-block-content">
                            <div class="healthy-grid">
            """
            for comp in healthy_components:
                html += f"""
                                <div class="healthy-item">
                                    <span class="healthy-icon">✓</span>
                                    <div class="healthy-info">
                                        <div class="healthy-name">{comp.get("name", "")}</div>
                                        <div class="healthy-message">{comp.get("message", "")}</div>
                                    </div>
                                </div>
                """
            html += """
                            </div>
                        </div>
                    </div>
            """

        # Category Breakdown
        if categories:
            max_count = max(c.get("count", 0) for c in categories) if categories else 1
            html += """
                    <!-- Category Breakdown - Collapsible -->
                    <div class="summary-block collapsible collapsed">
                        <div class="summary-block-header" onclick="toggleSummaryBlock(this)">
                            <div class="summary-block-title">
                                <span>📈</span> Issues by Category
                            </div>
                            <span class="block-toggle">▼</span>
                        </div>
                        <div class="summary-block-content">
            """
            for cat in categories[:8]:
                width = (cat.get("count", 0) / max_count * 100) if max_count > 0 else 0
                fill_class = (
                    "critical"
                    if cat.get("critical", 0) > 0
                    else "warning"
                    if cat.get("warning", 0) > 0
                    else ""
                )
                html += f"""
                            <div class="category-bar">
                                <div class="category-name">{cat.get("display_name", cat.get("category", ""))}</div>
                                <div class="category-bar-visual">
                                    <div class="category-bar-fill {fill_class}" style="width: {width}%;"></div>
                                </div>
                                <div class="category-count">{cat.get("count", 0)}</div>
                            </div>
                """
            html += """
                        </div>
                    </div>
            """

        html += """
                </div>
            </section>
        """

        return html

    def format(self, results):
        """Format results as interactive HTML"""
        metadata = results["metadata"]
        summary = results["summary"]
        findings = results.get("findings", {})
        recommendations = results.get("recommendations", [])
        errors = results.get("errors", [])
        correlations = results.get("correlations", [])
        first_issue = results.get("first_issue")

        severity_class = (
            "critical"
            if summary["critical"] > 0
            else ("warning" if summary["warning"] > 0 else "healthy")
        )
        severity_text = (
            "CRITICAL"
            if summary["critical"] > 0
            else ("WARNING" if summary["warning"] > 0 else "HEALTHY")
        )
        severity_icon = (
            "🔴" if summary["critical"] > 0 else ("⚠️" if summary["warning"] > 0 else "✅")
        )

        category_info = {
            "memory_pressure": {
                "icon": "💾",
                "source": "CloudWatch Metrics + kubectl",
                "color": "#ff6b6b",
            },
            "disk_pressure": {
                "icon": "💿",
                "source": "CloudWatch Metrics + kubectl",
                "color": "#ff9f43",
            },
            "pod_errors": {
                "icon": "🔴",
                "source": "kubectl events",
                "color": "#ee5a24",
            },
            "node_issues": {
                "icon": "🖥️",
                "source": "kubectl + EKS API",
                "color": "#9b59b6",
            },
            "oom_killed": {
                "icon": "💥",
                "source": "kubectl events + pod status",
                "color": "#c0392b",
            },
            "control_plane_issues": {
                "icon": "⚙️",
                "source": "CloudWatch Logs",
                "color": "#34495e",
            },
            "scheduling_failures": {
                "icon": "📅",
                "source": "kubectl events",
                "color": "#f39c12",
            },
            "network_issues": {
                "icon": "🌐",
                "source": "kubectl events + VPC-CNI",
                "color": "#00cec9",
            },
            "rbac_issues": {
                "icon": "🔒",
                "source": "kubectl events + audit logs",
                "color": "#6c5ce7",
            },
            "image_pull_failures": {
                "icon": "📦",
                "source": "kubectl events",
                "color": "#fd79a8",
            },
            "resource_quota_exceeded": {
                "icon": "📊",
                "source": "kubectl resourcequotas",
                "color": "#e17055",
            },
            "pvc_issues": {
                "icon": "💾",
                "source": "kubectl pvc + EBS CSI",
                "color": "#74b9ff",
            },
            "dns_issues": {
                "icon": "🔍",
                "source": "kubectl pods (CoreDNS)",
                "color": "#a29bfe",
            },
            "addon_issues": {"icon": "🔌", "source": "EKS API", "color": "#55a3ff"},
        }

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EKS Debug Report - {metadata["cluster"]}</title>
    <style>
        :root {{
            --primary: #667eea;
            --primary-dark: #764ba2;
            --critical: #ff6b6b;
            --warning: #feca57;
            --info: #48dbfb;
            --success: #1dd1a1;
            --bg-dark: #1a1a2e;
            --bg-card: #ffffff;
            --text-primary: #2d3748;
            --text-secondary: #718096;
            --border: #e2e8f0;
        }}
        
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #f0f2f5;
            color: var(--text-primary);
            line-height: 1.6;
        }}
        
        .app-container {{ display: flex; min-height: 100vh; }}
        
        /* Sidebar Navigation */
        .sidebar {{
            width: 280px;
            background: linear-gradient(180deg, var(--bg-dark) 0%, #16213e 100%);
            color: white;
            padding: 0;
            position: fixed;
            height: 100vh;
            overflow-y: auto;
        }}
        
        .sidebar-header {{
            padding: 1.5rem;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        
        .sidebar-logo {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 1.25rem;
            font-weight: 700;
        }}
        
        .sidebar-nav {{ padding: 1rem 0; }}
        
        .nav-section {{
            padding: 0.5rem 1rem;
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: rgba(255,255,255,0.4);
            margin-top: 1rem;
        }}
        
        .nav-item {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.75rem 1rem;
            color: rgba(255,255,255,0.7);
            text-decoration: none;
            transition: all 0.2s;
            cursor: pointer;
            border-left: 3px solid transparent;
        }}
        
        .nav-item:hover {{
            background: rgba(255,255,255,0.05);
            color: white;
            border-left-color: var(--primary);
        }}
        
        .nav-item.active {{
            background: rgba(102, 126, 234, 0.2);
            color: white;
            border-left-color: var(--primary);
        }}
        
        .nav-count {{
            background: rgba(255,255,255,0.1);
            padding: 0.15rem 0.5rem;
            border-radius: 10px;
            font-size: 0.75rem;
        }}
        
        .nav-count.has-issues {{ background: var(--critical); }}
        
        /* Main Content */
        .main-content {{
            flex: 1;
            margin-left: 280px;
            padding: 2rem;
        }}
        
        /* Header */
        .page-header {{
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
            color: white;
            padding: 2rem;
            border-radius: 16px;
            margin-bottom: 2rem;
            position: relative;
            overflow: hidden;
        }}
        
        .page-header::before {{
            content: '';
            position: absolute;
            top: -50%;
            right: -10%;
            width: 300px;
            height: 300px;
            background: rgba(255,255,255,0.1);
            border-radius: 50%;
        }}
        
        .header-content {{ position: relative; z-index: 1; }}
        
        .header-title {{
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }}
        
        .header-subtitle {{ opacity: 0.9; font-size: 1rem; }}
        
        .header-meta {{
            display: flex;
            gap: 2rem;
            margin-top: 1.5rem;
            flex-wrap: wrap;
        }}
        
        .meta-item {{
            background: rgba(255,255,255,0.15);
            padding: 0.75rem 1rem;
            border-radius: 8px;
            backdrop-filter: blur(10px);
        }}
        
        .meta-label {{ font-size: 0.75rem; opacity: 0.8; text-transform: uppercase; }}
        .meta-value {{ font-weight: 600; margin-top: 0.25rem; }}
        
        /* Toolbar */
        .toolbar {{
            display: flex;
            gap: 1rem;
            margin-bottom: 1.5rem;
            flex-wrap: wrap;
            align-items: center;
        }}
        
        .search-box {{
            flex: 1;
            min-width: 250px;
            position: relative;
        }}
        
        .search-box input {{
            width: 100%;
            padding: 0.75rem 1rem 0.75rem 2.5rem;
            border: 2px solid var(--border);
            border-radius: 10px;
            font-size: 0.9rem;
            transition: all 0.2s;
        }}
        
        .search-box input:focus {{
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }}
        
        .search-box::before {{
            content: '🔍';
            position: absolute;
            left: 0.75rem;
            top: 50%;
            transform: translateY(-50%);
        }}
        
        .toolbar-btn {{
            padding: 0.75rem 1.25rem;
            border: 2px solid var(--border);
            background: white;
            border-radius: 10px;
            cursor: pointer;
            font-weight: 500;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .toolbar-btn:hover {{
            border-color: var(--primary);
            background: var(--primary);
            color: white;
        }}
        
        .toolbar-btn.active {{
            background: var(--primary);
            color: white;
            border-color: var(--primary);
        }}
        
        /* Summary Cards */
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        
        .summary-card {{
            background: white;
            border-radius: 12px;
            padding: 1.25rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
            border: 1px solid var(--border);
            transition: all 0.2s;
        }}
        
        .summary-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 16px rgba(0,0,0,0.08);
        }}
        
        .summary-card.critical {{ border-left: 4px solid var(--critical); }}
        .summary-card.warning {{ border-left: 4px solid var(--warning); }}
        .summary-card.healthy {{ border-left: 4px solid var(--success); }}
        .summary-card.total {{ border-left: 4px solid var(--primary); }}
        
        .summary-icon {{ font-size: 2rem; margin-bottom: 0.5rem; }}
        .summary-value {{ font-size: 2rem; font-weight: 700; line-height: 1; }}
        .summary-label {{ font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.25rem; }}
        
        /* Finding Type Breakdown */
        .finding-type-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        
        .finding-type-card {{
            background: white;
            border-radius: 12px;
            padding: 1.25rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
            border: 1px solid var(--border);
        }}
        
        .finding-type-card.historical {{ border-left: 4px solid #8b5cf6; }}
        .finding-type-card.current {{ border-left: 4px solid #f59e0b; }}
        
        .finding-type-header {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.75rem;
        }}
        
        .finding-type-icon {{ font-size: 1.25rem; }}
        .finding-type-title {{ font-weight: 600; font-size: 0.95rem; color: var(--text); }}
        
        .finding-type-count {{
            font-size: 2rem;
            font-weight: 700;
            line-height: 1;
            margin-bottom: 0.5rem;
        }}
        
        .finding-type-card.historical .finding-type-count {{ color: #8b5cf6; }}
        .finding-type-card.current .finding-type-count {{ color: #f59e0b; }}
        
        .finding-type-desc {{
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }}
        
        .finding-type-critical {{
            font-size: 0.8rem;
            color: var(--critical);
            font-weight: 500;
        }}
        
        /* Finding Type Badge in Findings */
        .finding-type-badge {{
            display: inline-block;
            font-size: 0.65rem;
            padding: 0.15rem 0.5rem;
            border-radius: 4px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-left: 0.5rem;
        }}
        
        .finding-type-badge.historical {{
            background: #ede9fe;
            color: #7c3aed;
        }}
        
        .finding-type-badge.current {{
            background: #fef3c7;
            color: #d97706;
        }}
        
        /* Executive Summary Section */
        .executive-summary {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.08);
            margin-bottom: 2rem;
            overflow: hidden;
        }}
        
        .executive-summary-header {{
            background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
            color: white;
            padding: 1.5rem;
        }}
        
        .executive-summary-title {{
            font-size: 1.5rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .executive-summary-subtitle {{
            font-size: 0.9rem;
            opacity: 0.8;
        }}
        
        .executive-summary-content {{
            padding: 1.5rem;
        }}
        
        .health-assessment {{
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 1.25rem;
            border-radius: 12px;
            margin-bottom: 1.5rem;
        }}
        
        .health-assessment.critical {{
            background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
            border: 2px solid #ef4444;
        }}
        
        .health-assessment.warning {{
            background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
            border: 2px solid #f59e0b;
        }}
        
        .health-assessment.healthy {{
            background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
            border: 2px solid #22c55e;
        }}
        
        .health-icon {{
            font-size: 3rem;
        }}
        
        .health-message {{
            flex: 1;
        }}
        
        .health-message h3 {{
            margin: 0 0 0.25rem 0;
            font-size: 1.1rem;
        }}
        
        .health-message p {{
            margin: 0;
            color: var(--text-secondary);
            font-size: 0.9rem;
        }}
        
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
            margin-bottom: 1.5rem;
        }}
        
        .summary-block {{
            background: #f8fafc;
            border-radius: 12px;
            padding: 1.25rem;
        }}
        
        .summary-block-title {{
            font-weight: 600;
            font-size: 0.9rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .key-finding-item {{
            padding: 0.75rem;
            background: white;
            border-radius: 8px;
            margin-bottom: 0.5rem;
            border-left: 3px solid var(--border);
        }}
        
        .key-finding-item.critical {{ border-left-color: var(--critical); }}
        .key-finding-item.warning {{ border-left-color: var(--warning); }}
        
        .key-finding-summary {{
            font-size: 0.9rem;
            color: var(--text);
            margin-bottom: 0.25rem;
        }}
        
        .key-finding-meta {{
            font-size: 0.75rem;
            color: var(--text-secondary);
        }}
        
        .root-cause-item {{
            padding: 1rem;
            background: white;
            border-radius: 8px;
            margin-bottom: 0.5rem;
            border-left: 3px solid #8b5cf6;
        }}
        
        .root-cause-text {{
            font-weight: 500;
            color: var(--text);
            margin-bottom: 0.5rem;
        }}
        
        .root-cause-impact {{
            font-size: 0.85rem;
            color: var(--text-secondary);
        }}
        
        .action-item {{
            display: flex;
            align-items: flex-start;
            gap: 0.75rem;
            padding: 0.75rem;
            background: white;
            border-radius: 8px;
            margin-bottom: 0.5rem;
        }}
        
        .action-priority {{
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            flex-shrink: 0;
        }}
        
        .action-priority.high {{ background: #fef2f2; color: #dc2626; }}
        .action-priority.medium {{ background: #fffbeb; color: #d97706; }}
        .action-priority.low {{ background: #f0fdf4; color: #16a34a; }}
        
        .action-text {{
            flex: 1;
            font-size: 0.9rem;
        }}
        
        .affected-resources {{
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
        }}
        
        .resource-stat {{
            text-align: center;
            padding: 1rem;
            background: white;
            border-radius: 8px;
            min-width: 80px;
        }}
        
        .resource-stat-value {{
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--primary);
        }}
        
        .resource-stat-label {{
            font-size: 0.75rem;
            color: var(--text-secondary);
        }}
        
        .category-bar {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.5rem 0;
        }}
        
        .category-name {{
            width: 120px;
            font-size: 0.85rem;
            color: var(--text);
        }}
        
        .category-bar-visual {{
            flex: 1;
            height: 8px;
            background: #e2e8f0;
            border-radius: 4px;
            overflow: hidden;
        }}
        
        .category-bar-fill {{
            height: 100%;
            border-radius: 4px;
        }}
        
        .category-bar-fill.critical {{ background: var(--critical); }}
        .category-bar-fill.warning {{ background: var(--warning); }}
        
        .category-count {{
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--text);
            width: 40px;
            text-align: right;
        }}
        
        /* At a Glance Stats */
        .at-a-glance {{
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            margin-bottom: 1.5rem;
            padding: 1rem;
            background: #f8fafc;
            border-radius: 12px;
        }}
        
        .glance-stat {{
            flex: 1;
            min-width: 100px;
            text-align: center;
            padding: 0.75rem;
            background: white;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}
        
        .glance-value {{
            font-size: 1.75rem;
            font-weight: 700;
            color: var(--primary);
        }}
        
        .glance-label {{
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 0.25rem;
        }}
        
        /* First Issue Callout */
        .first-issue-callout {{
            background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
            border: 2px solid #f59e0b;
            border-radius: 12px;
            margin-bottom: 1.5rem;
            cursor: pointer;
            transition: all 0.2s;
        }}
        
        .first-issue-callout:hover {{
            box-shadow: 0 4px 12px rgba(245, 158, 11, 0.2);
        }}
        
        .first-issue-header {{
            display: flex;
            align-items: center;
            padding: 1rem 1.25rem;
            gap: 0.75rem;
        }}
        
        .first-issue-icon {{
            font-size: 1.5rem;
        }}
        
        .first-issue-title {{
            flex: 1;
            font-weight: 600;
            color: #92400e;
        }}
        
        .first-issue-toggle {{
            color: #92400e;
            font-size: 0.9rem;
            transition: transform 0.2s;
        }}
        
        .first-issue-callout.expanded .first-issue-toggle {{
            transform: rotate(180deg);
        }}
        
        .first-issue-content {{
            display: none;
            padding: 0 1.25rem 1.25rem;
            border-top: 1px solid rgba(245, 158, 11, 0.3);
        }}
        
        .first-issue-callout.expanded .first-issue-content {{
            display: block;
        }}
        
        .first-issue-time {{
            font-size: 0.8rem;
            color: #92400e;
            margin-bottom: 0.5rem;
        }}
        
        .first-issue-summary {{
            font-weight: 600;
            color: #78350f;
            margin-bottom: 0.5rem;
        }}
        
        .first-issue-category {{
            font-size: 0.85rem;
            color: #92400e;
        }}
        
        .first-issue-badge {{
            display: inline-block;
            margin-top: 0.75rem;
            padding: 0.25rem 0.75rem;
            background: #dc2626;
            color: white;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        
        /* Collapsible Summary Blocks */
        .summary-block.collapsible {{
            margin-bottom: 1rem;
        }}
        
        .summary-block.collapsed .summary-block-content {{
            display: none;
        }}
        
        .summary-block-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            padding: 0.5rem 0;
        }}
        
        .summary-block-header:hover {{
            opacity: 0.8;
        }}
        
        .block-toggle {{
            color: var(--text-secondary);
            font-size: 0.9rem;
            transition: transform 0.2s;
        }}
        
        .summary-block.collapsed .block-toggle {{
            transform: rotate(-90deg);
        }}
        
        .summary-block-content {{
            margin-top: 0.75rem;
        }}
        
        /* Namespace List */
        .namespace-list {{
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }}
        
        .namespace-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem 1rem;
            background: white;
            border-radius: 8px;
            border-left: 3px solid var(--primary);
        }}
        
        .namespace-name {{
            font-weight: 500;
            color: var(--text);
        }}
        
        .namespace-count {{
            background: #e2e8f0;
            padding: 0.25rem 0.75rem;
            border-radius: 12px;
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--text-secondary);
        }}
        
        /* Healthy Components Grid */
        .healthy-block {{
            background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%) !important;
            border: 1px solid #22c55e;
        }}
        
        .healthy-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 0.75rem;
        }}
        
        .healthy-item {{
            display: flex;
            align-items: flex-start;
            gap: 0.5rem;
            padding: 0.75rem;
            background: white;
            border-radius: 8px;
        }}
        
        .healthy-icon {{
            color: #22c55e;
            font-weight: bold;
        }}
        
        .healthy-info {{
            flex: 1;
        }}
        
        .healthy-name {{
            font-weight: 600;
            font-size: 0.9rem;
            color: var(--text);
        }}
        
        .healthy-message {{
            font-size: 0.8rem;
            color: var(--text-secondary);
        }}
        
        /* Trend Indicator (Phase 2) */
        .trend-indicator {{
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 1rem 1.25rem;
            border-radius: 12px;
            margin-bottom: 1.5rem;
        }}
        
        .trend-icon {{
            font-size: 1.5rem;
        }}
        
        .trend-content {{
            flex: 1;
        }}
        
        .trend-label {{
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-secondary);
        }}
        
        .trend-message {{
            font-weight: 600;
            color: var(--text);
        }}
        
        .trend-details {{
            text-align: right;
        }}
        
        .trend-current {{
            display: block;
            font-weight: 700;
            font-size: 1.1rem;
            color: var(--text);
        }}
        
        .trend-previous {{
            font-size: 0.75rem;
            color: var(--text-secondary);
        }}
        
        /* Error Types (Phase 2) */
        .error-type-list {{
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }}
        
        .error-type-item {{
            background: white;
            border-radius: 8px;
            padding: 0.75rem 1rem;
        }}
        
        .error-type-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .error-type-name {{
            font-weight: 600;
            color: var(--text);
            padding-left: 0.75rem;
        }}
        
        .error-type-count {{
            background: #e2e8f0;
            padding: 0.25rem 0.75rem;
            border-radius: 12px;
            font-size: 0.85rem;
            font-weight: 600;
        }}
        
        .error-example {{
            font-size: 0.8rem;
            color: var(--text-secondary);
            margin-top: 0.5rem;
            padding-left: 1rem;
        }}
        
        /* Business Impact (Phase 2) */
        .impact-block {{
            background: #fef2f2 !important;
        }}
        
        .impact-alert {{
            margin-bottom: 0.75rem;
        }}
        
        .impact-services {{
            margin-top: 0.75rem;
        }}
        
        .impact-service-item {{
            display: flex;
            justify-content: space-between;
            padding: 0.5rem 0.75rem;
            background: white;
            border-radius: 6px;
            margin-top: 0.5rem;
        }}
        
        .service-name {{
            font-weight: 500;
        }}
        
        .service-namespace {{
            font-size: 0.8rem;
            color: var(--text-secondary);
        }}
        
        /* Narrative Block (Phase 3) */
        .narrative-block {{
            background: linear-gradient(135deg, #faf5ff 0%, #f3e8ff 100%) !important;
            border: 1px solid #c084fc;
        }}
        
        .narrative-summary {{
            font-weight: 600;
            font-size: 1rem;
            color: #6b21a8;
            margin-bottom: 1rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid rgba(192, 132, 252, 0.3);
        }}
        
        .narrative-details {{
            font-size: 0.9rem;
            line-height: 1.6;
            color: var(--text);
        }}
        
        .narrative-details strong {{
            color: #7c3aed;
        }}
        
        /* Quick Wins (Phase 3) */
        .quick-wins-block {{
            background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%) !important;
            border: 1px solid #34d399;
        }}
        
        .quick-wins-count {{
            background: #059669;
            color: white;
            padding: 0.25rem 0.75rem;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
            margin-right: 0.5rem;
        }}
        
        .quick-wins-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1rem;
        }}
        
        .quick-win-item {{
            background: white;
            border-radius: 10px;
            padding: 1rem;
            border-left: 3px solid #22c55e;
        }}
        
        .quick-win-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }}
        
        .quick-win-title {{
            font-weight: 600;
            color: var(--text);
        }}
        
        .quick-win-time {{
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 600;
            color: white;
        }}
        
        .quick-win-solution {{
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }}
        
        .quick-win-affected {{
            font-size: 0.75rem;
            color: #6b7280;
            padding-top: 0.5rem;
            border-top: 1px solid #e5e7eb;
        }}
        
        /* Findings Section */
        .section {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
            margin-bottom: 1.5rem;
            overflow: hidden;
        }}
        
        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1.25rem 1.5rem;
            border-bottom: 1px solid var(--border);
            cursor: pointer;
            transition: background 0.2s;
        }}
        
        .section-header:hover {{ background: #f8fafc; }}
        
        .section-title {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-weight: 600;
            font-size: 1.1rem;
        }}
        
        .section-icon {{ font-size: 1.5rem; }}
        
        .section-meta {{
            display: flex;
            align-items: center;
            gap: 1rem;
        }}
        
        .section-count {{
            background: var(--primary);
            color: white;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 600;
        }}
        
        .section-source {{
            font-size: 0.75rem;
            color: var(--text-secondary);
            background: #f1f5f9;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
        }}
        
        .section-toggle {{
            font-size: 1.25rem;
            transition: transform 0.2s;
        }}
        
        .section.collapsed .section-toggle {{ transform: rotate(-90deg); }}
        .section.collapsed .section-content {{ display: none; }}
        
        .section-content {{ padding: 0; }}
        
        /* Finding Items */
        .finding-item {{
            padding: 1rem 1.5rem;
            border-bottom: 1px solid var(--border);
            transition: background 0.2s;
        }}
        
        .finding-item:last-child {{ border-bottom: none; }}
        .finding-item:hover {{ background: #f8fafc; }}
        
        .finding-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 1rem;
            cursor: pointer;
        }}
        
        .finding-summary {{ flex: 1; font-weight: 500; }}
        
        .finding-badges {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
        
        .severity-badge {{
            padding: 0.2rem 0.6rem;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
        }}
        
        .severity-badge.critical {{ background: #fee2e2; color: #dc2626; }}
        .severity-badge.warning {{ background: #fef3c7; color: #d97706; }}
        .severity-badge.info {{ background: #e0f2fe; color: #0284c7; }}
        
        .source-badge {{
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.7rem;
            background: #f1f5f9;
            color: var(--text-secondary);
        }}
        
        .source-badge.cw-logs {{ background: #fef3c7; color: #92400e; }}
        .source-badge.cw-metrics {{ background: #d1fae5; color: #065f46; }}
        .source-badge.kubectl {{ background: #e0e7ff; color: #3730a3; }}
        .source-badge.eks {{ background: #dbeafe; color: #1e40af; }}
        
        .finding-expand {{
            font-size: 0.9rem;
            color: var(--text-secondary);
            transition: transform 0.2s;
        }}
        
        .finding-item.expanded .finding-expand {{ transform: rotate(180deg); }}
        
        .finding-details {{
            display: none;
            margin-top: 1rem;
            background: #f8fafc;
            border-radius: 8px;
            padding: 1rem;
        }}
        
        .finding-item.expanded .finding-details {{ display: block; }}
        
        .detail-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 0.75rem;
        }}
        
        .detail-item {{ display: flex; flex-direction: column; gap: 0.25rem; }}
        
        .detail-label {{
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-secondary);
            font-weight: 600;
        }}
        
        .detail-value {{
            font-size: 0.9rem;
            font-family: 'Monaco', 'Menlo', monospace;
            background: white;
            padding: 0.5rem;
            border-radius: 4px;
            border: 1px solid var(--border);
            word-break: break-word;
        }}
        
        /* View All Modal */
        .modal {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.5);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }}
        
        .modal.active {{ display: flex; }}
        
        .modal-content {{
            background: white;
            border-radius: 16px;
            width: 90%;
            max-width: 900px;
            max-height: 80vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }}
        
        .modal-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1.25rem 1.5rem;
            border-bottom: 1px solid var(--border);
        }}
        
        .modal-title {{ font-size: 1.25rem; font-weight: 600; }}
        
        .modal-close {{
            background: none;
            border: none;
            font-size: 1.5rem;
            cursor: pointer;
            color: var(--text-secondary);
        }}
        
        .modal-body {{
            padding: 1.5rem;
            overflow-y: auto;
            flex: 1;
        }}
        
        /* Recommendations */
        .recommendation-card {{
            background: white;
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.25rem;
            margin-bottom: 1rem;
            border-left: 4px solid var(--primary);
            transition: all 0.2s;
        }}
        
        .recommendation-card:hover {{
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }}
        
        .recommendation-card.critical {{ border-left-color: var(--critical); }}
        .recommendation-card.high {{ border-left-color: var(--warning); }}
        .recommendation-card.medium {{ border-left-color: var(--info); }}
        
        .rec-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 0.75rem;
        }}
        
        .rec-title {{ font-weight: 600; font-size: 1rem; }}
        
        .priority-badge {{
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}
        
        .priority-badge.critical {{ background: #fee2e2; color: #dc2626; }}
        .priority-badge.high {{ background: #fef3c7; color: #d97706; }}
        .priority-badge.medium {{ background: #e0f2fe; color: #0284c7; }}
        
        .rec-action {{ color: var(--text-secondary); margin-bottom: 0.75rem; }}
        
        .rec-link {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            color: var(--primary);
            text-decoration: none;
            font-weight: 500;
            font-size: 0.9rem;
        }}
        
        .rec-link:hover {{ text-decoration: underline; }}
        
        /* Evidence Section */
        .evidence-section {{
            margin-top: 1rem;
            background: #f8fafc;
            border-radius: 8px;
            padding: 1rem;
            border-left: 3px solid var(--primary);
        }}
        
        .evidence-header {{
            font-weight: 600;
            font-size: 0.85rem;
            color: var(--primary);
            margin-bottom: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .evidence-content {{
            font-size: 0.9rem;
        }}
        
        .evidence-stats {{
            display: flex;
            gap: 1rem;
            margin-bottom: 0.75rem;
            flex-wrap: wrap;
        }}
        
        .stat-item {{
            background: white;
            padding: 0.25rem 0.75rem;
            border-radius: 4px;
            font-size: 0.85rem;
        }}
        
        .stat-item.critical {{ background: #fee2e2; color: #dc2626; }}
        .stat-item.warning {{ background: #fef3c7; color: #d97706; }}
        .stat-item.info {{ background: #e0f2fe; color: #0284c7; }}
        
        .evidence-examples {{
            margin-bottom: 0.75rem;
        }}
        
        .evidence-examples ul {{
            margin: 0.5rem 0 0 1rem;
            padding: 0;
        }}
        
        .evidence-examples li {{
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 0.25rem;
        }}
        
        .evidence-resources, .evidence-timing, .evidence-impact {{
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-top: 0.5rem;
        }}
        
        .evidence-resources strong, .evidence-timing strong, .evidence-impact strong {{
            color: var(--text-primary);
        }}
        
        /* Diagnostic Section */
        .diagnostic-section {{
            margin-top: 1rem;
            background: #fefce8;
            border-radius: 8px;
            padding: 1rem;
            border-left: 3px solid #ca8a04;
        }}
        
        .diagnostic-header {{
            font-weight: 600;
            font-size: 0.85rem;
            color: #854d0e;
            margin-bottom: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .diagnostic-steps {{
            margin: 0;
            padding-left: 1.5rem;
        }}
        
        .diagnostic-steps li {{
            margin-bottom: 0.5rem;
            font-size: 0.85rem;
        }}
        
        .diagnostic-steps code {{
            background: white;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 0.8rem;
            color: #1e40af;
            word-break: break-all;
        }}
        
        /* Correlation Cards */
        .correlation-card {{
            background: white;
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.25rem;
            margin-bottom: 1rem;
            border-left: 4px solid var(--primary);
            transition: all 0.2s;
        }}
        
        .correlation-card:hover {{
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }}
        
        .correlation-card.critical {{ border-left-color: var(--critical); }}
        .correlation-card.high {{ border-left-color: var(--warning); }}
        .correlation-card.warning {{ border-left-color: var(--info); }}
        
        .corr-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 0.75rem;
        }}
        
        .corr-title {{ font-weight: 600; font-size: 1rem; }}
        .corr-time {{ color: var(--text-secondary); font-size: 0.85rem; margin-bottom: 0.5rem; }}
        .corr-impact {{ color: var(--text-primary); margin-bottom: 0.5rem; }}
        .corr-recommendation {{ color: var(--text-secondary); font-size: 0.9rem; }}
        
        /* First Issue Card */
        .first-issue-card {{
            background: linear-gradient(135deg, #fff5f5 0%, #fff 100%);
            border: 2px solid var(--critical);
            border-radius: 12px;
            padding: 1.5rem;
        }}
        
        .first-issue-time {{
            color: var(--critical);
            font-weight: 600;
            margin-bottom: 0.5rem;
        }}
        
        .first-issue-category {{
            color: var(--text-secondary);
            font-size: 0.85rem;
            margin-bottom: 0.5rem;
        }}
        
        .first-issue-summary {{
            color: var(--text-primary);
            font-weight: 500;
            margin-bottom: 0.75rem;
        }}
        
        .first-issue-note {{
            color: var(--primary);
            font-size: 0.9rem;
            font-style: italic;
        }}
        
        /* Data Sources Summary */
        .sources-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        
        .source-card {{
            background: white;
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 1rem;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}
        
        .source-icon {{ font-size: 1.5rem; }}
        .source-info {{ flex: 1; }}
        .source-name {{ font-weight: 600; font-size: 0.9rem; }}
        .source-status {{ font-size: 0.75rem; color: var(--text-secondary); }}
        
        /* Errors */
        .error-item {{
            background: #fef2f2;
            border: 1px solid #fecaca;
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 0.75rem;
        }}
        
        .error-step {{ font-weight: 600; color: #dc2626; margin-bottom: 0.25rem; }}
        .error-msg {{ font-size: 0.9rem; color: #7f1d1d; font-family: monospace; }}
        
        /* Footer */
        .page-footer {{
            text-align: center;
            padding: 2rem;
            color: var(--text-secondary);
            font-size: 0.85rem;
        }}
        
        .footer-link {{ color: var(--primary); text-decoration: none; font-weight: 500; }}
        .footer-link:hover {{ text-decoration: underline; }}
        
        /* Responsive */
        @media (max-width: 1024px) {{
            .sidebar {{ transform: translateX(-100%); }}
            .main-content {{ margin-left: 0; }}
        }}
        
        @media print {{
            .sidebar, .toolbar {{ display: none; }}
            .main-content {{ margin-left: 0; }}
            .section.collapsed .section-content {{ display: block; }}
        }}
    </style>
</head>
<body>
    <div class="app-container">
        <!-- Sidebar Navigation -->
        <aside class="sidebar">
            <div class="sidebar-header">
                <div class="sidebar-logo">
                    <span>🔍</span>
                    <span>EKS Debugger</span>
                </div>
            </div>
            <nav class="sidebar-nav">
                <div class="nav-section">Overview</div>
                <a href="#summary" class="nav-item">
                    <span>📊 Dashboard</span>
                </a>
                <a href="#executive-summary" class="nav-item">
                    <span>📋 Executive Summary</span>
                </a>
                <a href="#sources" class="nav-item">
                    <span>📡 Data Sources</span>
                </a>
                
                <div class="nav-section">Findings</div>
                <a href="#all-findings" class="nav-item">
                    <span>📋 All Findings</span>
                    <span class="nav-count {"has-issues" if summary["total_issues"] > 0 else ""}">{summary["total_issues"]}</span>
                </a>
"""

        for cat, items in findings.items():
            if items:
                cat_title = cat.replace("_", " ").title()
                cat_icon = category_info.get(cat, {}).get("icon", "📋")
                html += f"""
                <a href="#{cat}" class="nav-item">
                    <span>{cat_icon} {cat_title}</span>
                    <span class="nav-count {"has-issues" if len(items) > 0 else ""}">{len(items)}</span>
                </a>
"""

        # Add correlation navigation items
        if correlations:
            html += f"""
                <a href="#correlations" class="nav-item">
                    <span>🔗 Root Cause Analysis</span>
                    <span class="nav-count has-issues">{len(correlations)}</span>
                </a>
"""

        if first_issue:
            html += """
                <a href="#first-issue" class="nav-item">
                    <span>🎯 Potential Root Cause</span>
                    <span class="nav-count">1</span>
                </a>
"""

        html += f"""
                <div class="nav-section">Actions</div>
                <a href="#recommendations" class="nav-item">
                    <span>💡 Recommendations</span>
                    <span class="nav-count">{len(recommendations)}</span>
                </a>
            </nav>
        </aside>

        <!-- Main Content -->
        <main class="main-content">
            <!-- Header -->
            <header class="page-header" id="summary">
                <div class="header-content">
                    <h1 class="header-title">🔍 EKS Cluster Analysis Report</h1>
                    <p class="header-subtitle">Comprehensive diagnostic analysis powered by AWS best practices</p>
                    
                    <div class="header-meta">
                        <div class="meta-item">
                            <div class="meta-label">Cluster</div>
                            <div class="meta-value">{metadata["cluster"]}</div>
                        </div>
                        <div class="meta-item">
                            <div class="meta-label">Region</div>
                            <div class="meta-value">{metadata["region"]}</div>
                        </div>
                        <div class="meta-item">
                            <div class="meta-label">Analysis Date</div>
                            <div class="meta-value">{metadata["analysis_date"].split("T")[0]}</div>
                        </div>
                        <div class="meta-item">
                            <div class="meta-label">Time Range</div>
                            <div class="meta-value">{metadata["date_range"]["start"].split("T")[0]} to {metadata["date_range"]["end"].split("T")[0]}</div>
                        </div>
                    </div>
                </div>
            </header>

            <!-- Toolbar -->
            <div class="toolbar">
                <div class="search-box">
                    <input type="text" id="searchInput" placeholder="Search findings..." onkeyup="filterFindings()">
                </div>
                <button class="toolbar-btn" onclick="expandAll()">📂 Expand All</button>
                <button class="toolbar-btn" onclick="collapseAll()">📁 Collapse All</button>
                <button class="toolbar-btn" onclick="showAllFindingsModal()">📋 View All</button>
                <button class="toolbar-btn" onclick="window.print()">🖨️ Print</button>
            </div>

            <!-- Summary Cards -->
            <div class="summary-grid">
                <div class="summary-card {severity_class}">
                    <div class="summary-icon">{severity_icon}</div>
                    <div class="summary-value">{severity_text}</div>
                    <div class="summary-label">Overall Status</div>
                </div>
                <div class="summary-card total">
                    <div class="summary-icon">📊</div>
                    <div class="summary-value">{summary["total_issues"]}</div>
                    <div class="summary-label">Total Findings</div>
                </div>
                <div class="summary-card critical">
                    <div class="summary-icon">🔴</div>
                    <div class="summary-value">{summary["critical"]}</div>
                    <div class="summary-label">Critical</div>
                </div>
                <div class="summary-card warning">
                    <div class="summary-icon">⚠️</div>
                    <div class="summary-value">{summary["warning"]}</div>
                    <div class="summary-label">Warnings</div>
                </div>
                <div class="summary-card healthy">
                    <div class="summary-icon">✅</div>
                    <div class="summary-value">{summary.get("healthy_checks", 0)}</div>
                    <div class="summary-label">Healthy Checks</div>
                </div>
            </div>

            <!-- Finding Type Breakdown -->
            <div class="finding-type-grid">
                <div class="finding-type-card historical">
                    <div class="finding-type-header">
                        <span class="finding-type-icon">📅</span>
                        <span class="finding-type-title">Historical Events</span>
                    </div>
                    <div class="finding-type-count">{summary.get("historical_event_count", 0)}</div>
                    <div class="finding-type-desc">Within date range ({metadata["date_range"]["start"].split("T")[0]} to {metadata["date_range"]["end"].split("T")[0]})</div>
                    <div class="finding-type-critical">🔴 {summary.get("historical_event_critical", 0)} critical</div>
                </div>
                <div class="finding-type-card current">
                    <div class="finding-type-header">
                        <span class="finding-type-icon">🔄</span>
                        <span class="finding-type-title">Current State</span>
                    </div>
                    <div class="finding-type-count">{summary.get("current_state_count", 0)}</div>
                    <div class="finding-type-desc">Current cluster state (not filtered by date)</div>
                    <div class="finding-type-critical">🔴 {summary.get("current_state_critical", 0)} critical</div>
                </div>
            </div>

            <!-- Data Sources Summary -->
            <div id="sources" class="sources-grid">
                <div class="source-card">
                    <div class="source-icon">📋</div>
                    <div class="source-info">
                        <div class="source-name">CloudWatch Logs</div>
                        <div class="source-status">Control plane logs enabled</div>
                    </div>
                </div>
                <div class="source-card">
                    <div class="source-icon">📊</div>
                    <div class="source-info">
                        <div class="source-name">Container Insights</div>
                        <div class="source-status">{"Enabled" if summary.get("has_metrics") else "Not detected"}</div>
                    </div>
                </div>
                <div class="source-card">
                    <div class="source-icon">⚙️</div>
                    <div class="source-info">
                        <div class="source-name">kubectl</div>
                        <div class="source-status">Connected via context</div>
                    </div>
                </div>
                <div class="source-card">
                    <div class="source-icon">🔵</div>
                    <div class="source-info">
                        <div class="source-name">EKS API</div>
                        <div class="source-status">5 addons checked</div>
                    </div>
                </div>
            </div>
"""

        # Generate Executive Summary
        exec_summary_gen = ExecutiveSummaryGenerator()
        exec_summary = exec_summary_gen.generate(results)

        html += self._generate_executive_summary_html(exec_summary)

        all_findings_json = []

        if findings:
            html += (
                """
            <!-- All Findings Section -->
            <section class="section" id="all-findings">
                <div class="section-header" onclick="toggleSection(this)">
                    <div class="section-title">
                        <span class="section-icon">📋</span>
                        <span>All Findings</span>
                    </div>
                    <div class="section-meta">
                        <span class="section-count">"""
                + str(summary["total_issues"])
                + """</span>
                        <span class="section-toggle">▼</span>
                    </div>
                </div>
                <div class="section-content">
"""
            )

            for cat, items in findings.items():
                if items:
                    cat_info = category_info.get(
                        cat, {"icon": "📋", "source": "Auto-detected", "color": "#666"}
                    )
                    cat_title = cat.replace("_", " ").title()

                    for idx, item in enumerate(items):
                        item_severity = self._classify_severity(
                            item.get("summary", ""), item.get("details", {})
                        )
                        source_badge = self._get_source_icon(item.get("details", {}))
                        finding_type_badge = self._get_finding_type_badge(item.get("details", {}))
                        finding_id = f"{cat}-{idx}"

                        all_findings_json.append(
                            {
                                "id": finding_id,
                                "category": cat_title,
                                "summary": item.get("summary", ""),
                                "severity": item_severity,
                                "details": item.get("details", {}),
                            }
                        )

                        html += f'''
                    <div class="finding-item" data-severity="{item_severity}" data-category="{cat}">
                        <div class="finding-header" onclick="toggleFinding(this.parentElement)">
                            <div class="finding-summary">{item.get("summary", "N/A")}</div>
                            <div class="finding-badges">
                                <span class="severity-badge {item_severity}">{item_severity}</span>
                                {finding_type_badge}
                                {source_badge}
                                <span class="finding-expand">▼</span>
                            </div>
                        </div>
                        <div class="finding-details">
                            <div class="detail-grid">
'''
                        if item.get("details"):
                            for key, value in item["details"].items():
                                html += f"""
                                <div class="detail-item">
                                    <div class="detail-label">{key}</div>
                                    <div class="detail-value">{value}</div>
                                </div>
"""
                        html += """
                            </div>
                        </div>
                    </div>
"""

            html += """
                </div>
            </section>
"""

        html += """
            <!-- Category Sections -->
"""

        for cat, items in findings.items():
            if items:
                cat_info = category_info.get(
                    cat, {"icon": "📋", "source": "Auto-detected", "color": "#666"}
                )
                cat_title = cat.replace("_", " ").title()

                severities = [
                    self._classify_severity(item.get("summary", ""), item.get("details", {}))
                    for item in items
                ]
                critical_count = severities.count("critical")
                warning_count = severities.count("warning")

                html += f'''
            <section class="section collapsed" id="{cat}">
                <div class="section-header" onclick="toggleSection(this)">
                    <div class="section-title">
                        <span class="section-icon">{cat_info["icon"]}</span>
                        <span>{cat_title}</span>
                    </div>
                    <div class="section-meta">
                        <span class="section-source">{cat_info["source"]}</span>
                        <span class="section-count">{len(items)}</span>
                        <span class="section-toggle">▼</span>
                    </div>
                </div>
                <div class="section-content">
'''
                for idx, item in enumerate(items[:50]):
                    item_severity = self._classify_severity(
                        item.get("summary", ""), item.get("details", {})
                    )
                    source_badge = self._get_source_icon(item.get("details", {}))
                    finding_type_badge = self._get_finding_type_badge(item.get("details", {}))

                    html += f'''
                    <div class="finding-item" data-severity="{item_severity}">
                        <div class="finding-header" onclick="toggleFinding(this.parentElement)">
                            <div class="finding-summary">{item.get("summary", "N/A")}</div>
                            <div class="finding-badges">
                                <span class="severity-badge {item_severity}">{item_severity}</span>
                                {finding_type_badge}
                                {source_badge}
                                <span class="finding-expand">▼</span>
                            </div>
                        </div>
                        <div class="finding-details">
                            <div class="detail-grid">
'''
                    if item.get("details"):
                        for key, value in item["details"].items():
                            html += f"""
                                <div class="detail-item">
                                    <div class="detail-label">{key}</div>
                                    <div class="detail-value">{value}</div>
                                </div>
"""
                    html += """
                            </div>
                        </div>
                    </div>
"""

                if len(items) > 50:
                    html += f"""
                    <div class="finding-item">
                        <div class="finding-summary" style="color: var(--text-secondary);">... and {len(items) - 50} more findings (use "View All" to see complete list)</div>
                    </div>
"""

                html += """
                </div>
            </section>
"""

        # Add correlations section
        correlations = results.get("correlations", [])
        if correlations:
            html += f"""
            <!-- Correlations Section -->
            <section class="section" id="correlations">
                <div class="section-header" onclick="toggleSection(this)">
                    <div class="section-title">
                        <span class="section-icon">🔗</span>
                        <span>Root Cause Analysis</span>
                    </div>
                    <div class="section-meta">
                        <span class="section-count">{len(correlations)}</span>
                        <span class="section-toggle">▼</span>
                    </div>
                </div>
                <div class="section-content" style="padding: 1.5rem;">
"""
            for corr in correlations:
                html += f"""
                    <div class="correlation-card {corr.get("severity", "warning")}">
                        <div class="corr-header">
                            <div class="corr-title">🔍 {corr["root_cause"]}</div>
                            <span class="severity-badge {corr.get("severity", "warning")}">{corr.get("severity", "warning")}</span>
                        </div>
                        <div class="corr-time">⏰ First detected: {corr.get("root_cause_time", "Unknown")}</div>
                        <div class="corr-impact">📊 Impact: {corr["impact"]}</div>
                        <div class="corr-recommendation">💡 Recommendation: {corr["recommendation"]}</div>
"""
                if corr.get("aws_doc"):
                    html += f"""
                        <a href="{corr["aws_doc"]}" class="rec-link" target="_blank">
                            📚 View AWS Documentation →
                        </a>
"""
                html += """
                    </div>
"""
            html += """
                </div>
            </section>
"""

        # Add first issue indicator
        first_issue = results.get("first_issue")
        if first_issue:
            html += f"""
            <!-- First Issue Section -->
            <section class="section" id="first-issue">
                <div class="section-header" onclick="toggleSection(this)">
                    <div class="section-title">
                        <span class="section-icon">🎯</span>
                        <span>Potential Root Cause</span>
                    </div>
                    <div class="section-meta">
                        <span class="section-toggle">▼</span>
                    </div>
                </div>
                <div class="section-content" style="padding: 1.5rem;">
                    <div class="first-issue-card">
                        <div class="first-issue-time">⏰ First Issue Detected: {first_issue["timestamp"]}</div>
                        <div class="first-issue-category">📁 Category: {first_issue["category"]}</div>
                        <div class="first-issue-summary">📝 {first_issue["summary"]}</div>
                        <div class="first-issue-note">💡 This may be the root cause of subsequent issues</div>
                    </div>
                </div>
            </section>
"""

        if recommendations:
            html += (
                """
            <!-- Recommendations Section -->
            <section class="section" id="recommendations">
                <div class="section-header" onclick="toggleSection(this)">
                    <div class="section-title">
                        <span class="section-icon">💡</span>
                        <span>Recommendations</span>
                    </div>
                    <div class="section-meta">
                        <span class="section-count">"""
                + str(len(recommendations))
                + """</span>
                        <span class="section-toggle">▼</span>
                    </div>
                </div>
                <div class="section-content" style="padding: 1.5rem;">
"""
            )
            for rec in recommendations:
                is_correlation = rec.get("is_correlation", False)
                card_class = "correlation-card" if is_correlation else "recommendation-card"

                html += f"""
                    <div class="{card_class} {rec.get("priority", "medium")}">
                        <div class="rec-header">
                            <div class="rec-title">{"🔗 " if is_correlation else ""}{rec["title"]}</div>
                            <span class="priority-badge {rec.get("priority", "medium")}">{rec.get("priority", "medium")}</span>
                        </div>
                        <div class="rec-action">{rec["action"]}</div>
"""

                # Add evidence section
                evidence = rec.get("evidence")
                if evidence and isinstance(evidence, dict):
                    html += """
                        <div class="evidence-section">
                            <div class="evidence-header">📊 Evidence</div>
                            <div class="evidence-content">
"""
                    # Show counts
                    total = evidence.get("total_count", 0)
                    critical = evidence.get("critical_count", 0)
                    warning = evidence.get("warning_count", 0)
                    info = evidence.get("info_count", 0)

                    if total:
                        html += f"""
                                <div class="evidence-stats">
                                    <span class="stat-item"><strong>{total}</strong> findings</span>
                                    {f'<span class="stat-item critical">{critical} critical</span>' if critical else ""}
                                    {f'<span class="stat-item warning">{warning} warning</span>' if warning else ""}
                                    {f'<span class="stat-item info">{info} info</span>' if info else ""}
                                </div>
"""

                    # Show examples
                    examples = evidence.get("examples", [])
                    if examples:
                        html += """
                                <div class="evidence-examples">
                                    <strong>Examples:</strong>
                                    <ul>
"""
                        for ex in examples[:3]:
                            html += f"                                        <li>{ex}</li>\n"
                        html += """                                    </ul>
                                </div>
"""

                    # Show affected resources
                    affected = evidence.get("affected_resources", [])
                    if affected:
                        html += f"""
                                <div class="evidence-resources">
                                    <strong>Affected resources:</strong> {", ".join(affected[:5])}
                                    {f"and {len(affected) - 5} more..." if len(affected) > 5 else ""}
                                </div>
"""

                    # Show timing
                    first_seen = evidence.get("first_seen")
                    last_seen = evidence.get("last_seen")
                    if first_seen:
                        html += f"""
                                <div class="evidence-timing">
                                    <strong>First seen:</strong> {first_seen}
                                    {f"<br><strong>Last seen:</strong> {last_seen}" if last_seen and last_seen != first_seen else ""}
                                </div>
"""

                    # Show correlation-specific info
                    if is_correlation:
                        impact = evidence.get("impact")
                        if impact:
                            html += f"""
                                <div class="evidence-impact">
                                    <strong>Impact:</strong> {impact}
                                </div>
"""

                    html += """
                            </div>
                        </div>
"""

                # Add diagnostic steps
                diagnostic_steps = rec.get("diagnostic_steps", [])
                if diagnostic_steps:
                    html += """
                        <div class="diagnostic-section">
                            <div class="diagnostic-header">🔍 Diagnostic Steps</div>
                            <ol class="diagnostic-steps">
"""
                    for step in diagnostic_steps:
                        html += f"                                <li><code>{step}</code></li>\n"
                    html += """                            </ol>
                        </div>
"""

                if rec.get("aws_doc"):
                    html += f'''
                        <a href="{rec["aws_doc"]}" class="rec-link" target="_blank">
                            📚 View AWS Documentation →
                        </a>
'''
                html += """
                    </div>
"""
            html += """
                </div>
            </section>
"""

        if errors:
            html += """
            <!-- Errors Section -->
            <section class="section">
                <div class="section-header">
                    <div class="section-title">
                        <span class="section-icon">⚠️</span>
                        <span>Analysis Errors</span>
                    </div>
                </div>
                <div class="section-content" style="padding: 1.5rem;">
"""
            for error in errors:
                html += f"""
                    <div class="error-item">
                        <div class="error-step">{error["step"]}</div>
                        <div class="error-msg">{error["message"]}</div>
                    </div>
"""
            html += """
                </div>
            </section>
"""

        html += (
            f"""
            <!-- Footer -->
            <footer class="page-footer">
                <p>Generated with <a href="#" class="footer-link">EKS Comprehensive Debugger v{VERSION}</a></p>
                <p>Analysis Date: {metadata["analysis_date"]}</p>
            </footer>
        </main>
    </div>

    <!-- View All Modal -->
    <div class="modal" id="allFindingsModal">
        <div class="modal-content">
            <div class="modal-header">
                <h3 class="modal-title">📋 All Findings ("""
            + str(len(all_findings_json))
            + """)</h3>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body" id="modalBody">
"""
        )

        for finding in all_findings_json:
            html += f"""
                <div class="finding-item">
                    <div class="finding-header">
                        <div class="finding-summary"><strong>{finding["category"]}:</strong> {finding["summary"]}</div>
                        <span class="severity-badge {finding["severity"]}">{finding["severity"]}</span>
                    </div>
                </div>
"""

        html += """
            </div>
        </div>
    </div>

    <script>
        function toggleSection(header) {
            const section = header.parentElement;
            section.classList.toggle('collapsed');
        }
        
        function toggleFinding(item) {
            item.classList.toggle('expanded');
        }
        
        function toggleSummaryBlock(header) {
            const block = header.parentElement;
            block.classList.toggle('collapsed');
        }
        
        function expandAll() {
            document.querySelectorAll('.section').forEach(s => s.classList.remove('collapsed'));
            document.querySelectorAll('.finding-item').forEach(f => f.classList.add('expanded'));
            document.querySelectorAll('.summary-block.collapsible').forEach(b => b.classList.remove('collapsed'));
        }
        
        function collapseAll() {
            document.querySelectorAll('.section').forEach(s => s.classList.add('collapsed'));
            document.querySelectorAll('.finding-item').forEach(f => f.classList.remove('expanded'));
            document.querySelectorAll('.summary-block.collapsible').forEach(b => b.classList.add('collapsed'));
        }
        
        function filterFindings() {
            const query = document.getElementById('searchInput').value.toLowerCase();
            document.querySelectorAll('.finding-item').forEach(item => {
                const text = item.textContent.toLowerCase();
                item.style.display = text.includes(query) ? 'block' : 'none';
            });
        }
        
        function showAllFindingsModal() {
            document.getElementById('allFindingsModal').classList.add('active');
        }
        
        function closeModal() {
            document.getElementById('allFindingsModal').classList.remove('active');
        }
        
        // Close modal on outside click
        document.getElementById('allFindingsModal').addEventListener('click', function(e) {
            if (e.target === this) closeModal();
        });
        
        // Smooth scroll for nav links
        document.querySelectorAll('.nav-item').forEach(link => {
            link.addEventListener('click', function(e) {
                const href = this.getAttribute('href');
                if (href && href.startsWith('#')) {
                    e.preventDefault();
                    const target = document.querySelector(href);
                    if (target) {
                        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                }
            });
        });
    </script>
</body>
</html>
"""
        return html


# === SECTION 5: CORE DEBUGGER CLASS ===


class ComprehensiveEKSDebugger(DateFilterMixin):
    """
    Comprehensive EKS cluster debugger with date filtering and multiple output formats.

    Provides systematic analysis of EKS cluster health including pod evictions,
    node conditions, OOM kills, control plane logs, networking, storage, and IAM.

    Attributes:
        profile: AWS profile name for authentication.
        region: AWS region where the cluster resides.
        cluster_name: Name of the EKS cluster being analyzed.
        start_date: Start of analysis window (timezone-aware datetime).
        end_date: End of analysis window (timezone-aware datetime).
        namespace: Optional Kubernetes namespace filter.
        kube_context: Optional kubectl context name for private clusters.
        findings: Dictionary of categorized findings by issue type.
        correlations: List of identified root cause correlations.
        timeline: Chronological list of all detected events.
        first_issue: Earliest detected issue (potential root cause).
        errors: List of errors encountered during analysis.

    Example:
        >>> debugger = ComprehensiveEKSDebugger(
        ...     profile="prod",
        ...     region="eu-west-1",
        ...     cluster_name="my-cluster",
        ...     days=1
        ... )
        >>> results = debugger.run_comprehensive_analysis()
    """

    def __init__(
        self,
        profile,
        region,
        cluster_name=None,
        start_date=None,
        end_date=None,
        namespace=None,
        progress=None,
        kube_context=None,
    ):
        """
        Initialize debugger

        Args:
            profile: AWS profile name
            region: AWS region
            cluster_name: EKS cluster name (optional, will prompt if not provided)
            start_date: Start date for analysis (timezone-aware datetime)
            end_date: End date for analysis (timezone-aware datetime)
            namespace: Kubernetes namespace filter (optional)
            progress: ProgressTracker instance
            kube_context: Kubernetes context name (optional, skips kubeconfig update if provided)
        """
        self.profile = profile
        self.region = region
        self.cluster_name = cluster_name
        self.start_date = start_date or (
            datetime.now(timezone.utc) - timedelta(hours=DEFAULT_LOOKBACK_HOURS)
        )
        self.end_date = end_date or datetime.now(timezone.utc)
        self.namespace = namespace
        self.progress = progress or ProgressTracker()
        self.kube_context = kube_context

        # AWS clients
        try:
            self.session = boto3.Session(profile_name=profile, region_name=region)
            self.eks_client = self.session.client("eks")
            self.logs_client = self.session.client("logs")
            self.cloudwatch_client = self.session.client("cloudwatch")
            self.sts_client = self.session.client("sts")
        except Exception as e:
            raise AWSAuthenticationError(f"Failed to initialize AWS session: {e}")

        # Findings structure - expanded categories
        self.findings = {
            # Existing categories
            "memory_pressure": [],
            "disk_pressure": [],
            "pod_errors": [],
            "node_issues": [],
            "oom_killed": [],
            # New comprehensive categories
            "control_plane_issues": [],
            "scheduling_failures": [],
            "network_issues": [],
            "rbac_issues": [],
            "image_pull_failures": [],
            "resource_quota_exceeded": [],
            "pvc_issues": [],
            "dns_issues": [],
            "addon_issues": [],
        }

        self.errors = []
        self.correlations = []
        self.timeline = []
        self.first_issue = None

    # === AWS Validation Methods (Reused from existing) ===

    def validate_aws_access(self):
        """Validate AWS credentials and permissions"""
        self.progress.step("Validating AWS credentials...")
        try:
            identity = self.sts_client.get_caller_identity()
            self.progress.info(f"Authenticated as: {identity['Arn']}")
            self.progress.info(f"Account: {identity['Account']}")
            return True
        except Exception as e:
            raise AWSAuthenticationError(f"AWS authentication failed: {e}")

    def get_cluster_name(self):
        """Get cluster name interactively or validate provided name"""
        self.progress.step("Identifying EKS cluster...")

        try:
            response = self.eks_client.list_clusters()
            clusters = response.get("clusters", [])

            if not clusters:
                raise ClusterNotFoundError("No EKS clusters found in this region")

            # If cluster name provided, validate it exists
            if self.cluster_name:
                if self.cluster_name not in clusters:
                    raise ClusterNotFoundError(
                        f"Cluster '{self.cluster_name}' not found in {self.region}"
                    )
                self.progress.info(f"Using cluster: {self.cluster_name}")
                return self.cluster_name

            # Interactive selection
            if len(clusters) == 1:
                self.cluster_name = clusters[0]
                self.progress.info(f"Auto-selected only cluster: {self.cluster_name}")
            else:
                print(f"\n✓ Found {len(clusters)} EKS clusters:")
                print()

                for idx, cluster in enumerate(clusters, 1):
                    try:
                        cluster_info = self.eks_client.describe_cluster(name=cluster)
                        status = cluster_info["cluster"]["status"]
                        version = cluster_info["cluster"]["version"]
                        created = cluster_info["cluster"]["createdAt"].strftime("%Y-%m-%d")

                        status_icon = "✓" if status == "ACTIVE" else "⚠️"
                        print(f"  {idx}. {cluster}")
                        print(
                            f"     {status_icon} Status: {status} | Version: {version} | Created: {created}"
                        )
                    except Exception:
                        print(f"  {idx}. {cluster} (details unavailable)")

                print()
                while True:
                    try:
                        choice = input(f"Select cluster (1-{len(clusters)}): ").strip()
                        choice_idx = int(choice) - 1

                        if 0 <= choice_idx < len(clusters):
                            self.cluster_name = clusters[choice_idx]
                            print(f"\n✓ Selected cluster: {self.cluster_name}")
                            break
                        else:
                            print(f"❌ Invalid choice. Please enter 1-{len(clusters)}")
                    except ValueError:
                        print("❌ Please enter a valid number")
                    except KeyboardInterrupt:
                        raise EKSDebuggerError("Cluster selection cancelled by user")

            # Get cluster details
            cluster_info = self.eks_client.describe_cluster(name=self.cluster_name)
            status = cluster_info["cluster"]["status"]
            version = cluster_info["cluster"]["version"]

            self.progress.info(f"Cluster Status: {status}, Version: {version}")

            if status != "ACTIVE":
                self.progress.warning(f"Cluster status is {status}, not ACTIVE")

            return self.cluster_name

        except ClusterNotFoundError:
            raise
        except Exception as e:
            raise ClusterNotFoundError(f"Error listing clusters: {e}")

    def update_kubeconfig(self):
        """Update kubeconfig with AWS best practices"""
        self.progress.step("Updating kubeconfig...")

        # Skip if custom context is provided
        if self.kube_context:
            self.progress.info(f"Using custom context: {self.kube_context}")
            return True

        try:
            cmd = f"aws eks update-kubeconfig --name {self.cluster_name} --region {self.region} --profile {self.profile}"
            result = subprocess.run(cmd, shell=True, check=True, capture_output=True, timeout=30)
            self.progress.info("kubeconfig updated")
            return True

        except subprocess.TimeoutExpired:
            raise KubectlNotAvailableError("Timeout updating kubeconfig")
        except subprocess.CalledProcessError as e:
            raise KubectlNotAvailableError(f"Failed to update kubeconfig: {e}")
        except FileNotFoundError:
            raise KubectlNotAvailableError("kubectl not found in PATH")

    # === Helper Methods ===

    def get_kubectl_output(self, cmd, timeout=DEFAULT_TIMEOUT, required=False):
        """Run kubectl command with error handling"""
        # Add context flag if custom context is set
        if self.kube_context:
            cmd = f"{cmd} --context {self.kube_context}"

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout,
            )
            return result.stdout
        except subprocess.TimeoutExpired:
            msg = f"kubectl command timed out: {cmd}"
            if required:
                raise EKSDebuggerError(msg)
            self.progress.warning(msg)
            return None
        except subprocess.CalledProcessError as e:
            msg = f"kubectl command failed: {e.stderr if e.stderr else str(e)}"
            if required:
                raise EKSDebuggerError(msg)
            self.progress.warning(msg)
            return None

    def safe_api_call(self, func, *args, **kwargs):
        """
        Safely call AWS API with retry logic

        Returns: (success: bool, result: Any)
        """
        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                result = func(*args, **kwargs)
                return True, result
            except Exception as e:
                if attempt < max_retries - 1:
                    self.progress.info(f"Retry {attempt + 1}/{max_retries} after error: {e}")
                    time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                else:
                    return False, str(e)

        return False, "Max retries exceeded"

    def safe_kubectl_call(self, cmd, required=False):
        """Safely call kubectl with error handling"""
        try:
            return self.get_kubectl_output(cmd, required=required)
        except EKSDebuggerError:
            if required:
                raise
            return None

    def _build_kubectl_events_cmd(self, reason: str) -> str:
        """Build kubectl events command with namespace handling."""
        if self.namespace:
            return (
                f"kubectl get events -n {self.namespace} --field-selector reason={reason} -o json"
            )
        return f"kubectl get events --all-namespaces --field-selector reason={reason} -o json"

    def _get_filtered_events(self, reason: str) -> dict | None:
        """Execute kubectl command and filter events by date."""
        cmd = self._build_kubectl_events_cmd(reason)
        output = self.safe_kubectl_call(cmd)
        if not output:
            return None
        events = json.loads(output)
        return self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

    def _parse_event_common(self, event: dict) -> dict:
        """Extract common fields from Kubernetes event."""
        return {
            "pod": event.get("involvedObject", {}).get("name", "Unknown"),
            "namespace": event.get("metadata", {}).get("namespace", "Unknown"),
            "timestamp": event.get("lastTimestamp", event.get("eventTime", "Unknown")),
            "message": event.get("message", "N/A"),
        }

    def _add_finding(
        self,
        category: str,
        summary: str,
        details: dict | None = None,
        finding_type: str = FindingType.CURRENT_STATE,
    ) -> None:
        """Add finding to appropriate category with finding type classification."""
        if details is None:
            details = {}
        details["finding_type"] = finding_type
        self.findings[category].append({"summary": summary, "details": details})

    def _classify_severity(self, summary_text: str, details: dict | None) -> str:
        """Classify finding severity based on content."""
        if details and isinstance(details, dict):
            explicit_severity = details.get("severity")
            if explicit_severity in ("critical", "warning", "info"):
                return explicit_severity

        summary_lower = summary_text.lower()

        critical_keywords = [
            "oom",
            "killed",
            "crash",
            "critical",
            "down",
            "unhealthy",
        ]
        warning_keywords = [
            "warning",
            "warn",
            "degraded",
            "pressure",
            "evicted",
            "pending",
            "timeout",
            "error",
            "failed",
        ]
        info_keywords = ["info", "notice", "fallback", "network not ready"]

        for kw in critical_keywords:
            if kw in summary_lower:
                return "critical"
        for kw in warning_keywords:
            if kw in summary_lower:
                return "warning"
        for kw in info_keywords:
            if kw in summary_lower:
                return "info"

        if details:
            msg = str(details.get("message", "")).lower()
            if msg.startswith("e"):
                return "critical"
            elif msg.startswith("w"):
                return "warning"

        return "info"

    # === Existing Analysis Methods (Enhanced with date filtering) ===

    def analyze_pod_evictions(self):
        """
        Analyze pod evictions within the configured date range.

        Queries kubectl events for Evicted reason and categorizes findings
        by eviction cause (memory, disk, or other).

        Populates:
            self.findings['memory_pressure']: Evictions due to memory pressure.
            self.findings['disk_pressure']: Evictions due to disk/ephemeral storage.
            self.findings['pod_errors']: Other eviction causes.

        Reference:
            https://repost.aws/knowledge-center/eks-resolve-disk-pressure
        """
        self.progress.step("Analyzing pod evictions...")

        try:
            cmd = "kubectl get events --all-namespaces --field-selector reason=Evicted -o json"
            if self.namespace:
                cmd = f"kubectl get events -n {self.namespace} --field-selector reason=Evicted -o json"

            output = self.safe_kubectl_call(cmd)
            if not output:
                self.progress.info("No eviction events found")
                return

            events = json.loads(output)

            # Apply date filtering
            events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

            eviction_reasons = defaultdict(int)

            for event in events.get("items", []):
                message = event.get("message", "Unknown")
                eviction_reasons[message] += 1

                pod_name = event["involvedObject"].get("name", "Unknown")
                namespace = event["metadata"]["namespace"]
                timestamp = event.get("lastTimestamp", event.get("eventTime", "Unknown"))

                finding = {
                    "summary": f"Pod {namespace}/{pod_name} evicted",
                    "details": {
                        "pod": pod_name,
                        "namespace": namespace,
                        "timestamp": timestamp,
                        "reason": message,
                        "finding_type": FindingType.HISTORICAL_EVENT,
                    },
                }

                if "memory" in message.lower():
                    self.findings["memory_pressure"].append(finding)
                elif "disk" in message.lower() or "ephemeral" in message.lower():
                    self.findings["disk_pressure"].append(finding)
                else:
                    self.findings["pod_errors"].append(finding)

            self.progress.info(
                f"Found {len(events.get('items', []))} eviction events in date range"
            )

        except Exception as e:
            self.errors.append({"step": "analyze_pod_evictions", "message": str(e)})
            self.progress.warning(f"Pod eviction analysis failed: {e}")

    def analyze_node_conditions(self):
        """
        Analyze node health conditions following AWS EKS best practices.

        Checks node conditions including Ready, MemoryPressure, DiskPressure,
        PIDPressure, and NetworkUnavailable states.

        Populates:
            self.findings['node_issues']: Unhealthy node conditions.
            self.findings['memory_pressure']: Nodes with MemoryPressure.
            self.findings['disk_pressure']: Nodes with DiskPressure.

        Reference:
            AWS EKS node health monitoring
            https://docs.aws.amazon.com/eks/latest/userguide/managed-node-groups.html
        """
        self.progress.step("Analyzing node health and conditions...")

        try:
            cmd = "kubectl get nodes -o json"
            output = self.safe_kubectl_call(cmd)

            if not output:
                return

            nodes_data = json.loads(output)

            for node in nodes_data.get("items", []):
                node_name = node["metadata"]["name"]
                conditions = node["status"].get("conditions", [])

                for condition in conditions:
                    ctype = condition["type"]
                    status = condition["status"]
                    message = condition.get("message", "N/A")

                    if status == "True" and ctype in [
                        "MemoryPressure",
                        "DiskPressure",
                        "PIDPressure",
                        "NetworkUnavailable",
                    ]:
                        finding = {
                            "summary": f"Node {node_name} has {ctype}",
                            "details": {
                                "node": node_name,
                                "condition": ctype,
                                "status": status,
                                "message": message,
                                "finding_type": FindingType.CURRENT_STATE,
                            },
                        }

                        if ctype == "MemoryPressure":
                            finding["details"]["severity"] = "critical"
                            finding["details"]["root_causes"] = [
                                "Pods without memory limits consuming excessive memory",
                                "Memory leak in application",
                                "Insufficient node memory capacity",
                                "Too many pods scheduled on node",
                            ]
                            finding["details"]["diagnostic_steps"] = [
                                f"kubectl describe node {node_name} | grep -A 5 'Allocated resources'",
                                "kubectl top pods --all-namespaces --sort-by=memory",
                                "Review pod memory limits and requests",
                                "Consider adding nodes or using larger instance types",
                            ]
                            finding["details"]["aws_doc"] = (
                                "https://repost.aws/knowledge-center/eks-resolve-memory-pressure"
                            )
                            self.findings["memory_pressure"].append(finding)
                        elif ctype == "DiskPressure":
                            finding["details"]["severity"] = "critical"
                            finding["details"]["root_causes"] = [
                                "Container images taking up disk space",
                                "Large container log files",
                                "EmptyDir volumes not cleaned up",
                                "Ephemeral storage limits exceeded",
                            ]
                            finding["details"]["diagnostic_steps"] = [
                                f"SSH to node: df -h to identify full mount",
                                "crictl images to list container images",
                                "crictl rmi --prune to remove unused images",
                                "du -sh /var/log/containers/* to find large log files",
                                f"kubectl describe node {node_name} | grep -A 10 'DiskPressure'",
                            ]
                            finding["details"]["aws_doc"] = (
                                "https://repost.aws/knowledge-center/eks-resolve-disk-pressure"
                            )
                            self.findings["disk_pressure"].append(finding)
                        elif ctype == "PIDPressure":
                            finding["details"]["severity"] = "critical"
                            finding["details"]["root_causes"] = [
                                "Application creating too many processes/threads",
                                "Process leak in application",
                                "Too many containers per node",
                                "Insufficient pid_max kernel setting",
                            ]
                            finding["details"]["diagnostic_steps"] = [
                                f"SSH to node: cat /proc/sys/kernel/pid_max",
                                "ps aux --sort=pid | tail -50 to find process hogs",
                                "Check per-pod process count: crictl pods",
                                f"kubectl describe node {node_name} | grep -A 5 'PIDPressure'",
                                "If a pod has process leak: identify and restart the pod",
                                "Increase --pid-max in kubelet config if needed",
                            ]
                            finding["details"]["impact"] = (
                                "New containers and processes cannot start - node may become unusable"
                            )
                            finding["details"]["aws_doc"] = (
                                "https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/#pid-pressure"
                            )
                            self.findings["node_issues"].append(finding)
                        elif ctype == "NetworkUnavailable":
                            finding["details"]["severity"] = "critical"
                            finding["details"]["root_causes"] = [
                                "VPC CNI not configured correctly",
                                "Node security group blocking traffic",
                                "Subnet route table issues",
                                "ENI attachment failures",
                            ]
                            finding["details"]["diagnostic_steps"] = [
                                f"kubectl describe node {node_name} | grep -A 5 'NetworkUnavailable'",
                                "Check aws-node DaemonSet: kubectl get ds aws-node -n kube-system",
                                "Verify node is in correct subnet",
                                "Check security group allows required traffic",
                            ]
                            finding["details"]["aws_doc"] = (
                                "https://docs.aws.amazon.com/eks/latest/userguide/eks-networking.html"
                            )
                            self.findings["network_issues"].append(finding)

                    elif ctype == "Ready" and status != "True":
                        self.findings["node_issues"].append(
                            {
                                "summary": f"Node {node_name} is not Ready",
                                "details": {
                                    "node": node_name,
                                    "condition": "NotReady",
                                    "message": message,
                                    "severity": "critical",
                                    "root_causes": [
                                        "Kubelet process crashed or unresponsive",
                                        "Container runtime (containerd) not running",
                                        "Node EC2 instance health issues",
                                        "Network connectivity to control plane lost",
                                        "Certificate rotation failure",
                                    ],
                                    "diagnostic_steps": [
                                        "SSH to node via SSM: aws ssm start-session --target <instance-id>",
                                        "systemctl status kubelet",
                                        "systemctl status containerd",
                                        "journalctl -u kubelet -n 100 --no-pager",
                                        "Check EC2 instance status in AWS Console",
                                    ],
                                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html",
                                    "finding_type": FindingType.CURRENT_STATE,
                                },
                            }
                        )

            # Check for PIDPressure-related events
            try:
                cmd = "kubectl get events --all-namespaces --field-selector reason=PIDPressure -o json"
                output = self.safe_kubectl_call(cmd)
                if output:
                    events = json.loads(output)
                    events = self.filter_kubectl_events_by_date(
                        events, self.start_date, self.end_date
                    )
                    for event in events.get("items", []):
                        node = event.get("involvedObject", {}).get("name", "Unknown")
                        message = event.get("message", "")
                        timestamp = event.get("lastTimestamp", event.get("eventTime", "Unknown"))

                        self.findings["node_issues"].append(
                            {
                                "summary": f"PIDPressure event on node {node}",
                                "details": {
                                    "node": node,
                                    "reason": "PIDPressure",
                                    "message": message[:200],
                                    "timestamp": str(timestamp),
                                    "severity": "critical",
                                    "diagnostic_steps": [
                                        f"SSH to node {node}: cat /proc/sys/kernel/pid_max",
                                        "ps aux | wc -l to count running processes",
                                        "Identify process-heavy pods and restart if needed",
                                    ],
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                },
                            }
                        )
            except Exception:
                pass

            self.progress.info(f"Analyzed {len(nodes_data.get('items', []))} nodes")

        except Exception as e:
            self.errors.append({"step": "analyze_node_conditions", "message": str(e)})
            self.progress.warning(f"Node condition analysis failed: {e}")

    def check_oom_events(self):
        """
        Check for OOMKilled (Out of Memory) events within the date range.

        Queries kubectl events for OOMKilling reason to identify pods
        that were terminated due to exceeding memory limits.

        Populates:
            self.findings['oom_killed']: Pods killed by OOM killer.
        """
        self.progress.step("Checking for OOM (Out of Memory) events...")

        try:
            cmd = "kubectl get events --all-namespaces --field-selector reason=OOMKilling -o json"
            if self.namespace:
                cmd = f"kubectl get events -n {self.namespace} --field-selector reason=OOMKilling -o json"

            output = self.safe_kubectl_call(cmd)
            if not output:
                self.progress.info("No OOMKilled events found")
                return

            events = json.loads(output)

            # Apply date filtering
            events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

            for event in events.get("items", []):
                pod = event["involvedObject"].get("name", "Unknown")
                namespace = event["metadata"]["namespace"]
                message = event.get("message", "N/A")
                timestamp = event.get("lastTimestamp", "Unknown")

                self.findings["oom_killed"].append(
                    {
                        "summary": f"Pod {namespace}/{pod} was OOM killed",
                        "details": {
                            "pod": pod,
                            "namespace": namespace,
                            "timestamp": timestamp,
                            "message": message,
                            "finding_type": FindingType.HISTORICAL_EVENT,
                        },
                    }
                )

            self.progress.info(f"Found {len(events.get('items', []))} OOM events in date range")

        except Exception as e:
            self.errors.append({"step": "check_oom_events", "message": str(e)})
            self.progress.warning(f"OOM event check failed: {e}")

    def check_container_insights_metrics(self):
        """
        Check CloudWatch Container Insights metrics for threshold violations.

        Analyzes node memory, CPU, and filesystem utilization metrics from
        Container Insights to detect resource pressure.

        Populates:
            self.findings['memory_pressure']: High memory utilization.
            self.findings['disk_pressure']: High disk utilization.

        Reference:
            https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/ContainerInsights.html
        """
        self.progress.step("Checking CloudWatch Container Insights metrics...")

        metrics_config = [
            {
                "name": "node_memory_utilization",
                "display": "Node Memory Utilization",
                "unit": "Percent",
                "threshold": Thresholds.MEMORY_WARNING,
                "critical": Thresholds.MEMORY_CRITICAL,
            },
            {
                "name": "node_cpu_utilization",
                "display": "Node CPU Utilization",
                "unit": "Percent",
                "threshold": Thresholds.CPU_WARNING,
                "critical": Thresholds.CPU_CRITICAL,
            },
            {
                "name": "node_filesystem_utilization",
                "display": "Node Filesystem (Disk) Utilization",
                "unit": "Percent",
                "threshold": Thresholds.DISK_WARNING,
                "critical": Thresholds.DISK_CRITICAL,
            },
        ]

        time_params = self.get_cloudwatch_time_params(self.start_date, self.end_date)

        for metric in metrics_config:
            try:
                success, response = self.safe_api_call(
                    self.cloudwatch_client.get_metric_statistics,
                    Namespace="ContainerInsights",
                    MetricName=metric["name"],
                    Dimensions=[{"Name": "ClusterName", "Value": self.cluster_name}],
                    StartTime=time_params["StartTime"],
                    EndTime=time_params["EndTime"],
                    Period=3600,
                    Statistics=["Average", "Maximum", "Minimum"],
                )

                if not success:
                    self.progress.warning(f"Failed to fetch {metric['name']}: {response}")
                    continue

                datapoints = sorted(response.get("Datapoints", []), key=lambda x: x["Timestamp"])

                if not datapoints:
                    self.progress.info(
                        f"No data for {metric['display']} (Container Insights may not be enabled)"
                    )
                    continue

                # Check for threshold violations
                for dp in datapoints:
                    avg = dp.get("Average", 0)
                    max_val = dp.get("Maximum", 0)
                    timestamp = dp["Timestamp"]

                    if metric["threshold"] and max_val >= metric["critical"]:
                        category = (
                            "memory_pressure" if "memory" in metric["name"] else "disk_pressure"
                        )
                        self.findings[category].append(
                            {
                                "summary": f"{metric['display']} exceeded critical threshold ({metric['critical']}%)",
                                "details": {
                                    "metric": metric["name"],
                                    "timestamp": str(timestamp),
                                    "average": f"{avg:.1f}%",
                                    "maximum": f"{max_val:.1f}%",
                                    "threshold": f"{metric['critical']}%",
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                },
                            }
                        )

            except Exception as e:
                self.errors.append(
                    {
                        "step": f"check_container_insights_metrics_{metric['name']}",
                        "message": str(e),
                    }
                )

    def analyze_cloudwatch_logging_health(self):
        """
        Analyze CloudWatch logging health for EKS
        Checks: Control plane logs, Container Insights logs, Prometheus metrics

        Catalog: Logging and metrics ingestion
        - No EKS control plane logs in CloudWatch
        - Container logs not appearing in CloudWatch
        - Prometheus metrics missing in CloudWatch

        Reference: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/ContainerInsights.html
        """
        self.progress.step("Checking CloudWatch logging health...")

        try:
            # 1. Check control plane logging
            control_plane_log_group = f"/aws/eks/{self.cluster_name}/cluster"
            success, response = self.safe_api_call(
                self.logs_client.describe_log_groups,
                logGroupNamePrefix=control_plane_log_group,
            )

            control_plane_enabled = False
            if success and response.get("logGroups"):
                log_group = response["logGroups"][0]
                retention = log_group.get("retentionInDays", -1)
                success, streams = self.safe_api_call(
                    self.logs_client.describe_log_streams,
                    logGroupName=control_plane_log_group,
                    orderBy="LastEventTime",
                    descending=True,
                    limit=1,
                )
                if success and streams.get("logStreams"):
                    last_event = streams["logStreams"][0].get("lastEventTimestamp")
                    if last_event:
                        from datetime import timezone

                        last_event_dt = datetime.fromtimestamp(last_event / 1000, tz=timezone.utc)
                        now = datetime.now(timezone.utc)
                        hours_since_log = (now - last_event_dt).total_seconds() / 3600
                        if hours_since_log < 24:
                            control_plane_enabled = True

            if not control_plane_enabled:
                self.findings["addon_issues"].append(
                    {
                        "summary": "EKS control plane logging not enabled or no recent logs",
                        "details": {
                            "log_group": control_plane_log_group,
                            "severity": "warning",
                            "finding_type": FindingType.CURRENT_STATE,
                            "impact": "Cannot diagnose control plane issues without logs",
                            "diagnostic_steps": [
                                'Enable control plane logging: aws eks update-cluster-config --name <cluster> --logging \'{"clusterLogging":[{"types":["api","audit","authenticator","controllerManager","scheduler"],"enabled":true}]}\'',
                                "Verify in EKS console under Logging tab",
                            ],
                            "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html",
                        },
                    }
                )

            # 2. Check Container Insights application logs
            app_log_group = f"/aws/containerinsights/{self.cluster_name}/application"
            success, response = self.safe_api_call(
                self.logs_client.describe_log_groups, logGroupNamePrefix=app_log_group
            )

            container_logs_enabled = False
            fluentbit_healthy = False

            if success and response.get("logGroups"):
                container_logs_enabled = True

            # Check FluentBit/CloudWatch agent DaemonSet
            cmd = "kubectl get daemonset -n amazon-cloudwatch -o json 2>/dev/null || kubectl get daemonset -n kube-system -l k8s-app=aws-node -o json 2>/dev/null"
            output = self.safe_kubectl_call(cmd)

            if output:
                try:
                    ds_data = json.loads(output)
                    for ds in ds_data.get("items", []):
                        ds_name = ds.get("metadata", {}).get("name", "")
                        if "fluent" in ds_name.lower() or "cloudwatch" in ds_name.lower():
                            status = ds.get("status", {})
                            desired = status.get("desiredNumberScheduled", 0)
                            ready = status.get("numberReady", 0)
                            if desired > 0 and ready == desired:
                                fluentbit_healthy = True
                            elif desired > 0 and ready < desired:
                                self.findings["addon_issues"].append(
                                    {
                                        "summary": f"Log agent DaemonSet {ds_name} not healthy: {ready}/{desired} ready",
                                        "details": {
                                            "daemonset": ds_name,
                                            "namespace": ds.get("metadata", {}).get(
                                                "namespace", "unknown"
                                            ),
                                            "desired": desired,
                                            "ready": ready,
                                            "severity": "warning",
                                            "finding_type": FindingType.CURRENT_STATE,
                                            "impact": "Container logs may not be flowing to CloudWatch",
                                            "diagnostic_steps": [
                                                f"kubectl describe ds {ds_name} -n amazon-cloudwatch",
                                                f"kubectl logs -n amazon-cloudwatch -l k8s-app={ds_name}",
                                                "Check IAM permissions for logs:PutLogEvents",
                                            ],
                                        },
                                    }
                                )
                except Exception:
                    pass

            if not container_logs_enabled:
                self.findings["addon_issues"].append(
                    {
                        "summary": "Container Insights application logs not configured",
                        "details": {
                            "expected_log_group": app_log_group,
                            "severity": "warning",
                            "finding_type": FindingType.CURRENT_STATE,
                            "impact": "Cannot view container logs in CloudWatch",
                            "diagnostic_steps": [
                                "Install CloudWatch agent or Fluent Bit",
                                "Verify IAM role has logs:PutLogEvents permission",
                                "Check amazon-cloudwatch namespace for DaemonSet",
                            ],
                            "aws_doc": "https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-setup-logs.html",
                        },
                    }
                )

            # 3. Check Prometheus metrics (Container Insights/Prometheus)
            prometheus_log_group = f"/aws/containerinsights/{self.cluster_name}/prometheus"
            success, response = self.safe_api_call(
                self.logs_client.describe_log_groups,
                logGroupNamePrefix=prometheus_log_group,
            )

            prometheus_enabled = False
            if success and response.get("logGroups"):
                prometheus_enabled = True

            # Check for CloudWatch agent with Prometheus scraping
            cmd = "kubectl get deployment -n amazon-cloudwatch -o json 2>/dev/null"
            output = self.safe_kubectl_call(cmd)

            prometheus_agent_found = False
            if output:
                try:
                    deployments = json.loads(output)
                    for dep in deployments.get("items", []):
                        dep_name = dep.get("metadata", {}).get("name", "")
                        if "cloudwatch" in dep_name.lower() and "agent" in dep_name.lower():
                            containers = (
                                dep.get("spec", {})
                                .get("template", {})
                                .get("spec", {})
                                .get("containers", [])
                            )
                            for container in containers:
                                env_vars = container.get("env", [])
                                for env in env_vars:
                                    if env.get("name", "").lower() == "prometheus_config":
                                        prometheus_agent_found = True
                except Exception:
                    pass

            if not prometheus_enabled and not prometheus_agent_found:
                self.findings["addon_issues"].append(
                    {
                        "summary": "Prometheus metrics scraping not configured for Container Insights",
                        "details": {
                            "expected_log_group": prometheus_log_group,
                            "severity": "info",
                            "finding_type": FindingType.CURRENT_STATE,
                            "impact": "Custom Prometheus metrics not available in CloudWatch",
                            "diagnostic_steps": [
                                "Deploy CloudWatch agent with Prometheus config",
                                "Create ServiceMonitor/PodMonitor CRDs if using Prometheus Operator",
                                "Verify prometheus-eks.yaml configuration",
                            ],
                            "aws_doc": "https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/ContainerInsights-Prometheus.html",
                        },
                    }
                )

            # 4. Check for metrics in ContainerInsights namespace
            success, response = self.safe_api_call(
                self.cloudwatch_client.list_metrics,
                Namespace="ContainerInsights",
                Dimensions=[{"Name": "ClusterName", "Value": self.cluster_name}],
            )

            if success and not response.get("Metrics"):
                self.findings["addon_issues"].append(
                    {
                        "summary": "No Container Insights metrics found for cluster",
                        "details": {
                            "cluster": self.cluster_name,
                            "severity": "warning",
                            "finding_type": FindingType.CURRENT_STATE,
                            "impact": "Cannot monitor cluster performance via CloudWatch",
                            "diagnostic_steps": [
                                "Enable Container Insights: aws eks update-addon --cluster-name <cluster> --addon-name amazon-cloudwatch-observability",
                                "Verify CloudWatch agent is running on nodes",
                                "Check IAM permissions for CloudWatch agent",
                            ],
                            "aws_doc": "https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/ContainerInsights.html",
                        },
                    }
                )

            # Summary finding
            health_status = []
            if control_plane_enabled:
                health_status.append("Control plane logs: ✅")
            else:
                health_status.append("Control plane logs: ❌")

            if container_logs_enabled:
                health_status.append("Container logs: ✅")
            else:
                health_status.append("Container logs: ❌")

            if prometheus_enabled:
                health_status.append("Prometheus metrics: ✅")
            else:
                health_status.append("Prometheus metrics: ❌")

            self.progress.info(f"CloudWatch logging health: {', '.join(health_status)}")

        except Exception as e:
            self.errors.append({"step": "analyze_cloudwatch_logging_health", "message": str(e)})
            self.progress.warning(f"CloudWatch logging health check failed: {e}")

    # === NEW: Comprehensive Analysis Methods ===

    def analyze_control_plane_logs(self):
        """
        Analyze EKS control plane CloudWatch logs for errors.

        Scans API server, scheduler, controller manager, and authenticator
        logs for error patterns while filtering out benign messages.

        Populates:
            self.findings['control_plane_issues']: Errors from control plane logs.

        Reference:
            https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html
        """
        self.progress.step("Analyzing control plane logs...")

        log_group = f"/aws/eks/{self.cluster_name}/cluster"

        try:
            success, response = self.safe_api_call(
                self.logs_client.describe_log_groups, logGroupNamePrefix=log_group
            )

            if not success or not response.get("logGroups"):
                self.progress.info(
                    f"Control plane logging not enabled for cluster {self.cluster_name}"
                )
                return

            success, streams_response = self.safe_api_call(
                self.logs_client.describe_log_streams,
                logGroupName=log_group,
                orderBy="LastEventTime",
                descending=True,
                limit=5,
            )

            if not success:
                return

            error_patterns = ["error", "fail", "denied", "forbidden", "unauthorized"]

            for stream in streams_response.get("logStreams", []):
                stream_name = stream["logStreamName"]

                success, logs_response = self.safe_api_call(
                    self.logs_client.get_log_events,
                    logGroupName=log_group,
                    logStreamName=stream_name,
                    startTime=int(self.start_date.timestamp() * 1000),
                    endTime=int(self.end_date.timestamp() * 1000),
                    limit=50,
                    startFromHead=False,
                )

                if not success:
                    continue

                for event in logs_response.get("events", []):
                    message = event["message"]
                    message_lower = message.lower()

                    if not any(pattern in message_lower for pattern in error_patterns):
                        continue

                    is_benign = any(
                        re.search(pattern, message, re.IGNORECASE)
                        for pattern in CONTROL_PLANE_BENIGN_PATTERNS
                    )

                    if is_benign:
                        continue

                    is_critical = any(
                        pattern in message_lower for pattern in CONTROL_PLANE_ERROR_PATTERNS
                    )

                    if message.startswith("E") and len(message) > 1 and message[1].isdigit():
                        severity = "critical"
                    elif is_critical:
                        severity = "critical"
                    else:
                        severity = "warning"

                    timestamp = datetime.fromtimestamp(event["timestamp"] / 1000, tz=timezone.utc)

                    self.findings["control_plane_issues"].append(
                        {
                            "summary": f"Control plane error in {stream_name}",
                            "details": {
                                "log_stream": stream_name,
                                "timestamp": str(timestamp),
                                "message": message[:300],
                                "severity": severity,
                                "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html",
                                "finding_type": FindingType.HISTORICAL_EVENT,
                            },
                        }
                    )

            self.progress.info("Control plane log analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_control_plane_logs", "message": str(e)})
            self.progress.warning(f"Control plane log analysis failed: {e}")

    def analyze_pod_scheduling_failures(self):
        """
        Analyze pod scheduling failures from FailedScheduling events.

        Detects pods stuck in Pending state and categorizes the root cause:
        resource constraints, affinity rules, taints/tolerations, etc.

        Populates:
            self.findings['scheduling_failures']: Pods that failed to schedule.
        """
        self.progress.step("Analyzing pod scheduling failures...")

        try:
            # Get FailedScheduling events
            cmd = "kubectl get events --all-namespaces --field-selector reason=FailedScheduling -o json"
            if self.namespace:
                cmd = f"kubectl get events -n {self.namespace} --field-selector reason=FailedScheduling -o json"

            output = self.safe_kubectl_call(cmd)
            if not output:
                self.progress.info("No scheduling failures found")
                return

            events = json.loads(output)

            # Apply date filtering
            events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

            for event in events.get("items", []):
                pod = event["involvedObject"].get("name", "Unknown")
                namespace = event["metadata"]["namespace"]
                message = event.get("message", "N/A")
                timestamp = event.get("lastTimestamp", event.get("eventTime", "Unknown"))

                # Categorize scheduling failure reason
                reason_category = "unknown"
                if "insufficient" in message.lower():
                    if "cpu" in message.lower():
                        reason_category = "insufficient CPU"
                    elif "memory" in message.lower():
                        reason_category = "insufficient memory"
                    elif "pods" in message.lower():
                        reason_category = "max pods per node reached"
                elif "node selector" in message.lower():
                    reason_category = "node selector mismatch"
                elif "taint" in message.lower() or "toleration" in message.lower():
                    reason_category = "taints/tolerations"
                elif "affinity" in message.lower():
                    reason_category = "affinity/anti-affinity rules"
                elif "volume" in message.lower():
                    reason_category = "volume zone constraints"

                self.findings["scheduling_failures"].append(
                    {
                        "summary": f"Pod {namespace}/{pod} failed to schedule: {reason_category}",
                        "details": {
                            "pod": pod,
                            "namespace": namespace,
                            "timestamp": timestamp,
                            "reason_category": reason_category,
                            "message": message,
                            "finding_type": FindingType.HISTORICAL_EVENT,
                        },
                    }
                )

            self.progress.info(
                f"Found {len(events.get('items', []))} scheduling failures in date range"
            )

        except Exception as e:
            self.errors.append({"step": "analyze_pod_scheduling_failures", "message": str(e)})
            self.progress.warning(f"Scheduling failure analysis failed: {e}")

    def analyze_network_issues(self):
        """
        Analyze network-related issues from kubectl events.

        Detects CNI errors, pod network failures, and connectivity issues
        by examining FailedCreatePodSandBox, FailedSync, and NetworkNotReady events.

        Populates:
            self.findings['network_issues']: Network-related failures.
        """
        self.progress.step("Analyzing network issues...")

        try:
            # Look for network-related events
            network_event_reasons = [
                "FailedCreatePodSandBox",
                "FailedSync",
                "NetworkNotReady",
            ]

            for reason in network_event_reasons:
                cmd = (
                    f"kubectl get events --all-namespaces --field-selector reason={reason} -o json"
                )
                if self.namespace:
                    cmd = f"kubectl get events -n {self.namespace} --field-selector reason={reason} -o json"

                output = self.safe_kubectl_call(cmd)
                if not output:
                    continue

                events = json.loads(output)

                # Apply date filtering
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                for event in events.get("items", []):
                    obj_name = event["involvedObject"].get("name", "Unknown")
                    namespace = event["metadata"]["namespace"]
                    message = event.get("message", "N/A")
                    timestamp = event.get("lastTimestamp", event.get("eventTime", "Unknown"))

                    self.findings["network_issues"].append(
                        {
                            "summary": f"Network issue for {namespace}/{obj_name}: {reason}",
                            "details": {
                                "object": obj_name,
                                "namespace": namespace,
                                "timestamp": timestamp,
                                "reason": reason,
                                "message": message,
                                "finding_type": FindingType.HISTORICAL_EVENT,
                            },
                        }
                    )

            # Check CoreDNS health
            cmd = "kubectl get pods -n kube-system -l k8s-app=kube-dns -o json"
            output = self.safe_kubectl_call(cmd)
            if output:
                pods = json.loads(output)
                for pod in pods.get("items", []):
                    pod_name = pod["metadata"]["name"]
                    phase = pod["status"].get("phase", "Unknown")

                    if phase != "Running":
                        self.findings["dns_issues"].append(
                            {
                                "summary": f"CoreDNS pod {pod_name} is not Running (status: {phase})",
                                "details": {
                                    "pod": pod_name,
                                    "namespace": "kube-system",
                                    "status": phase,
                                    "finding_type": FindingType.CURRENT_STATE,
                                },
                            }
                        )

            self.progress.info("Network issue analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_network_issues", "message": str(e)})
            self.progress.warning(f"Network issue analysis failed: {e}")

    def analyze_rbac_issues(self):
        """
        Analyze RBAC and authorization failures.

        Detects permission denied errors from control plane logs and events
        including Forbidden, Unauthorized, and AccessDenied patterns.

        Populates:
            self.findings['rbac_issues']: Authorization failures.
        """
        self.progress.step("Analyzing RBAC and authorization issues...")

        try:
            # Look for FailedMount events (often RBAC-related)
            cmd = "kubectl get events --all-namespaces --field-selector reason=FailedMount -o json"
            if self.namespace:
                cmd = f"kubectl get events -n {self.namespace} --field-selector reason=FailedMount -o json"

            output = self.safe_kubectl_call(cmd)
            if output:
                events = json.loads(output)

                # Apply date filtering
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                for event in events.get("items", []):
                    message = event.get("message", "")

                    if (
                        "permission" in message.lower()
                        or "forbidden" in message.lower()
                        or "unauthorized" in message.lower()
                    ):
                        pod = event["involvedObject"].get("name", "Unknown")
                        namespace = event["metadata"]["namespace"]
                        timestamp = event.get("lastTimestamp", event.get("eventTime", "Unknown"))

                        self.findings["rbac_issues"].append(
                            {
                                "summary": f"RBAC/Authorization issue for {namespace}/{pod}",
                                "details": {
                                    "pod": pod,
                                    "namespace": namespace,
                                    "timestamp": timestamp,
                                    "message": message,
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                },
                            }
                        )

            self.progress.info("RBAC analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_rbac_issues", "message": str(e)})
            self.progress.warning(f"RBAC analysis failed: {e}")

    def analyze_pvc_issues(self):
        """
        Analyze Persistent Volume Claim and Persistent Volume issues.

        Detects pending PVCs, volume attachment failures, and Released/Failed PVs
        that may be blocking workloads.

        Populates:
            self.findings['pvc_issues']: Storage-related problems.
        """
        self.progress.step("Analyzing PVC and storage issues...")

        try:
            cmd = "kubectl get pvc --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get pvc -n {self.namespace} -o json"

            output = self.safe_kubectl_call(cmd)
            if not output:
                self.progress.info("No PVCs found or kubectl command failed")
            else:
                pvcs = json.loads(output)

                for pvc in pvcs.get("items", []):
                    pvc_name = pvc["metadata"]["name"]
                    namespace = pvc["metadata"]["namespace"]
                    phase = pvc["status"].get("phase", "Unknown")

                    if phase != "Bound":
                        storage_class = pvc["spec"].get("storageClassName", "N/A")
                        requested_storage = pvc["spec"]["resources"]["requests"].get(
                            "storage", "N/A"
                        )

                        diagnostic_steps = [
                            f"kubectl describe pvc {pvc_name} -n {namespace}",
                            "Check Events section for provisioning failure reason",
                        ]

                        if phase == "Pending":
                            diagnostic_steps.extend(
                                [
                                    "Verify StorageClass exists: kubectl get storageclass",
                                    "Check EBS CSI driver: kubectl get pods -n kube-system -l app=ebs-csi-controller",
                                    "Verify AZ constraints match available nodes",
                                ]
                            )

                        self.findings["pvc_issues"].append(
                            {
                                "summary": f"PVC {namespace}/{pvc_name} is not Bound (status: {phase})",
                                "details": {
                                    "pvc": pvc_name,
                                    "namespace": namespace,
                                    "status": phase,
                                    "storage_class": storage_class,
                                    "requested_storage": requested_storage,
                                    "severity": "warning" if phase == "Pending" else "critical",
                                    "diagnostic_steps": diagnostic_steps,
                                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/ebs-csi.html",
                                    "finding_type": FindingType.CURRENT_STATE,
                                },
                            }
                        )

            try:
                cmd = "kubectl get pv -o json"
                output = self.safe_kubectl_call(cmd)

                if output:
                    pvs = json.loads(output)
                    released_pvs = []
                    failed_pvs = []
                    available_pvs = []

                    for pv in pvs.get("items", []):
                        pv_name = pv["metadata"]["name"]
                        phase = pv["status"].get("phase", "Unknown")
                        reclaim_policy = pv["spec"].get("persistentVolumeReclaimPolicy", "Unknown")
                        storage_class = pv["spec"].get("storageClassName", "N/A")
                        capacity = pv["spec"].get("capacity", {}).get("storage", "Unknown")

                        if phase == "Released":
                            released_pvs.append(
                                {
                                    "name": pv_name,
                                    "reclaim_policy": reclaim_policy,
                                    "storage_class": storage_class,
                                    "capacity": capacity,
                                }
                            )
                        elif phase == "Failed":
                            failed_pvs.append(
                                {
                                    "name": pv_name,
                                    "reclaim_policy": reclaim_policy,
                                    "storage_class": storage_class,
                                    "capacity": capacity,
                                }
                            )
                        elif phase == "Available":
                            available_pvs.append(
                                {
                                    "name": pv_name,
                                    "storage_class": storage_class,
                                    "capacity": capacity,
                                }
                            )

                    if released_pvs:
                        for pv_info in released_pvs:
                            self.findings["pvc_issues"].append(
                                {
                                    "summary": f"PV {pv_info['name']} is in Released state (claim deleted, PV not reclaimed)",
                                    "details": {
                                        "pv": pv_info["name"],
                                        "status": "Released",
                                        "reclaim_policy": pv_info["reclaim_policy"],
                                        "storage_class": pv_info["storage_class"],
                                        "capacity": pv_info["capacity"],
                                        "severity": "warning",
                                        "impact": "PV is not available for new claims - storage is orphaned",
                                        "diagnostic_steps": [
                                            f"kubectl describe pv {pv_info['name']}",
                                            f'Manual cleanup: kubectl patch pv {pv_info["name"]} -p \'{{"spec":{{"claimRef": null}}}}\'',
                                            "Then create a new PVC to bind to it, or delete the PV",
                                        ],
                                        "aws_doc": "https://kubernetes.io/docs/concepts/storage/persistent-volumes/#release",
                                    },
                                }
                            )

                    if failed_pvs:
                        for pv_info in failed_pvs:
                            self.findings["pvc_issues"].append(
                                {
                                    "summary": f"PV {pv_info['name']} is in Failed state",
                                    "details": {
                                        "pv": pv_info["name"],
                                        "status": "Failed",
                                        "reclaim_policy": pv_info["reclaim_policy"],
                                        "storage_class": pv_info["storage_class"],
                                        "capacity": pv_info["capacity"],
                                        "severity": "critical",
                                        "impact": "PV has failed and cannot be used - may require manual intervention",
                                        "diagnostic_steps": [
                                            f"kubectl describe pv {pv_info['name']}",
                                            "Check Events for failure reason",
                                            "If underlying EBS volume is corrupted, may need to delete PV and recreate",
                                            f"kubectl delete pv {pv_info['name']} (after confirming EBS volume status in AWS Console)",
                                        ],
                                        "aws_doc": "https://kubernetes.io/docs/concepts/storage/persistent-volumes/#phase",
                                    },
                                }
                            )

                    if len(available_pvs) > 10:
                        self.findings["pvc_issues"].append(
                            {
                                "summary": f"{len(available_pvs)} PVs in Available state (no bound claim)",
                                "details": {
                                    "count": len(available_pvs),
                                    "examples": [pv["name"] for pv in available_pvs[:5]],
                                    "severity": "info",
                                    "impact": "Available PVs are not being used - check if orphaned",
                                    "recommendation": "Review if these PVs are needed or should be cleaned up",
                                },
                            }
                        )

            except Exception:
                pass

            try:
                cmd = "kubectl get events --all-namespaces --field-selector reason=ProvisioningFailed -o json"
                output = self.safe_kubectl_call(cmd)

                if output:
                    events = json.loads(output)
                    events = self.filter_kubectl_events_by_date(
                        events, self.start_date, self.end_date
                    )

                    for event in events.get("items", []):
                        pvc_name = event["involvedObject"].get("name", "Unknown")
                        namespace = event["metadata"]["namespace"]
                        message = event.get("message", "")
                        timestamp = event.get("lastTimestamp", event.get("eventTime", "Unknown"))

                        self.findings["pvc_issues"].append(
                            {
                                "summary": f"PVC provisioning failed: {namespace}/{pvc_name}",
                                "details": {
                                    "pvc": pvc_name,
                                    "namespace": namespace,
                                    "reason": "ProvisioningFailed",
                                    "message": message[:300],
                                    "timestamp": str(timestamp),
                                    "severity": "warning",
                                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/ebs-csi.html",
                                },
                            }
                        )
            except Exception:
                pass

            try:
                cmd = "kubectl get events --all-namespaces --field-selector reason=VolumeResizeFailed -o json"
                output = self.safe_kubectl_call(cmd)

                if output:
                    events = json.loads(output)
                    events = self.filter_kubectl_events_by_date(
                        events, self.start_date, self.end_date
                    )

                    for event in events.get("items", []):
                        pvc_name = event["involvedObject"].get("name", "Unknown")
                        namespace = event["metadata"]["namespace"]
                        message = event.get("message", "")

                        self.findings["pvc_issues"].append(
                            {
                                "summary": f"PVC resize failed: {namespace}/{pvc_name}",
                                "details": {
                                    "pvc": pvc_name,
                                    "namespace": namespace,
                                    "reason": "VolumeResizeFailed",
                                    "message": message[:300],
                                    "severity": "warning",
                                    "recommendation": "Check if storage class supports volume expansion",
                                    "aws_doc": "https://kubernetes.io/blog/2018/07/12/resizing-persistent-volumes-using-kubernetes/",
                                },
                            }
                        )
            except Exception:
                pass

            self.progress.info("PVC/PV analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_pvc_issues", "message": str(e)})
            self.progress.warning(f"PVC analysis failed: {e}")

    def analyze_image_pull_failures(self):
        """
        Analyze image pull failures from kubectl events.

        Detects ImagePullBackOff and ErrImagePull events to identify
        container registry, authentication, or network issues.

        Populates:
            self.findings['image_pull_failures']: Image pull errors.
        """
        self.progress.step("Analyzing image pull failures...")

        try:
            # Look for image pull failure events
            image_pull_reasons = ["Failed", "BackOff", "ErrImagePull"]

            for reason in image_pull_reasons:
                cmd = (
                    f"kubectl get events --all-namespaces --field-selector reason={reason} -o json"
                )
                if self.namespace:
                    cmd = f"kubectl get events -n {self.namespace} --field-selector reason={reason} -o json"

                output = self.safe_kubectl_call(cmd)
                if not output:
                    continue

                events = json.loads(output)

                # Apply date filtering
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                for event in events.get("items", []):
                    message = event.get("message", "")

                    # Filter for image-related errors
                    if (
                        "image" in message.lower()
                        or "pull" in message.lower()
                        or "registry" in message.lower()
                    ):
                        pod = event["involvedObject"].get("name", "Unknown")
                        namespace = event["metadata"]["namespace"]
                        timestamp = event.get("lastTimestamp", event.get("eventTime", "Unknown"))

                        # Categorize failure reason
                        failure_category = "unknown"
                        if "not found" in message.lower() or "404" in message:
                            failure_category = "image not found"
                        elif (
                            "unauthorized" in message.lower()
                            or "401" in message
                            or "authentication" in message.lower()
                        ):
                            failure_category = "authentication failed"
                        elif (
                            "rate limit" in message.lower()
                            or "too many requests" in message.lower()
                        ):
                            failure_category = "registry rate limiting"
                        elif "timeout" in message.lower():
                            failure_category = "registry timeout"

                        self.findings["image_pull_failures"].append(
                            {
                                "summary": f"Image pull failure for {namespace}/{pod}: {failure_category}",
                                "details": {
                                    "pod": pod,
                                    "namespace": namespace,
                                    "timestamp": timestamp,
                                    "category": failure_category,
                                    "message": message,
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                },
                            }
                        )

            self.progress.info("Image pull failure analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_image_pull_failures", "message": str(e)})
            self.progress.warning(f"Image pull failure analysis failed: {e}")

    def check_eks_addons(self):
        """
        Check EKS managed addon health status.

        Verifies the health of VPC-CNI, CoreDNS, kube-proxy, and other
        EKS managed addons by querying the EKS API.

        Populates:
            self.findings['addon_issues']: Addon health problems.
        """
        self.progress.step("Checking EKS addon health...")

        try:
            success, response = self.safe_api_call(
                self.eks_client.list_addons, clusterName=self.cluster_name
            )

            if not success:
                self.progress.warning(f"Failed to list addons: {response}")
                return

            addons = response.get("addons", [])

            if not addons:
                self.progress.info("No EKS addons found")
                return

            for addon_name in addons:
                success, addon_info = self.safe_api_call(
                    self.eks_client.describe_addon,
                    clusterName=self.cluster_name,
                    addonName=addon_name,
                )

                if not success:
                    continue

                addon = addon_info.get("addon", {})
                status = addon.get("status", "Unknown")
                health = addon.get("health", {})
                health_issues = health.get("issues", [])

                if status != "ACTIVE" or health_issues:
                    self.findings["addon_issues"].append(
                        {
                            "summary": f"EKS addon {addon_name} is unhealthy (status: {status})",
                            "details": {
                                "addon": addon_name,
                                "status": status,
                                "version": addon.get("addonVersion", "N/A"),
                                "health_issues": [
                                    issue.get("message", "N/A") for issue in health_issues
                                ],
                                "finding_type": FindingType.CURRENT_STATE,
                            },
                        }
                    )

            self.progress.info(f"Checked {len(addons)} EKS addons")

        except Exception as e:
            self.errors.append({"step": "check_eks_addons", "message": str(e)})
            self.progress.warning(f"EKS addon check failed: {e}")

    def analyze_resource_quotas(self):
        """
        Analyze namespace resource quotas
        Detects quota exceeded errors
        """
        self.progress.step("Analyzing resource quotas...")

        try:
            cmd = "kubectl get resourcequotas --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get resourcequotas -n {self.namespace} -o json"

            output = self.safe_kubectl_call(cmd)
            if not output:
                self.progress.info("No resource quotas found")
                return

            quotas = json.loads(output)

            for quota in quotas.get("items", []):
                quota_name = quota["metadata"]["name"]
                namespace = quota["metadata"]["namespace"]
                status = quota.get("status", {})

                hard = status.get("hard", {})
                used = status.get("used", {})

                # Check if any resource is at or near quota
                for resource, hard_limit in hard.items():
                    used_amount = used.get(resource, "0")

                    # Convert to numbers for comparison (handle units like "10Gi", "1000m")
                    try:
                        # Simple numeric comparison (won't handle all cases perfectly)
                        if (
                            str(hard_limit)
                            .replace("Gi", "")
                            .replace("Mi", "")
                            .replace("m", "")
                            .isdigit()
                            and str(used_amount)
                            .replace("Gi", "")
                            .replace("Mi", "")
                            .replace("m", "")
                            .isdigit()
                        ):
                            hard_num = float(
                                str(hard_limit).replace("Gi", "").replace("Mi", "").replace("m", "")
                            )
                            used_num = float(
                                str(used_amount)
                                .replace("Gi", "")
                                .replace("Mi", "")
                                .replace("m", "")
                            )

                            if used_num >= (hard_num * 0.9):
                                self.findings["resource_quota_exceeded"].append(
                                    {
                                        "summary": f"Resource quota near limit in {namespace}: {resource}",
                                        "details": {
                                            "quota": quota_name,
                                            "namespace": namespace,
                                            "resource": resource,
                                            "used": used_amount,
                                            "hard_limit": hard_limit,
                                            "utilization": f"{(used_num / hard_num * 100):.1f}%",
                                            "finding_type": FindingType.CURRENT_STATE,
                                        },
                                    }
                                )
                    except (ValueError, ZeroDivisionError):
                        # Skip if conversion fails
                        pass

            self.progress.info("Resource quota analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_resource_quotas", "message": str(e)})
            self.progress.warning(f"Resource quota analysis failed: {e}")

    def analyze_pod_health_deep(self):
        """
        Deep analysis of pod health issues using knowledge base
        Detects CrashLoopBackOff, CreateContainerConfigError, and other issues
        """
        self.progress.step("Performing deep pod health analysis...")

        try:
            cmd = "kubectl get pods --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get pods -n {self.namespace} -o json"

            output = self.safe_kubectl_call(cmd)
            if not output:
                return

            pods = json.loads(output)

            for pod in pods.get("items", []):
                pod_name = pod["metadata"]["name"]
                namespace = pod["metadata"]["namespace"]
                status = pod.get("status", {})
                phase = status.get("phase", "Unknown")

                # Check container statuses
                for container_status in status.get("containerStatuses", []):
                    container_name = container_status.get("name", "Unknown")
                    state = container_status.get("state", {})
                    restart_count = container_status.get("restartCount", 0)

                    # Detect CrashLoopBackOff
                    waiting = state.get("waiting", {})
                    if waiting:
                        reason = waiting.get("reason", "")
                        message = waiting.get("message", "")

                        if reason == "CrashLoopBackOff":
                            self.findings["pod_errors"].append(
                                {
                                    "summary": f"Pod {namespace}/{pod_name} container {container_name} in CrashLoopBackOff",
                                    "details": {
                                        "pod": pod_name,
                                        "namespace": namespace,
                                        "container": container_name,
                                        "reason": reason,
                                        "restart_count": restart_count,
                                        "message": message[:200] if message else "N/A",
                                        "root_causes": EKS_ISSUE_PATTERNS["pod_issues"][
                                            "CrashLoopBackOff"
                                        ]["root_causes"],
                                        "severity": "critical",
                                        "aws_doc": EKS_ISSUE_PATTERNS["pod_issues"][
                                            "CrashLoopBackOff"
                                        ]["aws_doc"],
                                        "finding_type": FindingType.CURRENT_STATE,
                                    },
                                }
                            )
                        elif reason in ["ImagePullBackOff", "ErrImagePull"]:
                            self.findings["image_pull_failures"].append(
                                {
                                    "summary": f"Pod {namespace}/{pod_name} container {container_name} image pull failed",
                                    "details": {
                                        "pod": pod_name,
                                        "namespace": namespace,
                                        "container": container_name,
                                        "reason": reason,
                                        "message": message[:200] if message else "N/A",
                                        "root_causes": EKS_ISSUE_PATTERNS["pod_issues"][
                                            "ImagePullBackOff"
                                        ]["root_causes"],
                                        "severity": "critical",
                                        "aws_doc": EKS_ISSUE_PATTERNS["pod_issues"][
                                            "ImagePullBackOff"
                                        ]["aws_doc"],
                                        "finding_type": FindingType.CURRENT_STATE,
                                    },
                                }
                            )
                        elif reason == "CreateContainerConfigError":
                            self.findings["pod_errors"].append(
                                {
                                    "summary": f"Pod {namespace}/{pod_name} container {container_name} config error",
                                    "details": {
                                        "pod": pod_name,
                                        "namespace": namespace,
                                        "container": container_name,
                                        "reason": reason,
                                        "message": message[:200] if message else "N/A",
                                        "root_causes": EKS_ISSUE_PATTERNS["pod_issues"][
                                            "CreateContainerConfigError"
                                        ]["root_causes"],
                                        "severity": "critical",
                                        "aws_doc": EKS_ISSUE_PATTERNS["pod_issues"][
                                            "CreateContainerConfigError"
                                        ]["aws_doc"],
                                        "finding_type": FindingType.CURRENT_STATE,
                                    },
                                }
                            )

                    # Check for high restart count
                    if restart_count >= Thresholds.RESTART_CRITICAL:
                        self.findings["pod_errors"].append(
                            {
                                "summary": f"Pod {namespace}/{pod_name} container {container_name} has high restart count: {restart_count}",
                                "details": {
                                    "pod": pod_name,
                                    "namespace": namespace,
                                    "container": container_name,
                                    "restart_count": restart_count,
                                    "severity": "critical",
                                    "finding_type": FindingType.CURRENT_STATE,
                                },
                            }
                        )
                    elif restart_count >= Thresholds.RESTART_WARNING:
                        self.findings["pod_errors"].append(
                            {
                                "summary": f"Pod {namespace}/{pod_name} container {container_name} restarted {restart_count} times",
                                "details": {
                                    "pod": pod_name,
                                    "namespace": namespace,
                                    "container": container_name,
                                    "restart_count": restart_count,
                                    "severity": "warning",
                                    "finding_type": FindingType.CURRENT_STATE,
                                },
                            }
                        )

                # Check init container statuses (Catalog 3.5: Init Container Failure)
                init_container_statuses = status.get("initContainerStatuses", [])
                if init_container_statuses:
                    for idx, init_status in enumerate(init_container_statuses):
                        init_name = init_status.get("name", "Unknown")
                        state = init_status.get("state", {})

                        waiting = state.get("waiting", {})
                        terminated = state.get("terminated", {})

                        if waiting:
                            reason = waiting.get("reason", "")
                            message = waiting.get("message", "")

                            if reason in [
                                "ImagePullBackOff",
                                "ErrImagePull",
                                "CrashLoopBackOff",
                                "RunContainerError",
                                "CreateContainerConfigError",
                            ]:
                                failure_category = "unknown"
                                diagnostic_steps = []

                                if reason in ["ImagePullBackOff", "ErrImagePull"]:
                                    failure_category = "image_pull"
                                    diagnostic_steps = [
                                        f"kubectl describe pod {pod_name} -n {namespace}",
                                        "Verify image exists in registry",
                                        "Check imagePullSecrets configuration",
                                        "Verify node IAM role has ECR permissions",
                                    ]
                                elif reason == "CrashLoopBackOff":
                                    failure_category = "init_crash"
                                    diagnostic_steps = [
                                        f"kubectl logs {pod_name} -n {namespace} -c {init_name} --previous",
                                        "Check init container script for errors",
                                        "Verify init container has required permissions",
                                        "Check for missing dependencies",
                                    ]
                                elif reason == "CreateContainerConfigError":
                                    failure_category = "config_error"
                                    diagnostic_steps = [
                                        f"kubectl describe pod {pod_name} -n {namespace}",
                                        "Check for missing ConfigMaps or Secrets",
                                        "Verify volume mounts exist",
                                    ]

                                self.findings["pod_errors"].append(
                                    {
                                        "summary": f"Pod {namespace}/{pod_name} init container {init_name} failed: {reason}",
                                        "details": {
                                            "pod": pod_name,
                                            "namespace": namespace,
                                            "init_container": init_name,
                                            "init_index": idx,
                                            "container_type": "init",
                                            "reason": reason,
                                            "failure_category": failure_category,
                                            "message": message[:200] if message else "N/A",
                                            "severity": "critical",
                                            "diagnostic_steps": diagnostic_steps,
                                            "impact": "Pod cannot start until init containers complete successfully",
                                            "aws_doc": "https://kubernetes.io/docs/concepts/workloads/pods/init-containers/",
                                        },
                                    }
                                )

                        elif terminated:
                            exit_code = terminated.get("exitCode", 0)
                            reason = terminated.get("reason", "")

                            if exit_code != 0:
                                failure_category = "init_exit_error"
                                diagnostic_steps = [
                                    f"kubectl logs {pod_name} -n {namespace} -c {init_name}",
                                    f"Exit code {exit_code} indicates failure",
                                ]

                                if exit_code == 137:
                                    failure_category = "init_oom_killed"
                                    diagnostic_steps.extend(
                                        [
                                            "Init container was OOMKilled",
                                            "Increase init container memory limits",
                                        ]
                                    )
                                elif exit_code == 1:
                                    diagnostic_steps.extend(
                                        [
                                            "Check init container command/script for errors",
                                            "Verify all dependencies are available",
                                        ]
                                    )
                                elif exit_code == 126:
                                    diagnostic_steps.append(
                                        "Command permission denied or not executable"
                                    )
                                elif exit_code == 127:
                                    diagnostic_steps.append("Command not found")

                                self.findings["pod_errors"].append(
                                    {
                                        "summary": f"Pod {namespace}/{pod_name} init container {init_name} exited with code {exit_code}",
                                        "details": {
                                            "pod": pod_name,
                                            "namespace": namespace,
                                            "init_container": init_name,
                                            "container_type": "init",
                                            "exit_code": exit_code,
                                            "reason": reason,
                                            "failure_category": failure_category,
                                            "message": terminated.get("message", "")[:200],
                                            "severity": "critical",
                                            "diagnostic_steps": diagnostic_steps,
                                            "aws_doc": "https://kubernetes.io/docs/concepts/workloads/pods/init-containers/",
                                        },
                                    }
                                )

                # Check for pods stuck in Init state (Init:0/N, Init:Error, etc.)
                if phase == "Pending":
                    conditions = status.get("conditions", [])
                    for cond in conditions:
                        if cond.get("type") == "PodScheduled" and cond.get("status") == "True":
                            pass
                        elif cond.get("type") == "Initialized" and cond.get("status") == "False":
                            message = cond.get("message", "")
                            reason = cond.get("reason", "")

                            if "init" in message.lower() or "init" in reason.lower():
                                self.findings["pod_errors"].append(
                                    {
                                        "summary": f"Pod {namespace}/{pod_name} stuck in Init phase",
                                        "details": {
                                            "pod": pod_name,
                                            "namespace": namespace,
                                            "phase": phase,
                                            "reason": reason,
                                            "message": message[:300],
                                            "severity": "warning",
                                            "diagnostic_steps": [
                                                f"kubectl describe pod {pod_name} -n {namespace}",
                                                "Check init container statuses and logs",
                                                f"kubectl logs {pod_name} -n {namespace} -c <init-container-name>",
                                                "Verify dependencies are available",
                                            ],
                                            "aws_doc": "https://kubernetes.io/docs/concepts/workloads/pods/init-containers/",
                                        },
                                    }
                                )

            self.progress.info("Deep pod health analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_pod_health_deep", "message": str(e)})
            self.progress.warning(f"Deep pod health analysis failed: {e}")

    def analyze_vpc_cni_health(self):
        """
        Analyze VPC CNI health and IP address allocation
        """
        self.progress.step("Analyzing VPC CNI health...")

        try:
            # Check aws-node daemonset
            cmd = "kubectl get daemonset aws-node -n kube-system -o json"
            output = self.safe_kubectl_call(cmd)

            if output:
                ds = json.loads(output)
                status = ds.get("status", {})
                desired = status.get("desiredNumberScheduled", 0)
                current = status.get("currentNumberScheduled", 0)
                ready = status.get("numberReady", 0)

                if ready < desired:
                    self.findings["network_issues"].append(
                        {
                            "summary": f"VPC CNI aws-node DaemonSet not healthy: {ready}/{desired} ready",
                            "details": {
                                "daemonset": "aws-node",
                                "namespace": "kube-system",
                                "desired": desired,
                                "current": current,
                                "ready": ready,
                                "root_causes": EKS_ISSUE_PATTERNS["network_issues"]["CNINotReady"][
                                    "root_causes"
                                ],
                                "severity": "critical",
                                "aws_doc": EKS_ISSUE_PATTERNS["network_issues"]["CNINotReady"][
                                    "aws_doc"
                                ],
                                "finding_type": FindingType.CURRENT_STATE,
                            },
                        }
                    )

            # Check for IP allocation errors in events
            cmd = "kubectl get events --all-namespaces --field-selector reason=Failed -o json"
            output = self.safe_kubectl_call(cmd)

            if output:
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                ip_exhaustion_patterns = EKS_ISSUE_PATTERNS["network_issues"]["IPExhaustion"][
                    "detection"
                ]["patterns"]

                for event in events.get("items", []):
                    message = event.get("message", "").lower()
                    if any(pattern in message for pattern in ip_exhaustion_patterns):
                        involved = event.get("involvedObject", {})
                        self.findings["network_issues"].append(
                            {
                                "summary": f"IP address exhaustion detected in {involved.get('namespace', 'unknown')}",
                                "details": {
                                    "namespace": involved.get("namespace", "unknown"),
                                    "object": involved.get("name", "unknown"),
                                    "message": event.get("message", "N/A")[:200],
                                    "root_causes": EKS_ISSUE_PATTERNS["network_issues"][
                                        "IPExhaustion"
                                    ]["root_causes"],
                                    "severity": "critical",
                                    "aws_doc": EKS_ISSUE_PATTERNS["network_issues"]["IPExhaustion"][
                                        "aws_doc"
                                    ],
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                },
                            }
                        )

            self.progress.info("VPC CNI health analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_vpc_cni_health", "message": str(e)})
            self.progress.warning(f"VPC CNI health analysis failed: {e}")

    def analyze_coredns_health(self):
        """
        Analyze CoreDNS health and configuration
        """
        self.progress.step("Analyzing CoreDNS health...")

        try:
            # Check CoreDNS deployment
            cmd = "kubectl get deployment coredns -n kube-system -o json"
            output = self.safe_kubectl_call(cmd)

            if output:
                deployment = json.loads(output)
                status = deployment.get("status", {})
                replicas = status.get("replicas", 0)
                ready = status.get("readyReplicas", 0)
                unavailable = status.get("unavailableReplicas", 0)

                if ready < replicas or unavailable > 0:
                    self.findings["dns_issues"].append(
                        {
                            "summary": f"CoreDNS deployment unhealthy: {ready}/{replicas} ready",
                            "details": {
                                "deployment": "coredns",
                                "namespace": "kube-system",
                                "replicas": replicas,
                                "ready": ready,
                                "unavailable": unavailable,
                                "severity": "critical" if ready == 0 else "warning",
                                "finding_type": FindingType.CURRENT_STATE,
                            },
                        }
                    )

            # Check for DNS-related errors in events
            cmd = "kubectl get events --all-namespaces -o json"
            output = self.safe_kubectl_call(cmd)

            if output:
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                dns_patterns = [
                    "dns",
                    "name resolution",
                    "coredns",
                    "nslookup",
                    "nxdomain",
                ]

                for event in events.get("items", []):
                    message = event.get("message", "").lower()
                    reason = event.get("reason", "")
                    if any(pattern in message for pattern in dns_patterns) or reason in [
                        "DNSFetching",
                        "DNS_default",
                    ]:
                        involved = event.get("involvedObject", {})
                        self.findings["dns_issues"].append(
                            {
                                "summary": f"DNS issue detected in {involved.get('namespace', 'unknown')}/{involved.get('name', 'unknown')}",
                                "details": {
                                    "namespace": involved.get("namespace", "unknown"),
                                    "object": involved.get("name", "unknown"),
                                    "reason": reason,
                                    "message": event.get("message", "N/A")[:200],
                                    "root_causes": EKS_ISSUE_PATTERNS["network_issues"][
                                        "DNSResolutionFailure"
                                    ]["root_causes"],
                                    "severity": "warning",
                                    "aws_doc": EKS_ISSUE_PATTERNS["network_issues"][
                                        "DNSResolutionFailure"
                                    ]["aws_doc"],
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                },
                            }
                        )

            self.progress.info("CoreDNS health analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_coredns_health", "message": str(e)})
            self.progress.warning(f"CoreDNS health analysis failed: {e}")

    def analyze_iam_pod_identity(self):
        """
        Analyze IAM permissions and Pod Identity issues

        Catalog: EKS-Specific & Configuration Issues
        - IAM/RBAC Permission Errors
        - CloudTrail correlation for AssumeRoleForPodIdentity failures
        """
        self.progress.step("Analyzing IAM and Pod Identity...")

        try:
            # Check for EKS Pod Identity Agent
            cmd = "kubectl get deployment eks-pod-identity-agent -n kube-system -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                deployment = json.loads(output)
                status = deployment.get("status", {})
                replicas = status.get("replicas", 0)
                ready = status.get("readyReplicas", 0)

                if ready < replicas:
                    self.findings["rbac_issues"].append(
                        {
                            "summary": "EKS Pod Identity Agent not fully healthy",
                            "details": {
                                "deployment": "eks-pod-identity-agent",
                                "namespace": "kube-system",
                                "replicas": replicas,
                                "ready": ready,
                                "severity": "warning",
                                "finding_type": FindingType.CURRENT_STATE,
                            },
                        }
                    )

            # Check for AccessDenied errors in events
            cmd = "kubectl get events --all-namespaces -o json"
            output = self.safe_kubectl_call(cmd)

            if output:
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                access_patterns = ["accessdenied", "unauthorized", "forbidden", "403"]

                for event in events.get("items", []):
                    message = event.get("message", "").lower()
                    reason = event.get("reason", "").lower()
                    if any(pattern in message or pattern in reason for pattern in access_patterns):
                        involved = event.get("involvedObject", {})
                        self.findings["rbac_issues"].append(
                            {
                                "summary": f"IAM/RBAC access denied in {involved.get('namespace', 'unknown')}/{involved.get('name', 'unknown')}",
                                "details": {
                                    "namespace": involved.get("namespace", "unknown"),
                                    "object": involved.get("name", "unknown"),
                                    "reason": event.get("reason", "N/A"),
                                    "message": event.get("message", "N/A")[:200],
                                    "root_causes": EKS_ISSUE_PATTERNS["iam_issues"]["AccessDenied"][
                                        "root_causes"
                                    ],
                                    "severity": "critical",
                                    "aws_doc": EKS_ISSUE_PATTERNS["iam_issues"]["AccessDenied"][
                                        "aws_doc"
                                    ],
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                },
                            }
                        )

            # CloudTrail correlation for IRSA/Pod Identity failures
            try:
                cloudtrail_client = self.session.client("cloudtrail", region_name=self.region)

                success, response = self.safe_api_call(
                    cloudtrail_client.lookup_events,
                    LookupAttributes=[
                        {"AttributeKey": "EventName", "AttributeValue": "AssumeRole"}
                    ],
                    StartTime=self.start_date,
                    EndTime=self.end_date,
                    MaxResults=50,
                )

                if success:
                    for event in response.get("Events", []):
                        event_name = event.get("EventName", "")
                        resources = event.get("Resources", [])
                        username = event.get("Username", "")

                        if event_name == "AssumeRole":
                            cloud_trail_event = event.get("CloudTrailEvent", "{}")
                            try:
                                ct_data = (
                                    json.loads(cloud_trail_event)
                                    if isinstance(cloud_trail_event, str)
                                    else cloud_trail_event
                                )
                                error_code = ct_data.get("errorCode", "")
                                error_message = ct_data.get("errorMessage", "")

                                if error_code in ["AccessDenied", "UnauthorizedAccess"]:
                                    role_arn = ""
                                    for res in resources:
                                        if res.get("ResourceType") == "AWS::IAM::Role":
                                            role_arn = res.get("ResourceName", "")

                                    self.findings["rbac_issues"].append(
                                        {
                                            "summary": f"CloudTrail: AssumeRole failed for {role_arn or 'unknown role'}",
                                            "details": {
                                                "event_name": event_name,
                                                "role_arn": role_arn,
                                                "username": username,
                                                "error_code": error_code,
                                                "error_message": error_message[:300]
                                                if error_message
                                                else "N/A",
                                                "event_time": str(
                                                    event.get("EventTime", "Unknown")
                                                ),
                                                "severity": "critical",
                                                "root_causes": [
                                                    "IAM role trust policy does not allow OIDC provider",
                                                    "Service account missing eks.amazonaws.com/role-arn annotation",
                                                    "Pod Identity agent not configured correctly",
                                                    "Node IAM role missing AssumeRoleForPodIdentity permission",
                                                ],
                                                "finding_type": FindingType.HISTORICAL_EVENT,
                                            },
                                        }
                                    )
                            except (json.JSONDecodeError, TypeError):
                                pass
            except Exception:
                self.progress.info("CloudTrail access not available for IAM correlation")

            # Check for AssumeRoleForPodIdentity events (EKS Pod Identity)
            try:
                cloudtrail_client = self.session.client("cloudtrail", region_name=self.region)

                success, response = self.safe_api_call(
                    cloudtrail_client.lookup_events,
                    LookupAttributes=[
                        {
                            "AttributeKey": "EventName",
                            "AttributeValue": "AssumeRoleForPodIdentity",
                        }
                    ],
                    StartTime=self.start_date,
                    EndTime=self.end_date,
                    MaxResults=50,
                )

                if success:
                    for event in response.get("Events", []):
                        cloud_trail_event = event.get("CloudTrailEvent", "{}")
                        try:
                            ct_data = (
                                json.loads(cloud_trail_event)
                                if isinstance(cloud_trail_event, str)
                                else cloud_trail_event
                            )
                            error_code = ct_data.get("errorCode", "")

                            if error_code:
                                username = event.get("Username", "")
                                self.findings["rbac_issues"].append(
                                    {
                                        "summary": f"CloudTrail: AssumeRoleForPodIdentity failed for {username}",
                                        "details": {
                                            "event_name": "AssumeRoleForPodIdentity",
                                            "username": username,
                                            "error_code": error_code,
                                            "error_message": ct_data.get("errorMessage", "N/A")[
                                                :300
                                            ],
                                            "event_time": str(event.get("EventTime", "Unknown")),
                                            "severity": "critical",
                                            "root_causes": [
                                                "EKS Pod Identity agent not running",
                                                "IAM role trust policy incorrect",
                                                "Pod Identity association not configured",
                                            ],
                                            "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/pod-identity.html",
                                        },
                                    }
                                )
                        except (json.JSONDecodeError, TypeError):
                            pass
            except Exception:
                pass

            self.progress.info("IAM and Pod Identity analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_iam_pod_identity", "message": str(e)})
            self.progress.warning(f"IAM and Pod Identity analysis failed: {e}")

    def _extract_timestamp(self, details):
        """Extract timestamp from finding details"""
        ts = details.get("timestamp") or details.get("lastTimestamp") or details.get("eventTime")
        if ts:
            try:
                if isinstance(ts, str):
                    if "T" in ts:
                        return date_parser.parse(ts)
            except Exception:
                pass
        return None

    def _get_node_from_pod(self, pod_details):
        """Extract node name from pod details if available"""
        return pod_details.get("node") or pod_details.get("nodeName")

    def correlate_findings(self):
        """
        Smart correlation of findings across data sources.

        Identifies root causes, timelines, and cascading failures by analyzing
        relationships between different finding categories.

        Correlation Rules:
            - node_pressure_cascade: Node Disk/Memory Pressure → Pod Evictions
            - cni_cascade: VPC CNI issues → NetworkNotReady events
            - oom_pattern: OOMKilled pods + Memory pressure
            - control_plane_impact: Critical control plane errors → Pod failures

        Modifies:
            self.correlations: Populated with identified correlations.
            self.timeline: Populated with chronological events.
            self.first_issue: Set to earliest detected issue.
        """
        self.progress.step("Performing smart correlation analysis...")

        correlations = []
        timeline_events = []

        # Build timeline from all findings
        for category, findings_list in self.findings.items():
            for finding in findings_list:
                ts = self._extract_timestamp(finding.get("details", {}))
                if ts:
                    timeline_events.append(
                        {
                            "timestamp": ts,
                            "category": category,
                            "summary": finding.get("summary", ""),
                            "details": finding.get("details", {}),
                        }
                    )

        # Sort by timestamp
        timeline_events.sort(key=lambda x: x["timestamp"])

        # Correlation Rule 1: Node Pressure → Pod Evictions
        if self.findings["memory_pressure"] or self.findings["disk_pressure"]:
            pressure_type = "memory" if self.findings["memory_pressure"] else "disk"
            affected_nodes = set()

            for finding in self.findings.get(f"{pressure_type}_pressure", []):
                node = finding.get("details", {}).get("node")
                if node:
                    affected_nodes.add(node)

            # Find evicted pods on those nodes
            evicted_on_nodes = []
            for finding in self.findings.get("pod_errors", []):
                details = finding.get("details", {})
                if "evict" in details.get("reason", "").lower():
                    node = self._get_node_from_pod(details)
                    if node in affected_nodes:
                        evicted_on_nodes.append(finding)

            if evicted_on_nodes:
                # Find earliest pressure event as root cause
                pressure_times = []
                for f in self.findings.get(f"{pressure_type}_pressure", []):
                    ts = self._extract_timestamp(f.get("details", {}))
                    if ts:
                        pressure_times.append(ts)

                root_cause_time = min(pressure_times) if pressure_times else None

                correlations.append(
                    {
                        "correlation_type": "node_pressure_cascade",
                        "severity": "critical",
                        "root_cause": f"Node {pressure_type} pressure detected",
                        "root_cause_time": str(root_cause_time) if root_cause_time else "Unknown",
                        "affected_components": {
                            "nodes_with_pressure": list(affected_nodes),
                            "evicted_pods_count": len(evicted_on_nodes),
                        },
                        "impact": f"{len(evicted_on_nodes)} pods evicted due to {pressure_type} pressure on {len(affected_nodes)} node(s)",
                        "recommendation": f"Address {pressure_type} pressure on affected nodes. Consider increasing node resources or configuring resource limits.",
                        "aws_doc": f"https://repost.aws/knowledge-center/eks-resolve-{pressure_type}-pressure",
                    }
                )

        # Correlation Rule 2: CNI Issues → Network Failures
        if self.findings["network_issues"]:
            cni_issues = [
                f
                for f in self.findings["network_issues"]
                if any(p in str(f.get("details", {})).lower() for p in ["cni", "aws-node", "ipamd"])
            ]

            network_failures = [
                f
                for f in self.findings["network_issues"]
                if "NetworkNotReady" in f.get("summary", "")
                or "network" in f.get("summary", "").lower()
            ]

            if cni_issues and network_failures:
                cni_times = []
                for f in cni_issues:
                    ts = self._extract_timestamp(f.get("details", {}))
                    if ts:
                        cni_times.append(ts)

                root_cause_time = min(cni_times) if cni_times else None

                correlations.append(
                    {
                        "correlation_type": "cni_cascade",
                        "severity": "critical",
                        "root_cause": "VPC CNI (aws-node) issues detected",
                        "root_cause_time": str(root_cause_time) if root_cause_time else "Unknown",
                        "affected_components": {
                            "cni_issues_count": len(cni_issues),
                            "network_failures_count": len(network_failures),
                        },
                        "impact": f"VPC CNI issues causing {len(network_failures)} network-related pod failures",
                        "recommendation": "Check VPC CNI health, IAM permissions, and subnet IP availability",
                        "aws_doc": "https://repost.aws/knowledge-center/eks-troubleshoot-vpc-cni-add-on",
                    }
                )

        # Correlation Rule 3: OOMKilled → Memory pressure or low limits
        if self.findings["oom_killed"]:
            oom_pods = self.findings["oom_killed"]
            oom_times = []

            for f in oom_pods:
                ts = self._extract_timestamp(f.get("details", {}))
                if ts:
                    oom_times.append(ts)

            # Check if there's also node memory pressure
            has_node_pressure = bool(self.findings.get("memory_pressure"))

            root_cause = "Pod memory limits too low"
            if has_node_pressure:
                root_cause = "Node memory pressure causing OOM kills"

            first_oom = min(oom_times) if oom_times else None

            correlations.append(
                {
                    "correlation_type": "oom_pattern",
                    "severity": "critical",
                    "root_cause": root_cause,
                    "root_cause_time": str(first_oom) if first_oom else "Unknown",
                    "affected_components": {
                        "oom_killed_pods": len(oom_pods),
                        "node_memory_pressure": has_node_pressure,
                    },
                    "impact": f"{len(oom_pods)} pods killed due to OOM",
                    "recommendation": "Review pod memory limits and requests. Check for memory leaks in applications.",
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/best-practices/windows-oom.html",
                }
            )

        # Correlation Rule 4: Control Plane Errors → API issues
        if self.findings["control_plane_issues"]:
            critical_cp = [
                f
                for f in self.findings["control_plane_issues"]
                if f.get("details", {}).get("severity") == "critical"
            ]

            if critical_cp:
                cp_times = []
                for f in critical_cp:
                    ts = self._extract_timestamp(f.get("details", {}))
                    if ts:
                        cp_times.append(ts)

                first_critical = min(cp_times) if cp_times else None

                # Check for related pod failures
                pod_failures = len(self.findings.get("pod_errors", []))

                correlations.append(
                    {
                        "correlation_type": "control_plane_impact",
                        "severity": "critical",
                        "root_cause": "Control plane errors detected",
                        "root_cause_time": str(first_critical) if first_critical else "Unknown",
                        "affected_components": {
                            "critical_control_plane_events": len(critical_cp),
                            "potential_pod_impact": pod_failures,
                        },
                        "impact": f"Control plane instability may have caused {pod_failures} pod-related issues",
                        "recommendation": "Review control plane logs for etcd or API server issues",
                        "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html",
                    }
                )

        # Correlation Rule 5: Image Pull Failures → Registry/Auth issues
        if self.findings["image_pull_failures"]:
            image_failures = self.findings["image_pull_failures"]
            ecr_failures = [
                f
                for f in image_failures
                if "ecr" in str(f.get("details", {})).lower()
                or ".ecr." in str(f.get("details", {})).lower()
            ]
            auth_failures = [
                f
                for f in image_failures
                if any(
                    p in str(f.get("details", {})).lower()
                    for p in ["auth", "credential", "unauthorized", "denied"]
                )
            ]

            root_cause = "Image pull issues detected"
            if auth_failures:
                root_cause = "Image registry authentication issues"
            elif ecr_failures:
                root_cause = "ECR connectivity or permissions issues"

            img_times = []
            for f in image_failures:
                ts = self._extract_timestamp(f.get("details", {}))
                if ts:
                    img_times.append(ts)

            first_failure = min(img_times) if img_times else None

            correlations.append(
                {
                    "correlation_type": "image_pull_pattern",
                    "severity": "high",
                    "root_cause": root_cause,
                    "root_cause_time": str(first_failure) if first_failure else "Unknown",
                    "affected_components": {
                        "total_image_failures": len(image_failures),
                        "ecr_related": len(ecr_failures),
                        "auth_related": len(auth_failures),
                    },
                    "impact": f"{len(image_failures)} pods failed to start due to image pull issues",
                    "recommendation": "Verify image exists, check registry credentials, and ensure network connectivity",
                    "aws_doc": "https://repost.aws/knowledge-center/eks-troubleshoot-kubernetes-pods",
                }
            )

        # Correlation Rule 6: Scheduling Failures → Resource constraints
        if self.findings["scheduling_failures"]:
            sched_failures = self.findings["scheduling_failures"]
            resource_failures = [
                f for f in sched_failures if "insufficient" in f.get("summary", "").lower()
            ]
            affinity_failures = [
                f for f in sched_failures if "affinity" in f.get("summary", "").lower()
            ]

            root_cause = "Pod scheduling constraints"
            if resource_failures:
                root_cause = "Insufficient cluster resources"
            elif affinity_failures:
                root_cause = "Affinity/anti-affinity constraints"

            sched_times = []
            for f in sched_failures:
                ts = self._extract_timestamp(f.get("details", {}))
                if ts:
                    sched_times.append(ts)

            first_failure = min(sched_times) if sched_times else None

            correlations.append(
                {
                    "correlation_type": "scheduling_pattern",
                    "severity": "warning",
                    "root_cause": root_cause,
                    "root_cause_time": str(first_failure) if first_failure else "Unknown",
                    "affected_components": {
                        "total_scheduling_failures": len(sched_failures),
                        "resource_related": len(resource_failures),
                        "affinity_related": len(affinity_failures),
                    },
                    "impact": f"{len(sched_failures)} pods stuck in Pending state",
                    "recommendation": "Review resource requests, node capacity, and scheduling constraints",
                    "aws_doc": "https://repost.aws/knowledge-center/eks-pod-scheduling-node-availability",
                }
            )

        # Correlation Rule 7: DNS Issues → CoreDNS health
        if self.findings["dns_issues"]:
            dns_failures = self.findings["dns_issues"]

            # Check if CoreDNS is also unhealthy
            coredns_issues = [f for f in dns_failures if "coredns" in f.get("summary", "").lower()]

            dns_times = []
            for f in dns_failures:
                ts = self._extract_timestamp(f.get("details", {}))
                if ts:
                    dns_times.append(ts)

            first_failure = min(dns_times) if dns_times else None

            correlations.append(
                {
                    "correlation_type": "dns_pattern",
                    "severity": "warning",
                    "root_cause": "CoreDNS or DNS resolution issues",
                    "root_cause_time": str(first_failure) if first_failure else "Unknown",
                    "affected_components": {
                        "dns_issues_count": len(dns_failures),
                        "coredns_related": len(coredns_issues),
                    },
                    "impact": f"{len(dns_failures)} DNS-related issues detected",
                    "recommendation": "Check CoreDNS health, scale replicas, and review DNS throttling",
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/coredns.html",
                }
            )

        # Store correlations
        if correlations:
            self.correlations = correlations

        # Build incident timeline
        if timeline_events:
            # Group events by hour for timeline
            timeline_summary = []
            current_hour = None
            hour_events = []

            for event in timeline_events[:50]:  # Limit to first 50 events
                event_hour = event["timestamp"].strftime("%Y-%m-%d %H:00")
                if current_hour != event_hour:
                    if hour_events:
                        timeline_summary.append(
                            {
                                "time_bucket": current_hour,
                                "event_count": len(hour_events),
                                "categories": list(set(e["category"] for e in hour_events)),
                                "severity": self._get_bucket_severity(hour_events),
                            }
                        )
                    current_hour = event_hour
                    hour_events = [event]
                else:
                    hour_events.append(event)

            if hour_events:
                timeline_summary.append(
                    {
                        "time_bucket": current_hour,
                        "event_count": len(hour_events),
                        "categories": list(set(e["category"] for e in hour_events)),
                        "severity": self._get_bucket_severity(hour_events),
                    }
                )

            self.timeline = timeline_summary

            # Find first occurrence (root cause candidate)
            if timeline_events:
                first_event = timeline_events[0]
                self.first_issue = {
                    "timestamp": str(first_event["timestamp"]),
                    "category": first_event["category"],
                    "summary": first_event["summary"],
                    "potential_root_cause": True,
                }

        self.progress.info(f"Correlation analysis complete: {len(correlations)} correlations found")

    def _get_bucket_severity(self, events):
        """Determine severity for a timeline bucket"""
        categories = [e["category"] for e in events]
        if any(c in CRITICAL_CATEGORIES for c in categories):
            return "critical"
        elif any("control_plane" in c or "node" in c for c in categories):
            return "warning"
        return "info"

    def analyze_cpu_throttling(self):
        """
        Analyze CPU throttling via CloudWatch Container Insights
        Detects containers hitting CPU limits
        """
        self.progress.step("Analyzing CPU throttling...")

        try:
            namespace = "ContainerInsights"
            metric_name = "container_cpu_usage_total"

            start_time_ms = int(self.start_date.timestamp() * 1000)
            end_time_ms = int(self.end_date.timestamp() * 1000)

            success, response = self.safe_api_call(
                self.cloudwatch_client.list_metrics,
                Namespace=namespace,
                MetricName=metric_name,
            )

            if not success or not response.get("Metrics"):
                self.progress.info("Container Insights CPU metrics not available")
                return

            # Get CPU utilization metrics
            queries = []
            for metric in response.get("Metrics", [])[:5]:
                dimensions = metric.get("Dimensions", [])
                dim_dict = {d["Name"]: d["Value"] for d in dimensions}

                if "ClusterName" in dim_dict and dim_dict.get("ClusterName") == self.cluster_name:
                    queries.append(
                        {
                            "Id": f"cpu_{len(queries)}",
                            "MetricStat": {
                                "Metric": metric,
                                "Period": 300,
                                "Stat": "Maximum",
                            },
                        }
                    )

            if not queries:
                self.progress.info("No CPU metrics found for cluster")
                return

            success, metric_data = self.safe_api_call(
                self.cloudwatch_client.get_metric_data,
                MetricDataQueries=queries[:10],
                StartTime=self.start_date,
                EndTime=self.end_date,
            )

            if success and metric_data:
                for result in metric_data.get("MetricDataResults", []):
                    values = result.get("Values", [])
                    if values:
                        max_cpu = max(values)
                        # If CPU usage consistently hits high levels, flag it
                        if max_cpu >= Thresholds.CPU_CRITICAL:
                            self.findings["pod_errors"].append(
                                {
                                    "summary": f"High CPU usage detected: {max_cpu:.1f}% - potential throttling",
                                    "details": {
                                        "metric_id": result.get("Id", "Unknown"),
                                        "max_cpu": f"{max_cpu:.1f}%",
                                        "severity": "warning",
                                        "finding_type": FindingType.HISTORICAL_EVENT,
                                        "root_causes": [
                                            "CPU limits too low for workload",
                                            "Application inefficiency",
                                            "Unexpected traffic spike",
                                        ],
                                    },
                                }
                            )

            self.progress.info("CPU throttling analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_cpu_throttling", "message": str(e)})
            self.progress.warning(f"CPU throttling analysis failed: {e}")

    def analyze_service_health(self):
        """
        Analyze Kubernetes services, endpoints, and load balancers
        Detects services without endpoints, failed load balancers, connectivity issues

        Catalog: Network & Service Issues
        - Service Not Accessible / No Endpoints
        - Connectivity Check (passive via events)
        """
        self.progress.step("Analyzing service health...")

        try:
            # Check services with no endpoints
            cmd = "kubectl get endpoints --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get endpoints -n {self.namespace} -o json"

            output = self.safe_kubectl_call(cmd)
            if not output:
                return

            endpoints = json.loads(output)

            for ep in endpoints.get("items", []):
                ep_name = ep["metadata"]["name"]
                ep_namespace = ep["metadata"]["namespace"]
                subsets = ep.get("subsets", [])

                # Check if service has no endpoints
                if not subsets:
                    self.findings["network_issues"].append(
                        {
                            "summary": f"Service {ep_namespace}/{ep_name} has no endpoints (pods not ready)",
                            "details": {
                                "service": ep_name,
                                "namespace": ep_namespace,
                                "severity": "warning",
                                "finding_type": FindingType.CURRENT_STATE,
                                "root_causes": [
                                    "Pod selector does not match any pods",
                                    "Pods exist but not passing readiness probes",
                                    "Pods are in CrashLoopBackOff",
                                ],
                                "diagnostic_steps": [
                                    f"kubectl get pods -n {ep_namespace} -l <selector>",
                                    f"kubectl describe endpoints {ep_name} -n {ep_namespace}",
                                    f"kubectl get svc {ep_name} -n {ep_namespace} -o yaml | grep selector",
                                    "Check if pods are running and passing readiness probes",
                                ],
                                "aws_doc": "https://kubernetes.io/docs/tasks/debug/debug-application/debug-service/",
                            },
                        }
                    )

            # Check for LoadBalancer services with pending IPs
            cmd = "kubectl get services --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get services -n {self.namespace} -o json"

            output = self.safe_kubectl_call(cmd)
            if output:
                services = json.loads(output)

                for svc in services.get("items", []):
                    svc_name = svc["metadata"]["name"]
                    svc_namespace = svc["metadata"]["namespace"]
                    svc_type = svc.get("spec", {}).get("type", "ClusterIP")
                    status = svc.get("status", {})

                    if svc_type == "LoadBalancer":
                        lb_ingress = status.get("loadBalancer", {}).get("ingress", [])
                        if not lb_ingress:
                            self.findings["network_issues"].append(
                                {
                                    "summary": f"LoadBalancer service {svc_namespace}/{svc_name} has no external IP",
                                    "details": {
                                        "service": svc_name,
                                        "namespace": svc_namespace,
                                        "type": svc_type,
                                        "severity": "warning",
                                        "finding_type": FindingType.CURRENT_STATE,
                                        "root_causes": [
                                            "AWS Load Balancer Controller not running",
                                            "IAM permissions missing",
                                            "Subnet tagging issues",
                                            "Security group issues",
                                        ],
                                        "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html",
                                    },
                                }
                            )

            # Check for connectivity-related events (passive connectivity check)
            connectivity_event_patterns = [
                {
                    "pattern": "connection refused",
                    "issue": "Connection refused to service/pod",
                },
                {
                    "pattern": "no route to host",
                    "issue": "No route to host - network unreachable",
                },
                {"pattern": "network is unreachable", "issue": "Network unreachable"},
                {"pattern": "connection timed out", "issue": "Connection timeout"},
                {
                    "pattern": "i/o timeout",
                    "issue": "I/O timeout - possible network issue",
                },
                {"pattern": "dial tcp", "issue": "TCP connection failure"},
                {
                    "pattern": "temporary failure in name resolution",
                    "issue": "DNS resolution failure",
                },
                {"pattern": "no such host", "issue": "Unknown host - DNS failure"},
            ]

            cmd = "kubectl get events --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get events -n {self.namespace} -o json"
            output = self.safe_kubectl_call(cmd)

            if output:
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                for event in events.get("items", []):
                    message = event.get("message", "").lower()
                    involved = event.get("involvedObject", {})
                    namespace = event["metadata"]["namespace"]
                    timestamp = event.get("lastTimestamp", event.get("eventTime", "Unknown"))

                    for pattern_info in connectivity_event_patterns:
                        if pattern_info["pattern"] in message:
                            self.findings["network_issues"].append(
                                {
                                    "summary": f"Connectivity issue: {pattern_info['issue']} in {namespace}/{involved.get('name', 'unknown')}",
                                    "details": {
                                        "namespace": namespace,
                                        "resource": involved.get("name", "unknown"),
                                        "resource_kind": involved.get("kind", "unknown"),
                                        "pattern": pattern_info["pattern"],
                                        "message": event.get("message", "")[:200],
                                        "timestamp": str(timestamp),
                                        "severity": "warning",
                                        "finding_type": FindingType.HISTORICAL_EVENT,
                                        "diagnostic_steps": [
                                            f"kubectl describe {involved.get('kind', 'pod').lower()} {involved.get('name', '')} -n {namespace}",
                                            "Check if target service/pod is running",
                                            "Verify NetworkPolicies allow traffic",
                                            "Check DNS resolution: nslookup <service>",
                                            "Test connectivity: curl -v <service>:<port>",
                                        ],
                                        "aws_doc": "https://kubernetes.io/docs/tasks/debug/debug-application/debug-service/",
                                    },
                                }
                            )
                            break

            self.progress.info("Service health analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_service_health", "message": str(e)})
            self.progress.warning(f"Service health analysis failed: {e}")

    def analyze_eks_nodegroup_health(self):
        """
        Analyze EKS managed node groups via EKS API
        Detects degraded, unhealthy node groups
        """
        self.progress.step("Analyzing EKS node group health...")

        try:
            success, response = self.safe_api_call(
                self.eks_client.list_nodegroups, clusterName=self.cluster_name
            )

            if not success:
                self.progress.warning("Could not list node groups")
                return

            nodegroups = response.get("nodegroups", [])

            for ng_name in nodegroups:
                success, ng_info = self.safe_api_call(
                    self.eks_client.describe_nodegroup,
                    clusterName=self.cluster_name,
                    nodegroupName=ng_name,
                )

                if not success:
                    continue

                ng = ng_info.get("nodegroup", {})
                status = ng.get("status", "Unknown")
                health = ng.get("health", {})
                issues = health.get("issues", [])

                if status != "ACTIVE" or issues:
                    issue_messages = [issue.get("message", "Unknown") for issue in issues]

                    self.findings["node_issues"].append(
                        {
                            "summary": f"EKS node group {ng_name} is unhealthy (status: {status})",
                            "details": {
                                "nodegroup": ng_name,
                                "status": status,
                                "scaling_config": ng.get("scalingConfig", {}),
                                "instance_types": ng.get("instanceTypes", []),
                                "health_issues": issue_messages,
                                "severity": "critical"
                                if status in ["DEGRADED", "UNHEALTHY"]
                                else "warning",
                                "aws_doc": "https://repost.aws/knowledge-center/eks-node-group-degraded",
                                "finding_type": FindingType.CURRENT_STATE,
                            },
                        }
                    )

            self.progress.info(f"Checked {len(nodegroups)} EKS node groups")

        except Exception as e:
            self.errors.append({"step": "analyze_eks_nodegroup_health", "message": str(e)})
            self.progress.warning(f"EKS node group analysis failed: {e}")

    def analyze_probe_failures(self):
        """
        Analyze liveness and readiness probe failures
        Detects pods failing health checks
        """
        self.progress.step("Analyzing probe failures...")

        try:
            # Get events related to probe failures
            cmd = "kubectl get events --all-namespaces --field-selector reason=Unhealthy -o json"
            if self.namespace:
                cmd = f"kubectl get events -n {self.namespace} --field-selector reason=Unhealthy -o json"

            output = self.safe_kubectl_call(cmd)
            if not output:
                self.progress.info("No probe failure events found")
                return

            events = json.loads(output)
            events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

            for event in events.get("items", []):
                involved = event.get("involvedObject", {})
                message = event.get("message", "").lower()

                probe_type = "unknown"
                if "liveness" in message:
                    probe_type = "liveness"
                elif "readiness" in message:
                    probe_type = "readiness"

                self.findings["pod_errors"].append(
                    {
                        "summary": f"Pod {involved.get('namespace', 'unknown')}/{involved.get('name', 'unknown')} failing {probe_type} probe",
                        "details": {
                            "pod": involved.get("name", "Unknown"),
                            "namespace": involved.get("namespace", "Unknown"),
                            "probe_type": probe_type,
                            "message": event.get("message", "N/A")[:200],
                            "timestamp": event.get("lastTimestamp", "Unknown"),
                            "severity": "warning",
                            "root_causes": [
                                "Application slow to start (increase initialDelaySeconds)",
                                "Health check endpoint incorrect",
                                "Application overloaded",
                                "Network connectivity issues",
                                "Probe timeout too short",
                            ],
                            "aws_doc": "https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/",
                            "finding_type": FindingType.HISTORICAL_EVENT,
                        },
                    }
                )

            self.progress.info(f"Found {len(events.get('items', []))} probe failure events")

        except Exception as e:
            self.errors.append({"step": "analyze_probe_failures", "message": str(e)})
            self.progress.warning(f"Probe failure analysis failed: {e}")

    def analyze_ebs_csi_health(self):
        """
        Analyze EBS CSI driver health
        Detects driver issues affecting volume operations
        """
        self.progress.step("Analyzing EBS CSI driver health...")

        try:
            # Check EBS CSI controller deployment
            cmd = "kubectl get deployment ebs-csi-controller -n kube-system -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                deployment = json.loads(output)
                status = deployment.get("status", {})
                replicas = status.get("replicas", 0)
                ready = status.get("readyReplicas", 0)
                unavailable = status.get("unavailableReplicas", 0)

                if ready < replicas or unavailable > 0:
                    self.findings["pvc_issues"].append(
                        {
                            "summary": f"EBS CSI controller unhealthy: {ready}/{replicas} ready",
                            "details": {
                                "component": "ebs-csi-controller",
                                "namespace": "kube-system",
                                "replicas": replicas,
                                "ready": ready,
                                "unavailable": unavailable,
                                "severity": "critical",
                                "root_causes": [
                                    "IAM role missing EBS permissions",
                                    "Service account not configured for IRSA",
                                    "Resource limits too low",
                                ],
                                "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/ebs-csi.html",
                                "finding_type": FindingType.CURRENT_STATE,
                            },
                        }
                    )

            # Check for volume attachment events
            cmd = "kubectl get events --all-namespaces --field-selector reason=VolumeAttachFailed -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                for event in events.get("items", [])[:10]:
                    involved = event.get("involvedObject", {})
                    self.findings["pvc_issues"].append(
                        {
                            "summary": f"Volume attachment failed for {involved.get('namespace', 'unknown')}/{involved.get('name', 'unknown')}",
                            "details": {
                                "pvc": involved.get("name", "Unknown"),
                                "namespace": involved.get("namespace", "Unknown"),
                                "message": event.get("message", "N/A")[:200],
                                "timestamp": event.get("lastTimestamp", "Unknown"),
                                "severity": "critical",
                                "root_causes": EKS_ISSUE_PATTERNS["storage_issues"][
                                    "VolumeAttachmentFailed"
                                ]["root_causes"],
                                "aws_doc": EKS_ISSUE_PATTERNS["storage_issues"][
                                    "VolumeAttachmentFailed"
                                ]["aws_doc"],
                                "finding_type": FindingType.HISTORICAL_EVENT,
                            },
                        }
                    )

            self.progress.info("EBS CSI driver analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_ebs_csi_health", "message": str(e)})
            self.progress.warning(f"EBS CSI driver analysis failed: {e}")

    def analyze_service_quotas(self):
        """
        Analyze AWS Service Quotas for EC2, EBS, and VPC limits
        Detects if quota limits may be blocking cluster scaling
        """
        self.progress.step("Analyzing AWS Service Quotas...")

        try:
            quotas_client = self.session.client("service-quotas")

            # Critical quotas to check for EKS
            quota_checks = [
                {
                    "service_code": "ec2",
                    "quota_name": "Running On-Demand Standard instances",
                    "quota_code": "L-1216C47A",
                    "critical_threshold": 0.9,
                    "description": "EC2 On-Demand Instance Limit",
                },
                {
                    "service_code": "ec2",
                    "quota_name": "Number of EBS snapshots",
                    "quota_code": "L-309BAC07",
                    "critical_threshold": 0.9,
                    "description": "EBS Snapshot Limit",
                },
                {
                    "service_code": "ec2",
                    "quota_name": "Total size of all EBS snapshots",
                    "quota_code": "L-835FE1D7",
                    "critical_threshold": 0.9,
                    "description": "EBS Snapshot Storage Limit",
                },
                {
                    "service_code": "vpc",
                    "quota_name": "VPCs per Region",
                    "quota_code": "L-F678F1CE",
                    "critical_threshold": 0.9,
                    "description": "VPC Limit",
                },
                {
                    "service_code": "vpc",
                    "quota_name": "Internet gateways per Region",
                    "quota_code": "L-A4707A72",
                    "critical_threshold": 0.9,
                    "description": "Internet Gateway Limit",
                },
                {
                    "service_code": "vpc",
                    "quota_name": "NAT gateways per Availability Zone",
                    "quota_code": "L-FE5A380F",
                    "critical_threshold": 0.9,
                    "description": "NAT Gateway Limit",
                },
                {
                    "service_code": "elasticloadbalancing",
                    "quota_name": "Application Load Balancers per Region",
                    "quota_code": "L-53B6E32B",
                    "critical_threshold": 0.9,
                    "description": "ALB Limit",
                },
                {
                    "service_code": "elasticloadbalancing",
                    "quota_name": "Network Load Balancers per Region",
                    "quota_code": "L-69A177A4",
                    "critical_threshold": 0.9,
                    "description": "NLB Limit",
                },
            ]

            for quota_check in quota_checks:
                try:
                    success, response = self.safe_api_call(
                        quotas_client.get_service_quota,
                        ServiceCode=quota_check["service_code"],
                        QuotaCode=quota_check["quota_code"],
                    )

                    if success and response:
                        quota = response.get("Quota", {})
                        quota_value = quota.get("Value", 0)
                        usage = quota.get("UsageMetric", {})

                        if quota_value > 0:
                            quota_issues = self.findings.setdefault("quota_issues", [])

                            quota_issues.append(
                                {
                                    "summary": f"Service Quota check: {quota_check['quota_name']}",
                                    "details": {
                                        "service": quota_check["service_code"],
                                        "quota_name": quota_check["quota_name"],
                                        "limit": quota_value,
                                        "description": quota_check["description"],
                                        "severity": "info",
                                        "finding_type": FindingType.CURRENT_STATE,
                                    },
                                }
                            )

                except Exception:
                    continue

            self.progress.info("Service Quotas analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_service_quotas", "message": str(e)})
            self.progress.warning(f"Service Quotas analysis failed: {e}")

    def analyze_cluster_autoscaler(self):
        """
        Analyze Cluster Autoscaler health and configuration
        Detects scale-up failures and misconfigurations
        """
        self.progress.step("Analyzing Cluster Autoscaler health...")

        try:
            cas_issues = []

            cmd = "kubectl get deployment cluster-autoscaler -n kube-system -o json 2>/dev/null || kubectl get deployment cluster-autoscaler-aws-cluster-autoscaler -n kube-system -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                deployment = json.loads(output)
                status = deployment.get("status", {})
                replicas = status.get("replicas", 0)
                ready = status.get("readyReplicas", 0)

                if ready < replicas:
                    self.findings["addon_issues"].append(
                        {
                            "summary": "Cluster Autoscaler deployment not fully healthy",
                            "details": {
                                "component": "cluster-autoscaler",
                                "namespace": "kube-system",
                                "replicas": replicas,
                                "ready": ready,
                                "severity": "critical",
                                "finding_type": FindingType.CURRENT_STATE,
                                "root_causes": [
                                    "Insufficient permissions to access AWS APIs",
                                    "Missing or incorrect --node-group-auto-discovery flag",
                                    "Resource constraints on the pod",
                                    "Network connectivity issues",
                                ],
                                "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/autoscaling.html",
                            },
                        }
                    )

            cmd = "kubectl logs -l app=cluster-autoscaler -n kube-system --tail=100 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                cas_error_patterns = [
                    {
                        "pattern": "InstanceLimitExceeded|VcpuLimitExceeded",
                        "root_cause": "AWS service quota limit reached",
                        "severity": "critical",
                    },
                    {
                        "pattern": "UnauthorizedOperation|AccessDenied",
                        "root_cause": "IAM permissions missing",
                        "severity": "critical",
                    },
                    {
                        "pattern": "InsufficientInstanceCapacity",
                        "root_cause": "AWS region lacks capacity for instance type",
                        "severity": "warning",
                    },
                    {
                        "pattern": "no scale-up needed|scale-up not needed",
                        "root_cause": "Normal operation - no action needed",
                        "severity": "info",
                    },
                    {
                        "pattern": "failed to scale up|scale-up failed",
                        "root_cause": "Scale-up attempt failed",
                        "severity": "critical",
                    },
                ]

                import re

                for error_check in cas_error_patterns:
                    if re.search(error_check["pattern"], output, re.IGNORECASE):
                        if error_check["severity"] != "info":
                            self.findings["addon_issues"].append(
                                {
                                    "summary": f"Cluster Autoscaler issue: {error_check['root_cause']}",
                                    "details": {
                                        "component": "cluster-autoscaler",
                                        "issue": error_check["root_cause"],
                                        "severity": error_check["severity"],
                                        "finding_type": FindingType.HISTORICAL_EVENT,
                                        "aws_doc": "https://repost.aws/knowledge-center/eks-pod-scheduling-cluster-autoscaler",
                                    },
                                }
                            )

            self.progress.info("Cluster Autoscaler analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_cluster_autoscaler", "message": str(e)})
            self.progress.warning(f"Cluster Autoscaler analysis failed: {e}")

    def analyze_hpa_vpa(self):
        """
        Analyze Horizontal/Vertical Pod Autoscaler health
        Detects autoscaling failures and metric issues
        """
        self.progress.step("Analyzing HPA/VPA health...")

        try:
            cmd = "kubectl get hpa --all-namespaces -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                hpas = json.loads(output)

                for hpa in hpas.get("items", []):
                    hpa_name = hpa["metadata"]["name"]
                    namespace = hpa["metadata"]["namespace"]
                    status = hpa.get("status", {})
                    conditions = status.get("conditions", [])

                    for condition in conditions:
                        if (
                            condition.get("type") == "AbleToScale"
                            and condition.get("status") != "True"
                        ):
                            self.findings["pod_errors"].append(
                                {
                                    "summary": f"HPA {namespace}/{hpa_name} cannot scale",
                                    "details": {
                                        "hpa": hpa_name,
                                        "namespace": namespace,
                                        "reason": condition.get("reason", "Unknown"),
                                        "message": condition.get("message", "N/A")[:200],
                                        "severity": "warning",
                                        "finding_type": FindingType.CURRENT_STATE,
                                        "root_causes": [
                                            "Metrics server not available",
                                            "Resource limits already at maximum",
                                            "Insufficient cluster resources",
                                        ],
                                        "aws_doc": "https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/",
                                    },
                                }
                            )

                        if (
                            condition.get("type") == "ScalingActive"
                            and condition.get("status") != "True"
                        ):
                            self.findings["pod_errors"].append(
                                {
                                    "summary": f"HPA {namespace}/{hpa_name} scaling not active",
                                    "details": {
                                        "hpa": hpa_name,
                                        "namespace": namespace,
                                        "reason": condition.get("reason", "Unknown"),
                                        "message": condition.get("message", "N/A")[:200],
                                        "severity": "warning",
                                        "finding_type": FindingType.CURRENT_STATE,
                                        "root_causes": [
                                            "Missing metrics",
                                            "Target resource not found",
                                            "Invalid metric configuration",
                                        ],
                                    },
                                }
                            )

                    current_replicas = status.get("currentReplicas", 0)
                    desired_replicas = status.get("desiredReplicas", 0)
                    max_replicas = hpa.get("spec", {}).get("maxReplicas", 0)

                    if current_replicas >= max_replicas and current_replicas > 0:
                        self.findings["pod_errors"].append(
                            {
                                "summary": f"HPA {namespace}/{hpa_name} at max replicas ({max_replicas})",
                                "details": {
                                    "hpa": hpa_name,
                                    "namespace": namespace,
                                    "current_replicas": current_replicas,
                                    "max_replicas": max_replicas,
                                    "severity": "warning",
                                    "finding_type": FindingType.CURRENT_STATE,
                                    "recommendation": "Consider increasing maxReplicas if workload needs more scaling",
                                },
                            }
                        )

            self.progress.info("HPA/VPA analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_hpa_vpa", "message": str(e)})
            self.progress.warning(f"HPA/VPA analysis failed: {e}")

    def analyze_certificate_expiry(self):
        """
        Analyze certificate expiration for kubelet and control plane
        Detects certificates approaching expiration
        """
        self.progress.step("Analyzing certificate expiration...")

        try:
            cmd = "kubectl get nodes -o json"
            output = self.safe_kubectl_call(cmd)

            if output:
                nodes = json.loads(output)

                for node in nodes.get("items", []):
                    node_name = node["metadata"]["name"]
                    status = node.get("status", {})
                    conditions = status.get("conditions", [])

                    for condition in conditions:
                        if condition.get("type") == "Ready":
                            if "certificate" in condition.get("message", "").lower():
                                self.findings["node_issues"].append(
                                    {
                                        "summary": f"Node {node_name} may have certificate issues",
                                        "details": {
                                            "node": node_name,
                                            "message": condition.get("message", "N/A")[:200],
                                            "severity": "critical",
                                            "finding_type": FindingType.CURRENT_STATE,
                                            "root_causes": [
                                                "Kubelet certificate expired",
                                                "CA certificate rotation pending",
                                                "Clock skew between node and API server",
                                            ],
                                            "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/certificate-rotation.html",
                                        },
                                    }
                                )

            cmd = "kubectl get events --all-namespaces --field-selector reason=TLSHealthCheckSucceeded -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                for event in events.get("items", []):
                    message = event.get("message", "").lower()
                    if "cert" in message and ("expir" in message or "invalid" in message):
                        involved = event.get("involvedObject", {})
                        self.findings["control_plane_issues"].append(
                            {
                                "summary": f"Certificate issue detected in {involved.get('namespace', 'unknown')}",
                                "details": {
                                    "object": involved.get("name", "Unknown"),
                                    "namespace": involved.get("namespace", "Unknown"),
                                    "message": event.get("message", "N/A")[:200],
                                    "severity": "critical",
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                },
                            }
                        )

            self.progress.info("Certificate expiration analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_certificate_expiry", "message": str(e)})
            self.progress.warning(f"Certificate expiration analysis failed: {e}")

    def analyze_aws_lb_controller(self):
        """
        Analyze AWS Load Balancer Controller health
        Detects issues with ALB/NLB provisioning
        """
        self.progress.step("Analyzing AWS Load Balancer Controller...")

        try:
            cmd = "kubectl get deployment aws-load-balancer-controller -n kube-system -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                deployment = json.loads(output)
                status = deployment.get("status", {})
                replicas = status.get("replicas", 0)
                ready = status.get("readyReplicas", 0)

                if ready < replicas:
                    self.findings["network_issues"].append(
                        {
                            "summary": "AWS Load Balancer Controller not fully healthy",
                            "details": {
                                "component": "aws-load-balancer-controller",
                                "namespace": "kube-system",
                                "replicas": replicas,
                                "ready": ready,
                                "severity": "critical",
                                "finding_type": FindingType.CURRENT_STATE,
                                "root_causes": [
                                    "IAM role missing permissions for ELB/ACM",
                                    "Service account not configured correctly",
                                    "Subnet tagging issues",
                                ],
                                "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html",
                            },
                        }
                    )

            cmd = "kubectl logs -l app.kubernetes.io/name=aws-load-balancer-controller -n kube-system --tail=100 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                import re

                lb_error_patterns = [
                    {
                        "pattern": "AccessDenied|UnauthorizedAccess",
                        "root_cause": "IAM permissions missing",
                        "severity": "critical",
                    },
                    {
                        "pattern": "subnet.*not.*found|no.*subnet",
                        "root_cause": "Subnet tagging issues",
                        "severity": "critical",
                    },
                    {
                        "pattern": "certificate.*not.*found|no.*certificate",
                        "root_cause": "Certificate issues for HTTPS listeners",
                        "severity": "warning",
                    },
                    {
                        "pattern": "security.*group.*not.*found",
                        "root_cause": "Security group issues",
                        "severity": "critical",
                    },
                ]

                for error_check in lb_error_patterns:
                    if re.search(error_check["pattern"], output, re.IGNORECASE):
                        self.findings["network_issues"].append(
                            {
                                "summary": f"AWS LB Controller issue: {error_check['root_cause']}",
                                "details": {
                                    "component": "aws-load-balancer-controller",
                                    "issue": error_check["root_cause"],
                                    "severity": error_check["severity"],
                                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html",
                                },
                            }
                        )

            self.progress.info("AWS Load Balancer Controller analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_aws_lb_controller", "message": str(e)})
            self.progress.warning(f"AWS LB Controller analysis failed: {e}")

    def analyze_subnet_health(self):
        """
        Analyze VPC subnet health and IP availability
        Detects subnet exhaustion issues
        """
        self.progress.step("Analyzing subnet health...")

        try:
            ec2_client = self.session.client("ec2")

            cmd = "kubectl get nodes -o jsonpath='{.items[*].spec.providerID}' 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if not output or "not found" in output.lower():
                self.progress.info("Could not get node subnet info")
                return

            import re

            subnet_ids = set()
            instance_ids = []

            for provider_id in output.split():
                match = re.search(r"i-([a-f0-9]+)", provider_id)
                if match:
                    instance_ids.append(provider_id.split("/")[-1])

            if instance_ids:
                success, response = self.safe_api_call(
                    ec2_client.describe_instances, InstanceIds=instance_ids[:10]
                )

                if success and response:
                    for reservation in response.get("Reservations", []):
                        for instance in reservation.get("Instances", []):
                            subnet_id = instance.get("SubnetId")
                            if subnet_id:
                                subnet_ids.add(subnet_id)

            for subnet_id in subnet_ids:
                success, response = self.safe_api_call(
                    ec2_client.describe_subnets, SubnetIds=[subnet_id]
                )

                if success and response:
                    for subnet in response.get("Subnets", []):
                        available_ips = subnet.get("AvailableIpAddressCount", 0)
                        cidr = subnet.get("CidrBlock", "")
                        total_ips = 2 ** (32 - int(cidr.split("/")[1])) - 5

                        if available_ips < 5:
                            self.findings["network_issues"].append(
                                {
                                    "summary": f"Subnet {subnet_id} has very few IPs available ({available_ips})",
                                    "details": {
                                        "subnet_id": subnet_id,
                                        "availability_zone": subnet.get(
                                            "AvailabilityZone", "Unknown"
                                        ),
                                        "available_ips": available_ips,
                                        "total_ips": total_ips,
                                        "cidr": cidr,
                                        "severity": "critical",
                                        "finding_type": FindingType.CURRENT_STATE,
                                        "root_causes": [
                                            "Subnet CIDR too small",
                                            "Too many pods/nodes in subnet",
                                            "Need secondary CIDR block",
                                        ],
                                        "recommendation": "Consider adding a secondary CIDR block or expanding subnet",
                                        "aws_doc": "https://repost.aws/knowledge-center/eks-resolve-cluster-ip-address-issues",
                                    },
                                }
                            )
                        elif available_ips < 16:
                            self.findings["network_issues"].append(
                                {
                                    "summary": f"Subnet {subnet_id} running low on IPs ({available_ips} available)",
                                    "details": {
                                        "subnet_id": subnet_id,
                                        "availability_zone": subnet.get(
                                            "AvailabilityZone", "Unknown"
                                        ),
                                        "available_ips": available_ips,
                                        "severity": "warning",
                                        "finding_type": FindingType.CURRENT_STATE,
                                    },
                                }
                            )

            self.progress.info("Subnet health analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_subnet_health", "message": str(e)})
            self.progress.warning(f"Subnet health analysis failed: {e}")

    def analyze_karpenter(self):
        """
        Analyze Karpenter autoscaler health (alternative to Cluster Autoscaler)
        Detects provisioning failures
        """
        self.progress.step("Analyzing Karpenter health...")

        try:
            cmd = "kubectl get deployment karpenter -n kube-system -o json 2>/dev/null || kubectl get deployment -l app.kubernetes.io/name=karpenter -n kube-system -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                deployment = json.loads(output)
                status = deployment.get("status", {})
                replicas = status.get("replicas", 0)
                ready = status.get("readyReplicas", 0)

                if ready < replicas:
                    self.findings["addon_issues"].append(
                        {
                            "summary": "Karpenter deployment not fully healthy",
                            "details": {
                                "component": "karpenter",
                                "namespace": "kube-system",
                                "replicas": replicas,
                                "ready": ready,
                                "severity": "critical",
                                "finding_type": FindingType.CURRENT_STATE,
                                "root_causes": [
                                    "IAM role missing permissions",
                                    "Karpenter NodePool/EC2NodeClass misconfigured",
                                    "AWS SQS queue for interruptions not set up",
                                ],
                                "aws_doc": "https://karpenter.sh/docs/getting-started/getting-started-with-karpenter/",
                            },
                        }
                    )

            cmd = "kubectl get nodepools -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                nodepools = json.loads(output)

                for np in nodepools.get("items", []):
                    np_name = np["metadata"]["name"]
                    status = np.get("status", {})

                    if status.get("conditions"):
                        for condition in status["conditions"]:
                            if (
                                condition.get("type") == "Ready"
                                and condition.get("status") != "True"
                            ):
                                self.findings["addon_issues"].append(
                                    {
                                        "summary": f"Karpenter NodePool {np_name} not ready",
                                        "details": {
                                            "nodepool": np_name,
                                            "reason": condition.get("reason", "Unknown"),
                                            "message": condition.get("message", "N/A")[:200],
                                            "severity": "warning",
                                            "finding_type": FindingType.CURRENT_STATE,
                                        },
                                    }
                                )

            self.progress.info("Karpenter health analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_karpenter", "message": str(e)})
            self.progress.warning(f"Karpenter health analysis failed: {e}")

    def analyze_efs_csi_health(self):
        """
        Analyze EFS CSI driver health
        Detects issues with EFS volume mounting
        """
        self.progress.step("Analyzing EFS CSI driver health...")

        try:
            cmd = "kubectl get deployment efs-csi-controller -n kube-system -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                deployment = json.loads(output)
                status = deployment.get("status", {})
                replicas = status.get("replicas", 0)
                ready = status.get("readyReplicas", 0)

                if ready < replicas:
                    self.findings["pvc_issues"].append(
                        {
                            "summary": "EFS CSI controller unhealthy",
                            "details": {
                                "component": "efs-csi-controller",
                                "namespace": "kube-system",
                                "replicas": replicas,
                                "ready": ready,
                                "severity": "critical",
                                "finding_type": FindingType.CURRENT_STATE,
                                "root_causes": [
                                    "IAM role missing EFS permissions",
                                    "Service account not configured for IRSA",
                                    "EFS file system not accessible",
                                ],
                                "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/efs-csi.html",
                            },
                        }
                    )

            cmd = "kubectl get events --all-namespaces --field-selector reason=Warning -o json 2>/dev/null | grep -i efs || echo ''"
            output = self.safe_kubectl_call(cmd)

            if output and output.strip():
                self.findings["pvc_issues"].append(
                    {
                        "summary": "EFS-related warnings detected",
                        "details": {
                            "severity": "warning",
                            "finding_type": FindingType.HISTORICAL_EVENT,
                            "recommendation": "Review events for EFS mount issues",
                        },
                    }
                )

            self.progress.info("EFS CSI driver analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_efs_csi_health", "message": str(e)})
            self.progress.warning(f"EFS CSI driver analysis failed: {e}")

    def analyze_gpu_scheduling(self):
        """
        Analyze GPU scheduling issues for ML/AI workloads
        Detects GPU resource constraints
        """
        self.progress.step("Analyzing GPU scheduling issues...")

        try:
            cmd = "kubectl get nodes -o json"
            output = self.safe_kubectl_call(cmd)

            if not output:
                return

            nodes = json.loads(output)
            gpu_nodes = []
            total_gpus = 0

            for node in nodes.get("items", []):
                node_name = node["metadata"]["name"]
                capacity = node.get("status", {}).get("capacity", {})

                nvidia_gpu = capacity.get("nvidia.com/gpu", "0")
                amd_gpu = capacity.get("amd.com/gpu", "0")
                aws_neuron = capacity.get("aws.amazon.com/neuron", "0")

                gpu_count = int(nvidia_gpu) + int(amd_gpu) + int(aws_neuron)
                if gpu_count > 0:
                    gpu_nodes.append({"name": node_name, "gpus": gpu_count})
                    total_gpus += gpu_count

            if not gpu_nodes:
                cmd = "kubectl get pods --all-namespaces -o json"
                output = self.safe_kubectl_call(cmd)

                if output:
                    pods = json.loads(output)
                    for pod in pods.get("items", []):
                        resources = pod.get("spec", {}).get("containers", [])
                        for container in resources:
                            limits = container.get("resources", {}).get("limits", {})
                            if any(
                                gpu in limits
                                for gpu in [
                                    "nvidia.com/gpu",
                                    "amd.com/gpu",
                                    "aws.amazon.com/neuron",
                                ]
                            ):
                                pod_name = pod["metadata"]["name"]
                                namespace = pod["metadata"]["namespace"]
                                phase = pod.get("status", {}).get("phase", "Unknown")

                                if phase == "Pending":
                                    self.findings["scheduling_failures"].append(
                                        {
                                            "summary": f"GPU pod {namespace}/{pod_name} pending but no GPU nodes available",
                                            "details": {
                                                "pod": pod_name,
                                                "namespace": namespace,
                                                "severity": "critical",
                                                "finding_type": FindingType.CURRENT_STATE,
                                                "root_causes": [
                                                    "No GPU nodes in cluster",
                                                    "GPU node selector mismatch",
                                                    "Insufficient GPU quota",
                                                ],
                                                "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/gpu-ami.html",
                                            },
                                        }
                                    )
            else:
                cmd = "kubectl get events --all-namespaces --field-selector reason=FailedScheduling -o json 2>/dev/null || echo 'not found'"
                output = self.safe_kubectl_call(cmd)

                if output and "not found" not in output.lower():
                    events = json.loads(output)
                    events = self.filter_kubectl_events_by_date(
                        events, self.start_date, self.end_date
                    )

                    for event in events.get("items", []):
                        message = event.get("message", "").lower()
                        if "gpu" in message:
                            involved = event.get("involvedObject", {})
                            self.findings["scheduling_failures"].append(
                                {
                                    "summary": f"GPU scheduling failure for {involved.get('namespace', 'unknown')}/{involved.get('name', 'unknown')}",
                                    "details": {
                                        "pod": involved.get("name", "Unknown"),
                                        "namespace": involved.get("namespace", "Unknown"),
                                        "message": event.get("message", "N/A")[:200],
                                        "severity": "warning",
                                        "finding_type": FindingType.HISTORICAL_EVENT,
                                        "gpu_nodes_count": len(gpu_nodes),
                                        "total_gpus": total_gpus,
                                    },
                                }
                            )

            self.progress.info("GPU scheduling analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_gpu_scheduling", "message": str(e)})
            self.progress.warning(f"GPU scheduling analysis failed: {e}")

    def analyze_windows_nodes(self):
        """
        Analyze Windows node health and scheduling issues
        Detects Windows-specific problems
        """
        self.progress.step("Analyzing Windows node health...")

        try:
            cmd = "kubectl get nodes -o json"
            output = self.safe_kubectl_call(cmd)

            if not output:
                return

            nodes = json.loads(output)
            windows_nodes = []

            for node in nodes.get("items", []):
                node_name = node["metadata"]["name"]
                labels = node["metadata"].get("labels", {})

                if labels.get("kubernetes.io/os") == "windows":
                    conditions = node.get("status", {}).get("conditions", [])
                    ready_condition = next(
                        (c for c in conditions if c.get("type") == "Ready"), None
                    )

                    windows_nodes.append(
                        {
                            "name": node_name,
                            "ready": ready_condition.get("status") == "True"
                            if ready_condition
                            else False,
                            "runtime": labels.get("node.kubernetes.io/windows-build", "Unknown"),
                        }
                    )

                    if ready_condition and ready_condition.get("status") != "True":
                        self.findings["node_issues"].append(
                            {
                                "summary": f"Windows node {node_name} not ready",
                                "details": {
                                    "node": node_name,
                                    "os": "Windows",
                                    "reason": ready_condition.get("reason", "Unknown"),
                                    "message": ready_condition.get("message", "N/A")[:200],
                                    "severity": "critical",
                                    "finding_type": FindingType.CURRENT_STATE,
                                    "root_causes": [
                                        "Container runtime issue",
                                        "Network plugin not compatible with Windows",
                                        "OOM issues common on Windows nodes",
                                    ],
                                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/windows-support.html",
                                },
                            }
                        )

            if windows_nodes:
                cmd = "kubectl get events --all-namespaces --field-selector reason=FailedScheduling -o json 2>/dev/null || echo 'not found'"
                output = self.safe_kubectl_call(cmd)

                if output and "not found" not in output.lower():
                    events = json.loads(output)
                    events = self.filter_kubectl_events_by_date(
                        events, self.start_date, self.end_date
                    )

                    for event in events.get("items", []):
                        message = event.get("message", "").lower()
                        if "windows" in message:
                            involved = event.get("involvedObject", {})
                            self.findings["scheduling_failures"].append(
                                {
                                    "summary": f"Windows scheduling issue for {involved.get('name', 'unknown')}",
                                    "details": {
                                        "pod": involved.get("name", "Unknown"),
                                        "namespace": involved.get("namespace", "Unknown"),
                                        "message": event.get("message", "N/A")[:200],
                                        "severity": "warning",
                                        "finding_type": FindingType.HISTORICAL_EVENT,
                                        "windows_nodes_count": len(windows_nodes),
                                    },
                                }
                            )

            self.progress.info("Windows node analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_windows_nodes", "message": str(e)})
            self.progress.warning(f"Windows node analysis failed: {e}")

    def analyze_security_groups(self):
        """
        Analyze security group issues affecting EKS connectivity
        Detects common misconfigurations
        """
        self.progress.step("Analyzing security groups...")

        try:
            ec2_client = self.session.client("ec2")

            success, response = self.safe_api_call(
                ec2_client.describe_security_groups,
                Filters=[{"Name": "tag:aws:eks:cluster-name", "Values": [self.cluster_name]}],
            )

            if not success or not response.get("SecurityGroups"):
                success, response = self.safe_api_call(
                    ec2_client.describe_vpcs,
                    Filters=[
                        {
                            "Name": "tag:alpha.eksctl.io/cluster-name",
                            "Values": [self.cluster_name],
                        }
                    ],
                )

                if not success:
                    self.progress.info("Could not find cluster security groups")
                    return

            sg_issues = []

            for sg in response.get("SecurityGroups", []):
                sg_id = sg["GroupId"]
                sg_name = sg["GroupName"]
                inbound_rules = sg.get("IpPermissions", [])
                outbound_rules = sg.get("IpPermissionsEgress", [])

                for rule in inbound_rules:
                    if rule.get("IpProtocol") == "-1":
                        for ip_range in rule.get("IpRanges", []):
                            if ip_range.get("CidrIp") == "0.0.0.0/0":
                                sg_issues.append(
                                    {
                                        "sg_id": sg_id,
                                        "sg_name": sg_name,
                                        "issue": "Allows all inbound traffic from anywhere (0.0.0.0/0)",
                                        "severity": "warning",
                                    }
                                )

                has_outbound = any(
                    rule.get("IpProtocol") != "-1" or rule.get("IpRanges")
                    for rule in outbound_rules
                )
                all_outbound = any(
                    rule.get("IpProtocol") == "-1"
                    and any(ip.get("CidrIp") == "0.0.0.0/0" for ip in rule.get("IpRanges", []))
                    for rule in outbound_rules
                )

            cmd = "kubectl get events --all-namespaces -o json 2>/dev/null | grep -i 'security.*group\\|timeout.*connection\\|connection.*refused' || echo ''"
            output = self.safe_kubectl_call(cmd)

            if output and output.strip():
                sg_issues.append(
                    {
                        "issue": "Network connectivity issues detected in events",
                        "severity": "warning",
                        "recommendation": "Check security group rules allow required traffic",
                    }
                )

            for issue in sg_issues:
                self.findings["network_issues"].append(
                    {
                        "summary": f"Security group issue: {issue['issue']}",
                        "details": {
                            "sg_id": issue.get("sg_id", "N/A"),
                            "sg_name": issue.get("sg_name", "N/A"),
                            "severity": issue["severity"],
                            "finding_type": FindingType.CURRENT_STATE,
                            "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/sec-group-reqs.html",
                        },
                    }
                )

            self.progress.info("Security group analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_security_groups", "message": str(e)})
            self.progress.warning(f"Security group analysis failed: {e}")

    def analyze_fargate_health(self):
        """
        Analyze Fargate profile health for serverless workloads
        Detects profile issues and scheduling failures
        """
        self.progress.step("Analyzing Fargate profile health...")

        try:
            success, response = self.safe_api_call(
                self.eks_client.list_fargate_profiles, clusterName=self.cluster_name
            )

            if not success:
                self.progress.info("No Fargate profiles found")
                return

            profiles = response.get("fargateProfileNames", [])

            for profile_name in profiles:
                success, profile_info = self.safe_api_call(
                    self.eks_client.describe_fargate_profile,
                    clusterName=self.cluster_name,
                    fargateProfileName=profile_name,
                )

                if success and profile_info:
                    profile = profile_info.get("fargateProfile", {})
                    status = profile.get("status", "Unknown")

                    if status != "ACTIVE":
                        self.findings["addon_issues"].append(
                            {
                                "summary": f"Fargate profile {profile_name} is not active (status: {status})",
                                "details": {
                                    "profile": profile_name,
                                    "status": status,
                                    "pod_execution_role": profile.get("podExecutionRoleArn", "N/A"),
                                    "selectors": profile.get("selectors", []),
                                    "severity": "critical" if status == "FAILED" else "warning",
                                    "finding_type": FindingType.CURRENT_STATE,
                                    "root_causes": [
                                        "IAM role permissions missing",
                                        "Subnet not available",
                                        "Profile creation failed",
                                    ],
                                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/fargate-profile.html",
                                },
                            }
                        )

            cmd = "kubectl get pods --all-namespaces -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                pods = json.loads(output)

                for pod in pods.get("items", []):
                    annotations = pod["metadata"].get("annotations", {})
                    if annotations.get("eks.amazonaws.com/compute-type") == "fargate":
                        phase = pod.get("status", {}).get("phase", "Unknown")
                        if phase == "Pending":
                            pod_name = pod["metadata"]["name"]
                            namespace = pod["metadata"]["namespace"]

                            self.findings["scheduling_failures"].append(
                                {
                                    "summary": f"Fargate pod {namespace}/{pod_name} stuck in Pending",
                                    "details": {
                                        "pod": pod_name,
                                        "namespace": namespace,
                                        "compute_type": "fargate",
                                        "severity": "warning",
                                        "finding_type": FindingType.CURRENT_STATE,
                                        "root_causes": [
                                            "No matching Fargate profile selector",
                                            "Profile not in ACTIVE status",
                                            "Subnet/IP exhaustion in Fargate subnet",
                                        ],
                                    },
                                }
                            )

            self.progress.info(f"Fargate profile analysis completed ({len(profiles)} profiles)")

        except Exception as e:
            self.errors.append({"step": "analyze_fargate_health", "message": str(e)})
            self.progress.warning(f"Fargate health analysis failed: {e}")

    def analyze_apiserver_latency(self):
        """
        Analyze API Server latency and request patterns
        Detects slow requests, inflight saturation, rate limiting (429)
        """
        self.progress.step("Analyzing API Server latency...")

        try:
            latency_issues = []
            rate_limit_detected = False

            # Check control plane logs for API server latency patterns
            log_group = f"/aws/eks/{self.cluster_name}/cluster"

            success, response = self.safe_api_call(
                self.logs_client.describe_log_groups, logGroupNamePrefix=log_group
            )

            if not success or not response.get("logGroups"):
                self.progress.info("Control plane logging not enabled for API latency analysis")
                return

            # Patterns for API latency issues
            latency_patterns = [
                {"pattern": "request timeout", "issue": "Request timeout detected"},
                {
                    "pattern": "context deadline exceeded",
                    "issue": "Context deadline exceeded",
                },
                {"pattern": "slow request", "issue": "Slow API request"},
                {"pattern": "slow handler", "issue": "Slow handler detected"},
                {"pattern": "Throttling request", "issue": "Request throttling (429)"},
                {"pattern": "TooManyRequests", "issue": "429 Too Many Requests"},
                {"pattern": "client side throttle", "issue": "Client-side throttling"},
            ]

            success, streams_response = self.safe_api_call(
                self.logs_client.describe_log_streams,
                logGroupName=log_group,
                logStreamNamePrefix="kube-apiserver-",
                orderBy="LastEventTime",
                descending=True,
                limit=5,
            )

            if not success:
                return

            for stream in streams_response.get("logStreams", []):
                stream_name = stream["logStreamName"]

                success, logs_response = self.safe_api_call(
                    self.logs_client.get_log_events,
                    logGroupName=log_group,
                    logStreamName=stream_name,
                    startTime=int(self.start_date.timestamp() * 1000),
                    endTime=int(self.end_date.timestamp() * 1000),
                    limit=100,
                    startFromHead=False,
                )

                if not success:
                    continue

                for event in logs_response.get("events", []):
                    message = event["message"]
                    message_lower = message.lower()

                    for pattern_info in latency_patterns:
                        if pattern_info["pattern"].lower() in message_lower:
                            is_rate_limit = (
                                "throttl" in message_lower
                                or "429" in message_lower
                                or "too many" in message_lower
                            )

                            if is_rate_limit:
                                rate_limit_detected = True

                            timestamp = datetime.fromtimestamp(
                                event["timestamp"] / 1000, tz=timezone.utc
                            )

                            self.findings["control_plane_issues"].append(
                                {
                                    "summary": f"API Server issue: {pattern_info['issue']}",
                                    "details": {
                                        "log_stream": stream_name,
                                        "timestamp": str(timestamp),
                                        "message": message[:300],
                                        "issue_type": "rate_limiting"
                                        if is_rate_limit
                                        else "latency",
                                        "severity": "critical" if is_rate_limit else "warning",
                                        "finding_type": FindingType.HISTORICAL_EVENT,
                                        "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html",
                                    },
                                }
                            )
                            break

            # Check CloudWatch metrics for API latency
            try:
                success, metrics_response = self.safe_api_call(
                    self.cloudwatch_client.list_metrics,
                    Namespace="ContainerInsights",
                    MetricName="apiserver_request_duration_seconds",
                )

                if success and metrics_response.get("Metrics"):
                    for metric in metrics_response.get("Metrics", [])[:3]:
                        dimensions = {d["Name"]: d["Value"] for d in metric.get("Dimensions", [])}
                        if dimensions.get("ClusterName") == self.cluster_name:
                            success, data = self.safe_api_call(
                                self.cloudwatch_client.get_metric_statistics,
                                Namespace="ContainerInsights",
                                MetricName="apiserver_request_duration_seconds",
                                Dimensions=metric.get("Dimensions", []),
                                StartTime=self.start_date,
                                EndTime=self.end_date,
                                Period=300,
                                Statistics=["Maximum", "Average"],
                            )

                            if success and data.get("Datapoints"):
                                for dp in data["Datapoints"]:
                                    max_latency = dp.get("Maximum", 0)
                                    if max_latency > 1.0:  # > 1 second
                                        self.findings["control_plane_issues"].append(
                                            {
                                                "summary": f"API Server high latency detected: {max_latency:.2f}s",
                                                "details": {
                                                    "metric": "apiserver_request_duration_seconds",
                                                    "max_latency": f"{max_latency:.2f}s",
                                                    "average_latency": f"{dp.get('Average', 0):.2f}s",
                                                    "timestamp": str(
                                                        dp.get("Timestamp", "Unknown")
                                                    ),
                                                    "severity": "critical"
                                                    if max_latency > 5.0
                                                    else "warning",
                                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                                },
                                            }
                                        )
            except Exception:
                pass

            self.progress.info("API Server latency analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_apiserver_latency", "message": str(e)})
            self.progress.warning(f"API Server latency analysis failed: {e}")

    def analyze_apiserver_rate_limiting(self):
        """
        Analyze API Server rate limiting (429 errors)
        Catalog 1.2: Detects HTTP 429 responses, client-side throttling, APF saturation

        Detection:
        - [METRIC] CW: apiserver_request_total with 429 response code
        - [LOG] Control plane logs: "Throttling request", "429 Too Many Requests"
        - [LOG] Audit logs: responseStatus.code = 429
        - [API] kubectl get flowschemas, prioritylevelconfigurations

        Reference: https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html
        """
        self.progress.step("Analyzing API Server rate limiting...")

        try:
            rate_limit_findings = []
            throttled_agents = {}

            log_group = f"/aws/eks/{self.cluster_name}/cluster"

            success, response = self.safe_api_call(
                self.logs_client.describe_log_groups, logGroupNamePrefix=log_group
            )

            if not success or not response.get("logGroups"):
                self.progress.info("Control plane logging not enabled for rate limiting analysis")
                return

            rate_limit_patterns = [
                {
                    "pattern": "Throttling request",
                    "issue": "Request throttling detected",
                    "severity": "critical",
                },
                {
                    "pattern": "TooManyRequests",
                    "issue": "429 Too Many Requests",
                    "severity": "critical",
                },
                {
                    "pattern": "client side throttle",
                    "issue": "Client-side throttling",
                    "severity": "warning",
                },
                {
                    "pattern": "rate: Wait(n=",
                    "issue": "Rate limiter waiting",
                    "severity": "warning",
                },
                {
                    "pattern": "throttling request took",
                    "issue": "Throttling delay detected",
                    "severity": "warning",
                },
                {
                    "pattern": '"responseStatus":{"code":429',
                    "issue": "HTTP 429 in audit log",
                    "severity": "critical",
                },
            ]

            success, streams_response = self.safe_api_call(
                self.logs_client.describe_log_streams,
                logGroupName=log_group,
                logStreamNamePrefix="kube-apiserver-",
                orderBy="LastEventTime",
                descending=True,
                limit=10,
            )

            if not success:
                return

            for stream in streams_response.get("logStreams", []):
                stream_name = stream["logStreamName"]

                success, logs_response = self.safe_api_call(
                    self.logs_client.get_log_events,
                    logGroupName=log_group,
                    logStreamName=stream_name,
                    startTime=int(self.start_date.timestamp() * 1000),
                    endTime=int(self.end_date.timestamp() * 1000),
                    limit=200,
                    startFromHead=False,
                )

                if not success:
                    continue

                for event in logs_response.get("events", []):
                    message = event["message"]
                    message_lower = message.lower()

                    for pattern_info in rate_limit_patterns:
                        if pattern_info["pattern"].lower() in message_lower:
                            timestamp = datetime.fromtimestamp(
                                event["timestamp"] / 1000, tz=timezone.utc
                            )

                            user_agent = "unknown"
                            if "userAgent" in message:
                                ua_match = re.search(r'"userAgent":"([^"]+)"', message)
                                if ua_match:
                                    user_agent = ua_match.group(1)

                            if user_agent not in throttled_agents:
                                throttled_agents[user_agent] = 0
                            throttled_agents[user_agent] += 1

                            rate_limit_findings.append(
                                {
                                    "summary": f"API Server rate limiting: {pattern_info['issue']}",
                                    "details": {
                                        "log_stream": stream_name,
                                        "timestamp": str(timestamp),
                                        "pattern": pattern_info["pattern"],
                                        "user_agent": user_agent,
                                        "message": message[:400],
                                        "severity": pattern_info["severity"],
                                        "finding_type": FindingType.HISTORICAL_EVENT,
                                        "aws_doc": "https://kubernetes.io/docs/concepts/cluster-administration/flow-control/",
                                    },
                                }
                            )
                            break

            for finding in rate_limit_findings:
                self.findings["control_plane_issues"].append(finding)

            if throttled_agents:
                top_throttled = sorted(throttled_agents.items(), key=lambda x: x[1], reverse=True)[
                    :5
                ]

                summary_agents = ", ".join([f"{agent}: {count}" for agent, count in top_throttled])

                self.findings["control_plane_issues"].append(
                    {
                        "summary": f"API Server rate limiting summary: {len(rate_limit_findings)} events from {len(throttled_agents)} clients",
                        "details": {
                            "total_throttle_events": len(rate_limit_findings),
                            "throttled_clients": dict(top_throttled),
                            "recommendation": "Review client --kube-api-qps and --kube-api-burst settings, check APF flow schemas",
                            "severity": "warning" if len(rate_limit_findings) < 10 else "critical",
                            "finding_type": FindingType.HISTORICAL_EVENT,
                            "aws_doc": "https://kubernetes.io/docs/concepts/cluster-administration/flow-control/",
                        },
                    }
                )

            try:
                cmd = "kubectl get flowschemas -o json"
                output = self.safe_kubectl_call(cmd)

                if output:
                    flowschemas = json.loads(output)
                    for fs in flowschemas.get("items", []):
                        name = fs.get("metadata", {}).get("name", "unknown")
                        matching_cond = fs.get("status", {}).get("conditions", [])
                        for cond in matching_cond:
                            if cond.get("type") == "Dangling" and cond.get("status") == "True":
                                self.findings["control_plane_issues"].append(
                                    {
                                        "summary": f"APF FlowSchema '{name}' is dangling (no matching PriorityLevelConfiguration)",
                                        "details": {
                                            "flowschema": name,
                                            "condition": "Dangling",
                                            "recommendation": f"kubectl delete flowschema {name} or create matching PriorityLevelConfiguration",
                                            "severity": "warning",
                                            "finding_type": FindingType.CURRENT_STATE,
                                            "aws_doc": "https://kubernetes.io/docs/concepts/cluster-administration/flow-control/",
                                        },
                                    }
                                )
            except Exception:
                pass

            self.progress.info("API Server rate limiting analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_apiserver_rate_limiting", "message": str(e)})
            self.progress.warning(f"API Server rate limiting analysis failed: {e}")

    def analyze_etcd_health(self):
        """
        Analyze etcd health from control plane logs and kubectl events
        Detects slow fdatasync, quota issues, leader changes

        Catalog 1.4: etcd Storage Quota Exceeded
        Detection:
        - [LOG] CW control plane logs: "etcdserver: mvcc: database space exceeded", "ALARM NOSPACE"
        - [EVENT] kubectl events: FailedCreate with "space exceeded"
        - [API] kubectl get events --all-namespaces | grep "space exceeded"
        """
        self.progress.step("Analyzing etcd health...")

        try:
            log_group = f"/aws/eks/{self.cluster_name}/cluster"
            etcd_quota_exceeded = False

            success, response = self.safe_api_call(
                self.logs_client.describe_log_groups, logGroupNamePrefix=log_group
            )

            if not success or not response.get("logGroups"):
                return

            etcd_patterns = [
                {
                    "pattern": "etcdserver: mvcc: database space exceeded",
                    "issue": "etcd storage quota exceeded - CLUSTER READ-ONLY",
                    "severity": "critical",
                    "is_quota": True,
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html",
                    "diagnostic_steps": [
                        "Check: kubectl get events --all-namespaces | grep 'space exceeded'",
                        "Count objects: kubectl api-resources --verbs=list --namespaced=false -o name | xargs -I{} kubectl get {} --all-namespaces --no-headers 2>/dev/null | wc -l",
                        "Clean up: kubectl delete events --all-namespaces --field-selector reason!=''",
                        "Delete old ReplicaSets: kubectl get rs --all-namespaces -o json | jq '.items[] | select(.spec.replicas==0)' | kubectl delete -f -",
                        "Delete completed Pods: kubectl delete pods --all-namespaces --field-selector=status.phase==Succeeded",
                        "URGENT: Open AWS Support ticket for EKS-managed etcd defragmentation",
                    ],
                },
                {
                    "pattern": "ALARM NOSPACE",
                    "issue": "etcd alarm: no space - CLUSTER READ-ONLY",
                    "severity": "critical",
                    "is_quota": True,
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html",
                    "diagnostic_steps": [
                        "This is a P1 incident - cluster is in read-only mode",
                        "Immediately: Open AWS Support ticket for EKS-managed etcd",
                        "Clean up objects to reduce database size",
                        "Review event TTL settings after recovery",
                    ],
                },
                {
                    "pattern": "etcdserver: slow fdatasync",
                    "issue": "etcd slow disk I/O",
                    "severity": "critical",
                    "is_quota": False,
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html",
                    "diagnostic_steps": [
                        "Check for high object count in cluster",
                        "Review CloudWatch for API server latency correlation",
                        "Consider reducing object churn rate",
                    ],
                },
                {
                    "pattern": "etcdserver: request timed out",
                    "issue": "etcd request timeout",
                    "severity": "critical",
                    "is_quota": False,
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html",
                },
                {
                    "pattern": "etcdserver: leader changed",
                    "issue": "etcd leader election",
                    "severity": "warning",
                    "is_quota": False,
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html",
                },
                {
                    "pattern": "waiting for ReadIndex response took too long",
                    "issue": "etcd ReadIndex latency",
                    "severity": "warning",
                    "is_quota": False,
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html",
                },
                {
                    "pattern": "apply request took too long",
                    "issue": "etcd apply latency",
                    "severity": "warning",
                    "is_quota": False,
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html",
                },
                {
                    "pattern": "lost leader",
                    "issue": "etcd lost leader",
                    "severity": "critical",
                    "is_quota": False,
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html",
                },
            ]

            success, streams_response = self.safe_api_call(
                self.logs_client.describe_log_streams,
                logGroupName=log_group,
                orderBy="LastEventTime",
                descending=True,
                limit=5,
            )

            if not success:
                return

            for stream in streams_response.get("logStreams", []):
                stream_name = stream["logStreamName"]

                success, logs_response = self.safe_api_call(
                    self.logs_client.get_log_events,
                    logGroupName=log_group,
                    logStreamName=stream_name,
                    startTime=int(self.start_date.timestamp() * 1000),
                    endTime=int(self.end_date.timestamp() * 1000),
                    limit=100,
                    startFromHead=False,
                )

                if not success:
                    continue

                for event in logs_response.get("events", []):
                    message = event["message"]
                    message_lower = message.lower()

                    for pattern_info in etcd_patterns:
                        if pattern_info["pattern"].lower() in message_lower:
                            timestamp = datetime.fromtimestamp(
                                event["timestamp"] / 1000, tz=timezone.utc
                            )

                            if pattern_info.get("is_quota"):
                                etcd_quota_exceeded = True

                            finding_details = {
                                "log_stream": stream_name,
                                "timestamp": str(timestamp),
                                "message": message[:300],
                                "severity": pattern_info["severity"],
                                "finding_type": FindingType.HISTORICAL_EVENT,
                                "root_causes": [
                                    "High object count in cluster",
                                    "Disk I/O saturation",
                                    "Insufficient control plane resources",
                                    "Network latency to etcd",
                                ],
                                "aws_doc": pattern_info["aws_doc"],
                            }

                            if pattern_info.get("diagnostic_steps"):
                                finding_details["diagnostic_steps"] = pattern_info[
                                    "diagnostic_steps"
                                ]

                            if pattern_info.get("is_quota"):
                                finding_details["impact"] = (
                                    "Cluster is in READ-ONLY mode - no create/update/delete operations possible"
                                )
                                finding_details["immediate_action"] = (
                                    "Open AWS Support ticket for EKS-managed etcd defragmentation"
                                )

                            self.findings["control_plane_issues"].append(
                                {
                                    "summary": f"etcd issue: {pattern_info['issue']}",
                                    "details": finding_details,
                                }
                            )
                            break

            try:
                cmd = "kubectl get events --all-namespaces -o json"
                output = self.safe_kubectl_call(cmd)

                if output:
                    events = json.loads(output)
                    for evt in events.get("items", []):
                        message = evt.get("message", "").lower()
                        reason = evt.get("reason", "")

                        if "space exceeded" in message or "database space" in message:
                            namespace = evt.get("metadata", {}).get("namespace", "unknown")
                            involved_obj = evt.get("involvedObject", {})
                            obj_name = involved_obj.get("name", "unknown")
                            obj_kind = involved_obj.get("kind", "unknown")
                            timestamp = evt.get("lastTimestamp", evt.get("eventTime", "unknown"))

                            etcd_quota_exceeded = True

                            self.findings["control_plane_issues"].append(
                                {
                                    "summary": f"etcd quota exceeded: Failed to create {obj_kind}/{obj_name} in {namespace}",
                                    "details": {
                                        "namespace": namespace,
                                        "resource": f"{obj_kind}/{obj_name}",
                                        "reason": reason,
                                        "message": evt.get("message", "")[:200],
                                        "timestamp": str(timestamp),
                                        "severity": "critical",
                                        "finding_type": FindingType.HISTORICAL_EVENT,
                                        "impact": "Cluster is in READ-ONLY mode",
                                        "diagnostic_steps": [
                                            "URGENT: Open AWS Support ticket for EKS etcd defragmentation",
                                            "Clean up: kubectl delete events --all-namespaces --field-selector reason!=''",
                                            "Delete old ReplicaSets with 0 replicas",
                                            "Delete completed Pods",
                                            "Implement ongoing cleanup CronJob for Events and old ReplicaSets",
                                        ],
                                        "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html",
                                    },
                                }
                            )
            except Exception:
                pass

            try:
                cmd = "kubectl get events --all-namespaces --field-selector reason=FailedCreate -o json"
                output = self.safe_kubectl_call(cmd)

                if output:
                    events = json.loads(output)
                    for evt in events.get("items", []):
                        message = evt.get("message", "").lower()
                        if "exceeded" in message and "quota" not in message:
                            namespace = evt.get("metadata", {}).get("namespace", "unknown")
                            involved_obj = evt.get("involvedObject", {})
                            obj_name = involved_obj.get("name", "unknown")
                            obj_kind = involved_obj.get("kind", "unknown")

                            if "space" in message or "database" in message:
                                etcd_quota_exceeded = True
                                self.findings["control_plane_issues"].append(
                                    {
                                        "summary": f"etcd quota exceeded event: {obj_kind}/{obj_name} in {namespace}",
                                        "details": {
                                            "namespace": namespace,
                                            "resource": f"{obj_kind}/{obj_name}",
                                            "message": evt.get("message", "")[:200],
                                            "severity": "critical",
                                            "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html",
                                        },
                                    }
                                )
            except Exception:
                pass

            if etcd_quota_exceeded:
                self.findings["control_plane_issues"].append(
                    {
                        "summary": "CRITICAL: etcd storage quota exceeded detected - cluster may be read-only",
                        "details": {
                            "severity": "critical",
                            "impact": "All create/update/delete operations will fail until etcd is compacted",
                            "immediate_action": "Open AWS Support ticket immediately for EKS-managed etcd defragmentation",
                            "cleanup_commands": [
                                "kubectl delete events --all-namespaces --field-selector reason!=''",
                                "kubectl get rs --all-namespaces -o json | jq '.items[] | select(.spec.replicas==0)' | kubectl delete -f -",
                                "kubectl delete pods --all-namespaces --field-selector=status.phase==Succeeded",
                            ],
                            "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html",
                        },
                    }
                )

            self.progress.info("etcd health analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_etcd_health", "message": str(e)})
            self.progress.warning(f"etcd health analysis failed: {e}")

    def analyze_controller_manager(self):
        """
        Analyze kube-controller-manager health
        Detects reconciliation failures, panics, rate limiting
        """
        self.progress.step("Analyzing Controller Manager...")

        try:
            log_group = f"/aws/eks/{self.cluster_name}/cluster"

            success, response = self.safe_api_call(
                self.logs_client.describe_log_groups, logGroupNamePrefix=log_group
            )

            if not success or not response.get("logGroups"):
                return

            controller_patterns = [
                {
                    "pattern": "error syncing",
                    "issue": "Controller sync error",
                    "severity": "critical",
                },
                {
                    "pattern": "requeue",
                    "issue": "Controller requeuing frequently",
                    "severity": "warning",
                },
                {
                    "pattern": "failed to sync",
                    "issue": "Controller sync failure",
                    "severity": "critical",
                },
                {
                    "pattern": "rate limiter",
                    "issue": "Controller rate limited",
                    "severity": "warning",
                },
                {
                    "pattern": "panic",
                    "issue": "Controller panic detected",
                    "severity": "critical",
                },
                {
                    "pattern": "FailedCreate",
                    "issue": "Controller failed to create resource",
                    "severity": "warning",
                },
                {
                    "pattern": "FailedUpdate",
                    "issue": "Controller failed to update resource",
                    "severity": "warning",
                },
            ]

            success, streams_response = self.safe_api_call(
                self.logs_client.describe_log_streams,
                logGroupName=log_group,
                logStreamNamePrefix="kube-controller-manager-",
                orderBy="LastEventTime",
                descending=True,
                limit=3,
            )

            if not success:
                return

            for stream in streams_response.get("logStreams", []):
                stream_name = stream["logStreamName"]

                success, logs_response = self.safe_api_call(
                    self.logs_client.get_log_events,
                    logGroupName=log_group,
                    logStreamName=stream_name,
                    startTime=int(self.start_date.timestamp() * 1000),
                    endTime=int(self.end_date.timestamp() * 1000),
                    limit=100,
                    startFromHead=False,
                )

                if not success:
                    continue

                for event in logs_response.get("events", []):
                    message = event["message"]
                    message_lower = message.lower()

                    # Skip benign patterns
                    if any(p in message_lower for p in CONTROL_PLANE_BENIGN_PATTERNS):
                        continue

                    for pattern_info in controller_patterns:
                        if pattern_info["pattern"].lower() in message_lower:
                            timestamp = datetime.fromtimestamp(
                                event["timestamp"] / 1000, tz=timezone.utc
                            )

                            self.findings["control_plane_issues"].append(
                                {
                                    "summary": f"Controller Manager: {pattern_info['issue']}",
                                    "details": {
                                        "log_stream": stream_name,
                                        "timestamp": str(timestamp),
                                        "message": message[:300],
                                        "severity": pattern_info["severity"],
                                        "finding_type": FindingType.HISTORICAL_EVENT,
                                        "root_causes": [
                                            "RBAC permission issues",
                                            "Resource quota exceeded",
                                            "API server latency",
                                            "Invalid resource configuration",
                                        ],
                                        "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html",
                                    },
                                }
                            )
                            break

            self.progress.info("Controller Manager analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_controller_manager", "message": str(e)})
            self.progress.warning(f"Controller Manager analysis failed: {e}")

    def analyze_admission_webhooks(self):
        """
        Analyze admission webhook health
        Detects timeouts, failures, certificate issues
        """
        self.progress.step("Analyzing Admission Webhooks...")

        try:
            # Check validating webhooks
            cmd = "kubectl get validatingwebhookconfigurations -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                webhooks = json.loads(output)

                for webhook in webhooks.get("items", []):
                    webhook_name = webhook["metadata"]["name"]
                    webhook_config = webhook.get("webhooks", [])

                    for wh in webhook_config:
                        wh_name = wh.get("name", "unknown")
                        failure_policy = wh.get("failurePolicy", "Fail")
                        timeout_seconds = wh.get("timeoutSeconds", 30)

                        # Check for potentially problematic configurations
                        if failure_policy == "Fail" and timeout_seconds < 10:
                            self.findings["control_plane_issues"].append(
                                {
                                    "summary": f"Admission webhook {webhook_name}/{wh_name} has aggressive timeout ({timeout_seconds}s)",
                                    "details": {
                                        "webhook_config": webhook_name,
                                        "webhook_name": wh_name,
                                        "failure_policy": failure_policy,
                                        "timeout_seconds": timeout_seconds,
                                        "severity": "warning",
                                        "finding_type": FindingType.CURRENT_STATE,
                                        "recommendation": "Consider increasing timeout or changing failurePolicy to Ignore",
                                    },
                                }
                            )

            # Check for webhook-related events
            cmd = "kubectl get events --all-namespaces -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                webhook_error_patterns = [
                    "webhook",
                    "failed calling",
                    "postman",
                    "admission webhook",
                    "denied the request",
                ]

                for event in events.get("items", []):
                    message = event.get("message", "").lower()
                    reason = event.get("reason", "")

                    if (
                        any(p in message for p in webhook_error_patterns)
                        or "webhook" in reason.lower()
                    ):
                        involved = event.get("involvedObject", {})
                        self.findings["control_plane_issues"].append(
                            {
                                "summary": f"Admission webhook error: {involved.get('namespace', 'unknown')}/{involved.get('name', 'unknown')}",
                                "details": {
                                    "namespace": involved.get("namespace", "Unknown"),
                                    "object": involved.get("name", "Unknown"),
                                    "reason": reason,
                                    "message": event.get("message", "N/A")[:300],
                                    "timestamp": event.get("lastTimestamp", "Unknown"),
                                    "severity": "critical",
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                    "root_causes": [
                                        "Webhook service unavailable",
                                        "Webhook TLS certificate expired",
                                        "Webhook timeout",
                                        "Network policy blocking webhook traffic",
                                    ],
                                    "aws_doc": "https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/",
                                },
                            }
                        )

            self.progress.info("Admission webhook analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_admission_webhooks", "message": str(e)})
            self.progress.warning(f"Admission webhook analysis failed: {e}")

    def analyze_pleg_health(self):
        """
        Analyze PLEG (Pod Lifecycle Event Generator) health
        Detects PLEG not healthy issues
        """
        self.progress.step("Analyzing PLEG health...")

        try:
            # Check nodes for PLEG issues
            cmd = "kubectl get nodes -o json"
            output = self.safe_kubectl_call(cmd)

            if output:
                nodes = json.loads(output)

                for node in nodes.get("items", []):
                    node_name = node["metadata"]["name"]
                    conditions = node.get("status", {}).get("conditions", [])

                    for condition in conditions:
                        if condition.get("type") == "Ready" and condition.get("status") != "True":
                            message = condition.get("message", "").lower()
                            reason = condition.get("reason", "").lower()

                            if "pleg" in message or "pleg" in reason:
                                self.findings["node_issues"].append(
                                    {
                                        "summary": f"Node {node_name} has PLEG health issues",
                                        "details": {
                                            "node": node_name,
                                            "reason": condition.get("reason", "Unknown"),
                                            "message": condition.get("message", "N/A")[:300],
                                            "severity": "critical",
                                            "finding_type": FindingType.CURRENT_STATE,
                                            "root_causes": [
                                                "Container runtime unresponsive",
                                                "Zombie containers blocking PLEG",
                                                "High CPU/IO on node",
                                                "Containerd/docker process hung",
                                            ],
                                            "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html",
                                        },
                                    }
                                )

            # Check events for PLEG issues
            cmd = "kubectl get events --all-namespaces -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                for event in events.get("items", []):
                    message = event.get("message", "").lower()
                    if "pleg" in message and "not healthy" in message:
                        involved = event.get("involvedObject", {})
                        self.findings["node_issues"].append(
                            {
                                "summary": f"PLEG not healthy on {involved.get('name', 'unknown')}",
                                "details": {
                                    "node": involved.get("name", "Unknown"),
                                    "message": event.get("message", "N/A")[:200],
                                    "timestamp": event.get("lastTimestamp", "Unknown"),
                                    "severity": "critical",
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                },
                            }
                        )

            self.progress.info("PLEG health analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_pleg_health", "message": str(e)})
            self.progress.warning(f"PLEG health analysis failed: {e}")

    def analyze_container_runtime(self):
        """
        Analyze container runtime (containerd) health
        Detects runtime unresponsive issues
        """
        self.progress.step("Analyzing Container Runtime health...")

        try:
            # Check for runtime-related events
            cmd = "kubectl get events --all-namespaces -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                runtime_error_patterns = [
                    "runtime not responding",
                    "container runtime is down",
                    "failed to get container info",
                    "RuntimeHandler not supported",
                    "grpc: the client connection is closing",
                ]

                for event in events.get("items", []):
                    message = event.get("message", "").lower()

                    if any(p in message for p in runtime_error_patterns):
                        involved = event.get("involvedObject", {})
                        self.findings["node_issues"].append(
                            {
                                "summary": f"Container runtime issue on {involved.get('name', 'unknown')}",
                                "details": {
                                    "node": involved.get("name", "Unknown"),
                                    "namespace": involved.get("namespace", "Unknown"),
                                    "message": event.get("message", "N/A")[:200],
                                    "timestamp": event.get("lastTimestamp", "Unknown"),
                                    "severity": "critical",
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                    "root_causes": [
                                        "Containerd process crashed",
                                        "Containerd OOMKilled",
                                        "Containerd version incompatibility",
                                        "Node resource exhaustion",
                                    ],
                                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html",
                                },
                            }
                        )

            # Check node conditions for runtime issues
            cmd = "kubectl get nodes -o json"
            output = self.safe_kubectl_call(cmd)

            if output:
                nodes = json.loads(output)

                for node in nodes.get("items", []):
                    node_name = node["metadata"]["name"]
                    conditions = node.get("status", {}).get("conditions", [])

                    for condition in conditions:
                        if condition.get("type") == "Ready" and condition.get("status") != "True":
                            message = condition.get("message", "").lower()
                            if "runtime" in message or "container" in message:
                                self.findings["node_issues"].append(
                                    {
                                        "summary": f"Node {node_name} has container runtime issues",
                                        "details": {
                                            "node": node_name,
                                            "message": condition.get("message", "N/A"),
                                            "severity": "critical",
                                            "finding_type": FindingType.CURRENT_STATE,
                                        },
                                    }
                                )

            self.progress.info("Container Runtime analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_container_runtime", "message": str(e)})
            self.progress.warning(f"Container Runtime analysis failed: {e}")

    def analyze_pause_image_issues(self):
        """
        Analyze pause container image issues
        Catalog: CNI Misconfiguration - pause image missing/garbage-collected

        Detection:
        - Events: "failed to get sandbox image"
        - Events: "image ... not found" for pause image
        - Pods stuck in ContainerCreating due to sandbox creation failure

        The pause container (sandbox) is required for every pod. If it's garbage-collected
        or unavailable, pods cannot be created on that node.
        """
        self.progress.step("Analyzing pause image issues...")

        try:
            pause_image_issues = []

            # Check for sandbox/pause image errors in events
            cmd = "kubectl get events --all-namespaces -o json"
            output = self.safe_kubectl_call(cmd)

            if output:
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                pause_error_patterns = [
                    "failed to get sandbox image",
                    "sandbox image",
                    "pause" in "".join([]).lower() and "not found",
                    "image .*pause.* not found",
                    "failed to create pod sandbox",
                    "PodSandbox",
                ]

                for event in events.get("items", []):
                    message = event.get("message", "").lower()
                    reason = event.get("reason", "")

                    is_pause_issue = False
                    issue_type = "unknown"

                    if "sandbox image" in message and ("fail" in message or "not found" in message):
                        is_pause_issue = True
                        issue_type = "sandbox_image_missing"
                    elif "pause" in message and ("not found" in message or "fail" in message):
                        is_pause_issue = True
                        issue_type = "pause_image_missing"
                    elif "failed to create pod sandbox" in message:
                        is_pause_issue = True
                        issue_type = "sandbox_creation_failed"
                    elif reason == "FailedCreatePodSandBox":
                        is_pause_issue = True
                        issue_type = "sandbox_creation_failed"

                    if is_pause_issue:
                        involved = event.get("involvedObject", {})
                        namespace = event["metadata"]["namespace"]
                        timestamp = event.get("lastTimestamp", event.get("eventTime", "Unknown"))

                        pause_image_issues.append(
                            {
                                "summary": f"Pause/sandbox image issue: {involved.get('name', 'unknown')} in {namespace}",
                                "details": {
                                    "namespace": namespace,
                                    "pod": involved.get("name", "unknown"),
                                    "issue_type": issue_type,
                                    "reason": reason,
                                    "message": event.get("message", "")[:300],
                                    "timestamp": str(timestamp),
                                    "severity": "critical",
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                    "root_causes": [
                                        "Pause container image garbage-collected by kubelet",
                                        "Container image cache cleared",
                                        "Registry connectivity issues",
                                        "Disk pressure caused image cleanup",
                                    ],
                                    "impact": "Pods cannot be created on affected node(s)",
                                    "diagnostic_steps": [
                                        "Identify affected node from event",
                                        "SSH to node: crictl images | grep pause",
                                        "If missing, pull manually: crictl pull <pause-image>",
                                        "Check kubelet garbage collection settings",
                                        "Prevent future: increase image-gc-high-threshold",
                                    ],
                                    "aws_doc": "https://kubernetes.io/docs/concepts/workloads/pods/pause-container/",
                                },
                            }
                        )

            # Check for pods stuck in ContainerCreating that might be due to pause image
            cmd = "kubectl get pods --all-namespaces --field-selector=status.phase=Pending -o json"
            output = self.safe_kubectl_call(cmd)

            if output:
                pods = json.loads(output)

                for pod in pods.get("items", []):
                    pod_name = pod["metadata"]["name"]
                    namespace = pod["metadata"]["namespace"]
                    pod_ip = pod.get("status", {}).get("podIP", "")

                    # If pod is Pending but has no IP, might be sandbox issue
                    if not pod_ip:
                        container_statuses = pod.get("status", {}).get("containerStatuses", [])
                        init_statuses = pod.get("status", {}).get("initContainerStatuses", [])

                        # Check if any container shows sandbox-related waiting reason
                        for status in container_statuses + init_statuses:
                            waiting = status.get("state", {}).get("waiting", {})
                            reason = waiting.get("reason", "")
                            message = waiting.get("message", "").lower()

                            if reason in [
                                "ContainerCreating",
                                "CreateContainerConfigError",
                            ]:
                                if "sandbox" in message or "pause" in message or "image" in message:
                                    pause_image_issues.append(
                                        {
                                            "summary": f"Pod {namespace}/{pod_name} may be blocked by sandbox image issue",
                                            "details": {
                                                "pod": pod_name,
                                                "namespace": namespace,
                                                "container": status.get("name", "unknown"),
                                                "reason": reason,
                                                "message": waiting.get("message", "")[:200],
                                                "severity": "warning",
                                                "diagnostic_steps": [
                                                    f"kubectl describe pod {pod_name} -n {namespace}",
                                                    "Check node events for sandbox image errors",
                                                    "Verify pause image is available on node",
                                                ],
                                            },
                                        }
                                    )

            # Add findings
            for issue in pause_image_issues:
                self.findings["node_issues"].append(issue)

            # Summary if multiple nodes affected
            if len(pause_image_issues) > 3:
                affected_pods = set()
                for issue in pause_image_issues:
                    if "pod" in issue.get("details", {}):
                        affected_pods.add(issue["details"]["pod"])

                self.findings["node_issues"].append(
                    {
                        "summary": f"Multiple pause/sandbox image issues detected: {len(affected_pods)} pods affected",
                        "details": {
                            "issue_count": len(pause_image_issues),
                            "affected_pods": list(affected_pods)[:10],
                            "severity": "critical",
                            "recommendation": "Check for disk pressure on nodes triggering aggressive garbage collection. Consider increasing kubelet --image-gc-high-threshold.",
                            "aws_doc": "https://kubernetes.io/docs/concepts/workloads/pods/pause-container/",
                        },
                    }
                )

            self.progress.info(
                f"Pause image analysis completed ({len(pause_image_issues)} issues found)"
            )

        except Exception as e:
            self.errors.append({"step": "analyze_pause_image_issues", "message": str(e)})
            self.progress.warning(f"Pause image analysis failed: {e}")

    def analyze_pods_terminating(self):
        """
        Analyze pods stuck in Terminating state
        Detects finalizers, volume detach issues
        """
        self.progress.step("Analyzing stuck Terminating pods...")

        try:
            cmd = "kubectl get pods --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get pods -n {self.namespace} -o json"

            output = self.safe_kubectl_call(cmd)
            if not output:
                return

            pods = json.loads(output)

            for pod in pods.get("items", []):
                pod_name = pod["metadata"]["name"]
                namespace = pod["metadata"]["namespace"]
                deletion_ts = pod["metadata"].get("deletionTimestamp")
                finalizers = pod["metadata"].get("finalizers", [])

                if deletion_ts:
                    # Pod is being deleted but still exists
                    self.findings["pod_errors"].append(
                        {
                            "summary": f"Pod {namespace}/{pod_name} stuck in Terminating",
                            "details": {
                                "pod": pod_name,
                                "namespace": namespace,
                                "deletion_timestamp": deletion_ts,
                                "finalizers": finalizers,
                                "severity": "warning" if not finalizers else "info",
                                "finding_type": FindingType.CURRENT_STATE,
                                "root_causes": [
                                    "Finalizer blocking deletion",
                                    "PreStop hook stuck",
                                    "Volume detach failure",
                                    "Node unreachable",
                                ],
                                "aws_doc": "https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination",
                            },
                        }
                    )

            # Check for volume detach events
            cmd = "kubectl get events --all-namespaces --field-selector reason=FailedMount -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                for event in events.get("items", []):
                    message = event.get("message", "").lower()
                    if "detach" in message or "unmount" in message:
                        involved = event.get("involvedObject", {})
                        self.findings["pvc_issues"].append(
                            {
                                "summary": f"Volume detach/unmount issue for {involved.get('namespace', 'unknown')}/{involved.get('name', 'unknown')}",
                                "details": {
                                    "pod": involved.get("name", "Unknown"),
                                    "namespace": involved.get("namespace", "Unknown"),
                                    "message": event.get("message", "N/A")[:200],
                                    "timestamp": event.get("lastTimestamp", "Unknown"),
                                    "severity": "warning",
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                },
                            }
                        )

            self.progress.info("Stuck Terminating pods analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_pods_terminating", "message": str(e)})
            self.progress.warning(f"Stuck Terminating pods analysis failed: {e}")

    def analyze_deployment_rollouts(self):
        """
        Analyze deployment rollout issues
        Detects stuck rollouts, ProgressDeadlineExceeded
        """
        self.progress.step("Analyzing Deployment rollouts...")

        try:
            cmd = "kubectl get deployments --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get deployments -n {self.namespace} -o json"

            output = self.safe_kubectl_call(cmd)
            if not output:
                return

            deployments = json.loads(output)

            for deploy in deployments.get("items", []):
                deploy_name = deploy["metadata"]["name"]
                namespace = deploy["metadata"]["namespace"]
                spec = deploy.get("spec", {})
                status = deploy.get("status", {})

                replicas = spec.get("replicas", 1)
                updated_replicas = status.get("updatedReplicas", 0)
                ready_replicas = status.get("readyReplicas", 0)
                available_replicas = status.get("availableReplicas", 0)
                unavailable_replicas = status.get("unavailableReplicas", 0)

                conditions = status.get("conditions", [])

                for condition in conditions:
                    cond_type = condition.get("type", "")
                    cond_status = condition.get("status", "")
                    cond_reason = condition.get("reason", "")
                    cond_message = condition.get("message", "")

                    if cond_status != "True":
                        if cond_type == "Progressing":
                            self.findings["pod_errors"].append(
                                {
                                    "summary": f"Deployment {namespace}/{deploy_name} rollout not progressing",
                                    "details": {
                                        "deployment": deploy_name,
                                        "namespace": namespace,
                                        "condition": cond_type,
                                        "reason": cond_reason,
                                        "message": cond_message[:200],
                                        "replicas": replicas,
                                        "updated": updated_replicas,
                                        "ready": ready_replicas,
                                        "available": available_replicas,
                                        "severity": "critical"
                                        if "Deadline" in cond_reason
                                        else "warning",
                                        "finding_type": FindingType.CURRENT_STATE,
                                        "root_causes": [
                                            "New pods failing to start",
                                            "Image pull failures",
                                            "Resource constraints",
                                            "Probe failures",
                                            "Pending PVCs",
                                        ],
                                        "aws_doc": "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/",
                                    },
                                }
                            )
                        elif cond_type == "Available":
                            self.findings["pod_errors"].append(
                                {
                                    "summary": f"Deployment {namespace}/{deploy_name} not available",
                                    "details": {
                                        "deployment": deploy_name,
                                        "namespace": namespace,
                                        "condition": cond_type,
                                        "reason": cond_reason,
                                        "message": cond_message[:200],
                                        "severity": "warning",
                                        "finding_type": FindingType.CURRENT_STATE,
                                    },
                                }
                            )

                # Check for replica mismatch
                if unavailable_replicas > 0 or (replicas > 0 and ready_replicas < replicas):
                    self.findings["pod_errors"].append(
                        {
                            "summary": f"Deployment {namespace}/{deploy_name} has unavailable replicas ({unavailable_replicas})",
                            "details": {
                                "deployment": deploy_name,
                                "namespace": namespace,
                                "desired": replicas,
                                "ready": ready_replicas,
                                "available": available_replicas,
                                "unavailable": unavailable_replicas,
                                "severity": "warning" if ready_replicas > 0 else "critical",
                                "finding_type": FindingType.CURRENT_STATE,
                            },
                        }
                    )

            self.progress.info("Deployment rollout analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_deployment_rollouts", "message": str(e)})
            self.progress.warning(f"Deployment rollout analysis failed: {e}")

    def analyze_jobs_cronjobs(self):
        """
        Analyze Job and CronJob failures
        Detects BackoffLimitExceeded, missed schedules
        """
        self.progress.step("Analyzing Jobs and CronJobs...")

        try:
            # Check Jobs
            cmd = "kubectl get jobs --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get jobs -n {self.namespace} -o json"

            output = self.safe_kubectl_call(cmd)
            if output:
                jobs = json.loads(output)

                for job in jobs.get("items", []):
                    job_name = job["metadata"]["name"]
                    namespace = job["metadata"]["namespace"]
                    spec = job.get("spec", {})
                    status = job.get("status", {})

                    backoff_limit = spec.get("backoffLimit", 6)
                    failed = status.get("failed", 0)
                    succeeded = status.get("succeeded", 0)
                    active = status.get("active", 0)

                    conditions = status.get("conditions", [])

                    for condition in conditions:
                        cond_type = condition.get("type", "")
                        cond_reason = condition.get("reason", "")

                        if cond_type == "Failed":
                            self.findings["pod_errors"].append(
                                {
                                    "summary": f"Job {namespace}/{job_name} failed: {cond_reason}",
                                    "details": {
                                        "job": job_name,
                                        "namespace": namespace,
                                        "type": "Job",
                                        "reason": cond_reason,
                                        "message": condition.get("message", "N/A")[:200],
                                        "failed": failed,
                                        "succeeded": succeeded,
                                        "backoff_limit": backoff_limit,
                                        "severity": "critical",
                                        "finding_type": FindingType.CURRENT_STATE,
                                        "root_causes": [
                                            "Application error in job pod",
                                            "OOMKilled",
                                            "ConfigMap/Secret missing",
                                            "Resource quota exceeded",
                                            "Deadline exceeded",
                                        ],
                                        "aws_doc": "https://kubernetes.io/docs/concepts/workloads/controllers/job/",
                                    },
                                }
                            )

                    if failed > 0 and failed >= backoff_limit:
                        self.findings["pod_errors"].append(
                            {
                                "summary": f"Job {namespace}/{job_name} exceeded backoff limit ({backoff_limit})",
                                "details": {
                                    "job": job_name,
                                    "namespace": namespace,
                                    "failed": failed,
                                    "backoff_limit": backoff_limit,
                                    "severity": "critical",
                                    "finding_type": FindingType.CURRENT_STATE,
                                },
                            }
                        )

            # Check CronJobs
            cmd = "kubectl get cronjobs --all-namespaces -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                cronjobs = json.loads(output)

                for cj in cronjobs.get("items", []):
                    cj_name = cj["metadata"]["name"]
                    namespace = cj["metadata"]["namespace"]
                    status = cj.get("status", {})

                    last_schedule = status.get("lastScheduleTime")
                    last_successful = status.get("lastSuccessfulTime")

                    spec = cj.get("spec", {})
                    schedule = spec.get("schedule", "unknown")
                    suspended = spec.get("suspend", False)

                    if not suspended and last_schedule:
                        try:
                            from dateutil import parser as date_parser

                            last_schedule_dt = date_parser.parse(last_schedule)
                            time_since_schedule = datetime.now(timezone.utc) - last_schedule_dt

                            # If last schedule was more than 2x the expected interval, flag it
                            # This is a heuristic - could be improved with cron parsing
                            if time_since_schedule.total_seconds() > 3600:  # > 1 hour
                                self.findings["pod_errors"].append(
                                    {
                                        "summary": f"CronJob {namespace}/{cj_name} may have missed schedules",
                                        "details": {
                                            "cronjob": cj_name,
                                            "namespace": namespace,
                                            "schedule": schedule,
                                            "last_schedule": last_schedule,
                                            "last_successful": last_successful,
                                            "suspended": suspended,
                                            "severity": "warning",
                                            "finding_type": FindingType.CURRENT_STATE,
                                            "root_causes": [
                                                "CronJob controller issues",
                                                "Previous job still running",
                                                "Concurrency policy blocking",
                                                "startingDeadlineSeconds exceeded",
                                            ],
                                        },
                                    }
                                )
                        except Exception:
                            pass

            self.progress.info("Jobs/CronJobs analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_jobs_cronjobs", "message": str(e)})
            self.progress.warning(f"Jobs/CronJobs analysis failed: {e}")

    def analyze_network_policies(self):
        """
        Analyze NetworkPolicies for potential blocking issues
        Detects policies that might block critical traffic
        """
        self.progress.step("Analyzing NetworkPolicies...")

        try:
            cmd = "kubectl get networkpolicies --all-namespaces -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if not output or "not found" in output.lower():
                self.progress.info("No NetworkPolicies found")
                return

            netpols = json.loads(output)
            restrictive_policies = []

            for netpol in netpols.get("items", []):
                np_name = netpol["metadata"]["name"]
                namespace = netpol["metadata"]["namespace"]
                spec = netpol.get("spec", {})

                pod_selector = spec.get("podSelector", {})
                ingress_rules = spec.get("ingress", [])
                egress_rules = spec.get("egress", [])

                # Check for potentially restrictive policies
                is_restrictive = False
                issues = []

                # If egress is specified but doesn't allow DNS
                if egress_rules:
                    allows_dns = False
                    for rule in egress_rules:
                        ports = rule.get("ports", [])
                        for port in ports:
                            if port.get("port") in [53, "53"] and port.get("protocol", "TCP") in [
                                "UDP",
                                "TCP",
                            ]:
                                allows_dns = True

                    if not allows_dns:
                        is_restrictive = True
                        issues.append("Egress rules may block DNS traffic (port 53)")

                # Check for ingress that might block health checks
                if ingress_rules:
                    for rule in ingress_rules:
                        # If it specifies from but doesn't include kube-system
                        from_rules = rule.get("from", [])
                        if from_rules and len(from_rules) > 0:
                            allows_health_checks = any(
                                fr.get("namespaceSelector", {})
                                .get("matchLabels", {})
                                .get("kubernetes.io/metadata.name")
                                == "kube-system"
                                or not fr.get("namespaceSelector")  # allows all
                                for fr in from_rules
                            )

                if is_restrictive or issues:
                    self.findings["network_issues"].append(
                        {
                            "summary": f"NetworkPolicy {namespace}/{np_name} may be blocking traffic",
                            "details": {
                                "networkpolicy": np_name,
                                "namespace": namespace,
                                "pod_selector": str(pod_selector),
                                "ingress_rules_count": len(ingress_rules),
                                "egress_rules_count": len(egress_rules),
                                "issues": issues,
                                "severity": "warning",
                                "finding_type": FindingType.CURRENT_STATE,
                                "root_causes": [
                                    "Missing DNS egress rule",
                                    "Blocking health check probes",
                                    "Missing namespace selector for kube-system",
                                    "Too restrictive pod selector",
                                ],
                                "aws_doc": "https://kubernetes.io/docs/concepts/services-networking/network-policies/",
                            },
                        }
                    )

            self.progress.info(
                f"NetworkPolicy analysis completed ({len(netpols.get('items', []))} policies)"
            )

        except Exception as e:
            self.errors.append({"step": "analyze_network_policies", "message": str(e)})
            self.progress.warning(f"NetworkPolicy analysis failed: {e}")

    def analyze_alb_health(self):
        """
        Analyze AWS Load Balancer Controller and ALB health
        Detects 5xx errors, unhealthy targets
        """
        self.progress.step("Analyzing ALB health...")

        try:
            # Check AWS Load Balancer Controller
            cmd = "kubectl get deployment aws-load-balancer-controller -n kube-system -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                deployment = json.loads(output)
                status = deployment.get("status", {})
                replicas = status.get("replicas", 0)
                ready = status.get("readyReplicas", 0)

                if ready < replicas:
                    self.findings["network_issues"].append(
                        {
                            "summary": "AWS Load Balancer Controller not healthy",
                            "details": {
                                "component": "aws-load-balancer-controller",
                                "namespace": "kube-system",
                                "replicas": replicas,
                                "ready": ready,
                                "severity": "critical",
                                "finding_type": FindingType.CURRENT_STATE,
                            },
                        }
                    )

            # Check Ingress resources for issues
            cmd = "kubectl get ingress --all-namespaces -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                ingresses = json.loads(output)

                for ing in ingresses.get("items", []):
                    ing_name = ing["metadata"]["name"]
                    namespace = ing["metadata"]["namespace"]
                    status = ing.get("status", {})

                    load_balancer = status.get("loadBalancer", {})
                    ingress_list = load_balancer.get("ingress", [])

                    if not ingress_list:
                        # Ingress has no LB assigned
                        annotations = ing["metadata"].get("annotations", {})
                        if "alb.ingress.kubernetes.io" in str(annotations):
                            self.findings["network_issues"].append(
                                {
                                    "summary": f"ALB Ingress {namespace}/{ing_name} has no load balancer",
                                    "details": {
                                        "ingress": ing_name,
                                        "namespace": namespace,
                                        "severity": "warning",
                                        "finding_type": FindingType.CURRENT_STATE,
                                        "root_causes": [
                                            "AWS LB Controller not running",
                                            "Subnet not tagged for ELB",
                                            "IAM permissions missing",
                                            "Invalid annotations",
                                        ],
                                        "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html",
                                    },
                                }
                            )

            # Check CloudWatch for ALB metrics
            try:
                success, metrics_response = self.safe_api_call(
                    self.cloudwatch_client.list_metrics,
                    Namespace="AWS/ApplicationELB",
                )

                if success and metrics_response.get("Metrics"):
                    for metric in metrics_response.get("Metrics", [])[:5]:
                        metric_name = metric.get("MetricName", "")
                        dimensions = {d["Name"]: d["Value"] for d in metric.get("Dimensions", [])}

                        if metric_name in [
                            "HTTPCode_Target_5XX_Count",
                            "UnHealthyHostCount",
                        ]:
                            success, data = self.safe_api_call(
                                self.cloudwatch_client.get_metric_statistics,
                                Namespace="AWS/ApplicationELB",
                                MetricName=metric_name,
                                Dimensions=metric.get("Dimensions", []),
                                StartTime=self.start_date,
                                EndTime=self.end_date,
                                Period=300,
                                Statistics=["Sum", "Maximum"],
                            )

                            if success and data.get("Datapoints"):
                                for dp in data["Datapoints"]:
                                    value = dp.get("Sum", dp.get("Maximum", 0))
                                    if value > 0:
                                        self.findings["network_issues"].append(
                                            {
                                                "summary": f"ALB metric {metric_name} indicates issues",
                                                "details": {
                                                    "metric": metric_name,
                                                    "value": value,
                                                    "load_balancer": dimensions.get(
                                                        "LoadBalancer", "Unknown"
                                                    ),
                                                    "target_group": dimensions.get(
                                                        "TargetGroup", "Unknown"
                                                    ),
                                                    "timestamp": str(
                                                        dp.get("Timestamp", "Unknown")
                                                    ),
                                                    "severity": "critical"
                                                    if "5XX" in metric_name
                                                    else "warning",
                                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                                    "root_causes": [
                                                        "Backend pods unhealthy",
                                                        "Backend pods not ready",
                                                        "Security group blocking traffic",
                                                        "Application errors",
                                                        "Timeout issues",
                                                    ],
                                                    "aws_doc": "https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-troubleshooting.html",
                                                },
                                            }
                                        )
            except Exception:
                pass

            self.progress.info("ALB health analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_alb_health", "message": str(e)})
            self.progress.warning(f"ALB health analysis failed: {e}")

    def analyze_statefulset_issues(self):
        """
        Analyze StatefulSet-specific issues
        Detects PVC pending, ordinal failures
        """
        self.progress.step("Analyzing StatefulSets...")

        try:
            cmd = "kubectl get statefulsets --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get statefulsets -n {self.namespace} -o json"

            output = self.safe_kubectl_call(cmd)
            if not output:
                return

            statefulsets = json.loads(output)

            for sts in statefulsets.get("items", []):
                sts_name = sts["metadata"]["name"]
                namespace = sts["metadata"]["name"]
                spec = sts.get("spec", {})
                status = sts.get("status", {})

                replicas = spec.get("replicas", 1)
                ready_replicas = status.get("readyReplicas", 0)
                current_replicas = status.get("currentReplicas", 0)
                updated_replicas = status.get("updatedReplicas", 0)

                # Check for replica mismatch
                if ready_replicas < replicas:
                    self.findings["pod_errors"].append(
                        {
                            "summary": f"StatefulSet {namespace}/{sts_name} has insufficient ready replicas ({ready_replicas}/{replicas})",
                            "details": {
                                "statefulset": sts_name,
                                "namespace": namespace,
                                "desired": replicas,
                                "ready": ready_replicas,
                                "current": current_replicas,
                                "updated": updated_replicas,
                                "severity": "warning" if ready_replicas > 0 else "critical",
                                "finding_type": FindingType.CURRENT_STATE,
                                "root_causes": [
                                    "Pod stuck in Pending",
                                    "PVC provision failure",
                                    "Pod crash loop",
                                    "Init container failure",
                                    "Headless service missing",
                                ],
                                "aws_doc": "https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/",
                            },
                        }
                    )

                # Check for volume claim templates
                volume_claims = spec.get("volumeClaimTemplates", [])
                if volume_claims:
                    # Get PVCs for this StatefulSet
                    pvc_prefix = sts_name
                    cmd = f"kubectl get pvc -n {namespace} -o json 2>/dev/null || echo 'not found'"
                    pvc_output = self.safe_kubectl_call(cmd)

                    if pvc_output and "not found" not in pvc_output.lower():
                        pvcs = json.loads(pvc_output)

                        for pvc in pvcs.get("items", []):
                            pvc_name = pvc["metadata"]["name"]
                            if pvc_name.startswith(pvc_prefix):
                                phase = pvc.get("status", {}).get("phase", "Unknown")

                                if phase == "Pending":
                                    self.findings["pvc_issues"].append(
                                        {
                                            "summary": f"StatefulSet PVC {namespace}/{pvc_name} stuck in Pending",
                                            "details": {
                                                "pvc": pvc_name,
                                                "statefulset": sts_name,
                                                "namespace": namespace,
                                                "phase": phase,
                                                "severity": "critical",
                                                "finding_type": FindingType.CURRENT_STATE,
                                                "root_causes": [
                                                    "StorageClass not found",
                                                    "EBS CSI driver issue",
                                                    "AZ mismatch",
                                                    "Quota exceeded",
                                                ],
                                            },
                                        }
                                    )

            self.progress.info("StatefulSet analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_statefulset_issues", "message": str(e)})
            self.progress.warning(f"StatefulSet analysis failed: {e}")

    def analyze_conntrack_health(self):
        """
        Analyze conntrack table health
        Detects conntrack table full, dropping packet issues
        """
        self.progress.step("Analyzing conntrack health...")

        try:
            # Check for conntrack-related events
            cmd = "kubectl get events --all-namespaces -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                conntrack_patterns = [
                    "conntrack",
                    "table full",
                    "dropping packet",
                    "nf_conntrack",
                    "connection tracking",
                    "too many connections",
                ]

                for event in events.get("items", []):
                    message = event.get("message", "").lower()
                    reason = event.get("reason", "").lower()

                    if any(p in message or p in reason for p in conntrack_patterns):
                        involved = event.get("involvedObject", {})
                        self.findings["network_issues"].append(
                            {
                                "summary": f"Conntrack issue detected on {involved.get('name', 'unknown')}",
                                "details": {
                                    "node": involved.get("name", "Unknown"),
                                    "namespace": involved.get("namespace", "Unknown"),
                                    "message": event.get("message", "N/A")[:300],
                                    "timestamp": event.get("lastTimestamp", "Unknown"),
                                    "severity": "critical",
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                    "root_causes": [
                                        "High pod-to-pod traffic",
                                        "NodePort services with externalTrafficPolicy: Cluster",
                                        "Too many short-lived connections",
                                        "Insufficient conntrack table size",
                                    ],
                                    "diagnostic_steps": [
                                        "SSH to node: cat /proc/sys/net/netfilter/nf_conntrack_count",
                                        "SSH to node: cat /proc/sys/net/netfilter/nf_conntrack_max",
                                        "Check: kubectl get svc -A -o jsonpath='{.items[?(@.spec.type==\"NodePort\")].metadata.name}'",
                                        "Review: Service externalTrafficPolicy settings",
                                    ],
                                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html",
                                },
                            }
                        )

            # Check kube-proxy logs for conntrack issues
            cmd = "kubectl logs -n kube-system -l k8s-app=kube-proxy --tail=100 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                output_lower = output.lower()
                if "conntrack" in output_lower and (
                    "error" in output_lower or "fail" in output_lower
                ):
                    self.findings["network_issues"].append(
                        {
                            "summary": "kube-proxy reporting conntrack errors",
                            "details": {
                                "component": "kube-proxy",
                                "namespace": "kube-system",
                                "severity": "warning",
                                "recommendation": "Review kube-proxy logs for conntrack issues",
                                "root_causes": [
                                    "Conntrack table approaching limit",
                                    "Stale conntrack entries",
                                    "High connection churn rate",
                                ],
                            },
                        }
                    )

            # Check CloudWatch for related metrics
            try:
                # Check for high network traffic that might indicate conntrack pressure
                success, metrics_response = self.safe_api_call(
                    self.cloudwatch_client.list_metrics,
                    Namespace="ContainerInsights",
                    MetricName="pod_network_rx_bytes",
                )

                if success and metrics_response.get("Metrics"):
                    for metric in metrics_response.get("Metrics", [])[:3]:
                        dimensions = {d["Name"]: d["Value"] for d in metric.get("Dimensions", [])}
                        if dimensions.get("ClusterName") == self.cluster_name:
                            success, data = self.safe_api_call(
                                self.cloudwatch_client.get_metric_statistics,
                                Namespace="ContainerInsights",
                                MetricName="pod_network_rx_bytes",
                                Dimensions=metric.get("Dimensions", []),
                                StartTime=self.start_date,
                                EndTime=self.end_date,
                                Period=300,
                                Statistics=["Maximum"],
                            )

                            if success and data.get("Datapoints"):
                                # Check for unusually high network traffic
                                for dp in data["Datapoints"]:
                                    max_rx = dp.get("Maximum", 0)
                                    # If > 100 MB/s, could indicate conntrack pressure
                                    if max_rx > 100 * 1024 * 1024:
                                        self.findings["network_issues"].append(
                                            {
                                                "summary": f"High network traffic detected: {max_rx / (1024 * 1024):.1f} MB/s - may cause conntrack pressure",
                                                "details": {
                                                    "metric": "pod_network_rx_bytes",
                                                    "max_rx_bytes": max_rx,
                                                    "timestamp": str(
                                                        dp.get("Timestamp", "Unknown")
                                                    ),
                                                    "severity": "warning",
                                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                                    "recommendation": "Monitor conntrack table usage on nodes",
                                                },
                                            }
                                        )
                                        break
            except Exception:
                pass

            self.progress.info("Conntrack health analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_conntrack_health", "message": str(e)})
            self.progress.warning(f"Conntrack health analysis failed: {e}")

    def analyze_custom_controllers(self):
        """
        Analyze custom controllers and operators for issues
        Detects reconciliation failures, watch errors, panics
        """
        self.progress.step("Analyzing custom controllers...")

        try:
            # Look for common operator patterns
            operator_labels = [
                "control-plane=controller-manager",
                "app.kubernetes.io/component=controller",
                "app.kubernetes.io/name",
            ]

            for label in operator_labels:
                cmd = f"kubectl get pods --all-namespaces -l {label} -o json 2>/dev/null || echo 'not found'"
                output = self.safe_kubectl_call(cmd)

                if not output or "not found" in output.lower():
                    continue

                pods = json.loads(output)

                for pod in pods.get("items", []):
                    pod_name = pod["metadata"]["name"]
                    namespace = pod["metadata"]["namespace"]
                    phase = pod.get("status", {}).get("phase", "Unknown")

                    # Check for crash/restart issues
                    container_statuses = pod.get("status", {}).get("containerStatuses", [])
                    for cs in container_statuses:
                        restart_count = cs.get("restartCount", 0)
                        state = cs.get("state", {})

                        if restart_count >= Thresholds.RESTART_WARNING:
                            self.findings["addon_issues"].append(
                                {
                                    "summary": f"Custom controller {namespace}/{pod_name} has high restart count: {restart_count}",
                                    "details": {
                                        "pod": pod_name,
                                        "namespace": namespace,
                                        "container": cs.get("name", "Unknown"),
                                        "restart_count": restart_count,
                                        "severity": "critical"
                                        if restart_count >= Thresholds.RESTART_CRITICAL
                                        else "warning",
                                        "finding_type": FindingType.CURRENT_STATE,
                                        "root_causes": [
                                            "Controller panic or crash",
                                            "RBAC permission issues",
                                            "API server connectivity",
                                            "Invalid CRD schema",
                                            "Resource quota exceeded",
                                        ],
                                    },
                                }
                            )

                        waiting = state.get("waiting", {})
                        if waiting:
                            reason = waiting.get("reason", "")
                            if reason in [
                                "CrashLoopBackOff",
                                "ImagePullBackOff",
                                "ErrImagePull",
                            ]:
                                self.findings["addon_issues"].append(
                                    {
                                        "summary": f"Custom controller {namespace}/{pod_name} container issue: {reason}",
                                        "details": {
                                            "pod": pod_name,
                                            "namespace": namespace,
                                            "container": cs.get("name", "Unknown"),
                                            "reason": reason,
                                            "message": waiting.get("message", "N/A")[:200],
                                            "severity": "critical",
                                        },
                                    }
                                )

            # Check for controller-related events
            cmd = "kubectl get events --all-namespaces -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                controller_patterns = [
                    "failed to reconcile",
                    "reconcile error",
                    "watch error",
                    "reflector: ListWatch stopped",
                    "controller",
                    "operator",
                ]

                for event in events.get("items", []):
                    message = event.get("message", "").lower()
                    reason = event.get("reason", "").lower()

                    # Skip if it's a core k8s controller (already handled elsewhere)
                    involved = event.get("involvedObject", {})
                    involved_name = involved.get("name", "").lower()

                    if "kube-controller-manager" in involved_name:
                        continue

                    if any(p in message or p in reason for p in controller_patterns):
                        # Check if it's a repeating error
                        count = event.get("count", 1)
                        severity = "critical" if count > 5 else "warning"

                        self.findings["addon_issues"].append(
                            {
                                "summary": f"Controller reconciliation issue in {involved.get('namespace', 'unknown')}/{involved.get('name', 'unknown')}",
                                "details": {
                                    "object": involved.get("name", "Unknown"),
                                    "namespace": involved.get("namespace", "Unknown"),
                                    "kind": involved.get("kind", "Unknown"),
                                    "reason": event.get("reason", "N/A"),
                                    "message": event.get("message", "N/A")[:300],
                                    "count": count,
                                    "timestamp": event.get("lastTimestamp", "Unknown"),
                                    "severity": severity,
                                    "root_causes": [
                                        "CRD validation failure",
                                        "Missing dependencies",
                                        "RBAC permissions",
                                        "API server latency",
                                        "Invalid resource spec",
                                    ],
                                    "aws_doc": "https://kubernetes.io/docs/concepts/extend-kubernetes/operator/",
                                },
                            }
                        )

            # Check CRD health
            cmd = "kubectl get crds -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                crds = json.loads(output)

                for crd in crds.get("items", []):
                    crd_name = crd["metadata"]["name"]

                    # Check for CRDs with stored versions that might cause issues
                    status = crd.get("status", {})
                    conditions = status.get("conditions", [])

                    for condition in conditions:
                        if (
                            condition.get("type") == "Established"
                            and condition.get("status") != "True"
                        ):
                            self.findings["addon_issues"].append(
                                {
                                    "summary": f"CRD {crd_name} not established",
                                    "details": {
                                        "crd": crd_name,
                                        "reason": condition.get("reason", "Unknown"),
                                        "message": condition.get("message", "N/A")[:200],
                                        "severity": "warning",
                                    },
                                }
                            )

            self.progress.info("Custom controller analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_custom_controllers", "message": str(e)})
            self.progress.warning(f"Custom controller analysis failed: {e}")

    def analyze_psa_violations(self):
        """
        Analyze Pod Security Admission violations
        Detects pods rejected by PSA policies
        """
        self.progress.step("Analyzing Pod Security Admission...")

        try:
            # Check namespace PSA labels
            cmd = "kubectl get namespaces -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            namespaces_with_psa = []

            if output and "not found" not in output.lower():
                namespaces = json.loads(output)

                for ns in namespaces.get("items", []):
                    ns_name = ns["metadata"]["name"]
                    labels = ns["metadata"].get("labels", {})

                    # Check for PSA labels
                    enforce = labels.get("pod-security.kubernetes.io/enforce", "")
                    audit = labels.get("pod-security.kubernetes.io/audit", "")
                    warn = labels.get("pod-security.kubernetes.io/warn", "")

                    if enforce or audit or warn:
                        namespaces_with_psa.append(
                            {
                                "namespace": ns_name,
                                "enforce": enforce or "privileged",
                                "audit": audit or "privileged",
                                "warn": warn or "privileged",
                            }
                        )

                        # Check for pods that might violate PSA
                        cmd = (
                            f"kubectl get pods -n {ns_name} -o json 2>/dev/null || echo 'not found'"
                        )
                        pod_output = self.safe_kubectl_call(cmd)

                        if pod_output and "not found" not in pod_output.lower():
                            pods = json.loads(pod_output)

                            for pod in pods.get("items", []):
                                pod_name = pod["metadata"]["name"]
                                spec = pod.get("spec", {})

                                violations = []

                                # Check for PSA violations
                                containers = spec.get("containers", []) + spec.get(
                                    "initContainers", []
                                )

                                for container in containers:
                                    security_context = container.get("securityContext", {})

                                    # Check for privileged containers
                                    if security_context.get("privileged", False):
                                        if enforce in ["restricted", "baseline"]:
                                            violations.append(
                                                f"Container {container.get('name')} is privileged"
                                            )

                                    # Check for allowPrivilegeEscalation
                                    if security_context.get("allowPrivilegeEscalation", True):
                                        if enforce == "restricted":
                                            violations.append(
                                                f"Container {container.get('name')} allows privilege escalation"
                                            )

                                    # Check for running as root
                                    if security_context.get("runAsNonRoot", False) is False:
                                        if enforce == "restricted":
                                            violations.append(
                                                f"Container {container.get('name')} may run as root"
                                            )

                                    # Check for capabilities
                                    caps = security_context.get("capabilities", {})
                                    add_caps = caps.get("add", [])
                                    if add_caps and enforce in [
                                        "restricted",
                                        "baseline",
                                    ]:
                                        violations.append(
                                            f"Container {container.get('name')} adds capabilities: {add_caps}"
                                        )

                                # Check host networking
                                if spec.get("hostNetwork", False):
                                    if enforce in ["restricted", "baseline"]:
                                        violations.append("Pod uses host network")

                                # Check host PID
                                if spec.get("hostPID", False):
                                    if enforce in ["restricted", "baseline"]:
                                        violations.append("Pod uses host PID")

                                # Check host IPC
                                if spec.get("hostIPC", False):
                                    if enforce in ["restricted", "baseline"]:
                                        violations.append("Pod uses host IPC")

                                # Check for seccomp profile
                                for container in containers:
                                    security_context = container.get("securityContext", {})
                                    seccomp = security_context.get("seccompProfile", {})
                                    if not seccomp and enforce == "restricted":
                                        violations.append(
                                            f"Container {container.get('name')} missing seccomp profile"
                                        )

                                if violations:
                                    self.findings["rbac_issues"].append(
                                        {
                                            "summary": f"Pod {ns_name}/{pod_name} may violate PSA policy ({enforce})",
                                            "details": {
                                                "pod": pod_name,
                                                "namespace": ns_name,
                                                "psa_level": enforce,
                                                "violations": violations[:5],
                                                "severity": "warning"
                                                if enforce == "warn"
                                                else "info",
                                                "finding_type": FindingType.CURRENT_STATE,
                                                "root_causes": [
                                                    "Missing security context configuration",
                                                    "Privileged container requirements",
                                                    "Host namespace access needed",
                                                    "Missing seccomp/AppArmor profiles",
                                                ],
                                                "aws_doc": "https://kubernetes.io/docs/concepts/security/pod-security-admission/",
                                            },
                                        }
                                    )

            # Check for PSA-related events (rejections)
            cmd = "kubectl get events --all-namespaces -o json 2>/dev/null || echo 'not found'"
            output = self.safe_kubectl_call(cmd)

            if output and "not found" not in output.lower():
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                psa_patterns = [
                    "podsecurity",
                    "violates podsecurity",
                    "pod security policy",
                    "psa",
                ]

                for event in events.get("items", []):
                    message = event.get("message", "").lower()
                    reason = event.get("reason", "").lower()

                    if any(p in message or p in reason for p in psa_patterns):
                        involved = event.get("involvedObject", {})
                        self.findings["rbac_issues"].append(
                            {
                                "summary": f"PSA violation: {involved.get('namespace', 'unknown')}/{involved.get('name', 'unknown')}",
                                "details": {
                                    "object": involved.get("name", "Unknown"),
                                    "namespace": involved.get("namespace", "Unknown"),
                                    "kind": involved.get("kind", "Unknown"),
                                    "reason": event.get("reason", "N/A"),
                                    "message": event.get("message", "N/A")[:300],
                                    "timestamp": event.get("lastTimestamp", "Unknown"),
                                    "severity": "critical",
                                    "finding_type": FindingType.HISTORICAL_EVENT,
                                    "root_causes": [
                                        "Pod spec does not meet PSA requirements",
                                        "Namespace has restrictive PSA policy",
                                        "Missing security context fields",
                                    ],
                                    "aws_doc": "https://kubernetes.io/docs/concepts/security/pod-security-admission/",
                                },
                            }
                        )

            self.progress.info(
                f"PSA analysis completed ({len(namespaces_with_psa)} namespaces with PSA)"
            )

        except Exception as e:
            self.errors.append({"step": "analyze_psa_violations", "message": str(e)})
            self.progress.warning(f"PSA analysis failed: {e}")

    def analyze_missing_config_resources(self):
        """
        Analyze missing ConfigMaps and Secrets referenced by pods
        Catalog 8.2: Missing ConfigMap or Secret

        Detection:
        - [EVENT] kubectl get events | grep CreateContainerConfigError
        - [API] Check pod spec for references, verify resources exist
        - [LOG] Pod Events: "configmap not found", "secret not found"

        Reference: https://kubernetes.io/docs/concepts/configuration/configmap/
        """
        self.progress.step("Analyzing missing ConfigMaps and Secrets...")

        try:
            missing_configmaps = []
            missing_secrets = []
            config_errors = []

            # Get all ConfigMaps
            cmd = "kubectl get configmaps --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get configmaps -n {self.namespace} -o json"
            cm_output = self.safe_kubectl_call(cmd)
            existing_configmaps = set()
            if cm_output:
                cms = json.loads(cm_output)
                for cm in cms.get("items", []):
                    ns = cm["metadata"]["namespace"]
                    name = cm["metadata"]["name"]
                    existing_configmaps.add(f"{ns}/{name}")

            # Get all Secrets
            cmd = "kubectl get secrets --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get secrets -n {self.namespace} -o json"
            secret_output = self.safe_kubectl_call(cmd)
            existing_secrets = set()
            if secret_output:
                secrets = json.loads(secret_output)
                for secret in secrets.get("items", []):
                    ns = secret["metadata"]["namespace"]
                    name = secret["metadata"]["name"]
                    existing_secrets.add(f"{ns}/{name}")

            # Check pods for CreateContainerConfigError events
            cmd = "kubectl get events --all-namespaces --field-selector reason=CreateContainerConfigError -o json"
            output = self.safe_kubectl_call(cmd)

            if output:
                events = json.loads(output)
                events = self.filter_kubectl_events_by_date(events, self.start_date, self.end_date)

                for event in events.get("items", []):
                    message = event.get("message", "").lower()
                    pod = event["involvedObject"].get("name", "Unknown")
                    namespace = event["metadata"]["namespace"]
                    timestamp = event.get("lastTimestamp", event.get("eventTime", "Unknown"))

                    missing_resource = None
                    resource_type = None

                    if "configmap" in message and "not found" in message:
                        import re

                        match = re.search(r'configmap\s+"([^"]+)"', message)
                        if match:
                            missing_resource = match.group(1)
                            resource_type = "ConfigMap"
                            missing_configmaps.append(
                                {
                                    "name": missing_resource,
                                    "namespace": namespace,
                                    "pod": pod,
                                }
                            )
                    elif "secret" in message and "not found" in message:
                        import re

                        match = re.search(r'secret\s+"([^"]+)"', message)
                        if match:
                            missing_resource = match.group(1)
                            resource_type = "Secret"
                            missing_secrets.append(
                                {
                                    "name": missing_resource,
                                    "namespace": namespace,
                                    "pod": pod,
                                }
                            )

                    if missing_resource:
                        config_errors.append(
                            {
                                "summary": f"Missing {resource_type}: {namespace}/{missing_resource} (referenced by pod {pod})",
                                "details": {
                                    "resource_type": resource_type,
                                    "resource_name": missing_resource,
                                    "namespace": namespace,
                                    "pod": pod,
                                    "timestamp": str(timestamp),
                                    "message": event.get("message", "")[:200],
                                    "severity": "critical",
                                    "finding_type": FindingType.CURRENT_STATE,
                                    "diagnostic_steps": [
                                        f"kubectl describe pod {pod} -n {namespace}",
                                        f"Create missing {resource_type}: kubectl create {resource_type.lower()} {missing_resource} -n {namespace} --from-literal=key=value",
                                        "Or fix the pod spec to reference an existing resource",
                                    ],
                                    "impact": f"Pod cannot start until {resource_type} is created",
                                    "aws_doc": "https://kubernetes.io/docs/concepts/configuration/configmap/",
                                },
                            }
                        )

            # Check pod specs for references to non-existent resources
            cmd = "kubectl get pods --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get pods -n {self.namespace} -o json"
            pods_output = self.safe_kubectl_call(cmd)

            if pods_output:
                pods = json.loads(pods_output)
                for pod in pods.get("items", []):
                    pod_name = pod["metadata"]["name"]
                    ns = pod["metadata"]["namespace"]
                    spec = pod.get("spec", {})

                    # Check volumes for ConfigMap/Secret references
                    for volume in spec.get("volumes", []):
                        if "configMap" in volume:
                            cm_name = volume["configMap"].get("name", "")
                            if cm_name and f"{ns}/{cm_name}" not in existing_configmaps:
                                # Only report if not already found in events
                                already_reported = any(
                                    c["name"] == cm_name
                                    and c["namespace"] == ns
                                    and c["pod"] == pod_name
                                    for c in missing_configmaps
                                )
                                if not already_reported:
                                    self.findings["pod_errors"].append(
                                        {
                                            "summary": f"Pod {ns}/{pod_name} references non-existent ConfigMap: {cm_name}",
                                            "details": {
                                                "pod": pod_name,
                                                "namespace": ns,
                                                "resource_type": "ConfigMap",
                                                "resource_name": cm_name,
                                                "volume": volume.get("name", "unknown"),
                                                "severity": "warning",
                                                "finding_type": FindingType.CURRENT_STATE,
                                                "diagnostic_steps": [
                                                    f"kubectl get configmap {cm_name} -n {ns}",
                                                    f"Create the ConfigMap or fix the pod spec",
                                                ],
                                            },
                                        }
                                    )

                        if "secret" in volume:
                            secret_name = volume["secret"].get("secretName", "")
                            if secret_name and f"{ns}/{secret_name}" not in existing_secrets:
                                already_reported = any(
                                    s["name"] == secret_name
                                    and s["namespace"] == ns
                                    and s["pod"] == pod_name
                                    for s in missing_secrets
                                )
                                if not already_reported:
                                    self.findings["pod_errors"].append(
                                        {
                                            "summary": f"Pod {ns}/{pod_name} references non-existent Secret: {secret_name}",
                                            "details": {
                                                "pod": pod_name,
                                                "namespace": ns,
                                                "resource_type": "Secret",
                                                "resource_name": secret_name,
                                                "volume": volume.get("name", "unknown"),
                                                "severity": "warning",
                                                "finding_type": FindingType.CURRENT_STATE,
                                                "diagnostic_steps": [
                                                    f"kubectl get secret {secret_name} -n {ns}",
                                                    "Create the Secret or fix the pod spec",
                                                ],
                                            },
                                        }
                                    )

                    # Check environment variables from ConfigMaps/Secrets
                    for container in spec.get("containers", []):
                        for env_from in container.get("envFrom", []):
                            if "configMapRef" in env_from:
                                cm_name = env_from["configMapRef"].get("name", "")
                                if cm_name and f"{ns}/{cm_name}" not in existing_configmaps:
                                    self.findings["pod_errors"].append(
                                        {
                                            "summary": f"Pod {ns}/{pod_name} envFrom references non-existent ConfigMap: {cm_name}",
                                            "details": {
                                                "pod": pod_name,
                                                "namespace": ns,
                                                "container": container.get("name", "unknown"),
                                                "resource_type": "ConfigMap",
                                                "resource_name": cm_name,
                                                "severity": "warning",
                                                "finding_type": FindingType.CURRENT_STATE,
                                            },
                                        }
                                    )
                            if "secretRef" in env_from:
                                secret_name = env_from["secretRef"].get("name", "")
                                if secret_name and f"{ns}/{secret_name}" not in existing_secrets:
                                    self.findings["pod_errors"].append(
                                        {
                                            "summary": f"Pod {ns}/{pod_name} envFrom references non-existent Secret: {secret_name}",
                                            "details": {
                                                "pod": pod_name,
                                                "namespace": ns,
                                                "container": container.get("name", "unknown"),
                                                "resource_type": "Secret",
                                                "resource_name": secret_name,
                                                "severity": "warning",
                                                "finding_type": FindingType.CURRENT_STATE,
                                            },
                                        }
                                    )

            # Add config errors to findings
            for error in config_errors:
                self.findings["pod_errors"].append(error)

            # Summary if many missing resources
            if len(missing_configmaps) > 3:
                unique_cms = set(f"{c['namespace']}/{c['name']}" for c in missing_configmaps)
                self.findings["pod_errors"].append(
                    {
                        "summary": f"Multiple missing ConfigMaps detected: {len(unique_cms)} unique",
                        "details": {
                            "count": len(unique_cms),
                            "configmaps": list(unique_cms)[:10],
                            "severity": "warning",
                            "recommendation": "Review ConfigMap creation process and ensure all required ConfigMaps exist before deploying pods",
                        },
                    }
                )

            if len(missing_secrets) > 3:
                unique_secrets = set(f"{s['namespace']}/{s['name']}" for s in missing_secrets)
                self.findings["pod_errors"].append(
                    {
                        "summary": f"Multiple missing Secrets detected: {len(unique_secrets)} unique",
                        "details": {
                            "count": len(unique_secrets),
                            "secrets": [s.split("/")[1] for s in list(unique_secrets)[:10]],
                            "severity": "warning",
                            "recommendation": "Review Secret creation process and ensure all required Secrets exist before deploying pods",
                            "note": "Secret names are listed without namespace for security",
                        },
                    }
                )

            self.progress.info(
                f"ConfigMap/Secret analysis completed ({len(missing_configmaps)} missing CMs, {len(missing_secrets)} missing Secrets)"
            )

        except Exception as e:
            self.errors.append({"step": "analyze_missing_config_resources", "message": str(e)})
            self.progress.warning(f"ConfigMap/Secret analysis failed: {e}")

    def analyze_apiserver_inflight(self):
        """
        Analyze API Server inflight requests
        Detects request saturation
        """
        self.progress.step("Analyzing API Server inflight requests...")

        try:
            # Check CloudWatch for inflight metrics
            success, metrics_response = self.safe_api_call(
                self.cloudwatch_client.list_metrics,
                Namespace="ContainerInsights",
            )

            if success and metrics_response.get("Metrics"):
                inflight_metrics = []

                for metric in metrics_response.get("Metrics", []):
                    metric_name = metric.get("MetricName", "")
                    if "inflight" in metric_name.lower() or "apiserver" in metric_name.lower():
                        dimensions = {d["Name"]: d["Value"] for d in metric.get("Dimensions", [])}
                        if dimensions.get("ClusterName") == self.cluster_name:
                            inflight_metrics.append(metric)

                for metric in inflight_metrics[:5]:
                    success, data = self.safe_api_call(
                        self.cloudwatch_client.get_metric_statistics,
                        Namespace=metric.get("Namespace", "ContainerInsights"),
                        MetricName=metric.get("MetricName"),
                        Dimensions=metric.get("Dimensions", []),
                        StartTime=self.start_date,
                        EndTime=self.end_date,
                        Period=300,
                        Statistics=["Maximum", "Average"],
                    )

                    if success and data.get("Datapoints"):
                        metric_name = metric.get("MetricName")
                        for dp in data["Datapoints"]:
                            max_val = dp.get("Maximum", 0)
                            avg_val = dp.get("Average", 0)

                            # Check for high inflight requests
                            # Typical max is around 400-500 for mutating, 400 for readonly
                            threshold = 300 if "mutating" in metric_name.lower() else 400

                            if max_val > threshold:
                                self.findings["control_plane_issues"].append(
                                    {
                                        "summary": f"High API Server inflight requests: {metric_name} = {max_val:.0f}",
                                        "details": {
                                            "metric": metric_name,
                                            "maximum": max_val,
                                            "average": avg_val,
                                            "threshold": threshold,
                                            "timestamp": str(dp.get("Timestamp", "Unknown")),
                                            "severity": "critical"
                                            if max_val > threshold * 1.5
                                            else "warning",
                                            "finding_type": FindingType.HISTORICAL_EVENT,
                                            "root_causes": [
                                                "Too many concurrent API requests",
                                                "Controller/operator spamming API",
                                                "Insufficient API Priority and Fairness",
                                                "Large LIST/Watch operations",
                                            ],
                                            "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html",
                                        },
                                    }
                                )
                                break

            self.progress.info("API Server inflight analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_apiserver_inflight", "message": str(e)})
            self.progress.warning(f"API Server inflight analysis failed: {e}")

    def analyze_scheduler_health(self):
        """
        Analyze kube-scheduler health
        Detects scheduling latency and errors
        """
        self.progress.step("Analyzing Scheduler health...")

        try:
            log_group = f"/aws/eks/{self.cluster_name}/cluster"

            success, response = self.safe_api_call(
                self.logs_client.describe_log_groups, logGroupNamePrefix=log_group
            )

            if not success or not response.get("logGroups"):
                return

            scheduler_patterns = [
                {
                    "pattern": "Unable to schedule pod",
                    "issue": "Scheduler cannot schedule pod",
                    "severity": "warning",
                },
                {
                    "pattern": "no nodes available to schedule pods",
                    "issue": "No nodes available for scheduling",
                    "severity": "critical",
                },
                {
                    "pattern": "preemption: 0/N nodes",
                    "issue": "Preemption failed",
                    "severity": "warning",
                },
                {
                    "pattern": "binding rejected",
                    "issue": "Pod binding rejected",
                    "severity": "warning",
                },
                {
                    "pattern": "scheduler error",
                    "issue": "Scheduler error",
                    "severity": "critical",
                },
                {
                    "pattern": "panic",
                    "issue": "Scheduler panic",
                    "severity": "critical",
                },
            ]

            success, streams_response = self.safe_api_call(
                self.logs_client.describe_log_streams,
                logGroupName=log_group,
                logStreamNamePrefix="kube-scheduler-",
                orderBy="LastEventTime",
                descending=True,
                limit=3,
            )

            if not success:
                return

            for stream in streams_response.get("logStreams", []):
                stream_name = stream["logStreamName"]

                success, logs_response = self.safe_api_call(
                    self.logs_client.get_log_events,
                    logGroupName=log_group,
                    logStreamName=stream_name,
                    startTime=int(self.start_date.timestamp() * 1000),
                    endTime=int(self.end_date.timestamp() * 1000),
                    limit=100,
                    startFromHead=False,
                )

                if not success:
                    continue

                for event in logs_response.get("events", []):
                    message = event["message"]
                    message_lower = message.lower()

                    for pattern_info in scheduler_patterns:
                        if pattern_info["pattern"].lower() in message_lower:
                            timestamp = datetime.fromtimestamp(
                                event["timestamp"] / 1000, tz=timezone.utc
                            )

                            self.findings["scheduling_failures"].append(
                                {
                                    "summary": f"Scheduler: {pattern_info['issue']}",
                                    "details": {
                                        "log_stream": stream_name,
                                        "timestamp": str(timestamp),
                                        "message": message[:300],
                                        "severity": pattern_info["severity"],
                                        "finding_type": FindingType.HISTORICAL_EVENT,
                                        "root_causes": [
                                            "No nodes match pod requirements",
                                            "Resource constraints on all nodes",
                                            "Taints/tolerations mismatch",
                                            "Affinity rules too strict",
                                        ],
                                        "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html",
                                    },
                                }
                            )
                            break

            # Check CloudWatch for scheduler metrics
            try:
                success, metrics_response = self.safe_api_call(
                    self.cloudwatch_client.list_metrics,
                    Namespace="ContainerInsights",
                    MetricName="scheduler_schedule_attempts",
                )

                if success and metrics_response.get("Metrics"):
                    for metric in metrics_response.get("Metrics", [])[:3]:
                        dimensions = {d["Name"]: d["Value"] for d in metric.get("Dimensions", [])}
                        if dimensions.get("ClusterName") == self.cluster_name:
                            success, data = self.safe_api_call(
                                self.cloudwatch_client.get_metric_statistics,
                                Namespace="ContainerInsights",
                                MetricName="scheduler_schedule_attempts",
                                Dimensions=metric.get("Dimensions", []),
                                StartTime=self.start_date,
                                EndTime=self.end_date,
                                Period=300,
                                Statistics=["Sum"],
                            )

                            if success and data.get("Datapoints"):
                                for dp in data["Datapoints"]:
                                    # Check for any error results in scheduler attempts
                                    result = dimensions.get("result", "").lower()
                                    if result in ["error", "unschedulable"]:
                                        value = dp.get("Sum", 0)
                                        if value > 0:
                                            self.findings["scheduling_failures"].append(
                                                {
                                                    "summary": f"Scheduler {result} attempts: {value:.0f}",
                                                    "details": {
                                                        "result": result,
                                                        "count": value,
                                                        "timestamp": str(
                                                            dp.get("Timestamp", "Unknown")
                                                        ),
                                                        "severity": "warning",
                                                        "finding_type": FindingType.HISTORICAL_EVENT,
                                                    },
                                                }
                                            )
            except Exception:
                pass

            self.progress.info("Scheduler health analysis completed")

        except Exception as e:
            self.errors.append({"step": "analyze_scheduler_health", "message": str(e)})
            self.progress.warning(f"Scheduler health analysis failed: {e}")

    def analyze_limits_requests(self):
        """
        Analyze resource limits and requests configuration
        Detects pods without limits/requests, QoS issues
        """
        self.progress.step("Analyzing resource limits and requests...")

        try:
            cmd = "kubectl get pods --all-namespaces -o json"
            if self.namespace:
                cmd = f"kubectl get pods -n {self.namespace} -o json"

            output = self.safe_kubectl_call(cmd)
            if not output:
                return

            pods = json.loads(output)
            pods_without_limits = []
            pods_without_requests = []
            qos_breakdown = {"Guaranteed": 0, "Burstable": 0, "BestEffort": 0}

            for pod in pods.get("items", []):
                pod_name = pod["metadata"]["name"]
                namespace = pod["metadata"]["namespace"]
                spec = pod.get("spec", {})

                has_limits = False
                has_requests = False
                all_containers_have_limits = True
                all_containers_have_requests = True

                containers = spec.get("containers", []) + spec.get("initContainers", [])

                for container in containers:
                    resources = container.get("resources", {})
                    limits = resources.get("limits", {})
                    requests = resources.get("requests", {})

                    if limits:
                        has_limits = True
                    else:
                        all_containers_have_limits = False

                    if requests:
                        has_requests = True
                    else:
                        all_containers_have_requests = False

                # Determine QoS class
                if all_containers_have_limits and all_containers_have_requests:
                    # Check if limits == requests for Guaranteed
                    all_equal = True
                    for container in containers:
                        resources = container.get("resources", {})
                        limits = resources.get("limits", {})
                        requests = resources.get("requests", {})

                        # Compare CPU and memory
                        for resource in ["cpu", "memory"]:
                            if limits.get(resource) != requests.get(resource):
                                all_equal = False
                                break
                        if not all_equal:
                            break

                    if all_equal:
                        qos_breakdown["Guaranteed"] += 1
                    else:
                        qos_breakdown["Burstable"] += 1
                elif has_limits or has_requests:
                    qos_breakdown["Burstable"] += 1
                else:
                    qos_breakdown["BestEffort"] += 1

                # Flag pods without limits (BestEffort or partial Burstable)
                if not all_containers_have_limits:
                    pods_without_limits.append(f"{namespace}/{pod_name}")

                # Flag pods without requests
                if not all_containers_have_requests:
                    pods_without_requests.append(f"{namespace}/{pod_name}")

            # Report findings
            if len(pods_without_limits) > 0:
                self.findings["resource_quota_exceeded"].append(
                    {
                        "summary": f"{len(pods_without_limits)} pods without resource limits",
                        "details": {
                            "count": len(pods_without_limits),
                            "examples": pods_without_limits[:10],
                            "severity": "warning",
                            "finding_type": FindingType.CURRENT_STATE,
                            "impact": "Pods without limits can consume unbounded resources",
                            "recommendation": "Add resource limits to all pods",
                            "aws_doc": "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/",
                        },
                    }
                )

            if len(pods_without_requests) > 0:
                self.findings["resource_quota_exceeded"].append(
                    {
                        "summary": f"{len(pods_without_requests)} pods without resource requests",
                        "details": {
                            "count": len(pods_without_requests),
                            "examples": pods_without_requests[:10],
                            "severity": "info",
                            "finding_type": FindingType.CURRENT_STATE,
                            "impact": "Pods without requests may be scheduled on overloaded nodes",
                            "recommendation": "Add resource requests to all pods",
                            "aws_doc": "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/",
                        },
                    }
                )

            # Report QoS breakdown if there are BestEffort pods
            if qos_breakdown["BestEffort"] > 0:
                self.findings["resource_quota_exceeded"].append(
                    {
                        "summary": f"{qos_breakdown['BestEffort']} BestEffort pods (lowest QoS)",
                        "details": {
                            "qos_breakdown": qos_breakdown,
                            "severity": "info",
                            "finding_type": FindingType.CURRENT_STATE,
                            "recommendation": "Consider setting limits and requests for Guaranteed QoS on critical workloads",
                        },
                    }
                )

            self.progress.info(
                f"Resource limits analysis: {len(pods_without_limits)} without limits, "
                f"{len(pods_without_requests)} without requests"
            )

        except Exception as e:
            self.errors.append({"step": "analyze_limits_requests", "message": str(e)})
            self.progress.warning(f"Resource limits analysis failed: {e}")

    # === Orchestration ===

    def run_comprehensive_analysis(self):
        """
        Run all 56 analysis methods with graceful degradation.

        Executes all analysis methods in sequence, catching exceptions from
        individual methods to ensure the full analysis completes even if
        some methods fail.

        Returns:
            dict: Analysis results containing:
                - metadata: Cluster info, region, date range
                - summary: Issue counts by severity
                - findings: All findings by category
                - correlations: Root cause analysis
                - timeline: Chronological events
                - first_issue: Earliest detected issue
                - recommendations: Evidence-based recommendations
                - errors: Any errors encountered

        Raises:
            AWSAuthenticationError: If AWS credentials are invalid.
            ClusterNotFoundError: If the cluster doesn't exist.
            KubectlNotAvailableError: If kubectl is not in PATH.
        """
        self.progress.set_total_steps(60)

        # Step 1-3: Basic setup
        try:
            self.validate_aws_access()
            self.get_cluster_name()
            self.update_kubeconfig()
        except Exception as e:
            self.progress.error(f"Setup failed: {e}")
            raise

        # Step 4-58: Run all analyses (graceful degradation)
        analysis_methods = [
            # Pod lifecycle & health
            self.analyze_pod_evictions,
            self.check_oom_events,
            self.analyze_pod_health_deep,
            self.analyze_probe_failures,
            self.analyze_image_pull_failures,
            self.analyze_pods_terminating,
            self.analyze_deployment_rollouts,
            self.analyze_jobs_cronjobs,
            self.analyze_statefulset_issues,
            # Node health
            self.analyze_node_conditions,
            self.analyze_eks_nodegroup_health,
            self.analyze_certificate_expiry,
            self.analyze_windows_nodes,
            self.analyze_pleg_health,
            self.analyze_container_runtime,
            self.analyze_pause_image_issues,
            # Scheduling & resources
            self.analyze_pod_scheduling_failures,
            self.analyze_resource_quotas,
            self.analyze_cpu_throttling,
            self.analyze_hpa_vpa,
            self.analyze_gpu_scheduling,
            self.analyze_limits_requests,
            # Networking
            self.analyze_network_issues,
            self.analyze_vpc_cni_health,
            self.analyze_coredns_health,
            self.analyze_service_health,
            self.analyze_subnet_health,
            self.analyze_security_groups,
            self.analyze_network_policies,
            self.analyze_alb_health,
            self.analyze_conntrack_health,
            # Storage
            self.analyze_pvc_issues,
            self.analyze_ebs_csi_health,
            self.analyze_efs_csi_health,
            # IAM & RBAC
            self.analyze_rbac_issues,
            self.analyze_iam_pod_identity,
            self.analyze_psa_violations,
            self.analyze_missing_config_resources,
            # Autoscaling
            self.analyze_cluster_autoscaler,
            self.analyze_karpenter,
            self.analyze_fargate_health,
            # AWS infrastructure
            self.analyze_service_quotas,
            self.analyze_aws_lb_controller,
            self.analyze_custom_controllers,
            # Control Plane
            self.analyze_control_plane_logs,
            self.analyze_apiserver_latency,
            self.analyze_apiserver_rate_limiting,
            self.analyze_apiserver_inflight,
            self.analyze_etcd_health,
            self.analyze_controller_manager,
            self.analyze_scheduler_health,
            self.analyze_admission_webhooks,
            # Observability
            self.check_container_insights_metrics,
            self.analyze_cloudwatch_logging_health,
            # Addons
            self.check_eks_addons,
        ]

        for method in analysis_methods:
            try:
                method()
            except Exception as e:
                # Continue analysis even if one method fails
                self.progress.warning(f"Analysis method {method.__name__} failed: {e}")

        # Step 59: Run correlation analysis
        try:
            self.correlate_findings()
        except Exception as e:
            self.progress.warning(f"Correlation analysis failed: {e}")

        # Generate recommendations
        recommendations = self.generate_recommendations()

        # Build results
        results = {
            "metadata": {
                "cluster": self.cluster_name,
                "region": self.region,
                "analysis_date": datetime.now(timezone.utc).isoformat(),
                "date_range": {
                    "start": self.start_date.isoformat(),
                    "end": self.end_date.isoformat(),
                },
                "namespace": self.namespace if self.namespace else "all",
            },
            "summary": self._generate_summary(),
            "findings": {
                k: v for k, v in self.findings.items() if v
            },  # Only include non-empty categories
            "correlations": self.correlations,
            "timeline": self.timeline,
            "first_issue": self.first_issue,
            "recommendations": recommendations,
            "errors": self.errors,
        }

        return results

    def _generate_summary(self):
        """Generate summary of findings using same severity logic as HTML output"""
        critical = 0
        warning = 0
        info = 0
        current_state_count = 0
        historical_event_count = 0
        current_state_critical = 0
        historical_event_critical = 0

        for cat, items in self.findings.items():
            for item in items:
                severity = self._classify_severity(item.get("summary", ""), item.get("details", {}))
                finding_type = item.get("details", {}).get(
                    "finding_type", FindingType.CURRENT_STATE
                )

                if severity == "critical":
                    critical += 1
                    if finding_type == FindingType.HISTORICAL_EVENT:
                        historical_event_critical += 1
                    else:
                        current_state_critical += 1
                elif severity == "warning":
                    warning += 1
                else:
                    info += 1

                if finding_type == FindingType.HISTORICAL_EVENT:
                    historical_event_count += 1
                else:
                    current_state_count += 1

        total_issues = critical + warning + info
        categories_with_issues = [cat for cat, items in self.findings.items() if items]
        total_categories = len(self.findings)
        healthy_checks = total_categories - len(categories_with_issues)

        return {
            "total_issues": total_issues,
            "critical": critical,
            "warning": warning,
            "info": info,
            "categories": categories_with_issues,
            "healthy_checks": healthy_checks,
            "total_categories": total_categories,
            "current_state_count": current_state_count,
            "historical_event_count": historical_event_count,
            "current_state_critical": current_state_critical,
            "historical_event_critical": historical_event_critical,
        }

    def generate_recommendations(self):
        """
        Generate evidence-based recommendations with findings context.

        Creates actionable recommendations for each finding category, including
        AWS documentation links, diagnostic steps, and evidence from actual findings.

        Returns:
            list[dict]: List of recommendations, each containing:
                - title: Human-readable recommendation title
                - category: Finding category this addresses
                - priority: critical, high, medium, or low
                - action: Specific action to take
                - aws_doc: Link to relevant AWS documentation
                - evidence: Dict with counts, examples, affected resources
                - diagnostic_steps: List of kubectl/AWS CLI commands to run
                - is_correlation: True if this is a correlation-based recommendation
        """
        recommendations = []

        # Helper function to extract evidence from findings
        def extract_evidence(findings_list, max_examples=3):
            """Extract evidence summary from findings list"""
            if not findings_list:
                return None

            critical_count = 0
            warning_count = 0
            info_count = 0
            affected_resources = set()
            examples = []
            timestamps = []

            for finding in findings_list:
                summary = finding.get("summary", "")
                details = finding.get("details", {})

                severity = self._classify_severity(summary, details)
                if severity == "critical":
                    critical_count += 1
                elif severity == "warning":
                    warning_count += 1
                else:
                    info_count += 1

                # Extract affected resources
                for key in ["node", "pod", "namespace", "pvc", "service", "subnet_id"]:
                    if key in details and details[key]:
                        affected_resources.add(str(details[key]))

                # Extract timestamps
                ts = details.get("timestamp") or details.get("lastTimestamp")
                if ts:
                    timestamps.append(str(ts))

                # Collect examples
                if len(examples) < max_examples:
                    summary = finding.get("summary", "")
                    if summary:
                        examples.append(summary[:100])

            return {
                "total_count": len(findings_list),
                "critical_count": critical_count,
                "warning_count": warning_count,
                "info_count": info_count,
                "affected_resources": list(affected_resources)[:10],
                "examples": examples,
                "first_seen": min(timestamps) if timestamps else None,
                "last_seen": max(timestamps) if timestamps else None,
            }

        # Memory pressure recommendations
        if self.findings["memory_pressure"]:
            evidence = extract_evidence(self.findings["memory_pressure"])
            recommendations.append(
                {
                    "title": "Resolve Memory Pressure Issues",
                    "category": "memory_pressure",
                    "priority": "critical",
                    "action": "Increase pod memory limits, scale up node instance types, or enable cluster autoscaler",
                    "aws_doc": "https://repost.aws/knowledge-center/eks-resolve-memory-pressure",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Run: kubectl describe node <node-name> | grep -A 5 'Allocated resources'",
                        "Check: kubectl top pods --all-namespaces --sort-by=memory",
                        "Review: Application memory profiling and leak detection",
                        "Consider: Vertical Pod Autoscaler (VPA) for right-sizing",
                    ],
                }
            )

        # Disk pressure recommendations
        if self.findings["disk_pressure"]:
            evidence = extract_evidence(self.findings["disk_pressure"])
            recommendations.append(
                {
                    "title": "Resolve Disk Pressure Issues",
                    "category": "disk_pressure",
                    "priority": "critical",
                    "action": "Increase EBS volume size, configure kubelet garbage collection, or add ephemeral storage limits",
                    "aws_doc": "https://repost.aws/knowledge-center/eks-resolve-disk-pressure",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Run: kubectl describe node <node-name> | grep -A 10 'Conditions'",
                        "Check: df -h on affected nodes (via SSM/SSH)",
                        "Clean: docker system prune -a --volumes (careful on prod)",
                        "Configure: kubelet --image-gc-high-threshold and --image-gc-low-threshold",
                    ],
                }
            )

        # OOM recommendations
        if self.findings["oom_killed"]:
            evidence = extract_evidence(self.findings["oom_killed"])
            recommendations.append(
                {
                    "title": "Fix Out of Memory Kills",
                    "category": "oom_killed",
                    "priority": "critical",
                    "action": "Set appropriate memory requests/limits and review application memory usage",
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/best-practices/windows-oom.html",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Run: kubectl describe pod <pod-name> | grep -A 5 'Last State'",
                        "Check: kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].resources}'",
                        "Review: Application logs before OOM event",
                        "Consider: Memory profiling tools (pprof, jemalloc)",
                    ],
                }
            )

        # Scheduling failure recommendations
        if self.findings["scheduling_failures"]:
            evidence = extract_evidence(self.findings["scheduling_failures"])
            recommendations.append(
                {
                    "title": "Resolve Pod Scheduling Failures",
                    "category": "scheduling_failures",
                    "priority": "high",
                    "action": "Review resource requests, node capacity, node selectors, and taints/tolerations",
                    "aws_doc": "https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Run: kubectl describe pod <pod-name> | grep -A 20 'Events'",
                        "Check: kubectl get nodes -o custom-columns=NAME:.metadata.name,CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory",
                        "Review: Pod resource requests vs node allocatable",
                        "Consider: Cluster Autoscaler or Karpenter for dynamic scaling",
                    ],
                }
            )

        # Network issue recommendations
        if self.findings["network_issues"]:
            evidence = extract_evidence(self.findings["network_issues"])
            recommendations.append(
                {
                    "title": "Fix Network Issues",
                    "category": "network_issues",
                    "priority": "high",
                    "action": "Check VPC-CNI health, security groups, and network policies",
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html#troubleshoot-network",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Run: kubectl get pods -n kube-system -l k8s-app=aws-node",
                        "Check: kubectl logs -n kube-system -l k8s-app=aws-node --tail=100",
                        "Review: VPC CNI configuration (WARM_ENI_TARGET, ENABLE_PREFIX_DELEGATION)",
                        "Verify: Security group rules allow required traffic",
                    ],
                }
            )

        # Image pull failure recommendations
        if self.findings["image_pull_failures"]:
            evidence = extract_evidence(self.findings["image_pull_failures"])
            recommendations.append(
                {
                    "title": "Resolve Image Pull Failures",
                    "category": "image_pull_failures",
                    "priority": "high",
                    "action": "Verify image exists, check registry authentication, and review pull secrets",
                    "aws_doc": "https://kubernetes.io/docs/tasks/configure-pod-container/pull-image-private-registry/",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Run: kubectl describe pod <pod-name> | grep -A 10 'Events'",
                        "Check: kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data}'",
                        "Verify: ECR repository exists and has correct permissions",
                        "Test: aws ecr describe-repositories --repository-names <repo>",
                    ],
                }
            )

        # PVC issue recommendations
        if self.findings["pvc_issues"]:
            evidence = extract_evidence(self.findings["pvc_issues"])
            recommendations.append(
                {
                    "title": "Fix PVC and Storage Issues",
                    "category": "pvc_issues",
                    "priority": "medium",
                    "action": "Check storage class, EBS CSI driver, and volume availability zones",
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/ebs-csi.html",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Run: kubectl get pvc -A | grep -v Bound",
                        "Check: kubectl describe pvc <pvc-name> -n <namespace>",
                        "Verify: EBS CSI driver pod health",
                        "Review: StorageClass configuration and zone topology",
                    ],
                }
            )

        # Addon issue recommendations
        if self.findings["addon_issues"]:
            evidence = extract_evidence(self.findings["addon_issues"])
            recommendations.append(
                {
                    "title": "Update or Fix EKS Addons",
                    "category": "addon_issues",
                    "priority": "high",
                    "action": "Update addons to latest compatible version or troubleshoot specific addon issues",
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/eks-add-ons.html",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Run: aws eks list-addons --cluster-name <cluster>",
                        "Check: kubectl get pods -n kube-system",
                        "Review: Addon health issues in EKS console",
                        "Update: aws eks update-addon --cluster-name <cluster> --addon-name <addon> --addon-version <version>",
                    ],
                }
            )

        # Control plane issue recommendations
        if self.findings["control_plane_issues"]:
            evidence = extract_evidence(self.findings["control_plane_issues"])
            recommendations.append(
                {
                    "title": "Investigate Control Plane Errors",
                    "category": "control_plane_issues",
                    "priority": "high",
                    "action": "Review CloudWatch control plane logs, check API server latency, and verify IAM authenticator configuration",
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Check: CloudWatch Logs /aws/eks/<cluster>/cluster",
                        "Review: API server audit logs for patterns",
                        "Monitor: API server latency metrics",
                        "Verify: IAM authenticator configuration",
                    ],
                }
            )

        # RBAC issue recommendations
        if self.findings["rbac_issues"]:
            evidence = extract_evidence(self.findings["rbac_issues"])
            recommendations.append(
                {
                    "title": "Fix RBAC Authorization Issues",
                    "category": "rbac_issues",
                    "priority": "high",
                    "action": "Review RoleBindings, ClusterRoleBindings, and service account permissions",
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/access-entries.html",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Run: kubectl auth can-i --list --as=system:serviceaccount:<ns>:<sa>",
                        "Check: kubectl get rolebindings,clusterrolebindings -A",
                        "Review: AWS IAM to Kubernetes RBAC mapping",
                        "Verify: Service account annotations for IRSA",
                    ],
                }
            )

        # Node issue recommendations
        if self.findings["node_issues"]:
            evidence = extract_evidence(self.findings["node_issues"])
            recommendations.append(
                {
                    "title": "Resolve Node Health Issues",
                    "category": "node_issues",
                    "priority": "critical",
                    "action": "Check EC2 instance health, kubelet logs, and node capacity",
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/managed-node-groups.html",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Run: kubectl describe node <node-name>",
                        "Check: AWS Console EC2 instance status checks",
                        "Review: kubelet logs via SSM Session Manager",
                        "Verify: Node IAM role permissions",
                    ],
                }
            )

        # DNS issue recommendations
        if self.findings["dns_issues"]:
            evidence = extract_evidence(self.findings["dns_issues"])
            recommendations.append(
                {
                    "title": "Fix CoreDNS Issues",
                    "category": "dns_issues",
                    "priority": "high",
                    "action": "Check CoreDNS pod health, verify ConfigMap settings, and review DNS throttling",
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/coredns.html",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Run: kubectl get pods -n kube-system -l k8s-app=kube-dns",
                        "Check: kubectl logs -n kube-system -l k8s-app=kube-dns",
                        "Review: kubectl get configmap coredns -n kube-system -o yaml",
                        "Test: kubectl run -it --rm debug --image=busybox -- nslookup kubernetes",
                    ],
                }
            )

        # Resource quota recommendations
        if self.findings["resource_quota_exceeded"]:
            evidence = extract_evidence(self.findings["resource_quota_exceeded"])
            recommendations.append(
                {
                    "title": "Review Resource Quotas",
                    "category": "resource_quota_exceeded",
                    "priority": "medium",
                    "action": "Increase quota limits, optimize resource requests, or implement namespace isolation",
                    "aws_doc": "https://kubernetes.io/docs/concepts/policy/resource-quotas/",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Run: kubectl describe resourcequota -n <namespace>",
                        "Check: kubectl get pods -n <namespace> -o custom-columns=NAME:.metadata.name,CPU:.spec.containers[0].resources.requests.cpu",
                        "Review: Actual vs requested resource usage",
                        "Consider: ResourceQuota optimization or removal",
                    ],
                }
            )

        # Pod error recommendations
        if self.findings["pod_errors"]:
            evidence = extract_evidence(self.findings["pod_errors"])
            recommendations.append(
                {
                    "title": "Investigate Pod Errors",
                    "category": "pod_errors",
                    "priority": "high",
                    "action": "Review pod events, container logs, and resource constraints",
                    "aws_doc": "https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html",
                    "evidence": evidence,
                    "diagnostic_steps": [
                        "Run: kubectl describe pod <pod-name> -n <namespace>",
                        "Check: kubectl logs <pod-name> -n <namespace> --previous",
                        "Review: Container exit codes and restart counts",
                        "Verify: ConfigMaps and Secrets referenced by pod",
                    ],
                }
            )

        # Correlation-based recommendations (v2.0.0)
        if self.correlations:
            for corr in self.correlations:
                recommendations.append(
                    {
                        "title": f"Root Cause: {corr['root_cause']}",
                        "category": corr["correlation_type"],
                        "priority": "critical" if corr.get("severity") == "critical" else "high",
                        "action": corr["recommendation"],
                        "aws_doc": corr.get("aws_doc", ""),
                        "evidence": {
                            "correlation_type": corr["correlation_type"],
                            "impact": corr["impact"],
                            "root_cause_time": corr.get("root_cause_time"),
                            "affected_components": corr.get("affected_components", {}),
                        },
                        "is_correlation": True,
                    }
                )

        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        recommendations.sort(key=lambda x: priority_order.get(x.get("priority", "info"), 4))

        return recommendations


# === SECTION 6: CLI HANDLING ===


def create_argument_parser():
    """Create argument parser with all CLI options"""
    parser = argparse.ArgumentParser(
        description="Comprehensive EKS Debugging Tool - Systematic diagnosis of EKS cluster issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive cluster selection with default 24h lookback
  python eks_comprehensive_debugger.py --profile prod --region eu-west-1

  # Specific cluster with 6 hour lookback
  python eks_comprehensive_debugger.py --profile prod --region eu-west-1 --cluster-name my-cluster --hours 6

  # Using custom kube context (SSM tunnel, VPN, etc.)
  python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \\
    --cluster-name my-cluster --kube-context my-cluster-ssm-tunnel --days 2

  # Historical analysis with specific date range and timezone
  python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \\
    --cluster-name my-cluster \\
    --start-date "2026-02-15T08:00:00" --end-date "2026-02-16T18:00:00" \\
    --timezone "Asia/Dubai"

  # Focus on specific namespace
  python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \\
    --cluster-name my-cluster --namespace production

Output:
  Always generates two files:
    - {cluster}-eks-report-{timestamp}.html      - Interactive HTML dashboard
    - {cluster}-eks-findings-{timestamp}.json    - LLM-ready JSON for AI analysis
        """,
    )

    # Required arguments
    parser.add_argument("--profile", required=True, help="AWS profile from ~/.aws/credentials")
    parser.add_argument("--region", required=True, help="AWS region (e.g., eu-west-1, us-east-1)")

    # Optional cluster specification
    parser.add_argument(
        "--cluster-name",
        help="EKS cluster name (if not provided, will prompt for selection)",
    )
    parser.add_argument(
        "--kube-context",
        help="Kubernetes context name (skips kubeconfig update, e.g., 'levelshoes-prod-ssm-tunnel')",
    )

    # Date range options (mutually exclusive groups)
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument(
        "--start-date",
        help='Start date (ISO 8601: "2026-02-15T00:00:00Z" or "2026-02-15")',
    )
    date_group.add_argument("--hours", type=int, help="Look back N hours from now")
    date_group.add_argument("--days", type=int, help="Look back N days from now")

    parser.add_argument(
        "--end-date",
        help='End date (ISO 8601: "2026-02-16T00:00:00Z" or "2026-02-16", default: now)',
    )

    parser.add_argument(
        "--timezone",
        default="UTC",
        help="Timezone for date interpretation (default: UTC)",
    )

    # Filtering options
    parser.add_argument("--namespace", help="Focus on specific Kubernetes namespace")

    # Verbosity options
    verbosity_group = parser.add_mutually_exclusive_group()
    verbosity_group.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose/debug output"
    )
    verbosity_group.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress messages, show only results",
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    return parser


def parse_flexible_date(date_str, tz_name="UTC"):
    """
    Parse flexible date formats

    Supports:
    - ISO 8601: "2026-02-15T10:30:00Z"
    - Date only: "2026-02-15" (assumes 00:00:00)
    - Relative: "-2h", "-3d", "now"

    Returns timezone-aware datetime in UTC
    """
    if not date_str:
        return None

    tz = pytz.timezone(tz_name)

    # Handle relative dates
    if date_str.lower() == "now":
        return datetime.now(timezone.utc)

    if date_str.startswith("-"):
        # Relative date like "-2h" or "-3d"
        try:
            value = int(date_str[1:-1])
            unit = date_str[-1].lower()

            if unit == "h":
                return datetime.now(timezone.utc) - timedelta(hours=value)
            elif unit == "d":
                return datetime.now(timezone.utc) - timedelta(days=value)
            else:
                raise ValueError(f"Unknown time unit: {unit}")
        except (ValueError, IndexError) as e:
            raise DateValidationError(
                f"Invalid relative date format: {date_str}. Use '-2h' or '-3d'"
            )

    # Parse ISO 8601 or date-only format
    try:
        dt = date_parser.parse(date_str)

        # If no timezone info, assume the specified timezone
        if dt.tzinfo is None:
            dt = tz.localize(dt)

        # Convert to UTC
        return dt.astimezone(timezone.utc)
    except Exception as e:
        raise DateValidationError(
            f"Invalid date format: {date_str}. Use ISO 8601 (2026-02-15T10:00:00Z) or YYYY-MM-DD"
        )


def validate_and_parse_dates(args):
    """
    Validate and parse date arguments

    Returns: (start_date, end_date) as timezone-aware UTC datetimes
    """
    end_date = datetime.now(timezone.utc)
    start_date = None

    # Parse end date if provided
    if args.end_date:
        end_date = parse_flexible_date(args.end_date, args.timezone)

    # Parse start date based on different options
    if args.start_date:
        start_date = parse_flexible_date(args.start_date, args.timezone)
    elif args.hours:
        start_date = end_date - timedelta(hours=args.hours)
    elif args.days:
        start_date = end_date - timedelta(days=args.days)
    else:
        # Default: 24 hours lookback
        start_date = end_date - timedelta(hours=DEFAULT_LOOKBACK_HOURS)

    # Validate date range
    if start_date >= end_date:
        raise DateValidationError(f"Start date ({start_date}) must be before end date ({end_date})")

    # Warn if date range is very large
    date_range = (end_date - start_date).days
    if date_range > 7:
        print(
            f"⚠️  Warning: Large date range ({date_range} days) may take several minutes to analyze",
            file=sys.stderr,
        )

    return start_date, end_date


# === SECTION 7: OUTPUT HANDLING ===


def output_results(results, cluster_name: str, timezone_name: str = "UTC"):
    """
    Output results as both HTML and LLM-JSON files.

    Generates two files:
    - {cluster_name}-eks-report-{timestamp}.html
    - {cluster_name}-eks-findings-{timestamp}.json
    """

    html_formatter = HTMLOutputFormatter()
    llm_formatter = LLMJSONOutputFormatter()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_cluster_name = cluster_name.replace("_", "-").replace(".", "-").lower()

    html_file = f"{safe_cluster_name}-eks-report-{timestamp}.html"
    json_file = f"{safe_cluster_name}-eks-findings-{timestamp}.json"

    # Add timezone to metadata
    results["metadata"]["timezone"] = timezone_name

    success = True

    print()
    print("=" * 70)
    print("GENERATING REPORTS")
    print("=" * 70)

    try:
        html_output = html_formatter.format(results)
        with open(html_file, "w") as f:
            f.write(html_output)
        print(f"✓ HTML Report:     {html_file}")
    except Exception as e:
        print(f"✗ Failed to write HTML report: {e}", file=sys.stderr)
        success = False

    try:
        json_output = llm_formatter.format(results)
        with open(json_file, "w") as f:
            f.write(json_output)
        print(f"✓ LLM JSON Report: {json_file}")
    except Exception as e:
        print(f"✗ Failed to write JSON report: {e}", file=sys.stderr)
        success = False

    print("=" * 70)
    print()

    if not success:
        sys.exit(2)

    return html_file, json_file


def get_exit_code(results):
    """
    Determine exit code based on results

    0 = success, no issues
    1 = success, but issues found
    2 = error during analysis
    """
    if results.get("errors"):
        # Check if errors are critical
        return 2
    elif results["summary"]["total_issues"] > 0:
        return 1
    else:
        return 0


# === SECTION 8: MAIN ENTRY POINT ===


def main():
    """Main entry point"""
    parser = create_argument_parser()
    args = parser.parse_args()

    # Create progress tracker
    progress = ProgressTracker(verbose=args.verbose, quiet=args.quiet)

    try:
        # Validate and parse dates
        start_date, end_date = validate_and_parse_dates(args)

        if not args.quiet:
            print("=" * 70)
            print(f"COMPREHENSIVE EKS DEBUGGER v{VERSION}")
            print("=" * 70)
            print(f"Profile:     {args.profile}")
            print(f"Region:      {args.region}")
            print(f"Timezone:    {args.timezone}")
            print(
                f"Date Range:  {start_date.strftime('%Y-%m-%d %H:%M:%S')} to {end_date.strftime('%Y-%m-%d %H:%M:%S')} (UTC)"
            )
            if args.namespace:
                print(f"Namespace:   {args.namespace}")
            if args.kube_context:
                print(f"Context:     {args.kube_context}")
            print("=" * 70)
            print()

        # Initialize debugger
        debugger = ComprehensiveEKSDebugger(
            profile=args.profile,
            region=args.region,
            cluster_name=args.cluster_name,
            start_date=start_date,
            end_date=end_date,
            namespace=args.namespace,
            progress=progress,
            kube_context=args.kube_context,
        )

        # Run analysis
        results = debugger.run_comprehensive_analysis()

        # Output results (always generates HTML + LLM-JSON)
        output_results(results, args.cluster_name, args.timezone)

        # Exit with appropriate code
        sys.exit(get_exit_code(results))

    except DateValidationError as e:
        progress.error(f"Date validation error: {e}")
        sys.exit(2)
    except AWSAuthenticationError as e:
        progress.error(f"AWS authentication error: {e}")
        progress.error("Please check your AWS credentials and profile configuration")
        sys.exit(2)
    except ClusterNotFoundError as e:
        progress.error(f"Cluster error: {e}")
        sys.exit(2)
    except KubectlNotAvailableError as e:
        progress.error(f"kubectl error: {e}")
        progress.error("Please ensure kubectl is installed and in your PATH")
        sys.exit(2)
    except KeyboardInterrupt:
        progress.error("\nAnalysis interrupted by user")
        sys.exit(130)
    except Exception as e:
        progress.error(f"Unexpected error: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()
