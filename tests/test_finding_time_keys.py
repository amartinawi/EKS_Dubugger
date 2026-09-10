"""One definition of a finding's time, shared by correlation and window filtering."""

from datetime import datetime, timedelta, timezone

import eks_comprehensive_debugger as ekd
from tests.helpers_debugger import make_debugger


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


ALL_KEYS = [
    "timestamp",
    "lastTimestamp",
    "eventTime",
    "firstTimestamp",
    "creationTimestamp",
    "finished_at",
    "first_seen",
    "last_seen",
    "event_time",
    "created_at",
    "last_schedule",
    "deletion_timestamp",
]


def test_every_documented_time_key_is_extractable():
    dbg = make_debugger()
    for key in ALL_KEYS:
        assert dbg._extract_timestamp({key: "2026-09-09T09:31:19Z"}) is not None, f"{key} not recognised"


def test_duration_fields_are_not_treated_as_times():
    """Quick Wins store an effort estimate under 'time'; it is not a timestamp."""
    dbg = make_debugger()
    assert dbg._extract_timestamp({"time": "10 min"}) is None


def test_no_time_key_returns_none():
    dbg = make_debugger()
    assert dbg._extract_timestamp({"pod": "p", "namespace": "n"}) is None


def test_window_filter_uses_the_same_keys():
    """A CloudTrail finding dated months ago must not pass a 24 hour window."""
    dbg = make_debugger()
    dbg.end_date = datetime.now(timezone.utc)
    dbg.start_date = dbg.end_date - timedelta(hours=24)

    for key in ALL_KEYS:
        old = {"details": {key: _iso(60)}}
        recent = {"details": {key: _iso(0)}}
        assert dbg._is_finding_in_time_window(old) is False, f"{key} bypassed the window filter"
        assert dbg._is_finding_in_time_window(recent) is True, f"{key} wrongly excluded"


def test_finding_without_any_time_is_kept_in_window():
    dbg = make_debugger()
    dbg.end_date = datetime.now(timezone.utc)
    dbg.start_date = dbg.end_date - timedelta(hours=24)
    assert dbg._is_finding_in_time_window({"details": {"pod": "p"}}) is True


def test_key_list_is_shared_not_duplicated():
    """Both readers must consult one list, so they cannot drift apart again."""
    assert hasattr(ekd, "FINDING_TIME_KEYS")
    for key in ALL_KEYS:
        assert key in ekd.FINDING_TIME_KEYS
    assert "time" not in ekd.FINDING_TIME_KEYS
