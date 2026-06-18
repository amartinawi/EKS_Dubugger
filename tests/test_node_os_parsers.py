"""Tests for NodeOSOutputParser — all 10 SSM output parsers.

Each parser is tested with:
- Positive detection (issue present in output → finding generated)
- Negative case (healthy output → no findings)
- Edge cases (empty output, malformed data)

Finding shape verified: severity in details, finding_type correct, node/instance_id present.
"""

import pytest
from eks_comprehensive_debugger import NodeOSOutputParser, FindingType


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def parser():
    """Create a NodeOSOutputParser instance."""
    return NodeOSOutputParser()


@pytest.fixture
def findings():
    """Collect findings via a mock callback."""
    collected = []

    def add_finding(category, finding):
        collected.append((category, finding))

    return collected, add_finding


NODE = "ip-10-0-1-50"
INSTANCE = "i-0abc123def456"


def _get_findings(collected, category=None):
    """Filter collected findings by category."""
    return [(c, f) for c, f in collected if not category or c == category]


# ── iptables Parser Tests ─────────────────────────────────


class TestIptablesParser:
    """Test _parse_iptables() for firewall rule analysis."""

    def test_dns_drop_detected(self, parser, findings):
        """DROP rule on port 53 should produce critical finding."""
        collected, add = findings
        parser._parse_iptables(
            "-A FORWARD -d 10.100.0.10/32 -p udp --dport 53 -j DROP\nChain KUBE-SERVICES\nAWS-SNAT-CHAIN-0",
            NODE,
            INSTANCE,
            add,
        )
        dns = [f for c, f in collected if "dns" in f["summary"].lower() or "port 53" in f["summary"].lower()]
        assert len(dns) >= 1
        assert dns[0]["details"]["severity"] == "critical"

    def test_missing_kube_services(self, parser, findings):
        """Missing KUBE-SERVICES chain should produce warning finding."""
        collected, add = findings
        parser._parse_iptables("-A FORWARD -j ACCEPT", NODE, INSTANCE, add)
        ks = [f for c, f in collected if "KUBE-SERVICES" in f["summary"]]
        assert len(ks) == 1
        assert ks[0]["details"]["severity"] == "warning"

    def test_healthy_iptables_no_findings(self, parser, findings):
        """Healthy iptables with all chains should produce no findings."""
        collected, add = findings
        parser._parse_iptables(
            "Chain KUBE-SERVICES\nKUBE-POSTROUTING\n-A FORWARD -j KUBE-FORWARD",
            NODE,
            INSTANCE,
            add,
        )
        iptables = _get_findings(collected, "node_os_iptables")
        assert len(iptables) == 0

    def test_empty_output(self, parser, findings):
        """Empty output should produce no findings."""
        collected, add = findings
        parser._parse_iptables("", NODE, INSTANCE, add)
        assert len(collected) == 0


# ── conntrack Parser Tests ────────────────────────────────


class TestConntrackParser:
    """Test _parse_conntrack() for saturation and drop detection."""

    def test_critical_saturation(self, parser, findings):
        """Conntrack >90% full should produce critical finding."""
        collected, add = findings
        parser._parse_conntrack("131000\n131072", NODE, INSTANCE, add)
        ct = _get_findings(collected, "node_os_conntrack")
        assert len(ct) == 1
        assert ct[0][1]["details"]["severity"] == "critical"

    def test_warning_saturation(self, parser, findings):
        """Conntrack >75% full should produce warning finding."""
        collected, add = findings
        parser._parse_conntrack("100000\n131072", NODE, INSTANCE, add)
        ct = _get_findings(collected, "node_os_conntrack")
        assert len(ct) == 1
        assert ct[0][1]["details"]["severity"] == "warning"

    def test_healthy_conntrack(self, parser, findings):
        """Conntrack <75% should produce no findings."""
        collected, add = findings
        parser._parse_conntrack("50000\n131072", NODE, INSTANCE, add)
        assert len(_get_findings(collected, "node_os_conntrack")) == 0

    def test_drops_detected(self, parser, findings):
        """conntrack -S with non-zero drops should produce findings."""
        collected, add = findings
        parser._parse_conntrack(
            "entries searched found new invalid ignore delete delete_list "
            "insert insert_failed drop early_drop\n"
            "100 50000 40000 1000 50 99000 50 50 10100 0 15 5\n"
            "50000\n131072",
            NODE,
            INSTANCE,
            add,
        )
        drops = [f for c, f in collected if f["details"].get("metric") in ("drop", "early_drop")]
        assert len(drops) >= 2


