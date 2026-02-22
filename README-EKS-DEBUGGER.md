# EKS Comprehensive Debugger

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![AWS EKS](https://img.shields.io/badge/AWS-EKS-orange.svg)](https://aws.amazon.com/eks/)
[![Catalog Coverage](https://img.shields.io/badge/catalog%20coverage-100%25-green.svg)](#catalog-coverage)

A production-grade Python diagnostic tool for Amazon EKS cluster troubleshooting. Analyzes pod evictions, node conditions, OOM kills, CloudWatch metrics, control plane logs, and generates interactive HTML reports.

**Version:** 3.0.0 | **Analysis Methods:** 56 | **Catalog Coverage:** 100%

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

### Interactive HTML Reports
- Modern dashboard with sidebar navigation
- Real-time search and filtering
- Expandable findings with full details
- Severity classification (Critical/Warning/Info)
- Data source badges (CloudWatch Logs, kubectl, EKS API)
- Evidence-based recommendations
- Diagnostic step code blocks
- Print-friendly layout

### Smart Correlation
- Root cause identification across data sources
- Timeline of events by hour
- First issue detection (potential root cause)
- Cascading failure analysis

### Flexible Configuration
- Custom kubectl contexts (SSM tunnels, VPN)
- Date range filtering (hours, days, specific dates)
- Namespace filtering
- Multiple output formats (HTML, JSON, Markdown, YAML, Console)

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
# Basic usage with interactive cluster selection
python eks_comprehensive_debugger.py --profile prod --region eu-west-1

# Specific cluster with HTML output
python eks_comprehensive_debugger.py \
  --profile prod \
  --region eu-west-1 \
  --cluster-name my-cluster \
  --days 2 \
  --output-format html \
  --output-file report.html

# Using custom kubectl context (SSM tunnel, VPN)
python eks_comprehensive_debugger.py \
  --profile prod \
  --region eu-west-1 \
  --cluster-name my-cluster \
  --kube-context my-cluster-ssm-tunnel \
  --days 1 \
  --output-format html \
  --output-file report.html
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
| `--start-date` | No | Start date (ISO 8601 or YYYY-MM-DD) |
| `--end-date` | No | End date (ISO 8601 or YYYY-MM-DD) |
| `--namespace` | No | Focus on specific namespace |
| `--output-format` | No | Format: console, json, markdown, yaml, html |
| `--output-file` | No | Write to file instead of stdout |
| `--verbose` | No | Enable verbose output |
| `--quiet` | No | Suppress progress messages |

---

## Output Formats

### HTML (Recommended)
Interactive dashboard with navigation, search, and filtering.

```bash
python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \
  --cluster-name my-cluster \
  --output-format html --output-file report.html
```

### JSON
Structured output for automation and CI/CD integration.

```bash
python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \
  --cluster-name my-cluster \
  --output-format json --output-file report.json
```

### Markdown
Documentation-friendly format for Git-based runbooks.

```bash
python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \
  --cluster-name my-cluster \
  --output-format markdown --output-file report.md
```

### YAML
Human-readable structured output.

```bash
python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \
  --cluster-name my-cluster \
  --output-format yaml --output-file report.yaml
```

---

## Common Use Cases

### Incident Investigation
```bash
# Last 1 hour analysis
python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \
  --cluster-name production --hours 1 --output-format html
```

### Post-Mortem Analysis
```bash
# Specific incident timeframe
python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \
  --cluster-name production \
  --start-date "2026-02-15T00:00:00Z" \
  --end-date "2026-02-16T00:00:00Z" \
  --output-format markdown
```

### Private Cluster Access
```bash
# Using SSM tunnel or VPN context
python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \
  --cluster-name production \
  --kube-context production-ssm-tunnel \
  --days 2 --output-format html
```

### Weekly Health Check
```bash
python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \
  --cluster-name production \
  --days 7 --output-format json --output-file weekly-$(date +%Y%m%d).json
```

### Namespace-Specific Debugging
```bash
python eks_comprehensive_debugger.py --profile prod --region eu-west-1 \
  --cluster-name production \
  --namespace my-app \
  --days 1 --output-format html
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

### Control Plane Logs Not Available
Enable control plane logging in EKS console or via CLI:
```bash
aws eks update-cluster-config --name my-cluster --region eu-west-1 \
  --logging '{"clusterLogging":[{"types":["api","audit","authenticator","controllerManager","scheduler"],"enabled":true}]}'
```

### Private Cluster Access
For private endpoints, connect via:
- AWS VPN
- SSM Session Manager port forwarding
- Direct VPC access

### CloudTrail Permission Denied
If you see CloudTrail access errors, ensure your IAM role has:
```json
{
  "Effect": "Allow",
  "Action": "cloudtrail:LookupEvents",
  "Resource": "*"
}
```

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
