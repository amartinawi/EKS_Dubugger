# Security Policy

## Reporting a Vulnerability

We take the security of EKS Health Check Dashboard seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via:

- **Email:** security@amartinawi.com
- **GitHub Security Advisory:** Use the "Security" tab in the repository to create a private security advisory

You should receive a response within 48 hours. If for some reason you do not, please follow up via email to ensure we received your original message.

### What to Include

Please include the following information in your report:

1. **Type of issue** (e.g., buffer overflow, SQL injection, cross-site scripting, etc.)
2. **Full paths** of source file(s) related to the manifestation of the issue
3. **The location** of the affected source code (tag/branch/commit or direct URL)
4. **Any special configuration** required to reproduce the issue
5. **Step-by-step instructions** to reproduce the issue
6. **Proof-of-concept or exploit code** (if possible)
7. **Impact** of the issue, including how an attacker might exploit it

### Supported Versions

We release security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 3.7.x   | :white_check_mark: |
| 3.6.x   | :white_check_mark: |
| < 3.6   | :x:                |

### Security Features

This tool implements several security features:

#### Input Validation (v3.4.0+)
- All CLI parameters validated with strict regex patterns
- Maximum length of 256 characters for all inputs
- Blocks shell injection characters: `;`, `|`, `&&`, `$()`, backticks

#### Shell Injection Prevention (v3.4.0+)
- kubectl commands use `shell=False` with list arguments
- No user input passed directly to shell
- Safe subprocess execution patterns

#### XSS Prevention (v3.6.0+)
- HTML output properly escaped
- Modal content sanitized
- Error messages escaped in output

#### File Permissions (v3.4.0+)
- Output files (HTML, JSON) created with `0o600` (owner-only)
- Incremental cache files created with `0o600`
- Prevents credential leakage via world-readable reports

#### Log Sanitization (v3.4.0+)
- AWS Account ID masked (shows only last 4 digits: `****1234`)
- IAM ARN truncated to role/user name only
- Sensitive data not logged

#### API Security (v3.6.0+)
- Exponential backoff with jitter for API throttling
- Retryable vs non-retryable error classification
- No hard-coded credentials

### Security Best Practices When Using This Tool

1. **AWS Credentials:**
   - Never hard-code AWS credentials in scripts
   - Use IAM roles with least-privilege permissions
   - Use short-lived credentials (IRSA, Pod Identity)
   - Rotate credentials regularly

2. **Output Files:**
   - Review HTML reports before sharing (may contain sensitive cluster information)
   - Store reports securely (files are created with owner-only permissions)
   - Delete reports after use if they contain sensitive data

3. **Network Access:**
   - Run from a secure location with network access to your EKS cluster
   - Use VPN or bastion host for production clusters
   - Ensure kubectl context is configured correctly

4. **Permissions:**
   - Review required AWS permissions before running in production
   - See README for minimum required IAM policy
   - Use read-only permissions where possible

### Required AWS Permissions

The tool requires the following AWS permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "eks:DescribeCluster",
        "eks:ListClusters",
        "eks:ListAddons",
        "eks:DescribeAddon",
        "eks:ListUpdates",
        "eks:DescribeUpdate",
        "eks:ListNodegroups",
        "eks:DescribeNodegroup",
        "eks:ListFargateProfiles",
        "eks:ListInsights",
        "eks:DescribeInsight",
        "eks:ListPodIdentityAssociations"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
        "logs:GetLogEvents",
        "logs:StartQuery",
        "logs:GetQueryResults"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
        "cloudwatch:GetMetricData"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeSubnets",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeInstances"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudtrail:LookupEvents"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "servicequotas:ListServiceQuotas",
        "servicequotas:GetServiceQuota"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

### Disclosure Policy

We follow responsible disclosure:

1. **Report received:** We acknowledge within 48 hours
2. **Triage:** We assess severity and impact within 7 days
3. **Fix development:** We develop and test a fix
4. **Release:** We release a security update
5. **Disclosure:** We publish a security advisory after the fix is released

### Comments on this Policy

If you have suggestions on how this process could be improved, please submit a pull request or create an issue.

## Security Updates

Security updates are released as patch versions (e.g., 3.7.1, 3.7.2) and documented in [CHANGELOG.md](CHANGELOG.md).

### Recent Security Fixes

- **v3.7.2:** Fixed XSS vulnerability in copy-to-clipboard button
- **v3.6.0:** Added comprehensive XSS prevention in HTML output
- **v3.4.0:** Added input validation and shell injection prevention

## Additional Resources

- [AWS EKS Security Best Practices](https://docs.aws.amazon.com/eks/latest/userguide/security-best-practices.html)
- [Kubernetes Security Best Practices](https://kubernetes.io/docs/concepts/security/)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
