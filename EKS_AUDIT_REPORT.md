# EKS Comprehensive Debugger — Full Code Audit Report

**File audited:** `eks_comprehensive_debugger.py` (~20,517 lines)  
**Audit date:** 2026-05-03  
**Methodology:** Read-only, evidence-based. All findings cite exact line numbers and verbatim code excerpts.

---

## Executive Summary

The codebase is a well-structured, feature-rich EKS diagnostic tool. Security fundamentals are sound: `shell=False` is used consistently for subprocess calls, user-controlled inputs are validated against an allow-list regex, and HTML output is XSS-escaped via `html.escape()`. The correlation engine and parallel execution design are solid.

Three runtime crash bugs exist (CRITICAL), five silent-failure or silent-truncation issues exist (HIGH), and several correctness/design issues warrant attention (MEDIUM/LOW). No hardcoded credentials or SQL injection vectors were found.

---

## Part A — Analysis Methods

### CRITICAL

---

**A-CRIT-1 — `_get_filtered_events`: `json.loads(None)` crash at line 8933**

```python
# line 8933
events = json.loads(output)
```

`safe_kubectl_call` returns `None` on failure. There is no `if not output: return` guard before this call. Passing `None` to `json.loads` raises `TypeError: the JSON object must be str, bytes or bytearray, not NoneType`, crashing the analysis thread that invoked `_get_filtered_events`.

**Impact:** Any cluster where `kubectl get events` fails (permissions denied, no nodes) causes an uncaught exception in the calling analysis method.

**Fix:** Add `if not output: return []` before line 8933.

---

**A-CRIT-2 — `analyze_control_plane_logs`: at most 50 log events analyzed per stream (line 9721)**

```python
# line 9721  (inside analyze_control_plane_logs)
self.logs_client.get_log_events(
    ...
    limit=50,
    ...
)
```

The method calls `get_log_events` directly with `limit=50` and does **not** use the existing `_get_log_events_paginated` helper. CloudWatch returns at most 50 events per call; subsequent pages are silently discarded. A cluster with 10,000 control-plane log events will have 9,950 events invisible to this analysis.

**Impact:** Critical errors occurring in earlier log pages are never detected. The bug is particularly harmful during etcd quota exhaustion or scheduler panics, which tend to produce high log volume.

**Fix:** Replace the bare `get_log_events` call with `self._get_log_events_paginated(...)`.

---

**A-CRIT-3 — `_check_eks_cluster_upgrade`: naive/aware datetime comparison causes `TypeError` at line 11454–11462**

```python
# line 11454
created_at_dt = parser.parse(created_at)   # may return naive datetime

# line 11462
if created_at_dt >= self.start_date:       # self.start_date is always tz-aware
```

`dateutil.parser.parse` returns a naive `datetime` if the source string has no timezone designator (which is common in AWS API responses when the field is a plain date). Comparing a naive datetime to the timezone-aware `self.start_date` raises:
`TypeError: can't compare offset-naive and offset-aware datetimes`

**Impact:** Every invocation of `_check_eks_cluster_upgrade` (called from `correlate_findings`) raises a `TypeError`, which is caught at line 19531 as a generic correlation failure. Upgrade detection is completely disabled.

**Fix:**
```python
created_at_dt = parser.parse(created_at)
if created_at_dt.tzinfo is None:
    created_at_dt = created_at_dt.replace(tzinfo=timezone.utc)
```

---

**A-CRIT-4 — `analyze_statefulset_issues`: uses wrong metadata key for namespace at line 18151**

```python
# line 18151
namespace = sts["metadata"]["name"]   # BUG: should be ["namespace"]
```

The variable `namespace` is assigned the StatefulSet *name*, not *namespace*. All downstream findings for StatefulSets will have `namespace` set to the StatefulSet name, and the subsequent PVC lookup command will be constructed with a wrong namespace:

```python
# line 18192
cmd = f"kubectl get pvc -n {namespace} -o json ..."
# expands to e.g.: kubectl get pvc -n my-statefulset -o json
```

