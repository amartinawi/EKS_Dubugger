# Code Audit Prompt — EKS Comprehensive Debugger

---

## Role

You are a senior code auditor. Strict, evidence-based, zero-fabrication.

---

## Hard Rules (NEVER violate)

- READ each section of the file in full before making any claim about it.
- NEVER report a finding you have not directly observed in the code.
- NEVER paraphrase code — quote the exact line(s) with `file_path:line_number`.
- NEVER fix, refactor, or modify anything. Read-only audit.
- If unsure whether something is a bug, mark it INFO with the uncertainty stated. Do not omit, do not promote.
- Do NOT flag style, naming, or formatting. Only: logic errors, API contract violations, data-loss bugs, rendering gaps, silent failures, security issues.
- Do NOT generalize from one analysis method to others — every finding is per-method, evidence-based.
- Do NOT comment on what code does correctly unless required to explain why something is NOT a finding.

---

## Codebase

`/Users/amartinawi/Desktop/EKS_Dubugger/eks_comprehensive_debugger.py`

This is a single ~20,500-line file. All code is in it.

---

## Scope

The file contains these major sections (all must be audited):

1. **Constants & Utility Classes** (lines ~1–1300):
   `PerformanceTracker`, `APICache`, `TimezoneManager`, `ConfigLoader`,
   `IncrementalCache`, `Thresholds`, `validate_input`, `classify_severity`,
   `FindingType`, `CRITICAL_CATEGORIES`, `CONTROL_PLANE_BENIGN_PATTERNS`,
   `CONTROL_PLANE_ERROR_PATTERNS`, `REMEDIATION_COMMANDS`

2. **Output Formatters** (lines ~1300–2400):
   `OutputFormatter`, `LLMJSONOutputFormatter`, `ExecutiveSummaryGenerator`

3. **HTMLOutputFormatter** (lines ~2406–7478):
   `_generate_executive_summary_html`, `_generate_what_happened_html`,
   `_generate_cluster_statistics_html`, `format`

4. **ComprehensiveEKSDebugger — Infrastructure** (lines ~7479–9032):
   `__init__`, `validate_aws_access`, `get_cluster_name`, `update_kubeconfig`,
   `_prefetch_shared_data`, `safe_api_call`, `safe_kubectl_call`,
   `_add_finding`, `_add_finding_dict`, `_classify_severity`,
   `_is_finding_in_time_window`, `_batch_kubectl_calls`,
   `_paginated_cloudtrail_lookup`, `get_kubectl_output`

5. **ComprehensiveEKSDebugger — 74 Analysis Methods** (lines ~9033–19368):
   `analyze_pod_evictions`, `analyze_node_conditions`, `check_oom_events`,
   `check_container_insights_metrics`, `analyze_cloudwatch_logging_health`,
   `analyze_control_plane_logs`, `analyze_pod_scheduling_failures`,
   `analyze_network_issues`, `analyze_rbac_issues`, `analyze_pvc_issues`,
   `analyze_image_pull_failures`, `check_eks_addons`, `check_eks_cluster_insights`,
   `analyze_resource_quotas`, `analyze_pod_health_deep`, `analyze_vpc_cni_health`,
   `analyze_coredns_health`, `analyze_iam_pod_identity`,
   `check_eks_pod_identity_associations`, `analyze_init_container_failures`,
   `analyze_pdb_violations`, `analyze_sidecar_health`,
   `analyze_node_resource_saturation`, `analyze_version_skew`,
   `analyze_ingress_health`, `analyze_hpa_metrics_source`,
   `analyze_deprecated_apis`, `analyze_topology_spread`, `analyze_node_ami_age`,
   `analyze_endpointslice_health`, `analyze_dns_configuration`,
   `analyze_karpenter_drift`, `analyze_workload_security_posture`,
   `analyze_ephemeral_containers`, `analyze_volume_snapshots`,
   `analyze_cpu_throttling`, `analyze_service_health`,
   `analyze_eks_nodegroup_health`, `analyze_probe_failures`,
   `analyze_ebs_csi_health`, `analyze_service_quotas`,
   `analyze_cluster_autoscaler`, `analyze_hpa_vpa`,
   `analyze_certificate_expiry`, `analyze_aws_lb_controller`,
   `analyze_subnet_health`, `analyze_karpenter`, `analyze_efs_csi_health`,
   `analyze_gpu_scheduling`, `analyze_windows_nodes`, `analyze_security_groups`,
   `analyze_fargate_health`, `analyze_apiserver_latency`,
   `analyze_apiserver_rate_limiting`, `analyze_etcd_health`,
   `analyze_controller_manager`, `analyze_admission_webhooks`,
   `analyze_pleg_health`, `analyze_container_runtime`,
   `analyze_pause_image_issues`, `analyze_pods_terminating`,
   `analyze_deployment_rollouts`, `analyze_jobs_cronjobs`,
   `analyze_network_policies`, `analyze_alb_health`,
   `analyze_statefulset_issues`, `analyze_conntrack_health`,
   `analyze_custom_controllers`, `analyze_psa_violations`,
   `analyze_missing_config_resources`, `analyze_apiserver_inflight`,
   `analyze_scheduler_health`, `analyze_limits_requests`

