from __future__ import annotations

import argparse
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
from threading import Thread
import time
from typing import Any

from . import __version__
from .auditor import audit_route
from .integrations import IntegrationTester, PROVIDERS
from .models import RouteSpec, ValidationError
from .planner import PlanStore, build_initial_plan
from .storage import JsonStore
from .secrets_store import SecretsStore
from .unraid import UnraidClient, discover_newt, discover_reverse_proxies
from .providers.http import JsonHttpClient
from .providers.pangolin import PangolinClient
from .dns_discovery import DnsDiscovery
from .providers.caddy import observe_config
from .health import probe_upstream
from .route_apply import RouteApplyService
from .inventory import caddy_inventory, correlate_routes, pangolin_resources, resolution_status
from .certificates import certificate_settings
from .certificate_sync import CertificateInstaller, CertificatePlanStore, CertificateSyncClient, installed_certificate, renewal_comparison
from .providers.npm import NginxProxyManagerClient


MAX_BODY = 128 * 1024


class Application:
    def __init__(self, config_dir: Path, static_dir: Path):
        self.config_dir = config_dir
        self.store = JsonStore(config_dir)
        external_key = os.environ.get("WISE_MASTER_KEY_FILE")
        self.secrets = SecretsStore(config_dir, Path(external_key) if external_key else None)
        self.static_dir = static_dir
        self.plans = PlanStore()
        self.certificate_plans = CertificatePlanStore()
        self.token_path = config_dir / "api-token"
        if not self.token_path.exists():
            self.token_path.write_text(secrets.token_urlsafe(40) + "\n", encoding="utf-8")
            self.token_path.chmod(0o600)
        self.api_token = self.token_path.read_text(encoding="utf-8").strip()
        self.provider_mutations = os.environ.get("WISE_ENABLE_PROVIDER_MUTATIONS") == "1"
        self.edition = os.environ.get("WISE_EDITION", "full").strip().lower()
        if self.edition not in {"full", "lite"}:
            self.edition = "full"

    def check_certificate_renewal(self, *, automatic: bool = False) -> dict[str, Any]:
        settings=self.secrets.get("certificate-primary")
        if settings is None or settings.get("mode")!="pangolin_newt_sync": raise ValidationError("Pangolin certificate synchronization is not configured")
        bundle=CertificateSyncClient(str(settings["endpoint"]),str(settings["credential"])).fetch(str(settings["expected_name"]))
        comparison=renewal_comparison(installed_certificate(self.config_dir/"tls"/"tls.crt"),bundle)
        comparison.update({"automatic_renewal":bool(settings.get("auto_renew")),"automatic_renewal_active":bool(settings.get("auto_renew") and settings.get("initial_sync_approved"))})
        if automatic and comparison["update_available"] and comparison["automatic_renewal_active"] and self.provider_mutations:
            result=CertificateInstaller(self.config_dir/"tls",self.config_dir/"caddy"/"config.json").install(bundle)
            comparison.update({"status":"installed","installation":result,"update_available":False})
            self.store.audit({"event":"certificate.renewal_installed","fingerprint_sha256":bundle.fingerprint,"not_after":bundle.not_after})
        else:
            self.store.audit({"event":"certificate.renewal_checked","status":comparison["status"],"candidate_fingerprint_sha256":bundle.fingerprint,"automatic":automatic})
        return comparison

    def audit_managed_route(self, stored: dict[str, Any], observed: dict[str, Any] | None = None):
        """Collect live, secret-free observations and compare them to desired state."""
        route = RouteSpec.from_dict(stored)
        observations = dict(observed or {})
        if "upstream" not in observations:
            observations["upstream"] = probe_upstream(route)
        if route.dns_integration_id and "technitium" not in observations:
            integration = self.secrets.get(route.dns_integration_id)
            if integration:
                dns_observation = DnsDiscovery(integration).observe(route.hostname)
                if dns_observation is not None:
                    observations["technitium"] = dns_observation
        caddy_path = self.config_dir / "caddy" / "config.json"
        if "caddy" not in observations and caddy_path.exists():
            caddy_observation = observe_config(
                json.loads(caddy_path.read_text(encoding="utf-8")), route.hostname
            )
            if caddy_observation is not None:
                observations["caddy"] = caddy_observation
        if route.mode in {"remote", "lan_remote"} and "pangolin" not in observations:
            integration = self.secrets.get("pangolin-primary")
            if integration:
                try:
                    observations["pangolin"] = PangolinClient(
                        JsonHttpClient(str(integration["base_url"]), str(integration["credential"])),
                        str(integration["organization_id"]),
                    ).observe_resource(route.hostname, route.pangolin_site_id)
                except RuntimeError as exc:
                    observations["pangolin"] = {"error": str(exc)}
        if (route.source_container_id or route.source_container_name) and "unraid" not in observations:
            integration = self.secrets.get("unraid-primary")
            if integration:
                try:
                    observations["unraid"] = UnraidClient(
                        str(integration["base_url"]), str(integration["credential"])
                    ).observe_source(route.source_container_id, route.source_container_name, route.source_port)
                except RuntimeError as exc:
                    observations["unraid"] = {"exists": True, "running": False, "error": str(exc)}
        return audit_route(route, observations)

    def handler(self):
        application = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "WiseRouteManager/" + __version__

            def log_message(self, format: str, *args: Any) -> None:
                # The default access log is safe because secrets are header-only.
                super().log_message(format, *args)

            def _json(self, status: int, value: Any) -> None:
                payload = json.dumps(value, separators=(",", ":")).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(payload)

            def _body(self) -> dict[str, Any]:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise ValidationError("invalid Content-Length") from None
                if length < 1 or length > MAX_BODY:
                    raise ValidationError("request body is empty or too large")
                try:
                    value = json.loads(self.rfile.read(length))
                except json.JSONDecodeError:
                    raise ValidationError("request body is not valid JSON") from None
                if not isinstance(value, dict):
                    raise ValidationError("request body must be a JSON object")
                return value

            def _authorized(self) -> bool:
                header = self.headers.get("Authorization", "")
                supplied = header[7:] if header.startswith("Bearer ") else ""
                return bool(supplied) and secrets.compare_digest(supplied, application.api_token)

            def _require_auth(self) -> bool:
                if self._authorized():
                    return True
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication required"})
                return False

            def do_GET(self) -> None:
                if self.path == "/healthz":
                    self._json(HTTPStatus.OK, {"status": "ok", "version": __version__})
                    return
                if self.path == "/api/v1/routes":
                    if self._require_auth():
                        self._json(HTTPStatus.OK, {"routes": application.store.load_routes()})
                    return
                if self.path == "/api/v1/status":
                    if self._require_auth():
                        self._json(HTTPStatus.OK, {
                            "edition": application.edition,
                            "provider_mutations": application.provider_mutations,
                            "version": __version__,
                            "certificate": application.secrets.public(application.secrets.get("certificate-primary") or {"mode":"not_configured"}),
                        })
                    return
                if self.path == "/api/v1/integrations/providers":
                    if self._require_auth(): self._json(HTTPStatus.OK, {"providers": PROVIDERS})
                    return
                if self.path == "/api/v1/integrations":
                    if self._require_auth(): self._json(HTTPStatus.OK, {"integrations": application.secrets.list_public()})
                    return
                if self.path in {"/", "/index.html"}:
                    self._static("lite.html" if application.edition == "lite" else "index.html", "text/html; charset=utf-8")
                    return
                if self.path == "/app.js":
                    self._static("lite.js" if application.edition == "lite" else "app.js", "text/javascript; charset=utf-8")
                    return
                if self.path == "/style.css":
                    self._static("style.css", "text/css; charset=utf-8")
                    return
                if self.path == "/audit.css":
                    self._static("audit.css", "text/css; charset=utf-8")
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

            def _static(self, filename: str, content_type: str) -> None:
                try:
                    payload = (application.static_dir / filename).read_bytes()
                except FileNotFoundError:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "asset not found"})
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'self'")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:
                if not self._require_auth():
                    return
                try:
                    body = self._body()
                    if self.path == "/api/v1/plans":
                        route = RouteSpec.from_dict(body)
                        plan = application.plans.create(route, build_initial_plan(route))
                        application.store.audit({
                            "event": "plan.created",
                            "plan_id": plan.plan_id,
                            "hostname": route.hostname,
                            "desired_hash": plan.desired_hash,
                        })
                        self._json(HTTPStatus.CREATED, plan.public_dict())
                        return
                    if self.path == "/api/v1/certificates/settings":
                        existing=application.secrets.get("certificate-primary") or {}
                        merged=dict(body)
                        if not merged.get("credential") and existing.get("credential"): merged["credential"]=existing["credential"]
                        settings=certificate_settings(merged)
                        if existing.get("initial_sync_approved") and existing.get("endpoint")==settings.get("endpoint") and existing.get("expected_name")==settings.get("expected_name"): settings["initial_sync_approved"]=True
                        saved=application.secrets.put(settings)
                        application.store.audit({"event":"certificate.strategy_configured","mode":saved["mode"],"transport":saved.get("transport")})
                        self._json(HTTPStatus.OK,{"certificate":saved}); return
                    if self.path == "/api/v1/certificates/preview-sync":
                        settings=application.secrets.get("certificate-primary")
                        if settings is None or settings.get("mode")!="pangolin_newt_sync": raise ValidationError("Pangolin certificate synchronization is not configured")
                        bundle=CertificateSyncClient(str(settings["endpoint"]),str(settings["credential"])).fetch(str(settings["expected_name"]))
                        plan=application.certificate_plans.create(bundle)
                        application.store.audit({"event":"certificate.sync_previewed","fingerprint_sha256":bundle.fingerprint,"not_after":bundle.not_after})
                        self._json(HTTPStatus.OK,{"plan_id":plan.plan_id,"confirmation_token":plan.confirmation_token,"expires_at":plan.expires_at.isoformat(),"certificate":bundle.public(),"steps":[{"provider":"pangolin_vps","action":"pull_certificate","summary":"Pull the selected wildcard certificate through Newt"},{"provider":"lan_proxy","action":"install_certificate","summary":"Atomically install, validate, and reload the LAN proxy"}]}); return
                    if self.path == "/api/v1/certificates/check-renewal":
                        self._json(HTTPStatus.OK,application.check_certificate_renewal()); return
                    if self.path == "/api/v1/certificates/apply-sync":
                        if not application.provider_mutations: raise ValidationError("provider mutations must be enabled before certificate installation")
                        bundle=application.certificate_plans.consume(str(body.get("plan_id","")),str(body.get("confirmation_token","")))
                        result=CertificateInstaller(application.config_dir/"tls",application.config_dir/"caddy"/"config.json").install(bundle)
                        settings=application.secrets.get("certificate-primary")
                        if settings:
                            settings["initial_sync_approved"]=True
                            application.secrets.put(settings)
                        application.store.audit({"event":"certificate.sync_installed","fingerprint_sha256":bundle.fingerprint,"not_after":bundle.not_after})
                        self._json(HTTPStatus.OK,result); return
                    if self.path == "/api/v1/audits":
                        hostname = str(body.get("hostname", "")).strip().lower()
                        stored = next((r for r in application.store.load_routes() if r.get("hostname") == hostname), None)
                        if stored is None:
                            raise ValidationError("managed route was not found")
                        observed = body.get("observed")
                        if observed is not None and not isinstance(observed, dict):
                            raise ValidationError("observed must be an object")
                        report = application.audit_managed_route(stored, observed)
                        application.store.audit({"event": "route.audited", "hostname": hostname, "status": report.status})
                        self._json(HTTPStatus.OK, report.to_dict())
                        return
                    if self.path == "/api/v1/audits/all":
                        reports = []
                        for stored in application.store.load_routes():
                            try:
                                report = application.audit_managed_route(stored)
                                reports.append(report.to_dict())
                                application.store.audit({"event": "route.audited", "hostname": report.hostname, "status": report.status})
                            except (ValidationError, ValueError, RuntimeError) as exc:
                                reports.append({
                                    "hostname": str(stored.get("hostname", "unknown")),
                                    "status": "broken",
                                    "findings": [{"provider": "manager", "status": "broken", "summary": str(exc)}],
                                    "corrections": [],
                                })
                        self._json(HTTPStatus.OK, {"reports": reports})
                        return
                    if self.path == "/api/v1/inventory":
                        inventory: dict[str, Any] = {
                            "topology": {
                                "remote_edge": "pangolin_vps",
                                "remote_proxy_ownership": "pangolin_managed",
                                "lan_proxy": "unraid_discovered",
                                "local_connector": "newt_on_unraid",
                            },
                            "pangolin": [], "technitium": [], "reverse_proxy": [], "ports": [], "errors": {},
                        }
                        pangolin_integration=application.secrets.get("pangolin-primary")
                        if pangolin_integration:
                            try:
                                client=PangolinClient(JsonHttpClient(str(pangolin_integration["base_url"]),str(pangolin_integration["credential"]),verify_tls=bool(pangolin_integration.get("verify_tls",True))),str(pangolin_integration["organization_id"]))
                                inventory["pangolin"]=pangolin_resources(client)
                            except RuntimeError as exc: inventory["errors"]["pangolin"]=str(exc)
                        else: inventory["errors"]["pangolin"]="Pangolin is not connected"
                        dns_integrations=[item for item in application.secrets.list_public() if item.get("provider")=="technitium"]
                        if dns_integrations:
                            dns_id=str(body.get("dns_integration_id") or dns_integrations[0]["id"])
                            dns_integration=application.secrets.get(dns_id)
                            if dns_integration:
                                try: inventory["technitium"]=DnsDiscovery(dns_integration).discover()["records"]
                                except RuntimeError as exc: inventory["errors"]["technitium"]=str(exc)
                        else: inventory["errors"]["technitium"]="Technitium is not connected"
                        lan_proxy=application.secrets.get("lan-proxy-primary")
                        if lan_proxy and lan_proxy.get("provider")=="nginx_proxy_manager":
                            try: inventory["reverse_proxy"]=NginxProxyManagerClient(str(lan_proxy["base_url"]),str(lan_proxy["credential"]),verify_tls=bool(lan_proxy.get("verify_tls",True))).inventory()
                            except RuntimeError as exc: inventory["errors"]["reverse_proxy"]=str(exc)
                        else:
                            caddy_path=application.config_dir/"caddy"/"config.json"
                            if caddy_path.exists():
                                try: inventory["reverse_proxy"]=caddy_inventory(json.loads(caddy_path.read_text(encoding="utf-8")))
                                except (OSError,json.JSONDecodeError) as exc: inventory["errors"]["reverse_proxy"]=str(exc)
                            else: inventory["errors"]["reverse_proxy"]="No connected LAN proxy or managed Caddy configuration was found"
                        unraid_integration=application.secrets.get("unraid-primary")
                        if unraid_integration:
                            try:
                                containers=UnraidClient(str(unraid_integration["base_url"]),str(unraid_integration["credential"])).containers()
                                inventory["ports"]=[container for container in containers if container.get("services")]
                            except RuntimeError as exc: inventory["errors"]["ports"]=str(exc)
                        else: inventory["errors"]["ports"]="Unraid is not connected"
                        hostnames={str(item.get("hostname")) for key in ("pangolin","technitium","reverse_proxy") for item in inventory[key] if item.get("hostname")}
                        inventory["resolution"]={hostname:resolution_status(hostname) for hostname in sorted(hostnames)}
                        inventory["route_map"]=correlate_routes(inventory,inventory["resolution"])
                        application.store.audit({"event":"inventory.scanned","pangolin":len(inventory["pangolin"]),"technitium":len(inventory["technitium"]),"reverse_proxy":len(inventory["reverse_proxy"]),"port_containers":len(inventory["ports"])})
                        self._json(HTTPStatus.OK,inventory); return
                    if self.path == "/api/v1/integrations/test":
                        result = IntegrationTester(verify_tls=bool(body.get("verify_tls", True))).test(
                            str(body.get("provider", "")), str(body.get("base_url", "")),
                            str(body.get("credential", "")), str(body.get("username", "")),
                        )
                        application.store.audit({"event": "integration.tested", "provider": result["provider"], "result": "connected"})
                        if body.get("save") is True:
                            integration_id = secrets.token_urlsafe(12)
                            saved = application.secrets.put({
                                "id": integration_id, "name": str(body.get("name") or result["provider"]).strip()[:80],
                                "provider": result["provider"], "base_url": str(body.get("base_url", "")).strip().rstrip("/"),
                                "username": str(body.get("username", "")), "credential": str(body.get("credential", "")),
                                "verify_tls": bool(body.get("verify_tls", True)), "status": "connected",
                            })
                            result["integration"] = saved
                            application.store.audit({"event": "integration.saved", "integration_id": integration_id, "provider": result["provider"]})
                        self._json(HTTPStatus.OK, result)
                        return
                    if self.path == "/api/v1/integrations/delete":
                        integration_id = str(body.get("id", ""))
                        if not application.secrets.delete(integration_id): raise ValidationError("integration was not found")
                        application.store.audit({"event": "integration.deleted", "integration_id": integration_id})
                        self._json(HTTPStatus.OK, {"status": "deleted"})
                        return
                    if self.path == "/api/v1/unraid/connect":
                        base_url=str(body.get("base_url","")); api_key=str(body.get("api_key",""))
                        containers=UnraidClient(base_url,api_key).containers(); result={"status":"connected","container_count":len(containers)}
                        if body.get("save") is True:
                            result["integration"]=application.secrets.put({"id":"unraid-primary","name":"Unraid","provider":"unraid","base_url":base_url.rstrip("/"),"credential":api_key,"status":"connected"})
                        application.store.audit({"event":"unraid.connected","container_count":len(containers),"saved":body.get("save") is True})
                        self._json(HTTPStatus.OK,result); return
                    if self.path == "/api/v1/unraid/containers":
                        integration=application.secrets.get("unraid-primary")
                        if integration is None: raise ValidationError("saved Unraid integration was not found")
                        containers=UnraidClient(str(integration["base_url"]),str(integration["credential"])).containers()
                        application.store.audit({"event":"unraid.containers_discovered","count":len(containers)})
                        self._json(HTTPStatus.OK,{"containers":containers}); return
                    if self.path == "/api/v1/unraid/reverse-proxies":
                        integration=application.secrets.get("unraid-primary")
                        if integration is None: raise ValidationError("saved Unraid integration was not found")
                        containers=UnraidClient(str(integration["base_url"]),str(integration["credential"])).containers()
                        proxies=discover_reverse_proxies(containers)
                        application.store.audit({"event":"unraid.reverse_proxies_discovered","count":len(proxies)})
                        self._json(HTTPStatus.OK,{"proxies":proxies,"newt":discover_newt(containers),"fallback":"bundled_caddy" if not proxies else None}); return
                    if self.path == "/api/v1/proxies/npm/connect":
                        base_url=str(body.get("base_url","")).strip().rstrip("/"); api_token=str(body.get("api_token","")); verify_tls=bool(body.get("verify_tls",True))
                        client=NginxProxyManagerClient(base_url,api_token,verify_tls=verify_tls); hosts=client.inventory()
                        saved=application.secrets.put({"id":"lan-proxy-primary","name":"Nginx Proxy Manager","provider":"nginx_proxy_manager","base_url":base_url,"credential":api_token,"verify_tls":verify_tls,"status":"connected","access":"read_only"})
                        application.store.audit({"event":"lan_proxy.connected","provider":"nginx_proxy_manager","route_count":len(hosts)})
                        self._json(HTTPStatus.OK,{"status":"connected","route_count":len(hosts),"integration":saved,"routes":hosts}); return
                    if self.path == "/api/v1/pangolin/connect":
                        endpoint=str(body.get("endpoint","")).strip().rstrip("/"); org_id=str(body.get("organization_id","")).strip(); api_key=str(body.get("api_key",""))
                        if not endpoint.startswith("https://") or not org_id or not api_key: raise ValidationError("HTTPS endpoint, organization ID, and API key are required")
                        api_base=endpoint if endpoint.endswith("/v1") else endpoint+"/v1"
                        sites=PangolinClient(JsonHttpClient(api_base,api_key),org_id).sites(); result={"status":"connected","sites":sites}
                        if body.get("save") is True: result["integration"]=application.secrets.put({"id":"pangolin-primary","name":"Pangolin","provider":"pangolin","base_url":api_base,"organization_id":org_id,"credential":api_key,"status":"connected"})
                        application.store.audit({"event":"pangolin.connected","site_count":len(sites),"saved":body.get("save") is True}); self._json(HTTPStatus.OK,result); return
                    if self.path == "/api/v1/pangolin/sites":
                        integration=application.secrets.get("pangolin-primary")
                        if integration is None: raise ValidationError("saved Pangolin integration was not found")
                        sites=PangolinClient(JsonHttpClient(str(integration["base_url"]),str(integration["credential"])),str(integration["organization_id"])).sites()
                        application.store.audit({"event":"pangolin.sites_discovered","count":len(sites)}); self._json(HTTPStatus.OK,{"sites":sites}); return
                    if self.path == "/api/v1/dns/discover":
                        integration_id=str(body.get("integration_id","")); integration=application.secrets.get(integration_id)
                        if integration is None: raise ValidationError("saved DNS integration was not found")
                        result=DnsDiscovery(integration).discover(); application.store.audit({"event":"dns.discovered","integration_id":integration_id,"provider":result["provider"],"zone_count":len(result["zones"]),"record_count":len(result["records"])})
                        self._json(HTTPStatus.OK,result); return
                    if self.path == "/api/v1/apply":
                        plan = application.plans.consume(
                            str(body.get("plan_id", "")),
                            str(body.get("confirmation_token", "")),
                        )
                        desired = plan.route.to_dict()
                        routes = application.store.load_routes()
                        if application.provider_mutations:
                            dns_integration = None
                            if plan.route.mode in {"lan", "lan_remote"}:
                                if not plan.route.dns_integration_id:
                                    raise ValidationError("a saved DNS integration is required for live apply")
                                dns_integration = application.secrets.get(plan.route.dns_integration_id)
                                if dns_integration is None: raise ValidationError("saved DNS integration was not found")
                            pangolin_integration = None
                            if plan.route.mode in {"remote", "lan_remote"}:
                                pangolin_integration = application.secrets.get("pangolin-primary")
                                if pangolin_integration is None: raise ValidationError("saved Pangolin integration was not found")
                            result, routes = RouteApplyService(application.config_dir / "caddy" / "config.json").apply_route(
                                plan.route, routes, dns_integration=dns_integration,
                                pangolin_integration=pangolin_integration,
                            )
                            application.store.audit({
                                "event": "provider_transaction.finished",
                                "plan_id": plan.plan_id,
                                "hostname": plan.route.hostname,
                                "transaction": result.to_dict(),
                            })
                            if result.status != "applied":
                                self._json(HTTPStatus.CONFLICT, result.to_dict())
                                return
                            application.store.save_routes(routes)
                            self._json(HTTPStatus.OK, {"status": "applied", "transaction": result.to_dict(), "route": desired})
                            return
                        routes = [r for r in routes if r.get("hostname") != plan.route.hostname]
                        routes.append(desired)
                        application.store.save_routes(routes)
                        application.store.audit({
                            "event": "plan.applied",
                            "plan_id": plan.plan_id,
                            "hostname": plan.route.hostname,
                            "desired_hash": plan.desired_hash,
                            "result": "desired_state_saved",
                        })
                        self._json(HTTPStatus.OK, {
                            "status": "saved",
                            "warning": "provider mutations are not enabled in this development build",
                            "route": desired,
                        })
                        return
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                except (ValidationError, ValueError, RuntimeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except Exception:
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})

        return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", type=Path, default=Path("/config"))
    parser.add_argument("--listen", default="0.0.0.0:9080")
    parser.add_argument("--static-dir", type=Path, default=Path(__file__).parent / "static")
    args = parser.parse_args()
    host, port_text = args.listen.rsplit(":", 1)
    application = Application(args.config_dir, args.static_dir)
    try: renewal_interval=max(300,int(os.environ.get("WISE_CERT_RENEWAL_INTERVAL_SECONDS","21600")))
    except ValueError: renewal_interval=21600
    def renewal_loop() -> None:
        while True:
            time.sleep(renewal_interval)
            settings=application.secrets.get("certificate-primary")
            if not settings or not settings.get("auto_renew") or not settings.get("initial_sync_approved"): continue
            try: application.check_certificate_renewal(automatic=True)
            except Exception as exc: application.store.audit({"event":"certificate.renewal_failed","error_type":type(exc).__name__})
    Thread(target=renewal_loop,name="certificate-renewal",daemon=True).start()
    server = ThreadingHTTPServer((host, int(port_text)), application.handler())
    print(f"Wise Route Manager {__version__} listening on {args.listen}", flush=True)
    print(f"API token file: {application.token_path}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
