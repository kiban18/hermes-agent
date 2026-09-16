"""A gateway message turn is never a delegate_task child, so it must not inherit one.

Each gateway message runs in its own asyncio task created with ``create_task``,
which snapshots the current context. A message that starts while a
``delegate_task`` child is running inherits that child's
``_DELEGATED_CHILD_CONTEXT``. ``reset_session_vars`` already exists to drop
exactly this kind of inherited identity at handler entry, but it only clears the
vars declared in ``gateway.session_context`` — the delegation flag lives in
``agent.delegation_context`` and was left set.

The consequence is not a warning. ``build_subprocess_env`` sees the flag, stamps
``HERMES_DELEGATED_CHILD_CONTEXT=1`` onto every child env, and the Kanban
mutation guard refuses:

    kanban: could not initialize database: delegate_task child contexts cannot
    mutate Kanban tasks or boards

so the turn cannot create the card it was asked for. 1,228 occurrences between
2026-08-16 and 2026-09-16 across project_lead, project_developer,
executive_coordinator and several project rooms; nobody noticed because the
agent answered "별도 채널에서 처리하겠습니다" and the work was simply dropped.

The guard itself is correct and stays: a real delegated child must never mutate
the dispatcher's board. Only the misclassification is fixed here.

``_NON_DISPATCHER_OWNED_CONTEXT`` is deliberately NOT reset. Inheriting it means
"I do not own the dispatcher's task", which is the conservative direction;
clearing it would let a gateway turn claim ownership of a worker's task.
"""

from __future__ import annotations

import os

import pytest

import agent.delegation_context as dc
from agent.delegation_context import (
    DELEGATED_CHILD_ENV_MARKER,
    delegated_child_context,
    is_delegated_child_context,
    is_delegated_child_process_context,
    is_dispatcher_owned_worker_context,
    non_dispatcher_owned_context,
)
from gateway.session_context import reset_session_vars


@pytest.fixture(autouse=True)
def _clean_marker():
    """The env marker is process-global; keep tests from leaking into each other."""
    saved = os.environ.get(DELEGATED_CHILD_ENV_MARKER)
    os.environ.pop(DELEGATED_CHILD_ENV_MARKER, None)
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop(DELEGATED_CHILD_ENV_MARKER, None)
        else:
            os.environ[DELEGATED_CHILD_ENV_MARKER] = saved


def test_inherited_delegation_flag_is_dropped_at_handler_entry():
    """The reported failure: the flag survives into a fresh message turn."""
    token = dc._DELEGATED_CHILD_CONTEXT.set(True)  # inherited from a sibling task
    try:
        assert is_delegated_child_context() is True
        reset_session_vars()
        assert is_delegated_child_context() is False
    finally:
        dc._DELEGATED_CHILD_CONTEXT.reset(token)


def test_reset_clears_the_process_context_view_too():
    """build_subprocess_env reads this one; it decides whether children are stamped."""
    token = dc._DELEGATED_CHILD_CONTEXT.set(True)
    try:
        reset_session_vars()
        assert is_delegated_child_process_context() is False
    finally:
        dc._DELEGATED_CHILD_CONTEXT.reset(token)


def test_a_real_child_subprocess_marker_still_counts():
    """Resetting the ContextVar must not blind us to a genuine child process.

    A child spawned by delegate_task carries the env marker; that is a real
    delegated context and the Kanban guard must still fire there.
    """
    os.environ[DELEGATED_CHILD_ENV_MARKER] = "1"
    reset_session_vars()
    assert is_delegated_child_process_context() is True


def test_the_guard_still_blocks_inside_a_real_delegated_context():
    """The invariant is unchanged: a delegate_task child cannot mutate the board."""
    with delegated_child_context("child-session"):
        assert is_delegated_child_context() is True
        assert is_delegated_child_process_context() is True


def test_non_dispatcher_owned_flag_is_left_alone():
    """Not reset on purpose — clearing it would claim a worker's task."""
    with non_dispatcher_owned_context():
        assert is_dispatcher_owned_worker_context() is False
        reset_session_vars()
        assert is_dispatcher_owned_worker_context() is False


def test_binding_a_session_identity_also_clears_the_flag():
    """Every host binds identity through set_session_vars; none of them is a child.

    reset_session_vars covers only the gateway — it is the sole caller. cron,
    the API server, the TUI and the ACP adapter bind a session and never reset,
    so the inherited flag survived there and blocked 239 more turns (kanban 93,
    cron 89, cli 57) than the gateway alone. Clearing it where identity is bound
    is the placement a new host cannot forget, and it is safe because a
    delegate_task child never calls set_session_vars.
    """
    from gateway.session_context import clear_session_vars, set_session_vars

    token = dc._DELEGATED_CHILD_CONTEXT.set(True)
    try:
        tokens = set_session_vars(platform="cron", session_id="cron-1")
        try:
            assert is_delegated_child_context() is False
        finally:
            clear_session_vars(tokens)
    finally:
        dc._DELEGATED_CHILD_CONTEXT.reset(token)


def test_binding_does_not_hide_a_real_child_subprocess():
    """The env marker still wins: a genuine child process stays a child."""
    from gateway.session_context import clear_session_vars, set_session_vars

    os.environ[DELEGATED_CHILD_ENV_MARKER] = "1"
    tokens = set_session_vars(platform="cron", session_id="cron-2")
    try:
        assert is_delegated_child_process_context() is True
    finally:
        clear_session_vars(tokens)
