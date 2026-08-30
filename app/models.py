from __future__ import annotations

from dataclasses import asdict, dataclass, field
from ipaddress import ip_address
import re
from typing import Any, Literal
from urllib.parse import urlsplit


RouteMode = Literal["lan", "remote", "lan_remote"]


class ValidationError(ValueError):
    pass


_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def validate_hostname(value: str) -> str:
    hostname = value.strip().rstrip(".").lower()
    if len(hostname) > 253 or len(hostname.split(".")) < 2:
        raise ValidationError("hostname must be a fully qualified domain name")
    if not all(_LABEL.fullmatch(label) for label in hostname.split(".")):
        raise ValidationError("hostname contains an invalid DNS label")
    return hostname


@dataclass(frozen=True)
class Upstream:
    scheme: Literal["http", "https"]
    host: str
    port: int
    tls_server_name: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Upstream":
        scheme = str(value.get("scheme", "")).lower()
        if scheme not in {"http", "https"}:
            raise ValidationError("upstream scheme must be http or https")
        host = str(value.get("host", "")).strip()
        if not host or any(c in host for c in "/?#@"):
            raise ValidationError("upstream host is invalid")
        try:
            port = int(value.get("port"))
        except (TypeError, ValueError):
            raise ValidationError("upstream port must be an integer") from None
        if not 1 <= port <= 65535:
            raise ValidationError("upstream port must be between 1 and 65535")
        tls_name = value.get("tls_server_name")
        if tls_name is not None:
            tls_name = validate_hostname(str(tls_name))
        return cls(scheme=scheme, host=host, port=port, tls_server_name=tls_name)

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{self.scheme}://{host}:{self.port}"


@dataclass(frozen=True)
class RouteSpec:
    name: str
    hostname: str
    mode: RouteMode
    upstream: Upstream
    lan_address: str | None = None
    dns_integration_id: str | None = None
    source_container_id: str | None = None
    source_container_name: str | None = None
    source_port: int | None = None
    pangolin_site_id: int | None = None
    pangolin_domain_id: int | None = None
    require_authentication: bool = True
    health_path: str = "/"
    enabled: bool = True
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RouteSpec":
        name = str(value.get("name", "")).strip()
        if not name or len(name) > 80:
            raise ValidationError("name is required and must be at most 80 characters")
        hostname = validate_hostname(str(value.get("hostname", "")))
        mode = str(value.get("mode", ""))
        if mode not in {"lan", "remote", "lan_remote"}:
            raise ValidationError("mode must be lan, remote, or lan_remote")
        lan_address = value.get("lan_address")
        if mode in {"lan", "lan_remote"}:
            if not lan_address:
                raise ValidationError("lan_address is required for LAN routes")
            try:
                lan_address = str(ip_address(str(lan_address)))
            except ValueError:
                raise ValidationError("lan_address must be a valid IP address") from None
        elif lan_address:
            raise ValidationError("lan_address is only valid for LAN routes")

        site_id = value.get("pangolin_site_id")
        domain_id = value.get("pangolin_domain_id")
        if mode in {"remote", "lan_remote"}:
            try:
                site_id, domain_id = int(site_id), int(domain_id)
            except (TypeError, ValueError):
                raise ValidationError(
                    "Pangolin site and domain IDs are required for remote routes"
                ) from None

        health_path = str(value.get("health_path", "/"))
        parsed = urlsplit(health_path)
        if not health_path.startswith("/") or parsed.scheme or parsed.netloc:
            raise ValidationError("health_path must be an absolute URL path")

        source_port=value.get("source_port")
        if source_port is not None:
            try: source_port=int(source_port)
            except (TypeError,ValueError): raise ValidationError("source_port must be an integer") from None
        return cls(
            name=name,
            hostname=hostname,
            mode=mode,  # type: ignore[arg-type]
            upstream=Upstream.from_dict(dict(value.get("upstream") or {})),
            lan_address=lan_address,
            dns_integration_id=str(value.get("dns_integration_id")) if value.get("dns_integration_id") else None,
            source_container_id=str(value.get("source_container_id")) if value.get("source_container_id") else None,
            source_container_name=str(value.get("source_container_name")) if value.get("source_container_name") else None,
            source_port=source_port,
            pangolin_site_id=site_id,
            pangolin_domain_id=domain_id,
            require_authentication=bool(value.get("require_authentication", True)),
            health_path=health_path,
            enabled=bool(value.get("enabled", True)),
            metadata={str(k): str(v) for k, v in dict(value.get("metadata") or {}).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
