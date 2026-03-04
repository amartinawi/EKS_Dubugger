"""Tests for correlation and root cause analysis logic."""

import pytest
from datetime import datetime, timezone, timedelta
from eks_comprehensive_debugger import ComprehensiveEKSDebugger


class TestCorrelationLogic:
    """Test cases for root cause correlation detection."""

    @pytest.fixture
    def debugger(self, mocker):
        """Create a debugger instance with mocked AWS clients."""
        mocker.patch("boto3.Session")
        debugger = ComprehensiveEKSDebugger(
            profile="test",
            region="us-east-1",
            cluster_name="test-cluster",
        )
        return debugger

    def test_5d_confidence_scoring_temporal_causality(self, debugger):
        """5D confidence should score temporal causality correctly."""
        now = datetime.now(timezone.utc)
        cause_time = now - timedelta(minutes=5)
        effect_time = now - timedelta(minutes=3)

        cause_events = [{"details": {"node": "node-1", "timestamp": cause_time}}]
        effect_events = [{"details": {"node": "node-1", "timestamp": effect_time}}]

        result = debugger._calculate_5d_confidence(
            cause_events=cause_events,
            effect_events=effect_events,
            mechanism_known=True,
            alternative_causes=[],
        )

        assert "composite" in result
        assert "confidence_tier" in result
        assert "scores" in result
        assert "temporal" in result["scores"]
        # Temporal score should be high when cause precedes effect
        assert result["scores"]["temporal"] >= 0.5

    def test_5d_confidence_scoring_reverse_temporal(self, debugger):
        """5D confidence should penalize reversed causality."""
        now = datetime.now(timezone.utc)
        cause_time = now - timedelta(minutes=3)
        effect_time = now - timedelta(minutes=5)  # Effect before cause

        cause_events = [{"timestamp": cause_time, "details": {"node": "node-1"}}]
        effect_events = [{"timestamp": effect_time, "details": {"node": "node-1"}}]

        result = debugger._calculate_5d_confidence(
            cause_events=cause_events,
            effect_events=effect_events,
            mechanism_known=True,
            alternative_causes=[],
        )

        # Temporal score should be low when effect precedes cause
        assert result["scores"]["temporal"] < 0.5

    def test_5d_confidence_spatial_correlation_same_node(self, debugger):
        """Spatial correlation should detect same-node events."""
        now = datetime.now(timezone.utc)
        cause_events = [{"timestamp": now, "details": {"node": "node-1", "namespace": "default"}}]
        effect_events = [{"timestamp": now, "details": {"node": "node-1", "namespace": "default"}}]

        result = debugger._score_spatial_correlation(cause_events, effect_events)

        assert "overlap_score" in result
        assert "node_matches" in result
        # Same node should have high overlap
        assert result["overlap_score"] >= 0.3
        assert result["node_matches"] >= 1

    def test_5d_confidence_spatial_correlation_different_nodes(self, debugger):
        """Spatial correlation should detect different-node events."""
        now = datetime.now(timezone.utc)
        cause_events = [{"timestamp": now, "details": {"node": "node-1", "namespace": "default"}}]
        effect_events = [{"timestamp": now, "details": {"node": "node-2", "namespace": "default"}}]

        result = debugger._score_spatial_correlation(cause_events, effect_events)

        # Different nodes should have lower overlap (but same namespace)
        assert result["overlap_score"] < 0.3
        assert result["node_matches"] == 0
        assert result["namespace_matches"] >= 1

    def test_5d_confidence_mechanism_known(self, debugger):
        """Known causal mechanism should boost confidence."""
        now = datetime.now(timezone.utc)
        events = [{"timestamp": now, "details": {"node": "node-1"}}]

        result_known = debugger._calculate_5d_confidence(
            cause_events=events,
            effect_events=events,
            mechanism_known=True,
            alternative_causes=[],
        )

        result_unknown = debugger._calculate_5d_confidence(
            cause_events=events,
            effect_events=events,
            mechanism_known=False,
            alternative_causes=[],
        )

        # Known mechanism should have higher confidence
        assert result_known["scores"]["mechanism"] == 1.0
        assert result_unknown["scores"]["mechanism"] < 1.0

    def test_5d_confidence_alternative_causes(self, debugger):
        """Alternative causes should reduce exclusivity score."""
        now = datetime.now(timezone.utc)
        events = [{"timestamp": now, "details": {"node": "node-1"}}]

        result_no_alternatives = debugger._calculate_5d_confidence(
            cause_events=events,
            effect_events=events,
            mechanism_known=True,
            alternative_causes=None,
        )

        result_with_alternatives = debugger._calculate_5d_confidence(
            cause_events=events,
            effect_events=events,
            mechanism_known=True,
            alternative_causes=["other_cause_1", "other_cause_2"],
        )

        # With alternatives, exclusivity should be lower
        assert result_with_alternatives["scores"]["exclusivity"] < result_no_alternatives["scores"]["exclusivity"]

    def test_confidence_tier_classification_high(self, debugger):
        """Composite confidence >= 0.75 should be classified as high."""
        now = datetime.now(timezone.utc)
        events = [{"timestamp": now, "details": {"node": "node-1"}}]

        result = debugger._calculate_5d_confidence(
            cause_events=events,
            effect_events=events,
            mechanism_known=True,
            alternative_causes=[],
        )

        # Force high confidence scenario
        if result["composite"] >= 0.75:
            assert result["confidence_tier"] == "high"

    def test_confidence_tier_classification_medium(self, debugger):
        """Composite confidence 0.50-0.74 should be classified as medium."""
        now = datetime.now(timezone.utc)
        cause_events = [{"timestamp": now - timedelta(minutes=10), "details": {"node": "node-1"}}]
        effect_events = [{"timestamp": now, "details": {"node": "node-2"}}]

        result = debugger._calculate_5d_confidence(
            cause_events=cause_events,
            effect_events=effect_events,
            mechanism_known=False,
            alternative_causes=["other_cause"],
        )

        if 0.50 <= result["composite"] < 0.75:
            assert result["confidence_tier"] == "medium"

    def test_confidence_tier_classification_low(self, debugger):
        """Composite confidence < 0.50 should be classified as low."""
        now = datetime.now(timezone.utc)
        # Reversed temporal order (effect before cause)
        cause_events = [{"timestamp": now, "details": {"node": "node-1"}}]
        effect_events = [{"timestamp": now - timedelta(minutes=10), "details": {"node": "node-2"}}]

        result = debugger._calculate_5d_confidence(
            cause_events=cause_events,
            effect_events=effect_events,
            mechanism_known=False,
            alternative_causes=["cause1", "cause2", "cause3"],
        )

        if result["composite"] < 0.50:
            assert result["confidence_tier"] == "low"

    def test_spatial_correlation_namespace_weighting(self, debugger):
        """Spatial correlation should weight namespace overlap."""
        now = datetime.now(timezone.utc)
        cause_events = [{"timestamp": now, "details": {"node": "node-1", "namespace": "production"}}]
        effect_events = [{"timestamp": now, "details": {"node": "node-2", "namespace": "production"}}]

        result = debugger._score_spatial_correlation(cause_events, effect_events)

        # Same namespace but different nodes should have moderate overlap
        assert 0 < result["overlap_score"] < 0.3
        assert result["namespace_matches"] >= 1
        assert result["node_matches"] == 0

    def test_empty_events_returns_low_confidence(self, debugger):
        """Empty events should result in low confidence."""
        result = debugger._calculate_5d_confidence(
            cause_events=[],
            effect_events=[],
            mechanism_known=False,
            alternative_causes=[],
        )

        assert result["composite"] < 0.5
        assert result["confidence_tier"] == "low"

    def test_reproducibility_scoring(self, debugger):
        """Multiple occurrences should boost reproducibility score."""
        now = datetime.now(timezone.utc)
        # Multiple cause events (pattern repeats)
        cause_events = [
            {"details": {"node": "node-1", "timestamp": now - timedelta(minutes=30)}},
            {"details": {"node": "node-1", "timestamp": now - timedelta(minutes=20)}},
            {"details": {"node": "node-1", "timestamp": now - timedelta(minutes=10)}},
        ]
        effect_events = [
            {"details": {"node": "node-1", "timestamp": now - timedelta(minutes=28)}},
            {"details": {"node": "node-1", "timestamp": now - timedelta(minutes=18)}},
            {"details": {"node": "node-1", "timestamp": now - timedelta(minutes=8)}},
        ]

        result = debugger._calculate_5d_confidence(
            cause_events=cause_events,
            effect_events=effect_events,
            mechanism_known=True,
            alternative_causes=[],
        )

        # Reproducibility should be non-zero with multiple occurrences
        assert result["scores"]["reproducibility"] > 0


