# Time Window Filtering Fix - Summary

## Problem

The EKS debugger was incorrectly detecting old cluster upgrades (e.g., from August 2025) as recent activity when analyzing a different time window (e.g., March 2026). This led to false positives in root cause correlation.

## Root Cause

The upgrade detection logic in `correlate_findings()` was scanning ALL findings without:
1. Filtering by the analysis time window (`self.start_date` to `self.end_date`)
2. Distinguishing between HISTORICAL_EVENT and CURRENT_STATE findings

This meant old events from August 2025 were being considered when analyzing March 2026, leading to incorrect upgrade correlation.

## Solution

### 1. Added Time Window Filtering Helper Method

```python
def _is_finding_in_time_window(self, finding: dict) -> bool:
    """Check if a finding's timestamp falls within the analysis time window."""
    details = finding.get("details", {})
    timestamp = self._extract_timestamp(details)
    
    if not timestamp:
        return True  # No timestamp - assume in window
    
    # Ensure timestamp has timezone
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    
    # Check if within window
    return self.start_date <= timestamp <= self.end_date
```

### 2. Updated Upgrade Detection Logic

Modified the cluster upgrade correlation to:
- Only consider HISTORICAL_EVENT findings (not CURRENT_STATE)
- Only consider findings within the time window
- Apply filtering to all upgrade pattern checks

**Before:**
```python
# Checked ALL findings regardless of timestamp
for finding in self.findings.get("pod_errors", []):
    if "evict" in finding.get("summary", "").lower():
        evicted_pods.append(finding)
```

**After:**
```python
# Only check HISTORICAL findings within time window
evicted_pods = [
    f for f in self.findings.get("pod_errors", [])
    if f.get("details", {}).get("finding_type") == FindingType.HISTORICAL_EVENT
    and self._is_finding_in_time_window(f)
    and any(kw in f.get("summary", "").lower() for kw in ["evict", "terminat", ...])
]
```

### 3. Updated Node Pressure Correlation

Applied the same time window filtering to the node_pressure_cascade correlation pattern.

### 4. Added Comprehensive Tests

Created `tests/test_time_window_filtering.py` with 5 tests:
- ✅ Findings within time window return True
- ✅ Findings before time window return False
- ✅ Findings after time window return False
- ✅ Findings without timestamp return True (assumed current)
- ✅ Upgrade detection respects time window

## Impact

### Before Fix
```
Root Cause: Node group upgrade in progress or recently completed
Details: 40 upgrade-related events detected from August 2025
Impact: 90 critical, 176 warning findings
```

### After Fix
```
Root Cause: <Actual root cause within the time window>
Details: Only events from March 10, 2026 21:48:00 - 21:48:59
Impact: Findings limited to the specified time window
```

## Files Changed

1. **eks_comprehensive_debugger.py**
   - Added `_is_finding_in_time_window()` helper method
   - Updated `correlate_findings()` to filter by time window
   - Updated cluster upgrade detection patterns
   - Updated node pressure cascade detection

2. **tests/test_time_window_filtering.py** (NEW)
   - 5 comprehensive tests for time window filtering
   - Tests upgrade detection respects time window

## Testing

All 215 tests pass:
- ✅ 15 correlation tests
- ✅ 5 time window filtering tests (NEW)
- ✅ 11 performance tests
- ✅ 184 existing tests

## Verification

To verify the fix works:

```bash
# Run the debugger with a specific time window
python eks_comprehensive_debugger.py \
    --profile prod \
    --region eu-west-1 \
    --cluster-name cpp-cluster \
    --start-date "2026-03-10T21:48:00" \
    --end-date "2026-03-10T21:48:59"

# Expected: No upgrade correlation for old August 2025 events
# Expected: Only findings from March 10, 2026 21:48:00-21:48:59
```

## Future Improvements

1. Apply time window filtering to ALL correlation patterns (cni_cascade, oom_pattern, etc.)
2. Add logging to show how many findings were filtered out by time window
3. Add validation to ensure time window is reasonable (< 7 days)
4. Add summary stats showing filtered findings count

## References

- Issue: Old upgrade from August 2025 incorrectly detected as recent
- Fix: Time window filtering in correlation detection
- Test: tests/test_time_window_filtering.py
