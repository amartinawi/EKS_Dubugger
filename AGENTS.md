# AGENTS.md

Guidelines for AI coding agents working in the EKS Health Check Dashboard codebase.

## Project Overview

Python-based diagnostic tool for Amazon EKS cluster troubleshooting. Single-file application (`eks_comprehensive_debugger.py`) that analyzes pod evictions, node conditions, OOM kills, CloudWatch metrics, control plane logs, and generates interactive HTML reports.

**Version:** 3.5.0  
**Lines of Code:** ~13,700  
**Analysis Methods:** 56  
**Catalog Coverage:** 100% (79 issues across 3 catalogs)  
**Unit Tests:** 158 tests

## Quick Commands

```bash
# Setup
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# Run analysis (generates HTML + LLM-JSON reports)
python eks_comprehensive_debugger.py --profile <profile> --region <region> --cluster-name <cluster> --days 2

# With custom kubectl context
python eks_comprehensive_debugger.py --profile <profile> --region <region> --cluster-name <cluster> --kube-context <context-name> --days 1

# Run unit tests
python3 -m pytest tests/ -v

# Lint/type check (optional)
ruff check eks_comprehensive_debugger.py
mypy eks_comprehensive_debugger.py --ignore-missing-imports
```

## File Structure

```
eks_comprehensive_debugger.py  # Main debugger (~13,600 lines, all-in-one)
requirements.txt               # Python dependencies (includes test deps)
.gitignore                     # Git ignore rules
README-EKS-DEBUGGER.md         # User documentation
AGENTS.md                      # This file
tests/                         # Unit tests (158 tests)
├── __init__.py
├── conftest.py                # Shared fixtures
├── test_severity_classification.py  # Severity logic tests
├── test_input_validation.py         # Security/shell injection tests
├── test_findings.py                 # Findings management tests
├── test_kubectl_execution.py        # Kubectl shell safety tests
├── test_api_cache.py                # APICache tests
├── test_incremental_cache.py        # IncrementalCache tests
└── test_performance_tracker.py      # PerformanceTracker tests
venv/                          # Virtual environment (gitignored)
```

## Dependencies

Required: `boto3>=1.26.0`, `python-dateutil>=2.8.0`, `pytz>=2023.0`
Optional: `pyyaml>=6.0` (for YAML output)
Testing: `pytest>=8.0.0`, `pytest-mock>=3.12.0`

## Code Architecture

### Security Architecture (v3.4.0)

The debugger implements defense-in-depth security for production use:

**Input Validation:**
```python
INPUT_VALIDATION_PATTERNS = {
    "profile": re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$"),
    "region": re.compile(r"^[a-z]{2}-[a-z]+-\d+$"),
    "cluster_name": re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$"),
    "namespace": re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"),
    "kube_context": re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/@-]*$"),
}

def validate_input(name: str, value: str) -> str:
    """Validate input parameter against safe pattern to prevent shell injection."""
```

**Shell Injection Prevention:**
- All user inputs (profile, region, cluster_name, namespace, kube_context) validated with strict regex
- Blocks: `;`, `|`, `&&`, `$()`, backticks, redirections, special chars
- `update_kubeconfig()`: Uses `shell=False` with list args
- `get_kubectl_output()`: Uses `shell=True` (required for `||`, pipes) with validated inputs

**File Permissions:**
- Output files (HTML, JSON) created with `0o600` (owner-only)
- IncrementalCache files created with `0o600`
- Prevents credential leakage via world-readable reports

**Log Sanitization:**
- AWS Account ID masked (shows only last 4 digits: `****1234`)
- IAM ARN truncated to role/user name only

### Thread Safety (v3.4.0)

The debugger uses thread-safe data structures for parallel analysis:

```python
self._findings_lock = threading.Lock()  # Protects self.findings mutations
self._shared_data_lock = threading.Lock()  # Protects cache access
```

**Finding Addition Pattern:**
```python
def _add_finding(self, category, summary, details, finding_type):
    with self._findings_lock:
        if len(self.findings[category]) >= self.max_findings:
            return False  # Limit enforced
        self.findings[category].append({...})
        return True

def _add_finding_dict(self, category, finding):
    """Convenience wrapper for dict-based findings."""
    return self._add_finding(category, finding["summary"], ...)
```

