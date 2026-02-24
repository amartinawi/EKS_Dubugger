# Changelog

All notable changes to the EKS Comprehensive Debugger will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

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
