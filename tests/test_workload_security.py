"""Workload security posture: own category, owner-level dedupe, warning severity."""

import json

from tests.helpers_debugger import findings, make_debugger


def _agent_pod(i):
    return {
        "metadata": {
            "name": f"agent-{i}",
            "namespace": "monitoring",
            "ownerReferences": [{"kind": "DaemonSet", "name": "agent"}],
        },
        "spec": {
            "containers": [{"name": "agent", "securityContext": {"privileged": True}}],
            "volumes": [
                {"name": "root", "hostPath": {"path": "/"}},
                {"name": "sock", "hostPath": {"path": "/var/run/docker.sock"}},
            ],
        },
    }


def test_posture_findings_are_grouped_by_owner():
    pods = [_agent_pod(i) for i in range(13)]
    dbg = make_debugger({"get pods": json.dumps({"items": pods})})
    dbg.analyze_workload_security_posture()
    ws = findings(dbg, "workload_security")
    assert findings(dbg, "rbac_issues") == []
    assert len(ws) == 2  # one privileged, one hostPath, not 13 x 3
    priv = next(f for f in ws if "privileged" in f["summary"].lower())
    assert "DaemonSet monitoring/agent" in priv["summary"]
    assert priv["details"]["pod_count"] == 13
    assert priv["details"]["severity"] == "warning"
    hp = next(f for f in ws if "host path" in f["summary"].lower())
    assert set(hp["details"]["host_paths"]) == {"/", "/var/run/docker.sock"}


def test_replicaset_owner_maps_to_deployment():
    dbg = make_debugger()
    pod = {
        "metadata": {
            "name": "web-6d49894b79-d5jrz",
            "namespace": "ci",
            "ownerReferences": [{"kind": "ReplicaSet", "name": "web-6d49894b79"}],
        }
    }
    assert dbg._workload_owner(pod) == ("Deployment", "web", "ci")


def test_pod_without_owner_reports_itself():
    dbg = make_debugger()
    pod = {"metadata": {"name": "loose", "namespace": "ns"}}
    assert dbg._workload_owner(pod) == ("Pod", "loose", "ns")


def test_system_namespaces_excluded():
    pods = [
        {
            "metadata": {"name": "aws-node-1", "namespace": "kube-system"},
            "spec": {"containers": [{"name": "c", "securityContext": {"privileged": True}}], "volumes": []},
        }
    ]
    dbg = make_debugger({"get pods": json.dumps({"items": pods})})
    dbg.analyze_workload_security_posture()
    assert findings(dbg, "workload_security") == []


def test_sys_admin_capability_reported():
    pods = [
        {
            "metadata": {"name": "builder", "namespace": "ci", "ownerReferences": [{"kind": "Deployment", "name": "b"}]},
            "spec": {
                "containers": [{"name": "c", "securityContext": {"capabilities": {"add": ["SYS_ADMIN"]}}}],
                "volumes": [],
            },
        }
    ]
    dbg = make_debugger({"get pods": json.dumps({"items": pods})})
    dbg.analyze_workload_security_posture()
    ws = findings(dbg, "workload_security")
    assert len(ws) == 1
    assert "SYS_ADMIN" in ws[0]["summary"]
