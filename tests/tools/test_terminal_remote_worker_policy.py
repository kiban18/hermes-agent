import json
import tempfile
from pathlib import Path

import pytest

from tools import terminal_tool


@pytest.fixture(autouse=True)
def _clear_scheduler_cache(monkeypatch):
    monkeypatch.setattr(terminal_tool, "_REMOTE_WORKER_SCHEDULER", None)


def _write_scheduler(home: Path, body: str) -> None:
    path = home / ".claude/skills/remote-worker/scripts/active_scheduler.py"
    path.parent.mkdir(parents=True)
    path.write_text(body)


def test_long_local_verification_uses_shared_remote_worker(monkeypatch):
    with tempfile.TemporaryDirectory(dir=Path.home()) as tmp_dir:
        tmp = Path(tmp_dir)
        monkeypatch.setenv("HOME", str(tmp))
        _write_scheduler(tmp, """
def decision(payload):
    if "playwright" not in payload["tool_input"]["command"]:
        return None
    return {"hookSpecificOutput": {"updatedInput": {
        "command": "remote-worker run --mode verify"
    }}}
""")
        project = tmp / "project"
        project.mkdir()
        (project / "package.json").write_text("{}\n")

        rewritten = terminal_tool._apply_remote_worker_policy(
            "npx playwright test", str(project), "local"
        )

        assert "remote-worker run" in rewritten
        assert terminal_tool._apply_remote_worker_policy(
            "git status", str(project), "local"
        ) == "git status"


def test_missing_scheduler_blocks_heavy_local_command(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(terminal_tool.RemoteWorkerPolicyError):
        terminal_tool._apply_remote_worker_policy(
            "pytest", str(tmp_path), "local"
        )


def test_terminal_tool_surfaces_missing_scheduler_as_blocked(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = json.loads(terminal_tool.terminal_tool("pytest", workdir=str(tmp_path)))
    assert result["status"] == "blocked"
    assert result["exit_code"] == -1


def test_malformed_scheduler_blocks_heavy_local_command(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_scheduler(tmp_path, "def decision(payload):\n    return {'bad': True}\n")
    with pytest.raises(terminal_tool.RemoteWorkerPolicyError):
        terminal_tool._apply_remote_worker_policy(
            "npx playwright test", str(tmp_path), "local"
        )


@pytest.mark.parametrize(
    "command",
    [
        "API_TOKEN=example pytest",
        "PGPASSWORD=example pytest",
        "DATABASE_URL=postgres://user:password@db/test pytest",
        "pytest --access-token=example",
    ],
)
def test_inline_credentials_are_not_sent_to_remote_worker(
    monkeypatch, tmp_path, command,
):
    monkeypatch.setattr(
        terminal_tool,
        "_load_remote_worker_scheduler",
        lambda: pytest.fail("credential-bearing command must not load scheduler"),
    )
    assert terminal_tool._apply_remote_worker_policy(
        command, str(tmp_path), "local"
    ) == command


def test_missing_scheduler_blocks_npm_run_vitest(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(terminal_tool.RemoteWorkerPolicyError):
        terminal_tool._apply_remote_worker_policy(
            "npm run vitest", str(tmp_path), "local"
        )


def test_nonlocal_environment_is_unchanged(tmp_path):
    assert terminal_tool._apply_remote_worker_policy(
        "pytest", str(tmp_path), "docker"
    ) == "pytest"
