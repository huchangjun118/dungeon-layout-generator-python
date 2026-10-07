"""Layout lifecycle state machine with permission checks.

States:  DRAFT -> LOCKED -> PUBLISHED (terminal), LOCKED -> DRAFT (unlock).

Permissions: locking/unlocking requires EDITOR, publishing requires ADMIN.
Everything else (including no-op or backwards jumps) is rejected so every
persisted change is legal and auditable.
"""
from __future__ import annotations

from app.models import LayoutStatus, Role, StateTransitionError

# Legal transitions: from -> set of allowed targets.
TRANSITIONS: dict[LayoutStatus, set[LayoutStatus]] = {
    LayoutStatus.DRAFT: {LayoutStatus.LOCKED},
    LayoutStatus.LOCKED: {LayoutStatus.PUBLISHED, LayoutStatus.DRAFT},
    LayoutStatus.PUBLISHED: set(),  # terminal
}

# Minimum role required to enter each target state.
REQUIRED_ROLE: dict[LayoutStatus, Role] = {
    LayoutStatus.LOCKED: Role.EDITOR,
    LayoutStatus.DRAFT: Role.EDITOR,
    LayoutStatus.PUBLISHED: Role.ADMIN,
}

_ROLE_RANK = {Role.VIEWER: 0, Role.EDITOR: 1, Role.ADMIN: 2}


def check_transition(
    current: LayoutStatus, target: LayoutStatus, role: Role
) -> None:
    """Raise StateTransitionError if the transition or role is not allowed."""
    if target not in TRANSITIONS.get(current, set()):
        raise StateTransitionError(
            f"illegal transition: {current.value} -> {target.value}"
        )
    required = REQUIRED_ROLE[target]
    if _ROLE_RANK[role] < _ROLE_RANK[required]:
        raise StateTransitionError(
            f"role {role.value} may not enter state {target.value} "
            f"(requires {required.value})"
        )