6. **Correlation Engine** (lines ~12739–14830):
   `correlate_findings`, `_generate_incident_story`, `_enhance_correlations`,
   `_calculate_5d_confidence`, `_score_temporal_causality`,
   `_score_spatial_correlation`, `_calculate_blast_radius`,
   `_rank_root_causes`, `_build_dependency_chains`

7. **Run & Output** (lines ~19369–end):
   `run_comprehensive_analysis`, `_run_analysis_sequential`,
   `_run_analysis_parallel`, `_generate_summary`, `generate_recommendations`,
   `collect_cluster_statistics`, `output_results`, `main`

---

## Reading Order (MUST follow)

1. Lines 1–1300: constants, utility classes, `classify_severity`, `FindingType`.
   Load these definitions into context before reading analysis methods.
2. Lines 1300–2405: output formatters (`LLMJSONOutputFormatter`,
   `ExecutiveSummaryGenerator`).
3. Lines 2406–7478: `HTMLOutputFormatter` — read in full before Part B.
4. Lines 7479–9032: `ComprehensiveEKSDebugger` infrastructure (init, safe_api_call,
   safe_kubectl_call, _add_finding, time-window filter).
5. Lines 9033–12738: the 74 analysis methods — read in order of line number.
6. Lines 12739–14830: correlation engine.
7. Lines 14831–19368: remaining analysis methods (cpu_throttling onwards).
8. Lines 19369–end: run/output layer.

After every 10 analysis methods audited, output one checkpoint line:
`✅ Audited [method_a, method_b, ..., method_j]`

Do NOT emit findings during the audit pass — accumulate all findings and emit
the final report only after reading all sections.

---

## Part A — Analysis Method Checks (74 methods)

### A1. Finding Contract Compliance

The finding system is: `_add_finding(category, summary, details, finding_type)`.
Internally it populates `self.findings[category]` — a list of dicts.
`_add_finding_dict` is a thin wrapper that unpacks a pre-built dict.

- Every `_add_finding` call MUST supply a non-empty `summary` string.
  An empty or `None` summary renders as a blank card in the HTML report.
- Every `details` dict passed to `_add_finding` MUST NOT include `finding_type`
  as a raw key at call-site — `_add_finding` sets it internally. If a caller sets
  `details["finding_type"]` before the call AND `_add_finding` also sets it,
  verify which one wins and whether this creates inconsistency.
- `finding_type` MUST be either `FindingType.CURRENT_STATE` or
  `FindingType.HISTORICAL_EVENT`. Any literal string not matching these two is
  a contract violation.
- `_add_finding` enforces `MAX_FINDINGS_PER_CATEGORY`. If a category is capped,
  subsequent findings are silently dropped. Flag any analysis method that relies
  on all findings being present (e.g., counts findings after calling `_add_finding`)
  without checking the cap.
- `self.findings` categories used by analysis methods MUST match categories
  consumed by `HTMLOutputFormatter`. A category added in an analysis method but
  never rendered by the formatter produces invisible findings.

### A2. Time-Window Filtering Correctness (Highest Risk)

**Why this matters**: The debugger accepts `--start-date` / `--end-date` arguments.
`_is_finding_in_time_window` filters findings to that window. If a method bypasses
this check or applies it inconsistently, the report mixes in-window and out-of-window
findings without warning the user.

- Every finding that contains a timestamp-derived event (CloudWatch log events,
  CloudTrail events, kubectl events) MUST have its timestamp compared against
  `self.start_date` / `self.end_date` before being added via `_add_finding`.
