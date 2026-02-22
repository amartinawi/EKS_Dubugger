# Changelog

All notable changes to the EKS Comprehensive Debugger will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

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
