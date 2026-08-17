"""Multi-board Kanban aggregation.

Each named board is its own SQLite file. This module walks those files
and returns tasks annotated with ``board_slug`` so CLI list and the
dashboard can show one consolidated view without merging databases.
"""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import replace
from typing import Iterable, Optional

from . import kanban_db as kb

ALL_BOARDS_SLUG = "*"


def get_all_board_slugs(*, include_archived: bool = False) -> list[str]:
    """Return every discoverable board slug, ``default`` first."""
    return [
        entry["slug"]
        for entry in kb.list_boards(include_archived=include_archived)
        if entry.get("slug")
    ]


def resolve_board_slugs(boards: Iterable[str]) -> list[str]:
    """Expand ``*`` (or an empty list) to every board; otherwise keep order."""
    requested = [str(item).strip() for item in boards if str(item).strip()]
    if not requested or ALL_BOARDS_SLUG in requested:
        return get_all_board_slugs()
    seen: set[str] = set()
    slugs: list[str] = []
    for raw in requested:
        try:
            normed = kb._normalize_board_slug(raw)
        except ValueError:
            continue
        if not normed or normed in seen:
            continue
        if normed != kb.DEFAULT_BOARD and not kb.board_exists(normed):
            continue
        seen.add(normed)
        slugs.append(normed)
    return slugs


def find_task_board(task_id: str) -> Optional[str]:
    """Return the slug of the board that owns ``task_id``, or ``None``."""
    if not task_id:
        return None
    for slug in get_all_board_slugs():
        try:
            with contextlib.closing(kb.connect(board=slug)) as conn:
                if kb.get_task(conn, task_id) is not None:
                    return slug
        except (sqlite3.Error, OSError, ValueError):
            continue
    return None


def find_attachment_board(attachment_id: int) -> Optional[str]:
    """Return the slug of the board that owns ``attachment_id``, or ``None``."""
    for slug in get_all_board_slugs():
        try:
            with contextlib.closing(kb.connect(board=slug)) as conn:
                if kb.get_attachment(conn, attachment_id) is not None:
                    return slug
        except (sqlite3.Error, OSError, ValueError):
            continue
    return None


def _matches_query(task: kb.Task, query: str) -> bool:
    needle = query.strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        part
        for part in (task.id, task.title, task.body or "", task.assignee or "")
        if part
    )
    return needle in haystack.lower()


def _sort_key(task: kb.Task, sort_by: str):
    if sort_by in ("created", "created_at"):
        return (task.created_at or 0, task.id)
    if sort_by in ("created-desc",):
        return (-(task.created_at or 0), task.id)
    if sort_by in ("updated", "updated_at"):
        return (task.started_at or task.created_at or 0, task.id)
    if sort_by == "title":
        return ((task.title or "").lower(), task.id)
    if sort_by == "assignee":
        return ((task.assignee or "").lower(), task.created_at or 0, task.id)
    if sort_by == "status":
        return (task.status or "", task.created_at or 0, task.id)
    if sort_by == "priority-desc":
        return (task.priority or 0, task.created_at or 0, task.id)
    # Default and dashboard "priority": higher priority first.
    return (-(task.priority or 0), task.created_at or 0, task.id)


def query_multiple_boards(
    boards: Iterable[str],
    *,
    assignee: Optional[str] = None,
    status: Optional[str] = None,
    tenant: Optional[str] = None,
    query: Optional[str] = None,
    include_archived: bool = False,
    sort_by: str = "priority",
    limit: Optional[int] = None,
) -> list[kb.Task]:
    """Query tasks across boards and return ``Task`` rows with ``board_slug``."""
    all_tasks: list[kb.Task] = []
    needle = (query or "").strip()

    for slug in resolve_board_slugs(boards):
        try:
            with contextlib.closing(kb.connect(board=slug)) as conn:
                tasks = kb.list_tasks(
                    conn,
                    assignee=assignee,
                    status=status,
                    tenant=tenant,
                    include_archived=include_archived,
                )
        except (sqlite3.Error, OSError, ValueError, TypeError):
            continue
        for task in tasks:
            if needle and not _matches_query(task, needle):
                continue
            all_tasks.append(replace(task, board_slug=slug))

    reverse = sort_by in ("created-desc", "updated", "updated_at")
    if sort_by in ("priority", "priority-desc", "created", "created_at",
                   "title", "assignee", "status", "created-desc",
                   "updated", "updated_at"):
        all_tasks.sort(key=lambda task: _sort_key(task, sort_by), reverse=reverse)
    elif sort_by == "status_changed":
        # Caller (dashboard) re-sorts from task_events; keep priority order.
        all_tasks.sort(key=lambda task: _sort_key(task, "priority"))

    if limit is not None and limit > 0:
        return all_tasks[:limit]
    return all_tasks