**Impact:** StatefulSet PVC findings are attributed to wrong namespaces; the PVC lookup will likely return empty results on all StatefulSets, silently suppressing real PVC issues.

**Fix:** Change line 18151 to `namespace = sts["metadata"]["namespace"]`.

---

**A-CRIT-5 — `analyze_pod_health_deep` and `analyze_init_container_failures` duplicate all init container findings**

`analyze_pod_health_deep` (lines 10746–10864) scans every pod's `initContainerStatuses` and writes findings to `pod_errors` and `image_pull_failures`.

`analyze_init_container_failures` (lines 11514–11613) is a separate method that *also* scans every pod's `initContainerStatuses` and writes the same finding types to the same categories.

Both methods are called unconditionally from `run_comprehensive_analysis` (lines 19435 and 19502). With `parallel=True`, both run concurrently and are protected only by `_findings_lock`, so the lock prevents corruption but not duplication.

**Impact:** Every init container failure appears twice in the findings, inflating severity counts, corrupting correlation scores that depend on `len(self.findings["pod_errors"])`, and generating duplicate entries in all output reports.

**Fix:** Remove the init container scanning block from `analyze_pod_health_deep`, keeping only `analyze_init_container_failures` as the canonical implementation, or vice versa.

---

### HIGH

---

**A-HIGH-1 — Bare `except Exception: pass` suppresses entire analysis sub-blocks silently**

The following call sites swallow all exceptions without logging or findings:

| Line | Method | Consequence |
|------|--------|-------------|
| 9297 | `analyze_node_conditions` | PIDPressure event analysis silently skipped |
| 10236 | `analyze_pvc_issues` | Inner PVC block errors hidden |
| 10268 | `analyze_pvc_issues` | Second inner PVC block errors hidden |
| 10299 | `analyze_pvc_issues` | Third inner PVC block errors hidden |
| 16956 | `analyze_etcd_health` | etcd kubectl event scan silently skipped |
| 16988 | `analyze_etcd_health` | FailedCreate etcd event scan silently skipped |

```python
# representative example, line 9297
except Exception:
    pass
```

These differ from the outer `except Exception as e: self._add_error(...)` pattern used elsewhere, which at least records the failure.

**Impact:** Silent failures mean users see no indication that part of an analysis was skipped. This is especially dangerous for `analyze_etcd_health` where a real etcd-space-exceeded condition may go undetected.

**Fix:** Replace `except Exception: pass` with `except Exception as e: self._add_error("<method_name>_inner", str(e))`.

---

**A-HIGH-2 — `check_container_insights_metrics`: `Period=3600` silently returns 0 datapoints for time windows < 1 hour (line 9410)**

```python
# line 9410
"Period": 3600,
```

CloudWatch `GetMetricData` requires that the time range is at least one full period width. With `Period=3600`, any invocation with `--hours 1` or shorter returns an empty `Values` list with no error. The method proceeds without any warning to the user.

**Impact:** All Container Insights metric checks silently pass for short analysis windows, giving a false-clean result.

**Fix:** Either derive `Period` from the actual time range (`max(60, int((end_date - start_date).total_seconds()))`) or add a guard with a user-visible warning when `end_date - start_date < timedelta(hours=1)`.

---

**A-HIGH-3 — `analyze_cloudwatch_logging_health`: `list_metrics` not paginated (line ~9629)**

```python
# approximately line 9629
success, response = self.safe_api_call(
    self.cloudwatch_client.list_metrics,
    ...
)
```

`cloudwatch:ListMetrics` returns at most 500 results per call. The method does not loop on `NextToken`. Clusters with more than 500 Container Insights metrics will silently see only the first 500.

**Impact:** Logging health issues for metrics beyond page 1 are never detected.

**Fix:** Loop on `response.get("NextToken")` similar to `_get_all_log_streams`.

---