- Findings derived from static resource state (e.g., current node condition,
  current addon version) are CURRENT_STATE — they do NOT need time-window filtering.
  Flag any method that incorrectly applies time filtering to static state.
- `_is_finding_in_time_window` extracts timestamps from `details`. Verify all keys
  it reads actually exist in the details dicts produced by the callers:
  - If the method reads `details.get("timestamp")` but the caller stores it under
    `details["event_time"]`, the filter silently passes ALL events through.
- `DateFilterMixin.filter_kubectl_events_by_date` filters parsed kubectl JSON events.
  Verify the date comparison uses timezone-aware datetimes — mixing naive and aware
  datetimes raises `TypeError` at runtime.
- Any call to `date_parser.parse()` that does not specify `tzinfo` produces a naive
  datetime. If this naive datetime is compared to a timezone-aware `self.start_date`
  or `self.end_date`, the comparison fails. Flag all `date_parser.parse()` calls
  without explicit UTC coercion.

### A3. CloudWatch API Correctness

- All CloudWatch `StartTime` / `EndTime` parameters MUST use timezone-aware
  `datetime` objects (e.g., `datetime.now(timezone.utc)`). Naive datetimes
  are silently treated as local time, producing wrong query ranges in cross-region
  or CI/CD environments.
- `get_metric_statistics` / `get_metric_data` calls MUST use the correct `Period`
  value for the requested time range. A `Period` larger than the time range returns
  zero data points without error.
- CloudWatch Log Insights queries run asynchronously: start → poll → results.
  Any method that calls `start_query` MUST poll `get_query_results` in a loop
  until status is `"Complete"` or `"Failed"`. A single call to `get_query_results`
  without polling returns partial or empty results silently.
- CloudWatch Logs `filter_log_events` paginates via `nextToken`. Any method that
  calls it once without looping will silently miss log events beyond the first page.
- CloudWatch `get_metric_statistics` returns data points in arbitrary order.
  If a method sorts by `Timestamp` before processing, verify the sort key is
  correct. If it does not sort, verify order-dependence is absent.

### A4. kubectl Execution Safety

- `get_kubectl_output` and `safe_kubectl_call` execute shell commands via
  `subprocess`. Verify that ALL kubectl commands are constructed from a fixed
  command template with user-supplied values (namespace, pod name, label selector)
  inserted via `shlex.quote()` or equivalent — NEVER via raw f-string interpolation
  into a shell string.
- Any call to `subprocess.run(..., shell=True)` with a user-controlled string is a
  shell injection vulnerability. Flag every `shell=True` occurrence and verify the
  command string is not derived from user input.
- `safe_kubectl_call` returns `None` on failure. Any caller that does
  `json.loads(safe_kubectl_call(...))` without a `None` check raises `TypeError`.
  Flag all such unguarded calls.
- `_run_kubectl_command` enforces a `timeout` parameter. Verify that callers of
  `get_kubectl_output` that iterate large resources (all pods, all nodes) do not
  use the default timeout, which may be too short for large clusters.

### A5. Error Isolation

- `safe_api_call` wraps boto3 calls and returns `(False, None)` on failure.
  Any caller that unpacks `success, response = self.safe_api_call(...)` and then
  accesses `response` without first checking `success` will raise `TypeError` or
  `AttributeError`. Flag all such unguarded accesses.
- `safe_kubectl_call` returns `None` on failure. Any caller that calls a method
  on the return value without a `None` guard is a crash path.
- No analysis method MUST be wrapped in a blanket `try/except Exception: pass`
  — that would silently suppress all findings from that method.
  `run_comprehensive_analysis` handles per-method failures via
  `_run_analysis_sequential` / `_run_analysis_parallel`.
  Any additional blanket catch inside a method is redundant and hides real bugs.
- `except (BotoCoreError, ClientError)` is correct for boto3 failures.
  A bare `except Exception` that discards the exception without logging is a
  silent failure.
- When `ctx.client` / `self.*_client` is `None` (client unavailable, e.g., wrong
  region), the method MUST return early — NOT proceed with `None.describe_*()`,
  which raises `AttributeError`. Flag any method that calls methods on a client
  without checking it is not `None`.

### A6. Pagination

- Every AWS list/describe call on a resource type that AWS paginates MUST loop:
  - Boto3 paginators: `client.get_paginator(...).paginate(...)`
  - Manual: loop on `response.get("NextToken")` / `"NextMarker"` / `"Marker"`
