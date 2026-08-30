from __future__ import annotations
import ipaddress
import socket
import ssl
from typing import Any
from .models import RouteSpec

def _private_addresses(host: str) -> list[str]:
    try: addresses=[str(ipaddress.ip_address(host))]
    except ValueError: addresses=list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host,None,type=socket.SOCK_STREAM)))
    if not addresses: raise RuntimeError("host did not resolve")
    if any(not (ipaddress.ip_address(value).is_private or ipaddress.ip_address(value).is_loopback or ipaddress.ip_address(value).is_link_local) for value in addresses): raise RuntimeError("health probes are limited to private targets")
    return addresses

def probe_upstream(route: RouteSpec, timeout: float=3) -> dict[str,Any]:
    result: dict[str,Any]={"dns":False,"tcp":False,"tls":None,"http":False}
    try: addresses=_private_addresses(route.upstream.host); result["dns"]=True; result["addresses"]=addresses
    except Exception as exc: result["error"]=str(exc); return result
    address=addresses[0]
    try: raw=socket.create_connection((address,route.upstream.port),timeout=timeout); result["tcp"]=True
    except OSError as exc: result["error"]=f"TCP connection failed: {exc}"; return result
    connection=raw
    try:
        if route.upstream.scheme=="https":
            server_name=route.upstream.tls_server_name or route.upstream.host
            connection=ssl.create_default_context().wrap_socket(raw,server_hostname=server_name); result["tls"]=True; result["tls_version"]=connection.version()
        host_header=route.upstream.tls_server_name or route.upstream.host
        request=f"HEAD {route.health_path} HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\nUser-Agent: WiseRouteManager/0.1\r\n\r\n".encode()
        connection.sendall(request); response=connection.recv(1024); line=response.split(b"\r\n",1)[0].decode("ascii","replace"); result["status_line"]=line
        parts=line.split(); result["http"]=len(parts)>=2 and parts[1].isdigit() and int(parts[1])<500
    except (OSError,ssl.SSLError) as exc:
        if route.upstream.scheme=="https" and result["tls"] is not True: result["tls"]=False
        result["error"]=str(exc)
    finally:
        try: connection.close()
        except Exception: pass
    return result