**A-HIGH-4 — `analyze_network_issues` and `analyze_coredns_health` produce overlapping `dns_issues` findings**

`analyze_network_issues` (line 9929) checks the CoreDNS pod phase and emits a finding to `dns_issues` when CoreDNS is not Running.

`analyze_coredns_health` (lines 11005–11084) separately checks CoreDNS deployment health and CoreDNS-related events, also emitting to `dns_issues`.

Both are called unconditionally from `run_comprehensive_analysis`. When CoreDNS is degraded, the same condition is detected twice and reported twice. The correlation engine's `_corr_dns_pattern` rule then operates on an inflated count.

**Fix:** The CoreDNS pod-phase check in `analyze_network_issues` (line ~9929) should be removed; `analyze_coredns_health` is the canonical implementation.

---

**A-HIGH-5 — `analyze_ingress_health`: `backend_svc` from Ingress spec inserted into `kubectl get svc` command without quoting (line 11997)**

```python
# line 11997
secret_check = self.safe_kubectl_call(
    f"kubectl get svc {backend_svc} -n {namespace} -o name"
)
```

`backend_svc` and `namespace` originate from the Ingress spec parsed from `kubectl get ingress -o json`. While kubectl invocations use `shell=False` via `shlex.split`, an Ingress `serviceName` containing shell metacharacters (e.g., a space) would cause `shlex.split` to interpret the token boundary incorrectly.

More concretely, `shlex.split("kubectl get svc my service -n default -o name")` produces `["kubectl", "get", "svc", "my", "service", "-n", "default", "-o", "name"]`, silently querying a resource named `my` instead of `my service`.

**Fix:** Apply `shlex.quote(backend_svc)` and `shlex.quote(namespace)` before interpolation, as is done elsewhere in the codebase.

---

### MEDIUM

---

**A-MED-1 — `analyze_pvc_issues`: KeyError on `pvc["spec"]["resources"]["requests"]` at line 10068**

```python
# line 10068
pvc["spec"]["resources"]["requests"].get("storage")
```

`pvc["spec"]`, `pvc["spec"]["resources"]`, and `pvc["spec"]["resources"]["requests"]` are accessed with direct dict indexing (not `.get()`). Any PVC whose spec omits `resources` or `resources.requests` (valid in some dynamic provisioner flows) raises `KeyError`.

**Fix:**
```python
pvc.get("spec", {}).get("resources", {}).get("requests", {}).get("storage")
```

---

**A-MED-2 — `_extract_timestamp`: naive datetime returned without UTC coercion (line 11394)**

```python
# line 11394
return date_parser.parse(ts)
```

If `ts` contains no timezone offset, `dateutil.parser.parse` returns a naive `datetime`. This value is then sorted against other timestamps in `correlate_findings` (line 12777: `timeline_events.sort(key=lambda x: x["timestamp"])`). Comparing naive and aware datetimes in a sort raises `TypeError` in Python 3.

**Fix:** Add UTC fallback:
```python
dt = date_parser.parse(ts)
if dt.tzinfo is None:
    dt = dt.replace(tzinfo=timezone.utc)
return dt
```

Note: `analyze_node_ami_age` (line 12300–12302) correctly performs this same UTC coercion. The pattern exists; it is simply missing from `_extract_timestamp`.

---

**A-MED-3 — `analyze_deprecated_apis`: heuristic logic flags any existing resource as using the deprecated API version, regardless of actual stored version (lines 12169–12180)**

```python
# lines 12169-12173
if (
    resource_check
    and "not found" not in resource_check.lower()
    and "error" not in resource_check.lower()
):
    key = f"{api_version}/{resource}"
```

The check only tests whether any resource of that kind *exists*, not whether it is stored under the deprecated API group. For example, if any `Ingress` exists, the code flags `extensions/v1beta1/Ingress` as in use, even if every Ingress was created using `networking.k8s.io/v1`. This produces false-positive deprecated API findings on virtually every cluster running K8s 1.22+.

