"""Recoverable, user-authorized computer-use runtime."""

from typing import TYPE_CHECKING

from core.computer_use.models import (
    ComputerAction,
    ComputerActionType,
    ComputerCheckpoint,
    ComputerObservation,
    ComputerPlan,
    ComputerPlanStatus,
    ComputerTarget,
    ComputerTargetSource,
    ComputerVerification,
)

if TYPE_CHECKING:
    from core.computer_use.coordinator import ComputerUseCoordinator


def __getattr__(name: str):
    """Keep the Coordinator facade lazy so model imports cannot form a cycle."""
    if name == "ComputerUseCoordinator":
        from core.computer_use.coordinator import ComputerUseCoordinator

        return ComputerUseCoordinator
    raise AttributeError(name)


__all__ = [
    "ComputerAction",
    "ComputerActionType",
    "ComputerCheckpoint",
    "ComputerObservation",
    "ComputerPlan",
    "ComputerPlanStatus",
    "ComputerTarget",
    "ComputerTargetSource",
    "ComputerUseCoordinator",
    "ComputerVerification",
]
