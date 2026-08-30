from __future__ import annotations

from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit
import re

from .models import ValidationError


CERTIFICATE_MODES = {"independent_dns01", "pangolin_newt_sync"}


def certificate_settings(value: dict[str, Any]) -> dict[str, Any]:
    mode=str(value.get("mode", ""))
    if mode not in CERTIFICATE_MODES:
        raise ValidationError("certificate mode must be independent_dns01 or pangolin_newt_sync")
    result: dict[str, Any]={"id":"certificate-primary","name":"LAN certificate strategy","provider":"certificate","mode":mode,"status":"configured"}
    if mode == "pangolin_newt_sync":
        endpoint=str(value.get("endpoint", "")).strip().rstrip("/")
        credential=str(value.get("credential", ""))
        parsed=urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValidationError("certificate synchronization requires a clean HTTPS endpoint")
        try: address=ip_address(parsed.hostname)
        except ValueError:
            if parsed.hostname not in {"localhost"} and not parsed.hostname.endswith((".local",".lan",".internal")):
                raise ValidationError("certificate synchronization endpoint must be reachable only through the private Newt site") from None
        else:
            if not (address.is_private or address.is_loopback or address.is_link_local):
                raise ValidationError("certificate synchronization endpoint must use a private address")
        if not credential:
            raise ValidationError("a scoped pull token is required for certificate synchronization")
        expected_name=str(value.get("expected_name","")).strip().lower().rstrip(".")
        if not re.fullmatch(r"(?:\*\.)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,61}",expected_name):
            raise ValidationError("the expected certificate name must be a hostname or wildcard hostname")
        result.update({"endpoint":endpoint,"credential":credential,"expected_name":expected_name,"transport":"newt","access":"pull_only","auto_renew":bool(value.get("auto_renew",False)),"initial_sync_approved":False})
    else:
        result.update({"issuer":"dns01","key_scope":"lan_only"})
    return result
