"""Custom controller detection must not match every labelled pod."""

from tests.helpers_debugger import make_debugger


def _collect_label_selectors(dbg):
    calls = []

    def fake(cmd, *args, **kwargs):
        calls.append(cmd)
        return '{"items": []}'

    dbg.safe_kubectl_call.side_effect = fake
    dbg._get_cached_kubectl.side_effect = fake
    dbg.analyze_custom_controllers()
    selectors = []
    for cmd in calls:
        if " -l " in cmd:
            selectors.append(cmd.split(" -l ", 1)[1].split(" ")[0])
    return selectors


def test_label_existence_selector_removed():
    """A bare 'app.kubernetes.io/name' selector matches almost every pod in a cluster."""
    dbg = make_debugger()
    selectors = _collect_label_selectors(dbg)
    assert selectors, "expected at least one label selector"
    for sel in selectors:
        assert "=" in sel, f"label-existence selector still used: {sel}"


def test_component_selectors_used():
    dbg = make_debugger()
    selectors = _collect_label_selectors(dbg)
    assert "app.kubernetes.io/component=controller" in selectors
    assert "control-plane=controller-manager" in selectors