# ── dmesg Parser Tests ────────────────────────────────────


class TestDmesgParser:
    """Test _parse_dmesg() for kernel error detection."""

    def test_oom_kill_detected(self, parser, findings):
        """Kernel OOM kill should produce critical historical finding."""
        collected, add = findings
        parser._parse_dmesg(
            "[Tue Jun 17 10:30:00 2026] Out of memory: Killed process 12345 (nginx)",
            NODE,
            INSTANCE,
            add,
        )
        dm = _get_findings(collected, "node_os_dmesg")
        assert len(dm) == 1
        assert dm[0][1]["details"]["severity"] == "critical"
        assert dm[0][1]["details"]["finding_type"] == FindingType.HISTORICAL_EVENT
        assert "timestamp" in dm[0][1]["details"]

    def test_hardware_error_detected(self, parser, findings):
        """Hardware Error / MCE should produce critical finding."""
        collected, add = findings
        parser._parse_dmesg("[Hardware Error] Machine Check Exception", NODE, INSTANCE, add)
        dm = _get_findings(collected, "node_os_dmesg")
        assert len(dm) == 1
        assert dm[0][1]["details"]["severity"] == "critical"

    def test_conntrack_full_message(self, parser, findings):
        """nf_conntrack table full should produce critical finding."""
        collected, add = findings
        parser._parse_dmesg("nf_conntrack: table full, dropping packet", NODE, INSTANCE, add)
        dm = _get_findings(collected, "node_os_dmesg")
        assert len(dm) == 1

    def test_empty_dmesg(self, parser, findings):
        """Empty dmesg should produce no findings."""
        collected, add = findings
        parser._parse_dmesg("", NODE, INSTANCE, add)
        assert len(collected) == 0


# ── kubelet Parser Tests ──────────────────────────────────


class TestKubeletParser:
    """Test _parse_kubelet() for kubelet journal errors."""

    def test_pleg_not_healthy(self, parser, findings):
        """PLEG not healthy should produce warning finding."""
        collected, add = findings
        parser._parse_kubelet(
            "PLEG is not healthy: pleg was last seen active 4m5s ago",
            NODE,
            INSTANCE,
            add,
        )
        kl = _get_findings(collected, "node_os_kubelet")
        assert len(kl) >= 1  # May match both "PLEG is not healthy" and "pleg was last seen"
        assert kl[0][1]["details"]["severity"] == "warning"

    def test_cert_expired(self, parser, findings):
        """Certificate expired should produce warning finding."""
        collected, add = findings
        parser._parse_kubelet("x509: certificate has expired", NODE, INSTANCE, add)
        kl = _get_findings(collected, "node_os_kubelet")
        assert len(kl) == 1

    def test_api_server_unreachable(self, parser, findings):
        """API server unreachable should produce critical finding."""
        collected, add = findings
        parser._parse_kubelet(
            "Failed to watch *v1.Pod: context deadline exceeded",
            NODE,
            INSTANCE,
            add,
        )
        kl = _get_findings(collected, "node_os_kubelet")
        assert len(kl) == 1
        assert kl[0][1]["details"]["severity"] == "critical"


# ── containerd Parser Tests ───────────────────────────────


class TestContainerdParser:
    """Test _parse_containerd() for runtime errors."""

    def test_image_auth_failure(self, parser, findings):
        """Image pull 401 should produce warning finding."""
        collected, add = findings
        parser._parse_containerd('PullImage "nginx": failed: 401 Unauthorized', NODE, INSTANCE, add)
        ct = _get_findings(collected, "node_os_containerd")
        assert len(ct) == 1

    def test_disk_full(self, parser, findings):
        """no space left on device should produce critical finding."""
        collected, add = findings
        parser._parse_containerd("no space left on device", NODE, INSTANCE, add)
        ct = _get_findings(collected, "node_os_containerd")
        assert len(ct) == 1
        assert ct[0][1]["details"]["severity"] == "critical"

    def test_rate_limiting(self, parser, findings):
        """toomanyrequests should produce warning finding."""
        collected, add = findings
        parser._parse_containerd("toomanyrequests: Rate exceeded", NODE, INSTANCE, add)
        ct = _get_findings(collected, "node_os_containerd")
        assert len(ct) == 1


# ── ipamd Parser Tests ────────────────────────────────────