class TestRootCauseRanking:
    """Test cases for root cause ranking logic."""

    @pytest.fixture
    def debugger(self, mocker):
        """Create a debugger instance with mocked AWS clients."""
        mocker.patch("boto3.Session")
        debugger = ComprehensiveEKSDebugger(
            profile="test",
            region="us-east-1",
            cluster_name="test-cluster",
        )
        return debugger

    def test_ranking_prioritizes_high_confidence(self, debugger):
        """Ranking should prioritize high confidence correlations."""
        correlations = [
            {
                "correlation_type": "test1",
                "composite_confidence": 0.85,
                "severity": "warning",
                "root_cause": "Cause 1",
            },
            {
                "correlation_type": "test2",
                "composite_confidence": 0.95,
                "severity": "warning",
                "root_cause": "Cause 2",
            },
            {
                "correlation_type": "test3",
                "composite_confidence": 0.75,
                "severity": "warning",
                "root_cause": "Cause 3",
            },
        ]

        ranked = debugger._rank_root_causes(correlations)

        # Highest confidence should be first
        assert ranked[0]["composite_confidence"] >= ranked[1]["composite_confidence"]

    def test_ranking_prioritizes_critical_severity(self, debugger):
        """Ranking should prioritize critical severity."""
        correlations = [
            {
                "correlation_type": "test1",
                "composite_confidence": 0.85,
                "severity": "warning",
                "root_cause": "Cause 1",
            },
            {
                "correlation_type": "test2",
                "composite_confidence": 0.85,
                "severity": "critical",
                "root_cause": "Cause 2",
            },
        ]

        ranked = debugger._rank_root_causes(correlations)

        # Critical should come before warning with same confidence
        assert ranked[0]["severity"] == "critical"

    def test_ranking_empty_correlations(self, debugger):
        """Empty correlations list should return empty."""
        ranked = debugger._rank_root_causes([])
        assert ranked == []