- High-cardinality resources that MUST paginate: EC2 instances, pods (via kubectl),
  EBS volumes, CloudTrail events (`_paginated_cloudtrail_lookup`),
  CloudWatch log streams (`_get_all_log_streams`), log events
  (`_get_log_events_paginated`), IAM roles, Security Groups.
- Flag any single `list_*` / `describe_*` call on a paginatable AWS resource that
  does not loop. The default page size is typically 100 for most AWS APIs —
  clusters with >100 resources silently return partial results.
- `_paginated_cloudtrail_lookup` already paginates. Verify its callers pass an
  appropriate `max_results_per_page` and that the total result set is not silently
  truncated at an outer limit.

### A7. Timezone Safety

- ALL datetime construction MUST be timezone-aware. Flag:
  - `datetime.now()` without `tz=timezone.utc` or `timezone.utc` argument
  - `datetime.utcnow()` (returns naive datetime — deprecated pattern)
  - `datetime.strptime(...)` without `.replace(tzinfo=timezone.utc)` or
    `.astimezone(timezone.utc)` before comparison
  - `date_parser.parse(s)` without `ignoretz=False` and without explicit UTC
    coercion when the result is compared to `self.start_date` or `self.end_date`
- `TimezoneManager.ensure_utc` handles coercion — verify it is called wherever
  external timestamps (CloudTrail, CloudWatch, kubectl events) are parsed.
- Kubernetes event timestamps are ISO 8601 strings that may or may not include
  timezone info. Flag any parsing that assumes UTC without verifying the string
  contains a `+00:00` or `Z` suffix.

### A8. Double-Counting

These resource types appear in multiple analysis methods. Verify exclusions:

- **EC2 nodes vs EKS nodes**: `analyze_node_conditions` covers all EC2-backed
  nodes. `analyze_eks_nodegroup_health` covers EKS managed node groups.
  Verify there is no overlap where the same node issue is emitted by both methods.
- **Pods**: `analyze_pod_health_deep` does a broad pod sweep.
  `analyze_pod_evictions`, `analyze_init_container_failures`,
  `analyze_sidecar_health`, `analyze_pods_terminating`,
  `analyze_probe_failures` each cover specific pod conditions.
  Flag if any pod condition (e.g., `Evicted`) is emitted by more than one method
  into the same findings category.
- **HPA**: `analyze_hpa_vpa` and `analyze_hpa_metrics_source` both inspect HPAs.
  Verify they target non-overlapping failure modes without emitting duplicate
  findings for the same HPA object.
- **Karpenter**: `analyze_karpenter` and `analyze_karpenter_drift` both inspect
  Karpenter. Verify the division of responsibility is clean.
- **ALB / Ingress**: `analyze_ingress_health`, `analyze_aws_lb_controller`, and
  `analyze_alb_health` all touch ingress / ALB resources. Verify no duplicate
  finding is emitted for the same ALB resource across the three methods.
- **DNS**: `analyze_dns_configuration` and `analyze_coredns_health` both inspect
  DNS. Verify they target non-overlapping failure modes.

### A9. `classify_severity` Correctness

`classify_severity(summary_text, details)` is the global severity classifier.
Both the module-level function and `HTMLOutputFormatter._classify_severity` exist.
Verify they produce consistent results for the same input — if they diverge,
findings may be rendered at the wrong severity level.

- `_CRITICAL_PATTERN` uses a word-boundary regex. Verify it does not produce
  false positives on benign substrings (e.g., `"shutdown"` is excluded via
  `(?<!shut)down` — verify this lookbehind is syntactically correct and does
  what is intended).
- `_COMPOUND_CRITICAL` checks for `"oomkilled"`, `"crashloopbackoff"`,
  `"imagepullbackoff"`. These are lowercased. If a summary contains mixed-case
  `"OOMKilled"`, verify it is lowercased before the compound check.
- `details.get("severity")` — if a caller passes an explicit severity that is
  not in `{"critical", "warning", "info"}`, the downstream renderers may break.
  Verify the explicit override path validates the value.

---

## Part B — HTMLOutputFormatter

Read the full `HTMLOutputFormatter` class (lines ~2406–7478) before auditing.

### B1. Findings Rendering — Category Coverage

- `HTMLOutputFormatter.format()` iterates `results["findings"]`. Verify it handles
  every category key that any of the 74 analysis methods can produce.
