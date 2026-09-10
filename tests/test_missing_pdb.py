"""Multi-replica workloads without a PodDisruptionBudget."""

import json

from tests.helpers_debugger import findings, make_debugger


def _deploy(name, ns, replicas, labels):
    return {
        "metadata": {"name": name, "namespace": ns},
        "spec": {"replicas": replicas, "template": {"metadata": {"labels": labels}}},
    }


def _pdb_findings(dbg):
    return [f for f in findings(dbg, "scheduling_failures") if "PodDisruptionBudget" in f["summary"]]


def test_uncovered_multi_replica_deployment_flagged():
    deploys = {
        "items": [
            _deploy("magento", "default", 25, {"app": "magento"}),
            _deploy("single", "default", 1, {"app": "single"}),
            _deploy("coredns", "kube-system", 2, {"k8s-app": "kube-dns"}),
        ]
    }
    pdbs = {
        "items": [
            {
                "metadata": {"name": "coredns", "namespace": "kube-system"},
                "spec": {"selector": {"matchLabels": {"k8s-app": "kube-dns"}}},
            }
        ]
    }
    dbg = make_debugger(
        {
            "get deploy": json.dumps(deploys),
            "get statefulset": json.dumps({"items": []}),
            "get pdb": json.dumps(pdbs),
        }
    )
    dbg.analyze_missing_pdbs()
    f = _pdb_findings(dbg)
    assert [x["details"]["workload"] for x in f] == ["magento"]
    assert f[0]["details"]["severity"] == "warning"
    assert f[0]["details"]["replicas"] == 25


def test_covered_workload_not_flagged():
    deploys = {"items": [_deploy("web", "app", 3, {"app": "web", "tier": "fe"})]}
    pdbs = {
        "items": [
            {"metadata": {"name": "web", "namespace": "app"}, "spec": {"selector": {"matchLabels": {"app": "web"}}}}
        ]
    }
    dbg = make_debugger(
        {
            "get deploy": json.dumps(deploys),
            "get statefulset": json.dumps({"items": []}),
            "get pdb": json.dumps(pdbs),
        }
    )
    dbg.analyze_missing_pdbs()
    assert _pdb_findings(dbg) == []


def test_pdb_in_another_namespace_does_not_cover():
    deploys = {"items": [_deploy("web", "app", 3, {"app": "web"})]}
    pdbs = {
        "items": [
            {"metadata": {"name": "web", "namespace": "other"}, "spec": {"selector": {"matchLabels": {"app": "web"}}}}
        ]
    }
    dbg = make_debugger(
        {
            "get deploy": json.dumps(deploys),
            "get statefulset": json.dumps({"items": []}),
            "get pdb": json.dumps(pdbs),
        }
    )
    dbg.analyze_missing_pdbs()
    assert len(_pdb_findings(dbg)) == 1


def test_statefulsets_are_checked_too():
    sts = {
        "items": [
            {
                "metadata": {"name": "db", "namespace": "data"},
                "spec": {"replicas": 3, "template": {"metadata": {"labels": {"app": "db"}}}},
            }
        ]
    }
    dbg = make_debugger(
        {
            "get deploy": json.dumps({"items": []}),
            "get statefulset": json.dumps(sts),
            "get pdb": json.dumps({"items": []}),
        }
    )
    dbg.analyze_missing_pdbs()
    f = _pdb_findings(dbg)
    assert len(f) == 1
    assert f[0]["details"]["kind"] == "StatefulSet"