All 131+ finding additions go through `_add_finding_dict()` for:
1. Thread safety via lock
2. Max findings limit (500 per category)
3. Consistent finding_type classification

### Configuration Constants (v3.0.0)

```python
# Thresholds for alerting
class Thresholds:
    MEMORY_WARNING = 85        # %
    MEMORY_CRITICAL = 95       # %
    CPU_WARNING = 80           # %
    CPU_CRITICAL = 90          # %
    DISK_WARNING = 85          # %
    DISK_CRITICAL = 95         # %
    QUOTA_WARNING_RATIO = 0.9
    RESTART_WARNING = 5        # Container restart count
    RESTART_CRITICAL = 10
    PENDING_POD_WARNING = 5
    PENDING_POD_CRITICAL = 10

# Issue patterns knowledge base with root causes
EKS_ISSUE_PATTERNS = {
    "pod_issues": {
        "CrashLoopBackOff": {"root_causes": [...], "detection": {...}, "aws_doc": "..."},
        "ImagePullBackOff": {...},
        "CreateContainerConfigError": {...},
        "OOMKilled": {...},
        "Evicted": {...},
    },
    "node_issues": {
        "NotReady": {...},
        "DiskPressure": {...},
        "MemoryPressure": {...},
        "NetworkUnavailable": {...},
    },
    "network_issues": {
        "IPExhaustion": {...},
        "CNINotReady": {...},
        "DNSResolutionFailure": {...},
    },
    "iam_issues": {
        "AccessDenied": {...},
        "UnableToFetchCredentials": {...},
    },
    "storage_issues": {
        "PVCPending": {...},
        "VolumeAttachmentFailed": {...},
    },
    "scheduling_issues": {
        "InsufficientResources": {...},
        "AffinityConflict": {...},
    },
}

# Control plane log filtering
CONTROL_PLANE_BENIGN_PATTERNS = [
    'required revision has been compacted',
    'falling back to the standard LIST semantics',
    'watchlist request.*ended with an error',
    'etcdserver: mvcc',
    'resourceVersion.*is invalid',
]

CONTROL_PLANE_ERROR_PATTERNS = [
    'etcdserver: leader changed',
    'connection refused',
    'context deadline exceeded',
    'internal error',
    'admission denied',
    'authentication failed',
]
```

### Helper Methods

| Method | Purpose |
|--------|---------|
| `_build_kubectl_events_cmd(reason)` | Build kubectl events command with namespace/context |
| `_get_filtered_events(reason)` | Get and parse events filtered by reason |
| `_parse_event_common(event)` | Extract common fields from kubectl event |
| `_add_finding(category, summary, details)` | Thread-safe finding addition with limit enforcement |
| `_add_finding_dict(category, finding)` | Convenience wrapper for dict-based findings |
| `_classify_severity(summary, details)` | Classify finding severity based on content |
| `_extract_timestamp(details)` | Extract timestamp from finding details |
| `_get_node_from_pod(pod_details)` | Extract node name from pod details |
| `_get_bucket_severity(events)` | Determine severity for timeline bucket |
| `validate_input(name, value)` | Validate input against safe patterns (shell injection prevention) |

### Performance Architecture (v3.3.0)

The debugger uses several optimization strategies for fast analysis:

**Shared Data Pre-fetching:**
```python
def _prefetch_shared_data(self):
    """Pre-fetch commonly used data before parallel analysis."""
    # Pre-fetches CloudWatch log groups, kubectl nodes/pods
    # Reduces redundant API calls by 30-50%
```

**Caching Classes:**
| Class | Purpose |
|-------|---------|
| `APICache` | Thread-safe TTL cache for AWS API responses |
| `PerformanceTracker` | Track and report execution times for analysis methods |
| `IncrementalCache` | Store previous results for delta reporting |

