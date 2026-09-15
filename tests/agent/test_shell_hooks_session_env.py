"""Shell hooks must spawn with this turn's session identity, not the global.

Companion to ``tests/tools/test_local_env_session_leak.py``. That file proves
the subprocess-env bridge is correct; this one proves the *shell-hook* spawn
path actually goes through it.

``agent.shell_hooks._spawn`` called ``subprocess.Popen`` with no ``env=``, so
the hook inherited the raw process-global ``os.environ``. The session vars have
an ``os.environ`` mirror that is written last-writer-wins and never cleared, so
under a concurrent host it names whichever turn wrote it last — not this one.

Real consequence, 2026-09-15 09:21: the ``pre_llm_call`` room-identity hook in
a 사이버컴 turn read the 월드비전 turn's session id out of that global and
stamped the wrong room's board and SUMMARY as authoritative. The agent then
discarded its own room's context and dropped an approved task. 49 of 327
identity injections since 2026-09-01 named the wrong room.

The gateway process had been running for 61 seconds at that point, so a
restart is not a fix — the global is re-poisoned by the next concurrent turn.
The fix is to build the child env through ``build_subprocess_env``, which
resolves each session var from the task-local ContextVar and strips it when
this task never bound one.
"""

import os
import sys

import pytest

import gateway.session_context as sc
from agent.shell_hooks import ShellHookSpec, _spawn
from gateway.session_context import _VAR_MAP, clear_session_vars, set_session_vars

SESSION_VARS = list(_VAR_MAP.keys())

THIS_TURN = "20260915_091112_736451e2"      # 사이버컴
CONCURRENT_TURN = "20260915_071301_686e3232"  # 월드비전
THIS_CHAT = "-5426477826"
CONCURRENT_CHAT = "-5515742264"


@pytest.fixture(autouse=True)
def _isolate_session_context():
    saved_env = {k: os.environ.get(k) for k in SESSION_VARS}
    saved_ctx = {name: var.get() for name, var in _VAR_MAP.items()}
    saved_engaged = sc._session_context_engaged
    for var in _VAR_MAP.values():
        var.set(sc._UNSET)
    sc._session_context_engaged = False
    try:
        yield
    finally:
        for var, val in zip(_VAR_MAP.values(), saved_ctx.values()):
            var.set(val)
        sc._session_context_engaged = saved_engaged
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _echo_hook(tmp_path, *names):
    """A hook script that reports the env vars it was handed."""
    script = tmp_path / "echo_session.py"
    body = ", ".join(f'"{n}": os.environ.get("{n}", "")' for n in names)
    script.write_text(
        "import json, os, sys\n"
        "sys.stdin.read()\n"
        f"print(json.dumps({{{body}}}))\n",
        encoding="utf-8",
    )
    return ShellHookSpec(
        event="pre_llm_call",
        command=f"{sys.executable} {script}",
        timeout=15,
    )


def _run(spec):
    import json

    result = _spawn(spec, "{}")
    assert not result.get("error"), result
    assert not result.get("timed_out"), result
    return json.loads(result["stdout"])


def test_hook_gets_this_turns_session_not_the_poisoned_global(tmp_path):
    """The concurrent turn owns os.environ; this turn's ContextVar must win."""
    os.environ["HERMES_SESSION_ID"] = CONCURRENT_TURN
    os.environ["HERMES_SESSION_CHAT_ID"] = CONCURRENT_CHAT
    tokens = set_session_vars(
        platform="telegram",
        chat_id=THIS_CHAT,
        chat_type="group",
        session_id=THIS_TURN,
        session_key=f"agent:main:telegram:group:{THIS_CHAT}",
    )
    try:
        seen = _run(_echo_hook(tmp_path, "HERMES_SESSION_ID", "HERMES_SESSION_CHAT_ID"))
    finally:
        clear_session_vars(tokens)

    assert seen["HERMES_SESSION_ID"] == THIS_TURN
    assert seen["HERMES_SESSION_CHAT_ID"] == THIS_CHAT


def test_unbound_task_strips_rather_than_inherits_a_foreign_session(tmp_path):
    """No binding on this task + an engaged host: hand over nothing, not theirs.

    This is the window a freshly spawned task sits in before it binds its own
    session. Inheriting there is how a hook reads a neighbour's identity.
    """
    os.environ["HERMES_SESSION_ID"] = CONCURRENT_TURN
    os.environ["HERMES_SESSION_CHAT_ID"] = CONCURRENT_CHAT
    sc._session_context_engaged = True

    seen = _run(_echo_hook(tmp_path, "HERMES_SESSION_ID", "HERMES_SESSION_CHAT_ID"))

    assert seen["HERMES_SESSION_ID"] == ""
    assert seen["HERMES_SESSION_CHAT_ID"] == ""


def test_single_process_cli_keeps_the_environ_fallback(tmp_path):
    """Never engaged means no concurrency to leak across — keep legacy behavior."""
    os.environ["HERMES_SESSION_ID"] = THIS_TURN

    seen = _run(_echo_hook(tmp_path, "HERMES_SESSION_ID"))

    assert seen["HERMES_SESSION_ID"] == THIS_TURN


def test_hook_still_receives_ordinary_environment(tmp_path):
    """The env swap must not strip what configured hooks actually read."""
    os.environ["HERMES_KANBAN_TASK"] = "t_60f668d4"

    seen = _run(_echo_hook(tmp_path, "PATH", "HERMES_HOME", "HERMES_KANBAN_TASK"))

    assert seen["PATH"]
    assert seen["HERMES_HOME"]
    assert seen["HERMES_KANBAN_TASK"] == "t_60f668d4"
