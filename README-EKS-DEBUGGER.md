# EKS Comprehensive Debugger

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![AWS EKS](https://img.shields.io/badge/AWS-EKS-orange.svg)](https://aws.amazon.com/eks/)
[![Catalog Coverage](https://img.shields.io/badge/catalog%20coverage-100%25-green.svg)](#catalog-coverage)

A production-grade Python diagnostic tool for Amazon EKS cluster troubleshooting. Analyzes pod evictions, node conditions, OOM kills, CloudWatch metrics, control plane logs, and generates interactive HTML reports with LLM-ready JSON for AI analysis.

**Version:** 3.1.0 | **Analysis Methods:** 56 | **Catalog Coverage:** 100%

---

## Features

### Comprehensive Issue Detection (56 Analysis Methods)

#### Pod & Workload Issues
- **CrashLoopBackOff** - Container crash detection with exit code analysis
- **ImagePullBackOff** - Registry authentication, rate limits, network issues
- **OOMKilled** - Memory limit exceeded detection
- **Pod Evictions** - Memory, disk, PID pressure analysis
- **Probe Failures** - Liveness/readiness probe failures
- **Init Container Failures** - Init container crash, timeout, dependency issues
- **Stuck Terminating** - Finalizer and volume detach issues
- **Deployment Rollouts** - ProgressDeadlineExceeded detection
- **Jobs/CronJobs** - BackoffLimitExceeded, missed schedules
- **StatefulSets** - PVC issues, ordinal failures

#### Node Health
- **Node NotReady** - Kubelet, CNI, certificate issues
- **Disk/Memory/PID Pressure** - Resource exhaustion detection
- **PLEG Health** - Pod Lifecycle Event Generator issues
- **Container Runtime** - containerd unresponsive
- **Pause Image** - Sandbox image garbage-collected
- **Certificate Expiry** - Kubelet cert rotation failures
- **Node Group Health** - EKS managed node group status

#### Networking
- **VPC CNI** - IP exhaustion, aws-node health
- **CoreDNS** - DNS resolution failures
- **Service Health** - No endpoints, ClusterIP issues
- **Connectivity** - Connection refused, timeout, DNS failures
- **NetworkPolicy** - Traffic blocking detection
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

#### IAM & RBAC
- **RBAC Errors** - Forbidden, Unauthorized
- **IRSA/Pod Identity** - Credential fetch failures
- **CloudTrail Correlation** - AssumeRole failures
- **PSA Violations** - Pod Security Admission
- **Missing ConfigMaps/Secrets** - Resource not found

#### Autoscaling
- **Cluster Autoscaler** - Scaling issues
- **Karpenter** - Provisioning failures
- **Fargate** - Profile health
- **HPA/VPA** - Scaling not active

#### Observability
- **CloudWatch Logging** - Pipeline health
- **Container Insights** - Metrics availability
- **EKS Addons** - VPC-CNI, CoreDNS, kube-proxy

### Finding Type Classification
Each finding is classified as either:
- **📅 Historical Event** - Occurred within the specified date range (filtered by time)
- **🔄 Current State** - Current cluster state (not filtered by date)

### Smart Correlation
- Root cause identification across data sources
- Timeline of events by hour
- First issue detection (potential root cause)
- Cascading failure analysis

### Automatic Report Generation
- **HTML Report** - Interactive dashboard with sidebar navigation, search, and filtering
- **LLM-Ready JSON** - Structured output optimized for AI/LLM analysis

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

1. **Python 3.7+**
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
- Expandable findings with full details
- Severity classification
- Data source badges
- Evidence-based recommendations
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
  "potential_root_causes": [...],
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
