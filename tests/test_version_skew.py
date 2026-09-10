"""Version skew must surface one-minor drift and node group versions."""

import json

from tests.helpers_debugger import findings, make_debugger


def _nodes(*versions):
    return json.dumps(
        {
            "items": [
                {"metadata": {"name": f"n{i}"}, "status": {"nodeInfo": {"kubeletVersion": v}}}
                for i, v in enumerate(versions)
            ]
        }
    )


def _api(nodegroups=()):
    def fake(func, *args, **kwargs):
        if "nodegroupName" in kwargs:
            name = kwargs["nodegroupName"]
            return True, {"nodegroup": next(n for n in nodegroups if n["nodegroupName"] == name)}
        return True, {"nodegroups": [n["nodegroupName"] for n in nodegroups]}

    return fake


def test_one_minor_skew_is_one_info_finding():
    dbg = make_debugger({"get nodes": _nodes("v1.33.8-eks-f69f56f", "v1.33.8-eks-f69f56f")})
    dbg.eks_client.describe_cluster.return_value = {"cluster": {"version": "1.34"}}
    dbg.safe_api_call.side_effect = _api()
    dbg.analyze_version_skew()
    f = findings(dbg, "node_issues")
    assert len(f) == 1
    assert f[0]["details"]["severity"] == "info"
    assert "2 nodes" in f[0]["summary"]
    assert "1.33" in f[0]["summary"]


def test_matching_versions_produce_nothing():
    dbg = make_debugger({"get nodes": _nodes("v1.34.1-eks-abc")})
    dbg.eks_client.describe_cluster.return_value = {"cluster": {"version": "1.34"}}
    dbg.safe_api_call.side_effect = _api()
    dbg.analyze_version_skew()
    assert findings(dbg, "node_issues") == []


def test_nodegroup_two_behind_is_warning():
    dbg = make_debugger({"get nodes": _nodes()})
    dbg.eks_client.describe_cluster.return_value = {"cluster": {"version": "1.34"}}
    dbg.safe_api_call.side_effect = _api(
        [{"nodegroupName": "old", "version": "1.32", "scalingConfig": {"desiredSize": 0}}]
    )
    dbg.analyze_version_skew()
    f = findings(dbg, "node_issues")
    assert len(f) == 1
    assert f[0]["details"]["severity"] == "warning"
    assert "old" in f[0]["summary"]
    assert f[0]["details"]["desired_size"] == 0


def test_node_three_behind_stays_critical():
    dbg = make_debugger({"get nodes": _nodes("v1.31.0-eks-abc")})
    dbg.eks_client.describe_cluster.return_value = {"cluster": {"version": "1.34"}}
    dbg.safe_api_call.side_effect = _api()
    dbg.analyze_version_skew()
    f = findings(dbg, "node_issues")
    assert len(f) == 1
    assert f[0]["details"]["severity"] == "critical"


def test_control_plane_version_is_recorded_for_statistics():
    dbg = make_debugger({"get nodes": _nodes("v1.34.1-eks-abc")})
    dbg.eks_client.describe_cluster.return_value = {"cluster": {"version": "1.34"}}
    dbg.safe_api_call.side_effect = _api()
    dbg.analyze_version_skew()
    assert dbg._shared_data["control_plane_version"] == "1.34"
