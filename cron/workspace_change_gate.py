"""LLM-free gate for workspace-change-reconciler monitor jobs.

When a monitor snapshot changes, repositories that already have an open
「외부 작업 감지」 card get a one-line activity comment and do not wake
the agent. Only remaining repositories (new repo, or no open detection
card) are passed through as slim agent context.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

DETECTION_TITLE_PREFIX = "외부 작업 감지"
OPEN_STATUSES = ("triage", "todo", "ready", "running", "blocked", "review")
MONITOR_SCRIPT_MARKERS = (
    "workspace-delivery-monitor",
    "workspace-acquisition-monitor",
)
SKILL_NAME = "workspace-change-reconciler"


def is_workspace_change_monitor_job(job: dict | None) -> bool:
    if not isinstance(job, dict):
        return False
    script = str(job.get("monitor_script") or "")
    if any(marker in script for marker in MONITOR_SCRIPT_MARKERS):
        return True
    skills = job.get("skills")
    if isinstance(skills, str):
        skills = [skills]
    names = [str(name).strip() for name in (skills or []) if str(name).strip()]
    legacy = str(job.get("skill") or "").strip()
    if legacy:
        names.append(legacy)
    return SKILL_NAME in names


def is_workspace_detection_title(title: str | None) -> bool:
    return DETECTION_TITLE_PREFIX in str(title or "")


def owner_from_job(job: dict | None) -> str:
    profile = str(os.environ.get("HERMES_PROFILE") or "").strip()
    if profile:
        return profile
    script = str((job or {}).get("monitor_script") or "")
    if "acquisition" in script:
        return "proposal_lead"
    return "project_lead"


def parse_snapshot(text: str) -> tuple[Optional[dict], dict[str, dict]]:
    header: Optional[dict] = None
    repos: dict[str, dict] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        repo = obj.get("repo")
        if isinstance(repo, str) and repo.strip():
            repos[repo] = obj
        elif header is None:
            header = obj
    return header, repos


def changed_repo_states(old_text: str, new_text: str) -> list[dict]:
    _, old_repos = parse_snapshot(old_text)
    _, new_repos = parse_snapshot(new_text)
    changed: list[dict] = []
    for repo, state in new_repos.items():
        if old_repos.get(repo) != state:
            changed.append(state)
    return changed


def normalize_workspace(path: str | None) -> str:
    text = str(path or "").strip()
    if text.startswith("dir:"):
        text = text[4:].strip()
    if not text:
        return ""
    try:
        return str(Path(text).expanduser().resolve())
    except OSError:
        return os.path.normpath(os.path.expanduser(text))


def detection_title_for_repo(repo_path: str) -> str:
    return f"{DETECTION_TITLE_PREFIX} — {Path(repo_path).name}"


def activity_fingerprint(state: dict) -> str:
    digest = str(state.get("dirty_digest") or "")
    head = str(state.get("head") or "")
    receipt = state.get("receipt") if isinstance(state.get("receipt"), dict) else {}
    receipt_key = str(receipt.get("recorded_at") or receipt.get("summary") or "")
    return f"{digest}:{head}:{receipt_key}"


def activity_comment_body(state: dict) -> str:
    preview = state.get("dirty_preview") or []
    if not isinstance(preview, list):
        preview = []
    preview_text = ", ".join(str(item) for item in preview[:6])
    head = str(state.get("head") or "")[:12]
    return (
        f"활동 근거 · dirty={state.get('dirty_count', 0)} "
        f"digest={state.get('dirty_digest') or '-'} "
        f"HEAD={head or '-'} branch={state.get('branch') or '-'} "
        f"fp={activity_fingerprint(state)}"
        + (f" preview={preview_text}" if preview_text else "")
    )


def _iter_open_tasks(conn, *, statuses: Iterable[str] = OPEN_STATUSES):
    from hermes_cli import kanban_db as kb

    for status in statuses:
        try:
            rows = kb.list_tasks(conn, status=status, limit=1000)
        except Exception:
            continue
        yield from rows


def find_open_detection_card(repo_path: str) -> Optional[tuple[str, Any]]:
    """Return (board_slug, task) for an open detection card covering repo_path."""
    from hermes_cli import kanban_db as kb

    wanted = normalize_workspace(repo_path)
    expected_title = detection_title_for_repo(repo_path)
    basename = Path(repo_path).name
    matches: list[tuple[str, Any]] = []
    try:
        boards = kb.list_boards(include_archived=False)
    except Exception as exc:
        logger.debug("workspace-change gate: list_boards failed: %s", exc)
        return None
    for board in boards:
        slug = str(board.get("slug") or kb.DEFAULT_BOARD)
        try:
            with kb.connect_closing(board=slug) as conn:
                for task in _iter_open_tasks(conn):
                    title = (task.title or "").strip()
                    if not is_workspace_detection_title(title):
                        continue
                    workspace = normalize_workspace(task.workspace_path)
                    title_names_repo = bool(basename) and basename in title
                    if (
                        (wanted and workspace == wanted)
                        or title == expected_title
                        or title_names_repo
                    ):
                        matches.append((slug, task))
        except Exception as exc:
            logger.debug(
                "workspace-change gate: scan failed on board %s: %s", slug, exc
            )
            continue
    if not matches:
        return None
    matches.sort(key=lambda item: getattr(item[1], "created_at", 0) or 0)
    return matches[0]


def list_open_cards_for_repo(repo_path: str) -> list[dict[str, Any]]:
    from hermes_cli import kanban_db as kb

    wanted = normalize_workspace(repo_path)
    cards: list[dict[str, Any]] = []
    try:
        boards = kb.list_boards(include_archived=False)
    except Exception:
        return cards
    for board in boards:
        slug = str(board.get("slug") or kb.DEFAULT_BOARD)
        try:
            with kb.connect_closing(board=slug) as conn:
                for task in _iter_open_tasks(conn):
                    workspace = normalize_workspace(task.workspace_path)
                    if wanted and workspace == wanted:
                        cards.append(
                            {
                                "board": slug,
                                "id": task.id,
                                "title": task.title,
                                "status": task.status,
                                "assignee": task.assignee,
                                "workspace_path": task.workspace_path,
                            }
                        )
        except Exception:
            continue
    return cards


def _comment_already_has_fingerprint(conn, task_id: str, fingerprint: str) -> bool:
    from hermes_cli import kanban_db as kb

    try:
        comments = kb.list_comments(conn, task_id)
    except Exception:
        return False
    needle = f"fp={fingerprint}"
    digest = fingerprint.split(":", 1)[0]
    digest_needle = f"digest={digest}" if digest else ""
    for comment in comments:
        body = comment.body or ""
        if needle in body:
            return True
        if digest_needle and digest_needle in body and fingerprint.split(":")[1] in body:
            return True
    return False


def comment_on_detection_card(
    board: str,
    task_id: str,
    body: str,
    *,
    author: str,
    fingerprint: str,
) -> str:
    """Append a comment unless the same fingerprint is already present.

    Returns ``added``, ``duplicate``, or ``error``.
    """
    from hermes_cli import kanban_db as kb

    try:
        with kb.connect_closing(board=board) as conn:
            if _comment_already_has_fingerprint(conn, task_id, fingerprint):
                return "duplicate"
            kb.add_comment(conn, task_id, author, body)
            return "added"
    except Exception as exc:
        logger.warning(
            "workspace-change gate: comment failed on %s/%s: %s",
            board, task_id, exc,
        )
        return "error"


def slim_agent_context(remaining: list[dict], cards: list[dict]) -> str:
    repo_lines = [
        json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for state in remaining
    ]
    return (
        "## MONITOR CHANGE DETECTED\n\n"
        "열린 감지 카드가 없는 저장소만 남았다. "
        "workspace-change-reconciler 스킬만 적용한다. "
        "상태는 바꾸지 말고, 일치하는 열린 카드에 댓글로 연결하거나 "
        "후속 확인이 필요하면 담당자 Triage 한 장만 만든다. "
        "완료·검수·배포를 추론하지 않는다.\n\n"
        "### Changed repositories\n\n"
        f"```\n{chr(10).join(repo_lines)}\n```\n\n"
        "### Open cards matching those workspaces\n\n"
        f"```json\n{json.dumps(cards, ensure_ascii=False, indent=2)}\n```"
    )


def apply_workspace_change_gate(
    old_output: str,
    new_output: str,
    *,
    author: str,
    first_run: bool = False,
) -> tuple[list[dict], list[dict], Optional[str]]:
    """Comment on existing detection cards; return remaining agent work.

    Returns ``(remaining_states, handled_notes, context_block_or_none)``.
    An empty remaining list means the agent should not run.
    """
    if first_run:
        return [], [{"action": "baseline"}], None

    remaining: list[dict] = []
    handled: list[dict] = []
    for state in changed_repo_states(old_output, new_output):
        repo = str(state.get("repo") or "")
        if not repo:
            continue
        found = find_open_detection_card(repo)
        if found is None:
            remaining.append(state)
            continue
        board, task = found
        fingerprint = activity_fingerprint(state)
        result = comment_on_detection_card(
            board,
            task.id,
            activity_comment_body(state),
            author=author,
            fingerprint=fingerprint,
        )
        handled.append(
            {
                "action": result,
                "repo": repo,
                "task_id": task.id,
                "board": board,
            }
        )
        logger.info(
            "workspace-change gate: %s %s on %s/%s",
            result, repo, board, task.id,
        )

    if not remaining:
        return remaining, handled, None
    cards: list[dict] = []
    for state in remaining:
        cards.extend(list_open_cards_for_repo(str(state.get("repo") or "")))
    return remaining, handled, slim_agent_context(remaining, cards)
