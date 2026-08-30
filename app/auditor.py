from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .models import RouteSpec
from .planner import PlanStep

AuditStatus = Literal["healthy", "drifted", "broken", "incomplete", "unmanaged", "conflict"]

@dataclass(frozen=True)
class Finding:
    provider: str
    status: AuditStatus
    summary: str
    expected: Any = None
    observed: Any = None
    correction: PlanStep | None = None

@dataclass(frozen=True)
class AuditReport:
    hostname: str
    status: AuditStatus
    findings: tuple[Finding, ...]
    corrections: tuple[PlanStep, ...] = field(default_factory=tuple)
    def to_dict(self) -> dict[str, Any]: return asdict(self)

_SEVERITY = {"healthy": 0, "unmanaged": 1, "drifted": 2, "incomplete": 3, "broken": 4, "conflict": 5}

def _finding(provider: str, status: AuditStatus, summary: str, expected: Any, observed: Any, action: str) -> Finding:
    correction = None if status == "healthy" else PlanStep(provider, action, summary, "elevated" if status == "conflict" else "normal")
    return Finding(provider, status, summary, expected, observed, correction)

def audit_route(route: RouteSpec, observed: dict[str, Any]) -> AuditReport:
    """Compare desired state with normalized, secret-free observations."""
    findings: list[Finding] = []
    upstream=observed.get("upstream")
    if upstream is not None:
        if not upstream.get("dns"): findings.append(_finding("upstream","broken","Upstream host does not resolve safely",True,upstream,"diagnose_upstream"))
        elif not upstream.get("tcp"): findings.append(_finding("upstream","broken","Upstream TCP connection failed",True,upstream,"diagnose_upstream"))
        elif route.upstream.scheme=="https" and upstream.get("tls") is not True: findings.append(_finding("upstream","broken","Upstream TLS verification failed",True,upstream,"correct_tls"))
        elif not upstream.get("http"): findings.append(_finding("upstream","broken","Upstream HTTP health check failed",True,upstream,"diagnose_upstream"))
        else: findings.append(_finding("upstream","healthy","Upstream DNS, TCP, TLS, and HTTP checks pass",True,True,""))
    if route.source_container_id or route.source_container_name:
        source=observed.get("unraid"); expected={"container":route.source_container_name or route.source_container_id,"port":route.source_port}
        if source is None: findings.append(_finding("unraid","incomplete","Source container was not inspected",expected,None,"inspect_container"))
        elif not source.get("exists"): findings.append(_finding("unraid","broken","Source container no longer exists",expected,source,"select_source"))
        elif not source.get("running"): findings.append(_finding("unraid","broken","Source container is not running",expected,source.get("state"),"diagnose_container"))
        elif route.source_port and not source.get("port_available"): findings.append(_finding("unraid","drifted","Selected container port is no longer published",route.source_port,source.get("services"),"select_source_port"))
        else: findings.append(_finding("unraid","healthy","Source container and selected port are available",expected,expected,""))
    if route.mode in {"lan", "lan_remote"}:
        dns = observed.get("technitium")
        if dns is None:
            findings.append(_finding("technitium", "incomplete", "DNS record is missing", route.lan_address, None, "create_dns"))
        elif dns.get("conflict"):
            findings.append(_finding("technitium", "conflict", "Multiple conflicting DNS answers exist", route.lan_address, dns.get("addresses"), "resolve_dns_conflict"))
        elif route.lan_address not in dns.get("addresses", []):
            findings.append(_finding("technitium", "drifted", "DNS address does not match desired state", route.lan_address, dns.get("addresses", []), "replace_dns"))
        else:
            findings.append(_finding("technitium", "healthy", "DNS address matches", route.lan_address, route.lan_address, ""))
        caddy = observed.get("caddy"); expected_upstream = route.upstream.url
        if caddy is None:
            findings.append(_finding("caddy", "incomplete", "LAN proxy route is missing", expected_upstream, None, "create_proxy"))
        elif caddy.get("duplicate"):
            findings.append(_finding("caddy", "conflict", "Duplicate LAN proxy routes claim this hostname", expected_upstream, caddy.get("upstreams"), "resolve_proxy_conflict"))
        elif caddy.get("upstream") != expected_upstream:
            findings.append(_finding("caddy", "drifted", "LAN proxy upstream does not match", expected_upstream, caddy.get("upstream"), "replace_proxy"))
        elif caddy.get("healthy") is False:
            findings.append(_finding("caddy", "broken", "LAN proxy exists but its health check fails", True, False, "diagnose_proxy"))
        else:
            findings.append(_finding("caddy", "healthy", "LAN proxy route matches", expected_upstream, expected_upstream, ""))
    if route.mode in {"remote", "lan_remote"}:
        pangolin = observed.get("pangolin")
        expected = {"site_id": route.pangolin_site_id, "upstream": route.upstream.url, "authentication": route.require_authentication}
        if pangolin is None:
            findings.append(_finding("pangolin", "incomplete", "Public resource is missing", expected, None, "create_resource"))
        elif pangolin.get("error"):
            findings.append(_finding("pangolin", "broken", "Pangolin could not be inspected", "reachable", pangolin.get("error"), "diagnose_resource"))
        elif pangolin.get("duplicate"):
            findings.append(_finding("pangolin", "conflict", "Duplicate Pangolin resources claim this hostname", expected, pangolin, "resolve_resource_conflict"))
        else:
            actual = {key: pangolin.get(key) for key in expected}
            if actual != expected:
                findings.append(_finding("pangolin", "drifted", "Pangolin resource or target differs from desired state", expected, actual, "update_resource"))
            elif pangolin.get("healthy") is False:
                findings.append(_finding("pangolin", "broken", "Pangolin target exists but its health check fails", True, False, "diagnose_resource"))
            else:
                findings.append(_finding("pangolin", "healthy", "Pangolin resource and target match", expected, actual, ""))
    corrections = tuple(f.correction for f in findings if f.correction is not None)
    status = max((f.status for f in findings), key=lambda value: _SEVERITY[value], default="healthy")
    return AuditReport(route.hostname, status, tuple(findings), corrections)

def unmanaged_report(hostname: str, providers: list[str]) -> AuditReport:
    findings = tuple(Finding(p, "unmanaged", f"Existing {p} resource is not managed", None, hostname, PlanStep(p, "adopt", f"Adopt existing {p} resource for {hostname}")) for p in providers)
    return AuditReport(hostname, "unmanaged", findings, tuple(f.correction for f in findings if f.correction))
