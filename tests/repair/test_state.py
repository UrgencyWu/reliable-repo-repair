import pytest

from agent.repair.state import IllegalTransition, RepairStatus, require_transition

pytestmark = pytest.mark.asyncio


async def test_success_requires_generation_then_independent_validation() -> None:
    with pytest.raises(IllegalTransition):
        await require_transition(RepairStatus.PROVISIONING, RepairStatus.COMPLETED)
    with pytest.raises(IllegalTransition):
        await require_transition(RepairStatus.QUEUED, RepairStatus.VALIDATING)
    await require_transition(RepairStatus.PROVISIONING, RepairStatus.VALIDATING)
    await require_transition(RepairStatus.VALIDATING, RepairStatus.COMPLETED)


@pytest.mark.parametrize(
    "terminal", [RepairStatus.COMPLETED, RepairStatus.FAILED, RepairStatus.TIMEOUT]
)
async def test_terminal_task_cannot_restart_or_accept_late_completion(
    terminal: RepairStatus,
) -> None:
    for target in (RepairStatus.QUEUED, RepairStatus.PROVISIONING, RepairStatus.COMPLETED):
        with pytest.raises(IllegalTransition):
            await require_transition(terminal, target)


async def test_failure_and_timeout_are_possible_during_validation() -> None:
    await require_transition(RepairStatus.VALIDATING, RepairStatus.FAILED)
    await require_transition(RepairStatus.VALIDATING, RepairStatus.TIMEOUT)
