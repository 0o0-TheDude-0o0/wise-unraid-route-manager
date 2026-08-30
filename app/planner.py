from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
from threading import Lock
from typing import Any

from .models import RouteSpec


@dataclass(frozen=True)
class PlanStep:
    provider: str
    action: str
    summary: str
    risk: str = "normal"


@dataclass(frozen=True)
class Plan:
    plan_id: str
    confirmation_token: str
    expires_at: str
    desired_hash: str
    steps: tuple[PlanStep, ...]
    route: RouteSpec

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return value


class PlanStore:
    """Short-lived, single-use plan storage.

    Plan tokens bind approval to the exact validated desired state. A subsequent
    edit requires a new preview and therefore a new approval.
    """

    def __init__(self, lifetime_seconds: int = 600):
        self._lifetime = lifetime_seconds
        self._plans: dict[str, Plan] = {}
        self._lock = Lock()

    @staticmethod
    def desired_hash(route: RouteSpec) -> str:
        encoded = json.dumps(route.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    def create(self, route: RouteSpec, steps: list[PlanStep]) -> Plan:
        now = datetime.now(timezone.utc)
        plan = Plan(
            plan_id=secrets.token_urlsafe(18),
            confirmation_token=secrets.token_urlsafe(32),
            expires_at=(now + timedelta(seconds=self._lifetime)).isoformat(),
            desired_hash=self.desired_hash(route),
            steps=tuple(steps),
            route=route,
        )
        with self._lock:
            self._plans[plan.plan_id] = plan
        return plan

    def consume(self, plan_id: str, token: str) -> Plan:
        with self._lock:
            plan = self._plans.pop(plan_id, None)
        if plan is None or not secrets.compare_digest(plan.confirmation_token, token):
            raise ValueError("plan approval is invalid or has already been used")
        if datetime.fromisoformat(plan.expires_at) < datetime.now(timezone.utc):
            raise ValueError("plan approval has expired")
        return plan


def build_initial_plan(route: RouteSpec) -> list[PlanStep]:
    steps: list[PlanStep] = []
    if route.mode in {"lan", "lan_remote"}:
        steps.append(
            PlanStep(
                provider="technitium",
                action="reconcile_dns",
                summary=f"Point {route.hostname} to {route.lan_address}",
            )
        )
        steps.append(
            PlanStep(
                provider="caddy",
                action="reconcile_proxy",
                summary=f"Proxy {route.hostname} to {route.upstream.url}",
            )
        )
    if route.mode in {"remote", "lan_remote"}:
        auth = "with authentication" if route.require_authentication else "without authentication"
        steps.append(
            PlanStep(
                provider="pangolin",
                action="reconcile_resource",
                summary=f"Publish {route.hostname} through site {route.pangolin_site_id} {auth}",
                risk="elevated" if not route.require_authentication else "normal",
            )
        )
    return steps
