"""Tests for incremental cache and delta reporting."""

import pytest
import os
import json
import tempfile
import time
from unittest.mock import patch, MagicMock
from eks_comprehensive_debugger import IncrementalCache


class TestIncrementalCache:
    """Test cases for IncrementalCache class."""

    @pytest.fixture
    def temp_cache_dir(self, tmp_path):
        """Create a temporary cache directory."""
        cache_dir = tmp_path / ".eks-debugger-cache"
        cache_dir.mkdir()
        return str(cache_dir)

    def test_cache_key_generation(self):
        """Cache key should combine cluster and region."""
        cache = IncrementalCache("my-cluster", "us-east-1")
        assert cache.cache_key == "my-cluster-us-east-1"

    def test_compute_delta_first_run(self):
        """First run should return is_first_run=True."""
        cache = IncrementalCache("test-cluster", "us-east-1")
        current = {"findings": {"pod_errors": [{"summary": "Error 1"}]}}

        delta = cache.compute_delta(current, None)

        assert delta["is_first_run"] is True
        assert delta["new_issues"] == 0
        assert delta["resolved_issues"] == 0

    def test_compute_delta_no_changes(self):
        """No changes should return zero deltas."""
        cache = IncrementalCache("test-cluster", "us-east-1")
        findings = {"pod_errors": [{"summary": "Error 1"}]}
        current = {"findings": findings}
        previous = {"findings": findings}

        delta = cache.compute_delta(current, previous)

        assert delta["is_first_run"] is False
        assert delta["new_issues"] == 0
        assert delta["resolved_issues"] == 0

    def test_compute_delta_new_issues(self):
        """New issues should be detected."""
        cache = IncrementalCache("test-cluster", "us-east-1")
        previous = {"findings": {"pod_errors": [{"summary": "Error 1"}]}}
        current = {
            "findings": {
                "pod_errors": [
                    {"summary": "Error 1"},
                    {"summary": "Error 2"},
                    {"summary": "Error 3"},
                ]
            }
        }

        delta = cache.compute_delta(current, previous)

        assert delta["is_first_run"] is False
        assert delta["new_issues"] == 2
        assert delta["resolved_issues"] == 0
        assert "Error 2" in delta["new_issue_examples"]
        assert "Error 3" in delta["new_issue_examples"]

    def test_compute_delta_resolved_issues(self):
        """Resolved issues should be detected."""
        cache = IncrementalCache("test-cluster", "us-east-1")
        previous = {
            "findings": {
                "pod_errors": [
                    {"summary": "Error 1"},
                    {"summary": "Error 2"},
                    {"summary": "Error 3"},
                ]
            }
        }
        current = {"findings": {"pod_errors": [{"summary": "Error 1"}]}}

        delta = cache.compute_delta(current, previous)

        assert delta["is_first_run"] is False
        assert delta["new_issues"] == 0
        assert delta["resolved_issues"] == 2
        assert "Error 2" in delta["resolved_issue_examples"]
        assert "Error 3" in delta["resolved_issue_examples"]

    def test_compute_delta_mixed_changes(self):
        """Both new and resolved issues should be detected."""
        cache = IncrementalCache("test-cluster", "us-east-1")
        previous = {
            "findings": {
                "pod_errors": [
                    {"summary": "Error 1"},
                    {"summary": "Error 2"},
                ],
                "node_issues": [{"summary": "Node Error 1"}],
            }
        }
        current = {
            "findings": {
                "pod_errors": [
                    {"summary": "Error 1"},
                    {"summary": "Error 3"},  # New
                ],
                "node_issues": [
                    {"summary": "Node Error 2"}  # New, Error 1 resolved
                ],
            }
        }

        delta = cache.compute_delta(current, previous)

        assert delta["is_first_run"] is False
        assert delta["new_issues"] == 2  # Error 3, Node Error 2
        assert delta["resolved_issues"] == 2  # Error 2, Node Error 1

    def test_compute_delta_empty_findings(self):
        """Empty findings should be handled."""
        cache = IncrementalCache("test-cluster", "us-east-1")
        current = {"findings": {}}
        previous = {"findings": {}}

        delta = cache.compute_delta(current, previous)

        assert delta["is_first_run"] is False
        assert delta["new_issues"] == 0
        assert delta["resolved_issues"] == 0

    def test_compute_delta_example_limit(self):
        """Examples should be limited to 10."""
        cache = IncrementalCache("test-cluster", "us-east-1")

        # Create 15 issues in current but not in previous
        previous = {"findings": {"pod_errors": []}}
        current = {"findings": {"pod_errors": [{"summary": f"Error {i}"} for i in range(15)]}}

        delta = cache.compute_delta(current, previous)

        assert delta["new_issues"] == 15
        assert len(delta["new_issue_examples"]) == 10  # Limited to 10

    def test_compute_delta_different_categories(self):
        """Changes across different categories should be tracked."""
        cache = IncrementalCache("test-cluster", "us-east-1")
        previous = {
            "findings": {
                "pod_errors": [{"summary": "Pod Error"}],
                "node_issues": [{"summary": "Node Error"}],
            }
        }
        current = {
            "findings": {
                "pod_errors": [{"summary": "Pod Error"}],
                "node_issues": [],  # Node Error resolved
                "network_issues": [{"summary": "Network Error"}],  # New category
            }
        }

        delta = cache.compute_delta(current, previous)

        assert delta["resolved_issues"] == 1
        assert delta["new_issues"] == 1

    def test_compute_delta_same_summary_different_category(self):
        """Same summary in different categories should be treated as same."""
        cache = IncrementalCache("test-cluster", "us-east-1")
        previous = {
            "findings": {
                "pod_errors": [{"summary": "OOM Error"}],
            }
        }
        current = {
            "findings": {
                "node_issues": [{"summary": "OOM Error"}],  # Same summary, different category
            }
        }

        delta = cache.compute_delta(current, previous)

        # Same summary means no change from delta perspective
        assert delta["new_issues"] == 0
        assert delta["resolved_issues"] == 0

    def test_save_and_load_roundtrip(self, tmp_path):
        """Save and load should preserve data."""
        with patch("eks_comprehensive_debugger.CACHE_DIR", str(tmp_path)):
            cache = IncrementalCache("test-cluster", "us-east-1")
            results = {
                "findings": {"pod_errors": [{"summary": "Error 1"}]},
                "summary": {"total_issues": 1},
            }

            # Save
            cache.save(results)

            # Load
            loaded = cache.load_previous()

            assert loaded is not None
            assert loaded["findings"]["pod_errors"][0]["summary"] == "Error 1"
            assert loaded["summary"]["total_issues"] == 1

    def test_load_previous_no_file(self, tmp_path):
        """Loading when no cache file exists should return None."""
        with patch("eks_comprehensive_debugger.CACHE_DIR", str(tmp_path)):
            cache = IncrementalCache("test-cluster", "us-east-1")

            loaded = cache.load_previous()

            assert loaded is None

    def test_load_previous_expired_cache(self, tmp_path):
        """Expired cache (older than 24h) should return None."""
        with patch("eks_comprehensive_debugger.CACHE_DIR", str(tmp_path)):
            cache = IncrementalCache("test-cluster", "us-east-1")

            # Create an expired cache file
            cache_file = tmp_path / "test-cluster-us-east-1.json"
            expired_data = {
                "timestamp": time.time() - 86401,  # 24h + 1 second ago
                "cluster": "test-cluster-us-east-1",
                "results": {"findings": {}},
            }
            with open(cache_file, "w") as f:
                json.dump(expired_data, f)

            loaded = cache.load_previous()

            assert loaded is None

    def test_file_permissions_on_save(self, tmp_path):
        """Saved cache file should have 0o600 permissions."""
        with patch("eks_comprehensive_debugger.CACHE_DIR", str(tmp_path)):
            cache = IncrementalCache("test-cluster", "us-east-1")
            cache.save({"findings": {}})

            cache_file = tmp_path / "test-cluster-us-east-1.json"
            stat_info = os.stat(cache_file)
            # Check permissions (0o600 = owner read/write only)
            assert stat_info.st_mode & 0o777 == 0o600