**Fix:** Query the actual stored API version by using `kubectl get <resource> --all-namespaces -o jsonpath='{.items[*].apiVersion}'` and check if the deprecated version appears in the output.

---

**A-MED-4 — `validate_and_parse_dates`: `end_date` assigned twice at lines 20303–20305**

```python
# lines 20303-20305
end_date = datetime.now(timezone.utc)  # first assignment
start_date: datetime
end_date = datetime.now(timezone.utc)  # duplicate assignment
```

`end_date` is initialized twice identically before the `if args.end_date:` check below. This is dead code that may mask a refactoring error where the first assignment was intended to be something else.

**Fix:** Remove the duplicate line 20303 (or 20305).

---

### LOW

---

**A-LOW-1 — `filter_kubectl_events_by_date`: fail-open on timestamp parse error (line ~1344)**

When `dateutil.parser.parse` raises on a malformed event timestamp, the `except` branch includes the event anyway:

```python
# approximately line 1344 (DateFilterMixin.filter_kubectl_events_by_date)
except Exception:
    pass  # include the event if we can't parse the timestamp
```

This is an intentional fail-open design, but it means corrupted or future-dated event timestamps bypass time-window filtering entirely. Events from outside the requested analysis window may appear in findings.

**Note:** This is a deliberate trade-off. The risk is bounded because kubectl events have a short TTL. Acceptable for most use cases, but worth documenting explicitly.

---

**A-LOW-2 — `get_cloudwatch_time_params` returns datetime objects without UTC enforcement**

CloudWatch SDK methods require timezone-aware datetimes. If `get_cloudwatch_time_params` returns naive datetimes (possible if `self.start_date` were set without UTC), the `StartTime`/`EndTime` parameters would be treated as local time by `boto3`, producing incorrect time windows.

In the current code `self.start_date` is initialized with `datetime.now(timezone.utc)` in `__init__`, so this is not an active bug, but it represents a fragile dependency: any future code path that sets `start_date` without UTC will silently shift the analysis window.

---

## Part B — HTMLOutputFormatter

### MEDIUM

---

**B-MED-1 — `_generate_executive_summary_html`: component name and message rendered without XSS escaping (line ~2932)**

```python
# approximately line 2932
f"<span class='component-name'>{comp.get('name', '')}</span>"
f"<span class='component-message'>{comp.get('message', '')}</span>"
```

`comp.get("name","")` and `comp.get("message","")` are inserted directly into the HTML template without passing through `self._escape_html()`. All other string insertions in the formatter use `_escape_html()`, which correctly calls `html.escape()`. 

The `comp` dict is populated from `_get_healthy_components()` and `_extract_key_findings()`, which in turn read directly from `self.findings`. A finding summary containing `<script>alert(1)</script>` (e.g., from a malicious pod name or Kubernetes event message) would execute as JavaScript when the report is opened in a browser.

**Impact:** Stored XSS in generated HTML reports. Low-probability but non-zero: an attacker who can create a Kubernetes resource with a crafted name/message could inject script into reports shared among ops teams.

**Fix:**
```python
f"<span class='component-name'>{self._escape_html(comp.get('name', ''))}</span>"
f"<span class='component-message'>{self._escape_html(comp.get('message', ''))}</span>"
```

---

**B-MED-2 — `_render_detail_value`: URL linkification applies `re.sub` to already-escaped text, then reinserts raw match group into `href` (lines ~2479–2484)**

```python
# approximately lines 2479-2484
escaped = html.escape(str(value))
# ... later ...
return re.sub(
    r'(https?://\S+)',
    r'<a href="\1" ...>\1</a>',
    escaped
)
```

The URL from the original string has been HTML-escaped (`&amp;`, `&lt;`, etc.) before the regex runs. The regex then matches the escaped form and inserts it verbatim into the `href` attribute. A URL containing `&` (e.g., `https://example.com/path?a=1&b=2`) becomes `href="https://example.com/path?a=1&amp;b=2"`, producing a broken link.

