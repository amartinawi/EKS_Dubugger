"""Tests for performance tracking functionality."""

import pytest
import time
import threading
from eks_comprehensive_debugger import PerformanceTracker


class TestPerformanceTracker:
    """Test cases for PerformanceTracker class."""

    def test_record_single_timing(self):
        """Recording a single timing should work."""
        tracker = PerformanceTracker()
        tracker.record("analyze_pods", 1.5)

        summary = tracker.get_summary()
        assert "analyze_pods" in summary
        assert summary["analyze_pods"]["calls"] == 1
        assert summary["analyze_pods"]["total"] == 1.5
        assert summary["analyze_pods"]["avg"] == 1.5
        assert summary["analyze_pods"]["min"] == 1.5
        assert summary["analyze_pods"]["max"] == 1.5

    def test_record_multiple_timings_same_method(self):
        """Multiple recordings for same method should aggregate."""
        tracker = PerformanceTracker()
        tracker.record("analyze_pods", 1.0)
        tracker.record("analyze_pods", 2.0)
        tracker.record("analyze_pods", 3.0)

        summary = tracker.get_summary()
        assert summary["analyze_pods"]["calls"] == 3
        assert summary["analyze_pods"]["total"] == 6.0
        assert summary["analyze_pods"]["avg"] == 2.0
        assert summary["analyze_pods"]["min"] == 1.0
        assert summary["analyze_pods"]["max"] == 3.0

    def test_record_multiple_methods(self):
        """Different methods should be tracked separately."""
        tracker = PerformanceTracker()
        tracker.record("analyze_pods", 1.0)
        tracker.record("analyze_nodes", 2.0)
        tracker.record("analyze_network", 3.0)

        summary = tracker.get_summary()
        assert len(summary) == 3
        assert summary["analyze_pods"]["total"] == 1.0
        assert summary["analyze_nodes"]["total"] == 2.0
        assert summary["analyze_network"]["total"] == 3.0

    def test_get_summary_empty_tracker(self):
        """Empty tracker should return empty summary."""
        tracker = PerformanceTracker()
        summary = tracker.get_summary()
        assert summary == {}

    def test_get_slowest_methods(self):
        """Should return slowest methods by total time."""
        tracker = PerformanceTracker()
        tracker.record("fast_method", 1.0)
        tracker.record("slow_method", 10.0)
        tracker.record("medium_method", 5.0)
        tracker.record("another_slow", 8.0)

        slowest = tracker.get_slowest(limit=3)

        assert len(slowest) == 3
        # Should be sorted by total time descending
        assert slowest[0][0] == "slow_method"
        assert slowest[0][1] == 10.0
        assert slowest[1][0] == "another_slow"
        assert slowest[1][1] == 8.0
        assert slowest[2][0] == "medium_method"
        assert slowest[2][1] == 5.0

    def test_get_slowest_with_limit(self):
        """Limit parameter should control number of results."""
        tracker = PerformanceTracker()
        for i in range(20):
            tracker.record(f"method_{i}", float(i))

        slowest = tracker.get_slowest(limit=5)
        assert len(slowest) == 5

    def test_thread_safety_concurrent_recording(self):
        """Concurrent recordings should be safe."""
        tracker = PerformanceTracker()
        num_threads = 10
        records_per_thread = 100
        errors = []

        def record_timings(thread_id):
            try:
                for i in range(records_per_thread):
                    tracker.record(f"method_{thread_id}_{i}", 0.01 * (i + 1))
            except Exception as e:
                errors.append(str(e))

        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=record_timings, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # No errors should occur
        assert len(errors) == 0

        # All recordings should be present
        summary = tracker.get_summary()
        total_calls = sum(s["calls"] for s in summary.values())
        assert total_calls == num_threads * records_per_thread

    def test_thread_safety_concurrent_read_write(self):
        """Concurrent reads and writes should be safe."""
        tracker = PerformanceTracker()
        errors = []

        def write_values():
            try:
                for i in range(100):
                    tracker.record("shared_method", 0.01 * i)
            except Exception as e:
                errors.append(str(e))

        def read_values():
            try:
                for _ in range(100):
                    summary = tracker.get_summary()
                    _ = tracker.get_slowest()
            except Exception as e:
                errors.append(str(e))

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=write_values))
            threads.append(threading.Thread(target=read_values))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should occur
        assert len(errors) == 0

    def test_timing_values_preserved(self):
        """Timing values should be preserved accurately."""
        tracker = PerformanceTracker()
        timings = [0.001, 0.01, 0.1, 1.0, 10.0, 100.0]

        for t in timings:
            tracker.record("test_method", t)

        summary = tracker.get_summary()
        assert summary["test_method"]["min"] == 0.001
        assert summary["test_method"]["max"] == 100.0
        assert summary["test_method"]["total"] == sum(timings)