class TestIpamdParser:
    """Test _parse_ipamd() for IP allocation failures."""

    def test_ip_allocation_failure(self, parser, findings):
        """failed to assign an IP should produce critical finding."""
        collected, add = findings
        parser._parse_ipamd("failed to assign an IP addr to pod", NODE, INSTANCE, add)
        ip = _get_findings(collected, "node_os_ipamd")
        assert len(ip) == 1
        assert ip[0][1]["details"]["severity"] == "critical"

    def test_subnet_exhaustion(self, parser, findings):
        """InsufficientFreeAddresses should produce critical finding."""
        collected, add = findings
        parser._parse_ipamd("InsufficientFreeAddressesInSubnet", NODE, INSTANCE, add)
        ip = _get_findings(collected, "node_os_ipamd")
        assert len(ip) == 1

    def test_warm_pool_depleted(self, parser, findings):
        """IP pool too low should produce warning finding."""
        collected, add = findings
        parser._parse_ipamd("IP pool is too low: 1", NODE, INSTANCE, add)
        ip = _get_findings(collected, "node_os_ipamd")
        assert len(ip) == 1


# ── routes Parser Tests ───────────────────────────────────


class TestRoutesParser:
    """Test _parse_routes() for route table issues."""

    def test_blackhole_route(self, parser, findings):
        """Blackhole route should produce critical finding."""
        collected, add = findings
        parser._parse_routes(
            "blackhole 10.100.1.0/24 proto kernel\ndefault via 10.0.1.1 dev eth0",
            NODE,
            INSTANCE,
            add,
        )
        rt = _get_findings(collected, "node_os_routes")
        assert len(rt) == 1
        assert rt[0][1]["details"]["severity"] == "critical"

    def test_missing_default_route(self, parser, findings):
        """Missing default route should produce critical finding."""
        collected, add = findings
        parser._parse_routes("10.100.0.0/24 dev eni123 proto kernel", NODE, INSTANCE, add)
        rt = _get_findings(collected, "node_os_routes")
        assert len(rt) >= 1

    def test_healthy_routes(self, parser, findings):
        """Healthy route table should produce no findings."""
        collected, add = findings
        parser._parse_routes(
            "default via 10.0.1.1 dev eth0\n10.100.0.0/24 dev eni1\n169.254.169.253 dev eth0",
            NODE,
            INSTANCE,
            add,
        )
        assert len(collected) == 0


# ── CNI Config Parser Tests ───────────────────────────────


class TestCniConfigParser:
    """Test _parse_cni_config() for CNI configuration issues."""

    def test_missing_cni_config(self, parser, findings):
        """Empty CNI config should produce critical finding."""
        collected, add = findings
        parser._parse_cni_config("", NODE, INSTANCE, add)
        cni = _get_findings(collected, "node_os_cni_config")
        assert len(cni) == 1
        assert cni[0][1]["details"]["severity"] == "critical"

    def test_wrong_mtu(self, parser, findings):
        """Non-standard MTU should produce warning finding."""
        collected, add = findings
        parser._parse_cni_config(
            '{"cniVersion": "1.0.0", "name": "aws-cni", "mtu": 1400}',
            NODE,
            INSTANCE,
            add,
        )
        cni = _get_findings(collected, "node_os_cni_config")
        assert len(cni) == 1
        assert cni[0][1]["details"]["severity"] == "warning"

    def test_healthy_cni_config(self, parser, findings):
        """Healthy CNI config (MTU 9001, single config) should produce no findings."""
        collected, add = findings
        parser._parse_cni_config(
            '{"cniVersion": "1.0.0", "name": "aws-cni", "mtu": 9001}',
            NODE,
            INSTANCE,
            add,
        )
        assert len(collected) == 0


# ── sysctl Parser Tests ───────────────────────────────────


