from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
import uuid


Apply = Callable[[], dict[str, Any]]
Rollback = Callable[[dict[str, Any]], None]


@dataclass
class TransactionStep:
    provider: str
    action: str
    apply: Apply
    rollback: Rollback


@dataclass
class StepResult:
    provider: str
    action: str
    status: str
    rollback_status: str | None = None
    error: str | None = None
    state: dict[str, Any] = field(default_factory=dict)


@dataclass
class TransactionResult:
    transaction_id: str
    status: str
    started_at: str
    finished_at: str
    steps: list[StepResult]
    error: str | None = None
    rollback_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]: return asdict(self)


class TransactionExecutor:
    """Executes provider steps and compensates completed work on failure."""
    def run(self, steps: list[TransactionStep]) -> TransactionResult:
        transaction_id=str(uuid.uuid4()); started=datetime.now(timezone.utc).isoformat()
        completed: list[tuple[TransactionStep,StepResult]]=[]; results: list[StepResult]=[]
        try:
            for step in steps:
                state=step.apply()
                if not isinstance(state,dict): raise RuntimeError(f"{step.provider} apply did not return rollback state")
                result=StepResult(step.provider,step.action,"applied",state=state); results.append(result); completed.append((step,result))
            return TransactionResult(transaction_id,"applied",started,datetime.now(timezone.utc).isoformat(),results)
        except Exception as exc:
            failure=StepResult(step.provider,step.action,"failed",error=str(exc)); results.append(failure); rollback_errors=[]
            for completed_step,result in reversed(completed):
                try: completed_step.rollback(result.state); result.rollback_status="rolled_back"
                except Exception as rollback_exc:
                    result.rollback_status="rollback_failed"; message=f"{completed_step.provider}: {rollback_exc}"; rollback_errors.append(message)
            status="rollback_failed" if rollback_errors else "rolled_back"
            return TransactionResult(transaction_id,status,started,datetime.now(timezone.utc).isoformat(),results,str(exc),rollback_errors)