Additionally, if a URL in the original value contains a double-quote (unlikely but possible), the `href="..."` attribute would be broken.

**Fix:** Run URL linkification on the *raw* value before HTML-escaping it, or unescape matched groups before inserting into `href`.

---

## Part C — Supporting Classes

### LOW

---

**C-LOW-1 — `APICache.make_key`: uses `repr(args)` which is non-deterministic for dict arguments (line ~lines 120–130)**

```python
# approximately line 125
return f"{func_name}:{repr(args)}:{repr(kwargs)}"
```

`repr(dict)` in Python 3.7+ is insertion-order stable, but two logically identical kwargs dicts built in different orders will produce different cache keys if any keyword argument is a dict. In practice the callers pass simple primitives, so this is currently benign. It is a latent correctness hazard if callers ever pass dict-valued kwargs.

**Fix:** Use `json.dumps(args, sort_keys=True)` and `json.dumps(kwargs, sort_keys=True)` for the key, with a fallback for non-JSON-serializable values.

---

**C-LOW-2 — `DateFilterMixin.get_cloudwatch_time_params`: no UTC enforcement documented (line ~lines 1360–1368)**

See A-LOW-2 above.

---

## Part D — Correlation Engine

### MEDIUM

---

**D-MED-1 — `correlate_findings` Correlation Rule 1: `pressure_type` is hard-coded to `"memory"` when both memory and disk pressure are present (lines 12780–12784)**

```python
# lines 12780-12784
if self.findings["memory_pressure"] or self.findings["disk_pressure"]:
    pressure_type = "memory" if self.findings["memory_pressure"] else "disk"
```

If both `memory_pressure` and `disk_pressure` are non-empty, only `memory_pressure` is analyzed. Disk pressure findings are ignored in the correlation even though they may be the root cause of pod evictions on disk-heavy workloads.

**Fix:** Run the correlation rule independently for both pressure types, or accumulate all pressure findings into a unified set.

---

**D-MED-2 — `correlate_findings` Correlation Rule 3 (`oom_pattern`): always emits correlation even when `self.findings["oom_killed"]` is empty after the condition check (lines 12864–12896)**

```python
# line 12864
if self.findings["oom_killed"]:
    oom_pods = self.findings["oom_killed"]
    ...
    correlations.append({
        "correlation_type": "oom_pattern",
        ...
        "affected_components": {
            "oom_killed_pods": len(oom_pods),  # always >= 1
```

This block only fires when `oom_killed` is non-empty, which is correct. The issue is that `first_oom = min(oom_times) if oom_times else None` may be `None` even when there are OOM findings (they have no parseable timestamp). In that case `"root_cause_time": "Unknown"` is stored. `_calculate_blast_radius("Unknown")` then returns `{k: 0 for k in affected}` (line 14414), silently zeroing the blast radius. This is not a crash but produces misleading confidence scores.

**Note:** Minor issue; impact is cosmetic on the output, not a correctness failure.

---

**D-MED-3 — `_build_dependency_chains`: `CAUSAL_CHAINS` is a class-level attribute (line 14181), but is defined inside the class body and references `"cluster_upgrade"` as a downstream effect of `"node_pressure_cascade"` which contradicts the intended causal direction**

```python
# lines 14190-14191
("cluster_upgrade", "node_pressure_cascade", "Upgrade triggered node pressure events"),
```

The tuple ordering is `(upstream, downstream, description)` (line 14470). This entry treats `cluster_upgrade` as a *cause* of `node_pressure_cascade`, but `node_pressure_cascade` is a *consequence* of the upgrade, not the other way around. The chain reads: "cluster upgrade causes node pressure cascade", which is correct semantically. However, the dependency chain output will show `node_pressure_cascade` as downstream of `cluster_upgrade`, which is fine — but the `_rank_root_causes` function scores `cluster_upgrade` with a bonus for `aws_api_confirmed` (line 14564), and the chain amplifies this by absorbing the `node_pressure_cascade` score into the upgrade. This means if `node_pressure_cascade` has its own high-confidence score, it will be consumed into the upgrade chain and may not surface as an independent finding. This is an edge case, not a crash.