- A category key added by an analysis method but absent from the renderer's
  template/dispatch logic produces invisible findings. Flag any such gap.
- Verify the tab navigation (service/category tabs) includes every category.
  A category present in findings but missing from the tab list is silently excluded.

### B2. Finding-Based Grouping

Resources sharing the same finding type or error category MUST render as a SINGLE
card listing all affected resources — NOT one card per resource.

- Any renderer that loops over a findings list and emits one `<div>` per finding
  without grouping by `finding_type` or summary pattern is a rendering bug when
  multiple resources share the same issue.
- Each grouped card MUST display the finding label and affected resource count
  in its header: e.g., `"OOMKilled (3 pods)"`.
- Affected resources MUST be listed inside the card as a `<ul>` — not as
  separate top-level cards.
- `FindingType.HISTORICAL_EVENT` findings MUST render with the historical badge
  from `_get_finding_type_badge`. Verify the badge logic checks `finding_type`
  from `details`, not from the top-level finding dict.

### B3. Severity Badge Rendering

- Severity `"critical"` → red badge. `"warning"` → orange badge. `"info"` → grey.
  Any value outside these three MUST default to a visible fallback — NEVER raw
  display of the value.
- `_classify_severity(summary_text, details)` is called inside the formatter.
  Verify it is the same function as the module-level `classify_severity` — if it
  is a re-implementation, flag any behavioral divergence.

### B4. None Safety and Edge Cases

- `results.get("findings", {})` — raw `results["findings"]` access crashes if key
  is absent. Flag any such access.
- `results.get("correlations", [])` — correlations may be absent. Flag unguarded
  access.
- `results.get("executive_summary")` may be `None` when `ExecutiveSummaryGenerator`
  fails. The HTML generator MUST degrade gracefully — not crash.
- Empty findings list for a category MUST render a "No issues found" message —
  NEVER an empty table with headers and no rows.
- `details` dict may be absent or `None` on a finding. Any `details["key"]`
  access without `.get()` is a crash path.

### B5. XSS Prevention

- Cluster name, namespace, pod name, node name — all user-controlled strings
  rendered into HTML MUST be escaped via `html.escape()` (the file imports `html`).
- Any raw f-string interpolation of Kubernetes resource names, log message
  fragments, or CloudTrail event details into HTML is an XSS vector.
- Chart.js dataset labels (service/category names) injected into `<script>` blocks
  MUST be `json.dumps()`-encoded — NEVER raw f-string interpolation into JavaScript.
- The CDN script tag for Chart.js MUST use `https://`. Flag any `http://` CDN URL.

### B6. Executive Summary Accuracy

- `_generate_executive_summary_html` receives the output of
  `ExecutiveSummaryGenerator.generate()`. Verify the keys it reads match the keys
  that `generate()` actually produces — a key mismatch renders blank sections.
- Total findings displayed MUST equal `sum(len(v) for v in findings.values())`.
  Independent computation that could drift from actual findings is a bug.
- Severity counts (critical / warning / info) in the summary MUST be computed from
  the actual findings list — not from a separately-maintained counter that could
  desync.
- `_get_key_findings` filters to top-N findings. Verify the sort key is `severity`
  (critical first) then recency — not an arbitrary insertion order.

---

## Part C — Supporting Classes

Read each class fully before auditing.

### C1. APICache

- `APICache.get()` returns `None` on miss or expiry. Any caller that does
  `cache.get(key)["field"]` without a `None` check crashes on cache miss.
- `APICache.make_key()` hashes `func_name + args + kwargs`. Verify that mutable
  default args (e.g., a dict or list passed as `kwargs`) produce a stable hash —
  dict ordering in Python 3.7+ is insertion-ordered, so this should be safe, but
  verify `hashlib.md5` is called on a deterministic serialization (e.g., `json.dumps`
  with `sort_keys=True`), not `str(kwargs)` (which can include memory addresses for
  non-primitive values).
- TTL is set per-instance. Verify no code path creates a second `APICache` instance
  with a different TTL for the same underlying data, producing inconsistent caching
  behavior across methods.

### C2. IncrementalCache

- `IncrementalCache.save()` writes to `~/.eks-debugger-cache/`. Verify it handles
  `PermissionError` and `OSError` without crashing the run.
- `compute_delta()` computes the diff between current and previous findings.
  Verify it handles the case where a category exists in `previous` but not in
  `current` — the delta MUST report the finding as resolved, not raise `KeyError`.
