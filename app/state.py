"""Statusmodel og tilladte statusovergange.

Al forretningslogik om status ligger her, så den kan testes isoleret og
genbruges af både API og tests.
"""

from __future__ import annotations

PENDING = "pending"
REQUESTED = "requested"
READY = "ready"
LIVE = "live"
DONE = "done"
CANCELLED = "cancelled"

ALL_STATUSES = (PENDING, REQUESTED, READY, LIVE, DONE, CANCELLED)
ACTIVE_STATUSES = frozenset({PENDING, REQUESTED, READY, LIVE})

STATUS_LABELS = {
    PENDING: "Afventer",
    REQUESTED: "Ønskes klargjort",
    READY: "Klar",
    LIVE: "Afvikles",
    DONE: "Afsluttet",
    CANCELLED: "Annulleret",
}

ITEM_TYPES = {"speech": "Tale", "video": "Video", "other": "Andet"}

ROLE_FOH = "foh"
ROLE_STAGE = "stage"

# handling -> (målstatus, {rolle: tilladte fra-statusser})
ACTIONS: dict[str, tuple[str, dict[str, frozenset[str]]]] = {
    "request": (
        REQUESTED,
        {ROLE_STAGE: frozenset({PENDING}), ROLE_FOH: frozenset({PENDING})},
    ),
    "withdraw": (
        PENDING,
        {
            ROLE_STAGE: frozenset({REQUESTED, READY}),
            ROLE_FOH: frozenset({REQUESTED, READY}),
        },
    ),
    "ready": (READY, {ROLE_FOH: frozenset({PENDING, REQUESTED})}),
    "start": (LIVE, {ROLE_FOH: frozenset({PENDING, REQUESTED, READY})}),
    "finish": (DONE, {ROLE_FOH: frozenset({LIVE})}),
    "cancel": (CANCELLED, {ROLE_FOH: frozenset({PENDING, REQUESTED, READY, LIVE})}),
    "reopen": (PENDING, {ROLE_FOH: frozenset({DONE, CANCELLED})}),
}

ACTION_LABELS = {
    "request": "Anmod om klargøring",
    "withdraw": "Fortryd anmodning",
    "ready": "Markér klar",
    "start": "Start",
    "finish": "Afslut",
    "cancel": "Annullér",
    "reopen": "Genåbn",
}


class TransitionError(Exception):
    def __init__(self, message: str, *, forbidden: bool = False):
        super().__init__(message)
        self.message = message
        self.forbidden = forbidden


def resolve_transition(action: str, role: str, current: str) -> str:
    """Returnér målstatus for `action`, eller rejs TransitionError.

    Kaldes kun når nuværende status ikke allerede er målstatus
    (det tilfælde håndteres som idempotent no-op af kalderen).
    """
    if action not in ACTIONS:
        raise TransitionError(f"Ukendt handling: {action}")
    target, allowed_by_role = ACTIONS[action]
    allowed = allowed_by_role.get(role)
    if allowed is None:
        raise TransitionError("Din rolle må ikke udføre denne handling.", forbidden=True)
    if current not in allowed:
        raise TransitionError(
            f"Kan ikke udføre '{ACTION_LABELS[action]}', når punktet har status "
            f"'{STATUS_LABELS.get(current, current)}'."
        )
    return target


def target_status(action: str) -> str:
    return ACTIONS[action][0]


def role_may(action: str, role: str) -> bool:
    return action in ACTIONS and role in ACTIONS[action][1]