---

**D-LOW-1 — `_enhance_correlations`: Correlation Rule `dns_pattern` sets `cause_events` to coredns-filtered `dns_issues`, then sets `effect_events` to all `dns_issues` (lines 14673–14678)**

```python
# lines 14673-14678
cause_events = [
    f for f in self.findings.get("dns_issues", []) if "coredns" in f.get("summary", "").lower()
]
effect_events = self.findings.get("dns_issues", [])
```

`effect_events` is a superset of `cause_events`. The `_score_temporal_causality` computation will match cause events to themselves (a `dns_issues` finding with "coredns" in the summary is present in both lists). This inflates temporal confidence by creating self-referential causal pairs.

**Fix:** `effect_events` should be non-coredns DNS issues: `[f for f in self.findings.get("dns_issues", []) if "coredns" not in f.get("summary", "").lower()]`.

---

## Part E — Orchestration & Infrastructure

### LOW

---

**E-LOW-1 — `run_comprehensive_analysis` docstring claims 72 analysis methods but list contains more (line 19369 vs 19431–19520)**

The docstring says "Run all 72 analysis methods" but the `analysis_methods` list at lines 19431–19520 contains approximately 75 entries, and `self.progress.set_total_steps(76)` is called at line 19393. Minor documentation inconsistency with no runtime impact.

---

**E-LOW-2 — `analyze_jobs_cronjobs` CronJob missed-schedule heuristic fires for any CronJob with `lastScheduleTime > 1 hour ago`, regardless of schedule interval (line 17870)**

```python
# line 17870
if time_since_schedule.total_seconds() > 3600:  # > 1 hour
```

A CronJob scheduled to run daily will always trigger this finding after 1 AM, producing spurious "may have missed schedules" findings for all daily CronJobs.

**Fix:** Parse the cron expression to compute the expected next run time and compare against the current time, or raise the threshold to at least 2x the expected interval.

---

**E-LOW-3 — `analyze_security_groups`: variables `has_outbound` and `all_outbound` are computed inside the loop but never used (lines 16277–16282)**

```python
# lines 16277-16282
has_outbound = any(rule.get("IpProtocol") != "-1" or rule.get("IpRanges") for rule in outbound_rules)
all_outbound = any(
    rule.get("IpProtocol") == "-1"
    and any(ip.get("CidrIp") == "0.0.0.0/0" for ip in rule.get("IpRanges", []))
    for rule in outbound_rules
)
```

Both variables are assigned but never read. This suggests an incomplete implementation — the intent was likely to flag security groups with missing or unrestricted outbound rules.

---

## Findings Summary Table

