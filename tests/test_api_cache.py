"""Tests for API caching functionality."""

import pytest
import time
import threading
from eks_comprehensive_debugger import APICache


class TestAPICache:
    """Test cases for APICache class."""

    def test_cache_basic_set_get(self):
        """Basic set and get operations."""
        cache = APICache(ttl_seconds=60)
        cache.set("key1", ({"data": "value"},))
        result = cache.get("key1")
        assert result == ({"data": "value"},)

    def test_cache_missing_key(self):
        """Getting non-existent key returns None."""
        cache = APICache(ttl_seconds=60)
        result = cache.get("nonexistent")
        assert result is None

    def test_cache_ttl_expiration(self):
        """Cached data should expire after TTL."""
        cache = APICache(ttl_seconds=1)
        cache.set("key1", ({"data": "value"},))

        # Should exist immediately
        assert cache.get("key1") == ({"data": "value"},)

        # Wait for TTL to expire
        time.sleep(1.1)

        # Should be None after expiration
        assert cache.get("key1") is None

    def test_cache_overwrite(self):
        """Setting same key overwrites previous value."""
        cache = APICache(ttl_seconds=60)
        cache.set("key1", ({"data": "value1"},))
        cache.set("key1", ({"data": "value2"},))

        assert cache.get("key1") == ({"data": "value2"},)

    def test_cache_clear(self):
        """Clear should remove all entries."""
        cache = APICache(ttl_seconds=60)
        cache.set("key1", ("value1",))
        cache.set("key2", ("value2",))

        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_cache_thread_safety_concurrent_writes(self):
        """Concurrent writes should not corrupt cache."""
        cache = APICache(ttl_seconds=60)
        num_threads = 10
        writes_per_thread = 100
        errors = []

        def write_values(thread_id):
            try:
                for i in range(writes_per_thread):
                    key = f"thread_{thread_id}_key_{i}"
                    cache.set(key, ({"thread": thread_id, "index": i},))
            except Exception as e:
                errors.append(str(e))

        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=write_values, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # No errors should occur
        assert len(errors) == 0

    def test_cache_thread_safety_concurrent_reads(self):
        """Concurrent reads should be safe."""
        cache = APICache(ttl_seconds=60)
        cache.set("shared_key", ({"value": "shared"},))

        num_threads = 10
        reads_per_thread = 100
        results = []

        def read_values():
            for _ in range(reads_per_thread):
                result = cache.get("shared_key")
                results.append(result)

        threads = []
        for _ in range(num_threads):
            t = threading.Thread(target=read_values)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All reads should return the same value
        assert len(results) == num_threads * reads_per_thread
        for result in results:
            assert result == ({"value": "shared"},)

    def test_cache_make_key(self):
        """Static method make_key should generate consistent keys."""
        key1 = APICache.make_key("describe_clusters", "us-east-1", "my-cluster")
        key2 = APICache.make_key("describe_clusters", "us-east-1", "my-cluster")

        assert key1 == key2

    def test_cache_make_key_different_args(self):
        """Different arguments should produce different keys."""
        key1 = APICache.make_key("describe_clusters", "us-east-1")
        key2 = APICache.make_key("describe_clusters", "eu-west-1")

        assert key1 != key2

    def test_cache_with_kwargs(self):
        """Cache should handle keyword arguments in make_key."""
        key1 = APICache.make_key("api_call", region="us-east-1", cluster="test")
        key2 = APICache.make_key("api_call", cluster="test", region="us-east-1")

        # Same kwargs in different order should produce same key
        assert key1 == key2

    def test_cache_multiple_entries(self):
        """Cache should handle multiple entries."""
        cache = APICache(ttl_seconds=60)

        for i in range(100):
            cache.set(f"key_{i}", (f"value_{i}",))

        # All entries should be retrievable
        for i in range(100):
            assert cache.get(f"key_{i}") == (f"value_{i}",)
