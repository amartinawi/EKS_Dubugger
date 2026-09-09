"""HPA findings must describe the real problem, not the symptom."""

import json

from tests.helpers_debugger import findings, make_debugger


def _hpa(name, minr, maxr, current, conditions=(), metrics=None):
    return {
        "metadata": {"name": name, "namespace": "default"},
        "spec": {
            "minReplicas": minr,
            "maxReplicas": maxr,
            "metrics": [
                {
                    "type": "Resource",
                    "resource": {"name": "memory", "target": {"type": "Utilization", "averageUtilization": 70}},
                }
            ],
        },
        "status": {
            "currentReplicas": current,
            "desiredReplicas": current,
            "conditions": list(conditions),
            "currentMetrics": metrics or [],
        },
    }


def _hpa_findings(dbg):
    return [f for f in findings(dbg, "pod_errors") if "HPA" in f["summary"]]


def test_max_replicas_one_is_not_flagged():
    """min == max means the HPA is a deliberate no-op, not a capacity problem."""
    dbg = make_debugger({"get hpa": json.dumps({"items": [_hpa("admin", 1, 1, 1)]})})
    dbg.analyze_hpa_vpa()
    assert _hpa_findings(dbg) == []


def test_scaling_disabled_for_zero_replicas_is_info():
    cond = [
        {
            "type": "ScalingActive",
            "status": "False",
            "reason": "ScalingDisabled",
            "message": "scaling is disabled since the replica count of the target is zero",
        }
    ]
    dbg = make_debugger({"get hpa": json.dumps({"items": [_hpa("idle", 1, 2, 0, cond)]})})
    dbg.analyze_hpa_vpa()
    f = _hpa_findings(dbg)
    assert len(f) == 1
    assert f[0]["details"]["severity"] == "info"
    assert "scaled to zero" in f[0]["summary"]


def test_scaling_inactive_for_other_reasons_stays_warning():
    cond = [
        {
            "type": "ScalingActive",
            "status": "False",
            "reason": "FailedGetResourceMetric",
            "message": "unable to get metrics",
        }
    ]
    dbg = make_debugger({"get hpa": json.dumps({"items": [_hpa("broken", 1, 4, 2, cond)]})})
    dbg.analyze_hpa_vpa()
    f = _hpa_findings(dbg)
    assert len(f) == 1
    assert f[0]["details"]["severity"] == "warning"


def test_metric_over_target_at_max_is_reported_with_remedy():
    metrics = [{"type": "Resource", "resource": {"name": "memory", "current": {"averageUtilization": 271}}}]
    dbg = make_debugger({"get hpa": json.dumps({"items": [_hpa("nginx", 4, 6, 6, metrics=metrics)]})})
    dbg.analyze_hpa_vpa()
    f = _hpa_findings(dbg)
    assert len(f) == 1
    assert "memory 271%" in f[0]["summary"]
    assert "target 70%" in f[0]["summary"]
    assert "request" in f[0]["details"]["recommendation"].lower()


def test_plain_at_max_without_metric_pressure():
    dbg = make_debugger({"get hpa": json.dumps({"items": [_hpa("web", 2, 6, 6)]})})
    dbg.analyze_hpa_vpa()
    f = _hpa_findings(dbg)
    assert len(f) == 1
    assert "at max replicas" in f[0]["summary"]
    assert f[0]["details"]["severity"] == "warning"
