# Changelog

All notable changes to the EKS Health Check Dashboard will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [3.7.0] - 2026-03-01

### Added
- **Remediation Commands** - Each finding now includes actionable diagnostic and fix commands
  - Diagnostic commands to investigate the issue
  - Fix commands to resolve the issue
  - AWS documentation links for detailed guidance
  - One-click copy buttons for easy command execution
- 30+ remediation patterns covering all major issue types:
  - Pod issues (CrashLoopBackOff, OOMKilled, ImagePullBackOff, Evicted)
  - Node issues (NotReady, MemoryPressure, DiskPressure)
  - Network issues (DNS, CNI, IP exhaustion)
  - Storage issues (PVC pending, volume attachment)
  - IAM/RBAC issues (access denied, IRSA)
  - Security issues (security groups, privileged containers)
  - Autoscaling issues (HPA, Cluster Autoscaler)
  - And more...

### Changed
- Enhanced HTML report with remediation section styling
- Added copyToClipboard JavaScript function for command copying
- Improved dark mode support for remediation sections

## [3.6.1] - 2026-03-01

### Fixed
- `analyze_deprecated_apis` condition now correctly checks if cluster is approaching removal version (was checking all already-removed APIs)
- `analyze_workload_security_posture` hostPath detection now uses exact match + prefix matching (was matching every path due to `/` substring)
- Spatial correlation weighting corrected: pod=50%, node=35%, namespace=15% (was inverted)

## [3.6.0] - 2026-03-01

### Security
- Fixed XSS vulnerabilities in HTML modal and error rendering
- Added max-length validation (256 chars) for all input parameters
- Implemented exponential backoff with jitter in `safe_api_call()` for API throttling resilience

### Added - 16 New Analysis Methods (56 → 72 total)

#### HIGH Priority (8 methods)
- `analyze_init_container_failures` - Detects stuck/failed init containers (CrashLoopBackOff, exit codes)
- `analyze_pdb_violations` - Detects PDBs blocking node drains and upgrades
- `analyze_sidecar_health` - Detects failed sidecars (Istio, Envoy, Fluentd, etc.)
- `analyze_node_resource_saturation` - Pre-pressure detection (>90% CPU/memory/disk)
- `analyze_version_skew` - Kubelet version skew detection across nodes
- `analyze_ingress_health` - Missing backend services, TLS secrets, ingress class issues
- `analyze_hpa_metrics_source` - metrics-server health for HPA scaling
- `analyze_deprecated_apis` - Deprecated API usage for upgrade planning

#### MEDIUM Priority (6 methods)
- `analyze_topology_spread` - Topology constraint violations (zone/node spread)
- `analyze_node_ami_age` - AMI age detection (90/180 day warnings)
- `analyze_endpointslice_health` - EndpointSlice readiness and backend health
- `analyze_dns_configuration` - ndots:5 DNS amplification detection
- `analyze_karpenter_drift` - NodeClaim drift detection
- `analyze_workload_security_posture` - Privileged containers, host paths, capabilities

#### LOW Priority (2 methods)
- `analyze_ephemeral_containers` - Failed debug containers (kubectl debug)
- `analyze_volume_snapshots` - Failed volume snapshots (VSC, VS issues)

### Added - Enhanced Root Cause Detection

#### 5-Dimensional Confidence Scoring
- **Temporal (30%)** - Does cause precede effect within causal window?
- **Spatial (20%)** - Are cause and effect on same node/pod/namespace?
- **Mechanism (25%)** - Is there a known causal relationship?
- **Exclusivity (15%)** - Is this the only plausible cause?
- **Reproducibility (10%)** - Has this pattern occurred multiple times?

#### Confidence Tiers
- `high` (≥0.75 composite) - Strong evidence of causality
- `medium` (≥0.50 composite) - Moderate evidence, needs validation
- `low` (<0.50 composite) - Weak correlation, investigate further

#### Spatial Correlation
- Pod overlap scoring (50% weight - strongest evidence)
- Node overlap scoring (35% weight)
- Namespace overlap scoring (15% weight)
- Returns matched resources for evidence