**Helper Methods:**
| Method | Purpose |
|--------|---------|
| `_get_cached_log_group(prefix)` | Get cached CloudWatch log group data |
| `_get_cached_kubectl(cmd)` | Get cached kubectl output |
| `get_kubectl_output(cmd, use_cache=True)` | Run kubectl with optional caching |

**Parallel Execution:**
- Uses `ThreadPoolExecutor` with `MAX_PARALLEL_WORKERS=8`
- Analysis methods run concurrently with thread-safe findings collection
- Performance metrics logged for each method

**Results include performance data:**
```python
results = {
    ...
    "performance": {
        "slowest_methods": [{"method": "analyze_control_plane_logs", "total_time_seconds": 12.5}],
        "cache_stats": {"log_groups_cached": 5, "kubectl_commands_cached": 2}
    }
}
```

### Smart Correlation (v1.4.0)

The debugger performs intelligent correlation across data sources to identify root causes:

**Correlation Rules:**

| Rule | Trigger | Root Cause Detection |
|------|---------|---------------------|
| `node_pressure_cascade` | Node Disk/Memory Pressure + Pod Evictions | Pressure on node caused pod evictions |
| `cni_cascade` | VPC CNI issues + NetworkNotReady events | CNI problems caused network failures |
| `oom_pattern` | OOMKilled pods + Memory pressure | Node memory or pod limits causing OOM |
| `control_plane_impact` | Critical control plane errors + Pod failures | Control plane instability |
| `image_pull_pattern` | Image pull failures | Registry/auth issues |
| `scheduling_pattern` | Scheduling failures | Resource constraints or affinity rules |
| `dns_pattern` | DNS issues + CoreDNS health | CoreDNS configuration problems |

**Output Structure:**
```python
{
    "correlations": [
        {
            "correlation_type": "node_pressure_cascade",
            "severity": "critical",
            "root_cause": "Node memory pressure detected",
            "root_cause_time": "2026-02-20 10:30:00+00:00",
            "impact": "5 pods evicted due to memory pressure on 2 node(s)",
            "recommendation": "Address memory pressure on affected nodes...",
            "aws_doc": "https://repost.aws/knowledge-center/..."
        }
    ],
    "timeline": [
        {
            "time_bucket": "2026-02-20 10:00",
            "event_count": 15,
            "categories": ["oom_killed", "pod_errors"],
            "severity": "critical"
        }
    ],
    "first_issue": {
        "timestamp": "2026-02-20 10:00:05+00:00",
        "category": "node_issues",
        "summary": "Node ip-10-0-1-50 has MemoryPressure",
        "potential_root_cause": True
    }
}
```

### Main Classes

| Class | Purpose |
|-------|---------|
| `ComprehensiveEKSDebugger` | Main debugger orchestrator |
| `ProgressTracker` | Console progress reporting |
| `DateFilterMixin` | Date filtering utilities |
| `OutputFormatter` | Base class for output formatters |
| `ConsoleOutputFormatter` | Console output |
| `JSONOutputFormatter` | JSON output |
| `MarkdownOutputFormatter` | Markdown output |
| `YAMLOutputFormatter` | YAML output |
| `HTMLOutputFormatter` | Interactive HTML dashboard |
| `LLMJSONOutputFormatter` | LLM-optimized JSON output |
| `ExecutiveSummaryGenerator` | Generate executive summary from results |
| `APICache` | Thread-safe TTL cache for AWS API responses |
| `PerformanceTracker` | Track execution times for analysis methods |
| `IncrementalCache` | Store previous results for delta reporting |
| `TimezoneManager` | Centralized timezone handling |
| `ConfigLoader` | Load configuration from YAML/JSON files |
| `Thresholds` | Threshold configuration for alerts |
| `FindingType` | Finding type constants (current state vs historical) |

### Exception Hierarchy

```
EKSDebuggerError (base)
├── AWSAuthenticationError
├── ClusterNotFoundError
├── KubectlNotAvailableError
├── DateValidationError
├── InputValidationError    # v3.4.0: Invalid/unsafe input
└── EKSDebuggerError (general)
```

---

## Unit Tests (v3.4.0)

