"""CronJob analysis uses the parsed schedule and the active job duration."""

import json
from datetime import datetime, timedelta, timezone

from tests.helpers_debugger import findings, make_debugger


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cj(schedule, last_schedule_hours_ago, active=None, concurrency="Allow"):
    return {
        "metadata": {"name": "rot", "namespace": "default"},
        "spec": {"schedule": schedule, "suspend": False, "concurrencyPolicy": concurrency},
        "status": {"lastScheduleTime": _iso(last_schedule_hours_ago), "active": active or []},
    }


def _job(name, started_ago_hours):
    return {
        "metadata": {
            "name": name,
            "namespace": "default",
            "ownerReferences": [{"kind": "CronJob", "name": "rot"}],
        },
        "status": {"startTime": _iso(started_ago_hours), "active": 1},
    }


def _cj_findings(dbg):
    return [f for f in findings(dbg, "pod_errors") if "CronJob" in f["summary"]]


def test_daily_cronjob_not_flagged_after_two_hours():
    dbg = make_debugger(
        {"get cronjobs": json.dumps({"items": [_cj("0 3 * * *", 2)]}), "get jobs": json.dumps({"items": []})}
    )
    dbg.analyze_jobs_cronjobs()
    assert _cj_findings(dbg) == []


def test_active_job_longer_than_period_is_flagged_with_duration():
    cj = _cj("0 */6 * * *", 4, active=[{"name": "rot-1"}], concurrency="Forbid")
    dbg = make_debugger(
        {
            "get cronjobs": json.dumps({"items": [cj]}),
            "get jobs": json.dumps({"items": [_job("rot-1", 34)]}),
        }
    )
    dbg.analyze_jobs_cronjobs()
    f = _cj_findings(dbg)
    assert len(f) == 1
    assert "34h" in f[0]["summary"]
    assert "6h" in f[0]["summary"]
    assert f[0]["details"]["concurrency_policy"] == "Forbid"


def test_missed_schedule_uses_two_periods():
    cj = _cj("*/30 * * * *", 5)  # 30 min schedule, last run 5h ago
    dbg = make_debugger(
        {"get cronjobs": json.dumps({"items": [cj]}), "get jobs": json.dumps({"items": []})}
    )
    dbg.analyze_jobs_cronjobs()
    f = _cj_findings(dbg)
    assert len(f) == 1
    assert "missed schedules" in f[0]["summary"]


def test_period_helper_parses_common_schedules():
    dbg = make_debugger()
    assert dbg._cron_period_seconds("0 */6 * * *") == 6 * 3600
    assert dbg._cron_period_seconds("*/30 * * * *") == 1800
    assert dbg._cron_period_seconds("not a cron") is None
