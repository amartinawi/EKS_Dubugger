"""EKS Cluster Insights: correct response key and status gating."""

from tests.helpers_debugger import findings, make_debugger


def _insights_api(list_payload, detail_payload):
    """Route safe_api_call by kwargs: describe_insight passes an id, list_insights does not."""

    def fake(func, *args, **kwargs):
        if "id" in kwargs:
            return True, detail_payload
        return True, list_payload

    return fake


def test_warning_insight_becomes_warning_finding():
    dbg = make_debugger()
    dbg.safe_api_call.side_effect = _insights_api(
        {
            "insights": [
                {
                    "id": "i-1",
                    "name": "Kubelet version skew",
                    "category": "UPGRADE_READINESS",
                    "insightStatus": {"status": "WARNING", "reason": "kubelet two versions behind"},
                    "description": "Checks kubelet versions",
                }
            ]
        },
        {"insight": {"recommendation": "Upgrade node groups", "kubernetesResourceUri": []}},
    )
    dbg.check_eks_cluster_insights()
    cp = findings(dbg, "control_plane_issues")
    assert len(cp) == 1
    assert cp[0]["details"]["severity"] == "warning"
    assert "Kubelet version skew" in cp[0]["summary"]


def test_error_insight_is_critical():
    dbg = make_debugger()
    dbg.safe_api_call.side_effect = _insights_api(
        {
            "insights": [
                {
                    "id": "i-3",
                    "name": "Deprecated API usage",
                    "category": "UPGRADE_READINESS",
                    "insightStatus": {"status": "ERROR", "reason": "removed API in use"},
                    "description": "Checks deprecated APIs",
                }
            ]
        },
        {"insight": {}},
    )
    dbg.check_eks_cluster_insights()
    cp = findings(dbg, "control_plane_issues")
    assert len(cp) == 1
    assert cp[0]["details"]["severity"] == "critical"


def test_passing_insight_is_ignored():
    dbg = make_debugger()
    dbg.safe_api_call.side_effect = _insights_api(
        {
            "insights": [
                {
                    "id": "i-2",
                    "name": "Cluster health issues",
                    "category": "UPGRADE_READINESS",
                    "insightStatus": {"status": "PASSING"},
                    "description": "ok",
                }
            ]
        },
        {"insight": {}},
    )
    dbg.check_eks_cluster_insights()
    assert findings(dbg, "control_plane_issues") == []


def test_old_insight_summaries_key_is_not_used():
    """The API returns 'insights'; reading 'insightSummaries' silently found nothing."""
    dbg = make_debugger()
    dbg.safe_api_call.side_effect = _insights_api(
        {
            "insightSummaries": [
                {
                    "id": "i-9",
                    "name": "should not be read",
                    "category": "UPGRADE_READINESS",
                    "insightStatus": {"status": "WARNING"},
                    "description": "x",
                }
            ]
        },
        {"insight": {}},
    )
    dbg.check_eks_cluster_insights()
    assert findings(dbg, "control_plane_issues") == []