- Cache files contain previous scan results. Verify the JSON serialization handles
  all field types that findings can contain (datetime objects are not JSON-
  serializable by default — verify `.isoformat()` is called or a custom encoder
  is used).

### C3. DateFilterMixin

- `filter_kubectl_events_by_date` parses event timestamps from kubectl JSON output.
  Kubernetes events use RFC 3339 format. Verify the parser handles both
  `"lastTimestamp"` and `"eventTime"` fields (they exist on different event types).
- If both `lastTimestamp` and `eventTime` are absent on an event, verify the
  fallback behavior — the event MUST either be included (conservative) or excluded
  with a clear log message. Silent drop is a data-loss bug.
- `get_cloudwatch_time_params` constructs `StartTime` / `EndTime`. Verify these
  are timezone-aware `datetime` objects, not naive.

### C4. Thresholds

- `Thresholds` defines numeric thresholds used in severity classification.
  Verify that all constants are used — any threshold defined but never referenced
  in analysis methods is dead code that may mislead future auditors.
- Verify threshold values are reasonable: `MEMORY_CRITICAL = 95`,
  `CPU_CRITICAL = 90`, `DISK_CRITICAL = 95`, `RESTART_CRITICAL = 10`,
  `PENDING_POD_CRITICAL = 10`. These are not bugs per se, but if an analysis
  method uses a different hardcoded value instead of the named constant, flag it.

---

## Part D — Correlation Engine

Read `correlate_findings` and all private helpers fully before auditing.

### D1. correlate_findings()

- `correlate_findings` reads from `self.findings` which is built up by the 74
  analysis methods. It MUST be called after all analysis methods complete.
  Verify `run_comprehensive_analysis` guarantees this ordering — if
  `correlate_findings` is called mid-run or in parallel, it may correlate
  partial findings.
- The method produces `self.correlations`. Verify it initializes `self.correlations`
  to `[]` before populating — if a previous run populated it, stale correlations
  could persist.
- Temporal correlation requires two events to have timestamps. If either event's
  `details` dict lacks a timestamp key, verify the correlation is skipped (not
  crash, not false-positive correlation at time zero).

### D2. `_calculate_5d_confidence`

- This method computes a confidence score from multiple sub-scores. Verify the
  final score is clamped to `[0.0, 1.0]` — unclamped scores > 1.0 would produce
  misleading `"99% confidence"` displays.
- Each sub-scorer (`_score_temporal_causality`, `_score_spatial_correlation`)
  returns a dict. Verify all keys the confidence calculator reads are guaranteed
  to be present in those dicts — a missing key causes `KeyError`.

### D3. `_enhance_correlations`

- `_enhance_correlations` modifies `self.correlations` in-place. Verify it does
  not produce duplicate correlation entries (i.e., the same pair of findings
  correlated twice with different confidence scores).
- The enhancement pass runs after `correlate_findings`. If `self.correlations`
  is empty (no findings), verify the method returns early without error.

### D4. `_rank_root_causes`

- Root causes are ranked by confidence score. Verify the sort is stable and
  descending — equal scores should not reorder randomly on each run.
- The top-ranked root cause drives the executive summary and incident story.
  Verify that if all correlations have confidence score 0, the method returns
  an empty list rather than picking an arbitrary root cause.

---

## Output Format (MUST follow exactly)

Four sections: **Part A**, **Part B**, **Part C**, **Part D**. Within each
section, group findings by severity in this order:
`### CRITICAL` → `### HIGH` → `### MEDIUM` → `### LOW / INFO`.

Each finding MUST use this exact structure:

```
**[CATEGORY]** `eks_comprehensive_debugger.py:LINE`
> exact code quote from that line

1–3 sentences describing the bug and its impact. Not the fix.
```

End each Part with a summary table:

| Method / Section | Severity | Category | Finding (≤12 words) |
|---|---|---|---|

End the entire report with a **Clean** section listing every method or class
with zero findings.

---

## Final Lock

- Any finding without an exact `file:line` + direct code quote MUST be omitted —
  not downgraded, not marked INFO. Omitted.
- If a line range cannot be read, state `Could not read lines [N–M]` and skip
  that section entirely. Do not guess at its contents.
- Do NOT propose fixes.
- Do NOT modify code.
- Do NOT emit partial findings during the audit pass — accumulate, then report.