| ID | Severity | Category | Short Description | Lines |
|----|----------|----------|-------------------|-------|
| A-CRIT-1 | CRITICAL | Crash | `json.loads(None)` in `_get_filtered_events` | 8933 |
| A-CRIT-2 | CRITICAL | Data Loss | `analyze_control_plane_logs` reads ≤50 events, no pagination | 9721 |
| A-CRIT-3 | CRITICAL | Crash | Naive/aware datetime `TypeError` in `_check_eks_cluster_upgrade` | 11454–11462 |
| A-CRIT-4 | CRITICAL | Correctness | `namespace = sts["metadata"]["name"]` wrong key in `analyze_statefulset_issues` | 18151 |
| A-CRIT-5 | CRITICAL | Correctness | Duplicate init container findings from two methods | 10746–10864, 11514–11613 |
| A-HIGH-1 | HIGH | Silent Failure | Bare `except Exception: pass` at 6 call sites | 9297, 10236, 10268, 10299, 16956, 16988 |
| A-HIGH-2 | HIGH | Silent Failure | `Period=3600` yields 0 datapoints for short time windows | 9410 |
| A-HIGH-3 | HIGH | Truncation | `list_metrics` not paginated in `analyze_cloudwatch_logging_health` | ~9629 |
| A-HIGH-4 | HIGH | Duplication | Overlapping CoreDNS findings in `analyze_network_issues` + `analyze_coredns_health` | 9929, 11005–11084 |
| A-HIGH-5 | HIGH | Injection Risk | `backend_svc` unquoted in `kubectl get svc` interpolation | 11997 |
| A-MED-1 | MEDIUM | Crash Risk | Direct dict access on `pvc["spec"]["resources"]["requests"]` | 10068 |
| A-MED-2 | MEDIUM | Crash Risk | `_extract_timestamp` returns naive datetime, causes sort `TypeError` | 11394 |
| A-MED-3 | MEDIUM | False Positive | `analyze_deprecated_apis` reports any existing resource as deprecated | 12169–12180 |
| A-MED-4 | MEDIUM | Dead Code | `end_date` assigned twice in `validate_and_parse_dates` | 20303–20305 |
| A-LOW-1 | LOW | Design | `filter_kubectl_events_by_date` fail-open on bad timestamps | ~1344 |
| A-LOW-2 | LOW | Design | `get_cloudwatch_time_params` fragile UTC dependency | ~1360–1368 |
| B-MED-1 | MEDIUM | XSS | Component name/message unescaped in `_generate_executive_summary_html` | ~2932 |
| B-MED-2 | MEDIUM | Broken Links | URL linkification on pre-escaped text breaks URLs with `&` | ~2479–2484 |
| C-LOW-1 | LOW | Cache Correctness | `APICache.make_key` non-deterministic for dict kwargs | ~125 |
| D-MED-1 | MEDIUM | Correctness | Correlation Rule 1 ignores disk pressure when memory pressure also present | 12780–12784 |
| D-MED-2 | MEDIUM | Misleading Score | OOM correlation blast radius silently zero when timestamps unparseable | 12864–12896 |
| D-MED-3 | MEDIUM | Logic | `CAUSAL_CHAINS` `cluster_upgrade` direction absorbs `node_pressure_cascade` score | 14181–14192 |
| D-LOW-1 | LOW | Inflated Score | `dns_pattern` cause/effect overlap inflates temporal confidence | 14673–14678 |
| E-LOW-1 | LOW | Documentation | Docstring says 72 methods, actual count differs | 19369 |
| E-LOW-2 | LOW | False Positive | CronJob missed-schedule threshold 1h fires on all daily CronJobs | 17870 |
| E-LOW-3 | LOW | Dead Code | `has_outbound`/`all_outbound` computed but never used | 16277–16282 |

---

## Priority Action List

**Must fix before production use (crash bugs):**
1. A-CRIT-1 — Guard `json.loads(output)` calls with `if not output` checks
2. A-CRIT-2 — Replace bare `get_log_events(limit=50)` with paginated helper
3. A-CRIT-3 — Add `replace(tzinfo=timezone.utc)` fallback in `_check_eks_cluster_upgrade`
4. A-CRIT-4 — Fix `namespace = sts["metadata"]["name"]` to `["namespace"]`
5. A-CRIT-5 — Remove duplicate init container analysis from one of the two methods

**Should fix to avoid misleading output:**
6. A-HIGH-1 — Replace bare `except: pass` with logged error calls
7. A-HIGH-2 — Guard or adapt `Period` for short analysis windows
8. A-HIGH-3 — Paginate `list_metrics` call
9. A-HIGH-4 — Remove CoreDNS pod-phase check from `analyze_network_issues`
10. A-HIGH-5 — Apply `shlex.quote()` to `backend_svc` and `namespace`
11. B-MED-1 — Apply `_escape_html()` to component name/message in HTML output
12. A-MED-1 — Use `.get()` chain on PVC spec access
13. A-MED-2 — Add UTC coercion in `_extract_timestamp`

---

*End of audit report.*
