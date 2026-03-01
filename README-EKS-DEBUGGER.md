# EKS Health Check Dashboard

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![AWS EKS](https://img.shields.io/badge/AWS-EKS-orange.svg)](https://aws.amazon.com/eks/)
[![Catalog Coverage](https://img.shields.io/badge/catalog%20coverage-100%25-green.svg)](#catalog-coverage)
[![Tests](https://img.shields.io/badge/tests-158%20passing-brightgreen.svg)](#unit-tests)

A production-grade Python diagnostic tool for Amazon EKS cluster troubleshooting. Analyzes pod evictions, node conditions, OOM kills, CloudWatch metrics, control plane logs, and generates interactive HTML reports with LLM-ready JSON for AI analysis.

**Version:** 3.6.0 | **Analysis Methods:** 72 | **Catalog Coverage:** 100% | **Tests:** 158

---

## Features

### Comprehensive Issue Detection (72 Analysis Methods)

#### Pod & Workload Issues
- **CrashLoopBackOff** - Container crash detection with exit code analysis
- **ImagePullBackOff** - Registry authentication, rate limits, network issues
- **OOMKilled** - Memory limit exceeded detection
- **Pod Evictions** - Memory, disk, PID pressure analysis
- **Probe Failures** - Liveness/readiness probe failures
- **Init Container Failures** - Init container crash, timeout, dependency issues (v3.6.0)
- **Sidecar Health** - Istio, Envoy, Fluentd sidecar failures (v3.6.0)
- **Stuck Terminating** - Finalizer and volume detach issues
- **Deployment Rollouts** - ProgressDeadlineExceeded detection
- **Jobs/CronJobs** - BackoffLimitExceeded, missed schedules
- **StatefulSets** - PVC issues, ordinal failures
- **PDB Violations** - Pod Disruption Budget blocking drains (v3.6.0)
- **Ephemeral Containers** - Failed debug containers (v3.6.0)

#### Node Health
- **Node NotReady** - Kubelet, CNI, certificate issues
- **Disk/Memory/PID Pressure** - Resource exhaustion detection
- **Resource Saturation** - Pre-pressure detection >90% (v3.6.0)
- **PLEG Health** - Pod Lifecycle Event Generator issues
- **Container Runtime** - containerd unresponsive
- **Pause Image** - Sandbox image garbage-collected
- **Certificate Expiry** - Kubelet cert rotation failures
- **Node Group Health** - EKS managed node group status
- **Version Skew** - Kubelet version mismatch detection (v3.6.0)
- **AMI Age** - Outdated AMI detection (v3.6.0)

#### Networking
- **VPC CNI** - IP exhaustion, aws-node health
- **CoreDNS** - DNS resolution failures
- **DNS Configuration** - ndots:5 amplification detection (v3.6.0)
- **Service Health** - No endpoints, ClusterIP issues
- **EndpointSlices** - Backend readiness issues (v3.6.0)
- **Connectivity** - Connection refused, timeout, DNS failures
- **NetworkPolicy** - Traffic blocking detection
- **Ingress Health** - Missing backends, TLS secrets (v3.6.0)
- **ALB Health** - 5xx errors, unhealthy targets
- **Conntrack** - Connection tracking table exhaustion
- **Security Groups** - Rule misconfigurations
- **Subnet Health** - IP availability

#### Control Plane (8 methods)
- **API Server Latency** - High request latency
- **API Server Rate Limiting** - 429 errors, throttling
- **API Server Inflight** - Request saturation
- **etcd Health** - Quota exceeded, leader changes
- **Controller Manager** - Reconciliation failures
- **Scheduler Health** - Scheduling issues
- **Admission Webhooks** - Timeout/failure detection
- **Control Plane Logs** - Error pattern analysis

#### Storage
- **PVC Issues** - Pending, ProvisioningFailed
- **PV State** - Released/Failed detection
- **EBS CSI** - Attachment failures, AZ mismatch
- **EFS CSI** - Mount failures
- **Volume Snapshots** - Failed snapshot operations (v3.6.0)

#### IAM & RBAC
- **RBAC Errors** - Forbidden, Unauthorized
- **IRSA/Pod Identity** - Credential fetch failures
- **CloudTrail Correlation** - AssumeRole failures
- **PSA Violations** - Pod Security Admission
- **Missing ConfigMaps/Secrets** - Resource not found
- **Workload Security Posture** - Privileged containers, host paths (v3.6.0)

#### Autoscaling
- **Cluster Autoscaler** - Scaling issues
- **Karpenter** - Provisioning failures, drift detection (v3.6.0)
- **Fargate** - Profile health
- **HPA/VPA** - Scaling not active
- **HPA Metrics Source** - metrics-server health (v3.6.0)
- **Topology Spread** - Constraint violations (v3.6.0)

#### Observability
- **CloudWatch Logging** - Pipeline health
- **Container Insights** - Metrics availability
- **EKS Addons** - VPC-CNI, CoreDNS, kube-proxy
- **Deprecated APIs** - Upgrade readiness check (v3.6.0)

### Finding Type Classification
Each finding is classified as either:
- **📅 Historical Event** - Occurred within the specified date range (filtered by time)
- **🔄 Current State** - Current cluster state (not filtered by date)

### Smart Correlation with 5D Confidence Scoring (v3.6.0)
- **Root cause identification** across data sources
- **5-dimensional confidence scoring:**
  - Temporal (30%): Does cause precede effect?
  - Spatial (20%): Same node/pod/namespace?
  - Mechanism (25%): Known causal relationship?
  - Exclusivity (15%): Only plausible cause?
  - Reproducibility (10%): Pattern repeated?
- **Confidence tiers:** high (≥0.75), medium (≥0.50), low (<0.50)
- **Spatial correlation:** Node/namespace/pod overlap detection
- **Timeline of events** by hour
- **First issue detection** (potential root cause)
- **Cascading failure analysis**

### Performance Optimizations (v3.3.0)
- **Parallel Analysis** - 72 methods run concurrently using ThreadPoolExecutor
- **Shared Data Pre-fetching** - CloudWatch log groups and kubectl data fetched once
- **API Response Caching** - TTL-based cache for AWS API calls (5-minute default)
- **kubectl Output Caching** - Reuses kubectl command results across methods
- **Performance Metrics** - Reports slowest methods and cache statistics
- **Pagination Support** - Handles >100 clusters via nextToken (v3.6.0)

### Security Features (v3.4.0+)
- **Input Validation** - All CLI parameters validated with strict regex patterns (max 256 chars)
- **Shell Injection Prevention** - Blocks dangerous characters (`;`, `|`, `&&`, `$()`, backticks)
- **XSS Prevention** - HTML output properly escaped (v3.6.0)
- **Secure File Permissions** - Output files created with `0o600` (owner-only)
- **Log Sanitization** - AWS Account ID masked, IAM ARN truncated
- **Thread-Safe Operations** - Concurrent analysis with proper locking
- **Exponential Backoff** - API throttling resilience with jitter (v3.6.0)

### Automatic Report Generation
- **HTML Report** - Interactive dashboard with sidebar navigation, search, filtering, and dark mode
- **LLM-Ready JSON** - Structured output with confidence tiers optimized for AI analysis

---

## Installation

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Prerequisites

1. **Python 3.8+**
2. **kubectl** installed and configured
3. **AWS CLI** with appropriate credentials
4. **IAM Permissions**:
   - `eks:ListClusters`, `eks:DescribeCluster`
   - `eks:ListAddons`, `eks:DescribeAddon`
   - `eks:ListNodegroups`, `eks:DescribeNodegroup`
   - `cloudwatch:GetMetricStatistics`, `cloudwatch:ListMetrics`
   - `logs:DescribeLogGroups`, `logs:DescribeLogStreams`, `logs:GetLogEvents`
   - `ec2:DescribeInstances`, `ec2:DescribeInstanceStatus`
   - `ec2:DescribeSubnets`, `ec2:DescribeSecurityGroups`
   - `service-quotas:ListServiceQuotas`
   - `cloudtrail:LookupEvents` (optional, for IAM correlation)
   - `sts:GetCallerIdentity`

---

## Quick Start

```bash
# Basic usage - generates both HTML and JSON reports
python eks_comprehensive_debugger.py --profile prod --region eu-west-1

# Specific cluster with time range
python eks_comprehensive_debugger.py \
  --profile prod \
  --region eu-west-1 \
  --cluster-name my-cluster \
  --days 2

# Using custom kubectl context (SSM tunnel, VPN)
python eks_comprehensive_debugger.py \
  --profile prod \
  --region eu-west-1 \
  --cluster-name my-cluster \
  --kube-context my-cluster-ssm-tunnel \
  --days 1

# Historical analysis with timezone
python eks_comprehensive_debugger.py \
  --profile prod \
  --region eu-west-1 \
  --cluster-name my-cluster \
  --start-date "2026-01-26T08:00:00" \
  --end-date "2026-01-27T18:00:00" \
  --timezone "Asia/Dubai"
```

---

## CLI Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--profile` | Yes | AWS profile from ~/.aws/credentials |
| `--region` | Yes | AWS region (e.g., eu-west-1) |
| `--cluster-name` | No | EKS cluster name (prompts if not provided) |
| `--kube-context` | No | Kubernetes context name (skips kubeconfig update) |
| `--hours` | No | Look back N hours from now |
| `--days` | No | Look back N days from now |
| `--start-date` | No | Start date (ISO 8601 or YYYY-MM-DD, supports time: 2026-01-26T08:00:00) |
| `--end-date` | No | End date (ISO 8601 or YYYY-MM-DD, supports time: 2026-01-27T18:00:00) |
| `--timezone` | No | Timezone for date parsing (default: UTC, e.g., "Asia/Dubai") |
| `--namespace` | No | Focus on specific namespace |
| `--verbose` | No | Enable verbose output |
| `--quiet` | No | Suppress progress messages |

---

## Output Files

The tool **always generates two files** automatically:

### 1. HTML Report
`{cluster}-eks-report-{timestamp}.html`

Interactive dashboard with:
- Summary cards showing critical/warning/info counts
- Finding type breakdown (Historical Events vs Current State)
- Root cause confidence tiers (v3.6.0)
- Expandable findings with full details
- Severity classification
- Data source badges
- Evidence-based recommendations
- Dark mode support
- Print-friendly layout

### 2. LLM-Ready JSON
`{cluster}-eks-findings-{timestamp}.json`

Structured JSON optimized for AI analysis:

```json
{
  "analysis_context": {
    "cluster": "my-cluster",
    "region": "eu-west-1",
    "date_range": {"start": "2026-01-26T08:00:00Z", "end": "2026-01-27T18:00:00Z"},
    "timezone": "Asia/Dubai"
  },
  "summary": {
    "total_issues": 15,
    "critical": 3,
    "warning": 5,
    "info": 7,
    "historical_events": 8,
    "current_state_issues": 7
  },
  "findings": [
    {
      "id": "abc123",
      "category": "oom_killed",
      "severity": "critical",
      "finding_type": "historical_event",
      "summary": "Pod default/my-app was OOM killed",
      "timestamp": "2026-01-26T10:30:00Z"
    }
  ],
  "correlations": [...],
  "correlations_by_confidence_tier": {
    "high": [...],
    "medium": [...],
    "low": [...]
  },
  "potential_root_causes": [
    {
      "correlation_type": "node_pressure_cascade",
      "root_cause": "Node memory pressure detected",
      "confidence_tier": "high",
      "composite_confidence": 0.85,
      "spatial_evidence": {"overlap_score": 0.72, "node_matches": 3}
    }
  ],
  "recommendations": [...]
}
```

---

## Common Use Cases

### Incident Investigation
```bash
# Last 1 hour analysis
python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \
  --cluster-name production --hours 1
```

### Post-Mortem Analysis
```bash
# Specific incident timeframe with local timezone
python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \
  --cluster-name production \
  --start-date "2026-02-15T08:00:00" \
  --end-date "2026-02-16T18:00:00" \
  --timezone "America/New_York"
```

### Private Cluster Access
```bash
# Using SSM tunnel or VPN context
python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \
  --cluster-name production \
  --kube-context production-ssm-tunnel \
  --days 2
```

### Namespace-Specific Debugging
```bash
python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \
  --cluster-name production \
  --namespace my-app \
  --days 1
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success, no issues found |
| 1 | Success, issues found in cluster |
| 2 | Error during analysis |
| 130 | Interrupted by user (Ctrl+C) |

---

## Troubleshooting

### kubectl Timeout
Use `--kube-context` to provide a pre-configured context:
```bash
python eks_comprehensive_debugger.py ... --kube-context my-context
```

### Container Insights Not Available
Enable Container Insights:
```bash
aws eks update-cluster-config --name my-cluster --region eu-west-1 \
  --logging '{"clusterLogging":[{"types":["api","audit","authenticator","controllerManager","scheduler"],"enabled":true}]}'
```

### Private Cluster Access
For private endpoints, connect via:
- AWS VPN
- SSM Session Manager port forwarding
- Direct VPC access

---

## Unit Tests

The debugger includes a comprehensive test suite covering security and core functionality:

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run with coverage
python3 -m pytest tests/ -v --cov=. --cov-report=term-missing
```

### Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_severity_classification.py` | 35 | Critical/warning/info keyword detection, priority ordering |
| `test_input_validation.py` | 67 | Shell injection prevention, invalid character detection |
| `test_findings.py` | 10 | Finding limits, thread safety with concurrent access |
| `test_kubectl_execution.py` | 12 | shell=False execution, fallback logic, caching |
| `test_api_cache.py` | 11 | TTL expiration, thread safety, key generation |
| `test_incremental_cache.py` | 14 | Delta reporting, save/load, file permissions |
| `test_performance_tracker.py` | 9 | Timing aggregation, slowest methods, thread safety |

---

## Catalog Coverage

This tool implements 100% coverage of three comprehensive EKS troubleshooting catalogs:

| Catalog | Issues | Coverage |
|---------|--------|----------|
| EKS Issue Patterns | 49 | 100% |
| High-Value Kubernetes Issues | 21 | 100% |
| Common Kubernetes Issues | 9 | 100% |
| **Total** | **79** | **100%** |

---

## AWS Documentation References

- [EKS Troubleshooting](https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html)
- [EKS Disk Pressure Resolution](https://repost.aws/knowledge-center/eks-resolve-disk-pressure)
- [CloudWatch Container Insights](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/ContainerInsights.html)
- [EKS Observability Best Practices](https://docs.aws.amazon.com/prescriptive-guidance/latest/amazon-eks-observability-best-practices/)
- [EKS Control Plane Logging](https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html)
- [IAM Roles for Service Accounts](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identity.html)
- [AWS Load Balancer Controller](https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html)
- [VPC CNI](https://docs.aws.amazon.com/eks/latest/userguide/managing-vpc-cni.html)

---

## License

MIT License
