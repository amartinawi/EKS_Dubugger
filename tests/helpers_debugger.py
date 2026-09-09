"""Shared factory for a network-free ComprehensiveEKSDebugger."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import eks_comprehensive_debugger as ekd


def make_debugger(kubectl_responses: dict[str, str] | None = None, **kwargs):
    """Return a debugger whose kubectl and AWS calls are stubbed.

    kubectl_responses maps a substring of the kubectl command to the JSON text
    to return. Any command that matches no key returns an empty item list.
    """
    responses = kubectl_responses or {}

    def fake_kubectl(cmd, *args, **kw):
        for key, value in responses.items():
            if key in cmd:
                return value
        return '{"items": []}'

    with patch("eks_comprehensive_debugger.boto3.Session"):
        dbg = ekd.ComprehensiveEKSDebugger(profile="test", region="eu-west-1", cluster_name="test-cluster", **kwargs)
    dbg._get_cached_kubectl = Mock(side_effect=fake_kubectl)
    dbg.safe_kubectl_call = Mock(side_effect=fake_kubectl)
    dbg.safe_api_call = Mock(return_value=(True, {}))
    dbg.progress = Mock()
    dbg.end_date = datetime.now(timezone.utc)
    dbg.start_date = dbg.end_date - timedelta(hours=24)
    return dbg


def findings(dbg, category):
    """Return the findings recorded under one category."""
    return dbg.findings.get(category, [])