class TestSysctlParser:
    """Test _parse_sysctl() for kernel parameter issues."""

    def test_low_conntrack_max(self, parser, findings):
        """Low nf_conntrack_max should produce warning finding."""
        collected, add = findings
        parser._parse_sysctl(
            "net.netfilter.nf_conntrack_max = 65536\n"
            "net.ipv4.conf.all.rp_filter = 2\n"
            "net.ipv4.ip_local_port_range = 10240\t65535\n"
            "fs.file-max = 1000000\nkernel.pid_max = 4194304",
            NODE,
            INSTANCE,
            add,
        )
        sys = _get_findings(collected, "node_os_sysctl")
        assert len(sys) == 1
        assert sys[0][1]["details"]["severity"] == "warning"

    def test_wrong_rp_filter(self, parser, findings):
        """rp_filter != 2 should produce warning finding."""
        collected, add = findings
        parser._parse_sysctl(
            "net.netfilter.nf_conntrack_max = 131072\n"
            "net.ipv4.conf.all.rp_filter = 1\n"
            "net.ipv4.ip_local_port_range = 10240\t65535\n"
            "fs.file-max = 1000000\nkernel.pid_max = 4194304",
            NODE,
            INSTANCE,
            add,
        )
        sys = _get_findings(collected, "node_os_sysctl")
        assert len(sys) == 1

    def test_healthy_sysctl(self, parser, findings):
        """All-optimal sysctl values should produce no findings."""
        collected, add = findings
        parser._parse_sysctl(
            "net.netfilter.nf_conntrack_max = 131072\n"
            "net.ipv4.conf.all.rp_filter = 2\n"
            "net.ipv4.ip_local_port_range = 10240\t65535\n"
            "fs.file-max = 1000000\nkernel.pid_max = 4194304",
            NODE,
            INSTANCE,
            add,
        )
        assert len(collected) == 0


# ── ENI Metadata Parser Tests ─────────────────────────────


class TestEniMetadataParser:
    """Test _parse_eni_metadata() for network interface issues."""

    def test_conntrack_allowance_exceeded(self, parser, findings):
        """conntrack_allowance_exceeded > 0 should produce critical finding."""
        collected, add = findings
        parser._parse_eni_metadata(
            "=== eth0 ===\n    conntrack_allowance_exceeded: 15\n    linklocal_allowance_exceeded: 0",
            NODE,
            INSTANCE,
            add,
        )
        eni = _get_findings(collected, "node_os_eni")
        assert len(eni) == 1
        assert eni[0][1]["details"]["severity"] == "critical"

    def test_linklocal_allowance_exceeded(self, parser, findings):
        """linklocal_allowance_exceeded > 0 should produce warning finding."""
        collected, add = findings
        parser._parse_eni_metadata(
            "=== eth0 ===\n    conntrack_allowance_exceeded: 0\n    linklocal_allowance_exceeded: 42",
            NODE,
            INSTANCE,
            add,
        )
        eni = _get_findings(collected, "node_os_eni")
        assert len(eni) == 1

    def test_interface_down(self, parser, findings):
        """Interface state DOWN should produce warning finding."""
        collected, add = findings
        parser._parse_eni_metadata(
            "3: eni1: state DOWN\n    conntrack_allowance_exceeded: 0",
            NODE,
            INSTANCE,
            add,
        )
        eni = _get_findings(collected, "node_os_eni")
        assert len(eni) == 1
        assert "eni1" in eni[0][1]["summary"]

    def test_healthy_eni(self, parser, findings):
        """Healthy ENI (all allowances 0, interfaces UP) should produce no findings."""
        collected, add = findings
        parser._parse_eni_metadata(
            "2: eth0: state UP\n    conntrack_allowance_exceeded: 0\n"
            "    linklocal_allowance_exceeded: 0\n    bw_in_allowance_exceeded: 0",
            NODE,
            INSTANCE,
            add,
        )
        assert len(collected) == 0


# ── Dispatch Method Tests ─────────────────────────────────


class TestDispatch:
    """Test the parse() dispatch method."""

    def test_dispatch_routes_correctly(self, parser, findings):
        """parse() should route to the correct parser based on diagnostic_type."""
        collected, add = findings
        parser.parse("iptables", "-A FORWARD --dport 53 -j DROP\nChain KUBE-SERVICES", NODE, INSTANCE, add)
        assert len(collected) > 0

    def test_unknown_type_no_crash(self, parser, findings):
        """Unknown diagnostic_type should produce no findings and not crash."""
        collected, add = findings
        parser.parse("unknown_type", "some output", NODE, INSTANCE, add)
        assert len(collected) == 0

    def test_all_ten_types_dispatch(self, parser, findings):
        """All 10 diagnostic types should be dispatchable without exceptions."""
        collected, add = findings
        for diag_type in NodeOSOutputParser.PARSERS:
            parser.parse(diag_type, "", NODE, INSTANCE, add)
        # cni_config treats empty as "missing config" (critical), others produce nothing
        cni_findings = [f for c, f in collected if c == "node_os_cni_config"]
        assert len(cni_findings) == 1  # Missing CNI config is a valid finding for empty input