#### Enhanced Cluster Upgrade Detection
- AWS API-confirmed upgrades now get **high confidence** (0.92) and **primary ranking**
- Pattern-based detection with lowered threshold (score >= 2 instead of 3)
- New upgrade indicators: pod evictions, node pressure, DaemonSet restarts, OOM kills
- Multi-dimensional evidence collection: category spread, finding density, node churn
- AWS API confirmation bonus increased from +5 to +15 points in ranking
- Cluster upgrade with AWS confirmation gets additional +10 bonus

### Added - Enhanced LLM JSON Output
- `confidence_tier` field on all potential root causes
- `composite_confidence` and `confidence_5d` scores
- `spatial_evidence` with overlap details
- `correlations_by_confidence_tier` grouping (high/medium/low)
- Root causes sorted by composite confidence + score

### Changed
- `_rank_root_causes()` now uses 5D confidence + spatial correlation
- `_enhance_correlations()` applies 5D scoring to all correlation types
- `list_clusters()` now handles pagination for >100 clusters
- Thread-safe error handling via `_add_error()` helper (60+ calls updated)

### Fixed
- `services_offline` counting now tracks unique services with a set
- Duplicate `.summary-grid` CSS definition removed
- Dict rendering in `_render_detail_value()` fixed
- Dark mode styling for finding details, badges, and hover states
- Phone breakpoint (< 768px) responsive layout
- `exportFindingsCSV` function double-brace syntax
- `analyze_endpointslice_health` NoneType error when endpoints field is null
- `analyze_deprecated_apis` shell redirection issue (`2>&1` passed as resource name)

### Changed
- Kubectl error messages now suppress expected errors (NotFound, resource type not found)
- Added `suppress_expected_errors` parameter to `get_kubectl_output()` and `safe_kubectl_call()`
- Cleaner CLI output during analysis - no more noise from expected missing resources

## [3.5.0] - 2026-02-24

### Security
- Eliminated all `shell=True` subprocess calls to prevent shell injection
- Added `_run_kubectl_command()` helper with `shell=False` and list args
- Implemented `||` fallback logic in Python instead of shell
- Added 12 kubectl execution tests for shell safety verification

### Added
- 38 new unit tests for cache and performance classes
  - `test_api_cache.py`: 12 tests for APICache
  - `test_incremental_cache.py`: 16 tests for IncrementalCache
  - `test_performance_tracker.py`: 10 tests for PerformanceTracker
- Total test count: 158 (up from 124)

## [3.4.0] - 2026-02-23

### Security
- Input validation with strict regex patterns for all user inputs
- Secure file permissions (0o600) on HTML/JSON/cache files
- Log sanitization (masked AWS Account ID and truncated ARN)
- Escaped `aws_doc` hrefs in HTML output

### Added
- Thread-safe findings collection with `_findings_lock`
- `_add_finding_dict()` wrapper for consistent finding management
- 112 unit tests covering severity, input validation, and findings

## [3.0.0] - 2025-02-22

### Added
- 56 comprehensive analysis methods for EKS troubleshooting
- Interactive HTML dashboard with sidebar navigation and search
- Smart correlation engine for root cause identification
- Evidence-based recommendations with diagnostic steps
- Control plane log analysis (API server, etcd, scheduler, controller manager)
- VPC CNI and CoreDNS health analysis
- EBS/EFS CSI driver health checks
- IAM Pod Identity and IRSA validation
- Cluster Autoscaler and Karpenter analysis
- HPA/VPA and resource quota analysis
- Network policy and ALB health analysis
- Windows node and GPU scheduling support
- Admission webhook timeout detection
- 100% catalog coverage (79 issues across 3 catalogs)

### Changed
- Complete rewrite from original evictions-only tool
- Modular architecture with DateFilterMixin
- Multiple output formats (HTML, JSON, Markdown, YAML, Console)

### Fixed
- Improved kubectl context handling for private clusters
- Better error handling with graceful degradation

## [2.0.0] - 2024-12-01

### Added
- Control plane log analysis
- Multiple output format support
- Date range filtering

### Changed
- Renamed from `eks_eviction_debugger.py` to `eks_comprehensive_debugger.py`

## [1.0.0] - 2024-06-15

### Added
- Initial release
- Pod eviction analysis
- Node condition monitoring
- OOM kill detection
- CloudWatch metrics integration