The test suite covers critical security and functionality areas:

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_severity_classification.py` | 35 | Critical/warning/info keyword detection, priority ordering, case insensitivity |
| `test_input_validation.py` | 67 | Shell injection prevention, invalid character detection, edge cases |
| `test_findings.py` | 10 | Finding limits, thread safety with concurrent access |
| `test_kubectl_execution.py` | 12 | shell=False execution, fallback logic, caching |
| `test_api_cache.py` | 11 | TTL expiration, thread safety, key generation |
| `test_incremental_cache.py` | 14 | Delta reporting, save/load, file permissions |
| `test_performance_tracker.py` | 9 | Timing aggregation, slowest methods, thread safety |

**Run Tests:**
```bash
python3 -m pytest tests/ -v
```

---

## Analysis Methods (56 total)

### Pod Lifecycle & Health (9 methods)

| Method | Data Source | Catalog Coverage |
|--------|-------------|------------------|
| `analyze_pod_evictions` | kubectl events | Pod evicted due to resource pressure |
| `check_oom_events` | kubectl events | Container OOMKilled (exit code 137) |
| `analyze_pod_health_deep` | kubectl pods | CrashLoopBackOff, init container failures, high restarts |
| `analyze_probe_failures` | kubectl events | Liveness/readiness probe failures |
| `analyze_image_pull_failures` | kubectl events | ImagePullBackOff, ErrImagePull, auth failures |
| `analyze_pods_terminating` | kubectl pods | Stuck in Terminating (finalizers) |
| `analyze_deployment_rollouts` | kubectl deployments | Rollout stuck, ProgressDeadlineExceeded |
| `analyze_jobs_cronjobs` | kubectl jobs/cronjobs | BackoffLimitExceeded, missed schedules |
| `analyze_statefulset_issues` | kubectl statefulsets | StatefulSet PVC issues, ordinal failures |

### Node Health (7 methods)

| Method | Data Source | Catalog Coverage |
|--------|-------------|------------------|
| `analyze_node_conditions` | kubectl nodes | NotReady, DiskPressure, MemoryPressure, PIDPressure |
| `analyze_eks_nodegroup_health` | EKS API | Managed node group degradation |
| `analyze_certificate_expiry` | kubectl nodes/events | Kubelet certificate rotation failures |
| `analyze_windows_nodes` | kubectl nodes | Windows node specific issues |
| `analyze_pleg_health` | kubectl nodes/events | PLEG not healthy |
| `analyze_container_runtime` | kubectl events | containerd not responding |
| `analyze_pause_image_issues` | kubectl events | Pause/sandbox image garbage-collected |

### Scheduling & Resources (6 methods)

| Method | Data Source | Catalog Coverage |
|--------|-------------|------------------|
| `analyze_pod_scheduling_failures` | kubectl events | FailedScheduling, taint/toleration, affinity |
| `analyze_resource_quotas` | kubectl resourcequotas | Quota exceeded, near-limit warnings |
| `analyze_cpu_throttling` | CloudWatch Metrics | CPU throttling, high utilization |
| `analyze_hpa_vpa` | kubectl hpa | HPA unable to scale, metrics unavailable |
| `analyze_gpu_scheduling` | kubectl nodes/pods | GPU scheduling issues |
| `analyze_limits_requests` | kubectl pods | Missing limits/requests, QoS analysis |

### Networking (9 methods)

| Method | Data Source | Catalog Coverage |
|--------|-------------|------------------|
| `analyze_network_issues` | kubectl events/pods | General network connectivity |
| `analyze_vpc_cni_health` | kubectl daemonset/events | IP exhaustion, aws-node health |
| `analyze_coredns_health` | kubectl deployment/events | DNS resolution failures |
| `analyze_service_health` | kubectl endpoints/services | No endpoints, connectivity issues |
| `analyze_subnet_health` | EC2 API | Subnet IP availability |
| `analyze_security_groups` | EC2 API | Security group rule issues |
| `analyze_network_policies` | kubectl networkpolicies | NetworkPolicy blocking traffic |
| `analyze_alb_health` | CloudWatch ALB metrics | ALB 5xx errors, unhealthy targets |
| `analyze_conntrack_health` | kubectl events/nodes | Conntrack table exhaustion |

### Storage (3 methods)

| Method | Data Source | Catalog Coverage |
|--------|-------------|------------------|
| `analyze_pvc_issues` | kubectl pvc/pv | PVC Pending, PV Released/Failed, ProvisioningFailed |
| `analyze_ebs_csi_health` | kubectl deployment/events | EBS CSI attachment failures |
| `analyze_efs_csi_health` | kubectl deployment/events | EFS mount failures |

### IAM & RBAC (4 methods)

| Method | Data Source | Catalog Coverage |
|--------|-------------|------------------|
| `analyze_rbac_issues` | kubectl events | Forbidden, Unauthorized errors |
| `analyze_iam_pod_identity` | kubectl + CloudTrail | IRSA/Pod Identity failures |
| `analyze_psa_violations` | kubectl pods/namespaces | Pod Security Admission violations |
| `analyze_missing_config_resources` | kubectl | Missing ConfigMaps/Secrets |

### Autoscaling (3 methods)

| Method | Data Source | Catalog Coverage |
|--------|-------------|------------------|
| `analyze_cluster_autoscaler` | kubectl deployment/logs | Cluster Autoscaler issues |
| `analyze_karpenter` | kubectl deployment/nodepools | Karpenter provisioning failures |
| `analyze_fargate_health` | EKS API | Fargate profile issues |

### AWS Infrastructure (3 methods)

| Method | Data Source | Catalog Coverage |
|--------|-------------|------------------|
| `analyze_service_quotas` | Service Quotas API | Quota limits approaching |
| `analyze_aws_lb_controller` | kubectl deployment/logs | AWS LB Controller issues |
| `analyze_custom_controllers` | kubectl deployments/events | Custom operator failures |

### Control Plane (8 methods)

| Method | Data Source | Catalog Coverage |
|--------|-------------|------------------|
| `analyze_control_plane_logs` | CloudWatch Logs | Control plane errors |
| `analyze_apiserver_latency` | CloudWatch Logs/Metrics | API server high latency |
| `analyze_apiserver_rate_limiting` | CloudWatch Logs | 429 rate limiting, throttling |
| `analyze_apiserver_inflight` | CloudWatch Metrics | Inflight request saturation |
| `analyze_etcd_health` | CloudWatch Logs | etcd quota exceeded, leader changes |
| `analyze_controller_manager` | CloudWatch Logs | Reconciliation failures |
| `analyze_scheduler_health` | CloudWatch Logs/Metrics | Scheduler issues |
| `analyze_admission_webhooks` | kubectl webhooks/events | Webhook timeouts/failures |

### Observability (4 methods)

| Method | Data Source | Catalog Coverage |
|--------|-------------|------------------|
| `check_container_insights_metrics` | CloudWatch Metrics | Node/pod resource metrics |
| `analyze_cloudwatch_logging_health` | CloudWatch Logs | Logging pipeline health |
| `check_eks_addons` | EKS API | EKS addon health |
| `correlate_findings` | Cross-source | Root cause correlation |

---

## Code Style

### Naming
- Classes: `PascalCase`
- Functions/Methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: `_prefix_with_underscore`
- Exceptions: Suffix with `Error`

### Type Hints
```python
def get_kubectl_output(self, cmd: str, timeout: int = DEFAULT_TIMEOUT, required: bool = False) -> str | None:
def safe_api_call(self, func: Callable, *args, **kwargs) -> tuple[bool, Any]:
```

### Error Handling

**Analysis Methods Exception Philosophy:**
Each of the 56 analysis methods wraps its logic in `try/except Exception` for **graceful degradation**. This is intentional: if one analysis method fails (e.g., API timeout, malformed data), other methods continue and the tool still produces useful output.

Known exception sources within methods:
- `json.loads()` → `json.JSONDecodeError` (malformed kubectl/AWS responses)
- Dict access → `KeyError` (unexpected response structure)
- boto3 API calls → `botocore.exceptions.ClientError` (permissions, throttling)
- subprocess → `subprocess.CalledProcessError`, `TimeoutExpired` (kubectl failures)

These are caught by `safe_kubectl_call()` and `safe_api_call()` helpers, but dict access and JSON parsing may still raise. The outer `Exception` catch is the safety net.

```python
try:
    method()
