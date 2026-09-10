"""Node OS findings must respect the analysis window."""

from datetime import datetime, timezone

from tests.helpers_debugger import make_debugger


def _sink_debugger():
    dbg = make_debugger()
    dbg.start_date = datetime(2026, 6, 17, tzinfo=timezone.utc)
    dbg.end_date = datetime(2026, 6, 18, tzinfo=timezone.utc)
    collected = []
    return dbg, collected


def test_dmesg_finding_outside_window_is_dropped():
    dbg, collected = _sink_debugger()
    add = dbg._node_os_add_finding(lambda category, finding: collected.append((category, finding)))
    parser = __import__("eks_comprehensive_debugger").NodeOSOutputParser()
    parser.parse(
        "dmesg",
        "[Mon Feb  9 10:57:00 2026] Out of memory: Killed process 123 (java)",
        "n1",
        "i-1",
        add,
    )
    assert collected == []


def test_dmesg_finding_inside_window_is_kept():
    dbg, collected = _sink_debugger()
    add = dbg._node_os_add_finding(lambda category, finding: collected.append((category, finding)))
    parser = __import__("eks_comprehensive_debugger").NodeOSOutputParser()
    parser.parse(
        "dmesg",
        "[Wed Jun 17 12:00:00 2026] Out of memory: Killed process 123 (java)",
        "n1",
        "i-1",
        add,
    )
    assert len(collected) == 1


def test_finding_without_timestamp_is_kept():
    """Current-state findings carry no timestamp and must not be filtered out."""
    dbg, collected = _sink_debugger()
    add = dbg._node_os_add_finding(lambda category, finding: collected.append((category, finding)))
    add("node_os_sysctl", {"summary": "somaxconn is low", "details": {"severity": "warning"}})
    assert len(collected) == 1
