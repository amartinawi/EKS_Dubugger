"""AMI patch level comes from the node group release version, not node uptime."""

from tests.helpers_debugger import findings, make_debugger


def _api(nodegroups, recommended):
    def fake(func, *args, **kwargs):
        if "nodegroupName" in kwargs:
            name = kwargs["nodegroupName"]
            return True, {"nodegroup": next(n for n in nodegroups if n["nodegroupName"] == name)}
        if "Name" in kwargs:
            return True, {"Parameter": {"Value": recommended}}
        return True, {"nodegroups": [n["nodegroupName"] for n in nodegroups]}

    return fake


def test_outdated_release_is_flagged_with_days_behind():
    dbg = make_debugger()
    dbg.safe_api_call.side_effect = _api(
        [
            {
                "nodegroupName": "web",
                "version": "1.33",
                "releaseVersion": "1.33.8-20260304",
                "amiType": "AL2023_x86_64_STANDARD",
            }
        ],
        "1.33.13-20260903",
    )
    dbg.analyze_node_ami_age()
    f = findings(dbg, "node_issues")
    assert len(f) == 1
    assert "1.33.8-20260304" in f[0]["summary"]
    assert "1.33.13-20260903" in f[0]["summary"]
    assert f[0]["details"]["days_behind"] == 183
    assert f[0]["details"]["severity"] == "critical"


def test_recent_but_not_latest_release_is_warning():
    dbg = make_debugger()
    dbg.safe_api_call.side_effect = _api(
        [
            {
                "nodegroupName": "web",
                "version": "1.33",
                "releaseVersion": "1.33.12-20260810",
                "amiType": "AL2023_x86_64_STANDARD",
            }
        ],
        "1.33.13-20260903",
    )
    dbg.analyze_node_ami_age()
    f = findings(dbg, "node_issues")
    assert len(f) == 1
    assert f[0]["details"]["severity"] == "warning"


def test_current_release_produces_nothing():
    dbg = make_debugger()
    dbg.safe_api_call.side_effect = _api(
        [
            {
                "nodegroupName": "web",
                "version": "1.33",
                "releaseVersion": "1.33.13-20260903",
                "amiType": "AL2023_x86_64_STANDARD",
            }
        ],
        "1.33.13-20260903",
    )
    dbg.analyze_node_ami_age()
    assert findings(dbg, "node_issues") == []


def test_custom_ami_is_info():
    dbg = make_debugger()
    dbg.safe_api_call.side_effect = _api(
        [{"nodegroupName": "gpu", "version": "1.33", "releaseVersion": "ami-0123456789abcdef0", "amiType": "CUSTOM"}],
        "x",
    )
    dbg.analyze_node_ami_age()
    f = findings(dbg, "node_issues")
    assert len(f) == 1
    assert f[0]["details"]["severity"] == "info"
    assert "custom AMI" in f[0]["summary"]


def test_node_uptime_alone_is_not_reported():
    """A node up for 200 days on a current AMI is fully patched."""
    dbg = make_debugger()
    dbg.safe_api_call.side_effect = _api(
        [
            {
                "nodegroupName": "web",
                "version": "1.33",
                "releaseVersion": "1.33.13-20260903",
                "amiType": "AL2023_x86_64_STANDARD",
            }
        ],
        "1.33.13-20260903",
    )
    dbg.analyze_node_ami_age()
    assert not [f for f in findings(dbg, "node_issues") if "days old" in f["summary"]]
