"""Enhedstests af statusmodellen."""

import pytest

from app import state as st


@pytest.mark.parametrize(
    "action,role,current,target",
    [
        ("request", "stage", st.PENDING, st.REQUESTED),
        ("withdraw", "stage", st.REQUESTED, st.PENDING),
        ("withdraw", "stage", st.READY, st.PENDING),
        ("ready", "foh", st.REQUESTED, st.READY),
        ("ready", "foh", st.PENDING, st.READY),
        ("start", "foh", st.READY, st.LIVE),
        ("start", "foh", st.PENDING, st.LIVE),  # FOH kan springe trin over
        ("finish", "foh", st.LIVE, st.DONE),
        ("cancel", "foh", st.LIVE, st.CANCELLED),
        ("reopen", "foh", st.DONE, st.PENDING),
        ("reopen", "foh", st.CANCELLED, st.PENDING),
    ],
)
def test_allowed_transitions(action, role, current, target):
    assert st.resolve_transition(action, role, current) == target


@pytest.mark.parametrize("action", ["ready", "start", "finish", "cancel", "reopen"])
def test_stage_cannot_do_foh_actions(action):
    with pytest.raises(st.TransitionError) as exc:
        st.resolve_transition(action, "stage", st.READY)
    assert exc.value.forbidden


def test_stage_cannot_withdraw_live_item():
    with pytest.raises(st.TransitionError) as exc:
        st.resolve_transition("withdraw", "stage", st.LIVE)
    assert not exc.value.forbidden


def test_cannot_finish_item_that_is_not_live():
    with pytest.raises(st.TransitionError):
        st.resolve_transition("finish", "foh", st.PENDING)


def test_monitor_role_has_no_actions():
    for action in st.ACTIONS:
        assert not st.role_may(action, "monitor")