except Exception as e:
    self.errors.append({'step': 'method_name', 'message': str(e)})
    self.progress.warning(f"Analysis failed: {e}")
```

### kubectl Commands with Context
```python
# Context is added automatically if --kube-context is provided
output = self.safe_kubectl_call(cmd)
# Internally adds: --context {self.kube_context}
```

---

## Findings Structure

```python
self.findings = {
    'memory_pressure': [],      # Pod evictions due to memory
    'disk_pressure': [],        # Pod evictions due to disk
    'pod_errors': [],           # General pod errors
    'node_issues': [],          # Node conditions
    'oom_killed': [],           # OOMKilled containers
    'control_plane_issues': [], # Control plane log errors
    'scheduling_failures': [],  # FailedScheduling events
    'network_issues': [],       # CNI/DNS issues
    'rbac_issues': [],          # Authorization failures
    'image_pull_failures': [],  # Image pull errors
    'resource_quota_exceeded': [], # Quota warnings
    'pvc_issues': [],           # Storage issues
    'dns_issues': [],           # CoreDNS problems
    'addon_issues': []          # EKS addon health
}
```

---

## Results Output Format

```python
results = {
    'metadata': {
        'cluster': str,
        'region': str,
        'analysis_date': str,  # ISO 8601
        'date_range': {'start': str, 'end': str},
        'namespace': str | 'all'
    },
    'summary': {
        'total_issues': int,
        'critical': int,
        'warning': int,
        'info': int,
        'categories': list[str]
    },
    'findings': dict[str, list[dict]],
    'correlations': list[dict],      # Root cause analysis
    'timeline': list[dict],          # Event timeline by hour
    'first_issue': dict | None,      # Earliest detected issue
    'recommendations': list[dict],
    'errors': list[dict],
    'performance': {                 # v3.3.0+
        'slowest_methods': list[dict],
        'cache_stats': dict
    }
}
```

---

## Evidence-Based Recommendations (v2.1.0)

Each recommendation includes evidence from actual findings:

```python
{
    "title": "Resolve Memory Pressure Issues",
    "category": "memory_pressure",
    "priority": "critical",
    "action": "Increase pod memory limits...",
    "aws_doc": "https://repost.aws/knowledge-center/...",
    "evidence": {
        "total_count": 5,
        "critical_count": 2,
        "warning_count": 3,
        "info_count": 0,
        "affected_resources": [...],
        "examples": [...],
        "first_seen": "2026-02-20T10:00:00Z",
        "last_seen": "2026-02-20T12:00:00Z"
    },
    "diagnostic_steps": [
        "Run: kubectl describe node <node-name>",
        "Check: kubectl top pods --all-namespaces",
        ...
    ]
}
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success, no issues found |
| 1 | Success, issues found |
| 2 | Error during analysis |
| 130 | Interrupted (Ctrl+C) |

---

## Adding New Analysis

1. Create analysis method in `ComprehensiveEKSDebugger`
2. Add findings category to `self.findings` dict
3. Add icon mapping in `HTMLOutputFormatter.category_info`
4. Add category to sidebar navigation in HTML template
5. Generate recommendations in `generate_recommendations()`
6. Update `set_total_steps()` count
7. Add method to `analysis_methods` list in `run_comprehensive_analysis()`

---

## AWS Documentation References

- [EKS Disk Pressure](https://repost.aws/knowledge-center/eks-resolve-disk-pressure)
- [EKS Memory Pressure](https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html)
- [CloudWatch Container Insights](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/ContainerInsights.html)
- [EKS Observability Best Practices](https://docs.aws.amazon.com/prescriptive-guidance/latest/amazon-eks-observability-best-practices/)
- [EKS Troubleshooting](https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html)
- [EKS Control Plane Logging](https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html)
- [IRSA](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identity.html)
- [AWS Load Balancer Controller](https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html)
- [VPC CNI](https://docs.aws.amazon.com/eks/latest/userguide/managing-vpc-cni.html)
