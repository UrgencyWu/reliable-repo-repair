from enum import StrEnum


class RepairStatus(StrEnum):
    RECEIVED = "RECEIVED"
    QUEUED = "QUEUED"
    PROVISIONING = "PROVISIONING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class DispatchStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    RECONCILING = "RECONCILING"
    DISPATCHED = "DISPATCHED"
    FAILED = "FAILED"


TERMINAL_STATUSES = frozenset({RepairStatus.COMPLETED, RepairStatus.FAILED, RepairStatus.TIMEOUT})
TRANSITIONS: dict[RepairStatus, frozenset[RepairStatus]] = {
    RepairStatus.RECEIVED: frozenset(
        {RepairStatus.QUEUED, RepairStatus.FAILED, RepairStatus.TIMEOUT}
    ),
    RepairStatus.QUEUED: frozenset(
        {RepairStatus.PROVISIONING, RepairStatus.FAILED, RepairStatus.TIMEOUT}
    ),
    RepairStatus.PROVISIONING: frozenset(
        {RepairStatus.VALIDATING, RepairStatus.FAILED, RepairStatus.TIMEOUT}
    ),
    RepairStatus.VALIDATING: frozenset(
        {RepairStatus.COMPLETED, RepairStatus.FAILED, RepairStatus.TIMEOUT}
    ),
    RepairStatus.COMPLETED: frozenset(),
    RepairStatus.FAILED: frozenset(),
    RepairStatus.TIMEOUT: frozenset(),
}


class IllegalTransition(ValueError):
    pass


async def require_transition(current: RepairStatus, target: RepairStatus) -> None:
    if target not in TRANSITIONS[current]:
        raise IllegalTransition(f"Illegal repair transition: {current} -> {target}")
