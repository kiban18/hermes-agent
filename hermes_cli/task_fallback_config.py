"""Kanban task routing: live policy at spawn, optional column pin as exception.

Version 2 ``[task-runtime]`` records store profile/level only. The dispatcher
and worker fallback chain resolve against ``policies/task-model-routing.json``
at run time. Version 1 records that froze provider/model remain valid until
rewritten. ``model_override`` columns still win when set (``set-model``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import sys

PREFIX = '[task-runtime] '
VALID_LEVELS = ('simple', 'standard', 'complex', 'critical')


def policy_root() -> Path:
    env = os.environ.get('HERMES_HOME')
    candidates = []
    if env:
        home = Path(env)
        candidates.append(home)
        if home.name != '.hermes':
            candidates.append(home.parent)
            candidates.append(home.parent.parent)
    candidates.append(Path.home() / '.hermes')
    for root in candidates:
        if (root / 'policies' / 'task-model-routing.json').is_file():
            return root
    return Path.home() / '.hermes'


def parse_runtime(body) -> dict | None:
    first = (body or '').split('\n', 1)[0]
    if not first.startswith(PREFIX):
        return None
    record = json.loads(first[len(PREFIX):])
    if not isinstance(record, dict) or record.get('version') not in (1, 2):
        raise ValueError('unsupported task runtime version')
    return record


def policy_profiles() -> set[str]:
    path = policy_root() / 'policies' / 'task-model-routing.json'
    try:
        return set((json.loads(path.read_text()).get('profiles') or {}))
    except (OSError, ValueError, TypeError):
        return set()


def ensure_runtime_body(
    body,
    *,
    profile,
    level='standard',
    extra_review=False,
):
    """Prefix version 2 ``[task-runtime]`` when the card has none.

    Org-profile cards without a runtime would spawn on YAML standard only.
    Version 1 and valid version 2 records are left unchanged. Invalid first
    lines that claim to be runtime are replaced.
    """
    profile = (profile or '').strip() or None
    if not profile or profile not in policy_profiles():
        return body
    level = (level or 'standard').strip()
    if level not in VALID_LEVELS:
        raise ValueError(f'unsupported routing level {level!r}')
    text = body or ''
    first, sep, rest = text.partition('\n')
    if first.startswith(PREFIX):
        try:
            rec = json.loads(first[len(PREFIX):])
        except (json.JSONDecodeError, ValueError, TypeError):
            rec = None
        if isinstance(rec, dict) and rec.get('version') in (1, 2):
            return text
        text = rest
    record = {
        'version': 2,
        'routing': {
            'profile': profile,
            'level': level,
            'simple_verified': False,
            'extra_review': bool(extra_review),
            'exclude_provider': ['_unspecified'] if extra_review else [],
            'escalation_reason': None,
        },
    }
    header = PREFIX + json.dumps(record, ensure_ascii=False)
    remainder = text.strip('\n')
    return header + '\n\n' + remainder if remainder else header


def _load_router():
    scripts = str(policy_root() / 'scripts')
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import task_model_router
    return task_model_router


def _live_route(record: dict, *, assignee=None):
    routing = record.get('routing') or {}
    extra = bool(record.get('extra_review') or routing.get('extra_review'))
    level = routing.get('level') or record.get('level') or 'standard'
    if extra:
        level = 'standard'
    profile = routing.get('profile') or assignee
    if not profile:
        raise ValueError('task runtime is missing profile')
    exclude = routing.get('exclude_provider') or record.get('exclude_provider')
    if extra and not exclude:
        exclude = ['_unspecified']
    router = _load_router()
    return router.resolve_route(
        profile,
        level,
        simple_verified=bool(routing.get('simple_verified')),
        escalation_reason=routing.get('escalation_reason'),
        extra_review=extra,
        exclude_provider=exclude,
    )


def _fallback_entries(entries):
    if not isinstance(entries, list):
        raise ValueError('fallback_providers must be a list')
    result = []
    for entry in entries:
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(k), str) and entry[k].strip() for k in ('provider', 'model')
        ):
            raise ValueError('invalid task fallback route')
        result.append({'provider': entry['provider'], 'model': entry['model']})
    return result


def resolve_task_worker_route(
    *,
    body=None,
    assignee=None,
    model_override=None,
    provider_override=None,
    reasoning_effort=None,
):
    """Return spawn route dict or None to use the profile default.

    Keys: model, provider, effort, fallback_providers, source.
    """
    model_override = (model_override or '').strip() or None
    provider_override = (provider_override or '').strip() or None
    record = None
    if body:
        try:
            record = parse_runtime(body)
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError('Invalid task fallback contract') from exc

    if model_override:
        fallback = None
        effort = reasoning_effort
        if record and record.get('version') == 1:
            primary = record.get('primary') or {}
            if (primary.get('model'), primary.get('provider')) != (model_override, provider_override):
                raise ValueError('task route and model override disagree; reroute the card')
            fallback = _fallback_entries(record.get('fallback_providers') or [])
            effort = effort or primary.get('effort')
        elif record and record.get('version') == 2:
            live = _live_route(record, assignee=assignee)
            fallback = live.get('fallback_providers')
            effort = effort or live.get('effort')
        return {
            'model': model_override,
            'provider': provider_override,
            'effort': effort,
            'fallback_providers': fallback,
            'source': 'column',
        }

    if record and record.get('version') == 2:
        live = _live_route(record, assignee=assignee)
        return {
            'model': live['model'],
            'provider': live['provider'],
            'effort': live.get('effort') or reasoning_effort,
            'fallback_providers': live.get('fallback_providers') or [],
            'source': 'policy',
        }

    if record and record.get('version') == 1:
        primary = record['primary']
        return {
            'model': primary['model'],
            'provider': primary['provider'],
            'effort': primary.get('effort') or reasoning_effort,
            'fallback_providers': _fallback_entries(record.get('fallback_providers') or []),
            'source': 'v1',
        }
    return None


def worker_cli_model_flags(task) -> list[str]:
    route = resolve_task_worker_route(
        body=getattr(task, 'body', None),
        assignee=getattr(task, 'assignee', None),
        model_override=getattr(task, 'model_override', None),
        provider_override=getattr(task, 'provider_override', None),
        reasoning_effort=getattr(task, 'reasoning_effort', None),
    )
    flags: list[str] = []
    if route:
        flags.extend(['-m', route['model']])
        if route.get('provider'):
            flags.extend(['--provider', route['provider']])
        if route.get('effort'):
            flags.extend(['--reasoning', route['effort']])
        return flags
    effort = getattr(task, 'reasoning_effort', None)
    if effort:
        flags.extend(['--reasoning', effort])
    return flags


def read_task_fallback_override(*, task_id=None, db_path=None):
    task_id = task_id or os.environ.get('HERMES_KANBAN_TASK')
    db_path = db_path or os.environ.get('HERMES_KANBAN_DB')
    if not task_id:
        return None
    if not db_path:
        raise RuntimeError('Task fallback resolution requires HERMES_KANBAN_DB')
    uri = Path(db_path).resolve().as_uri() + '?mode=ro'
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            try:
                row = conn.execute(
                    'SELECT body, model_override, provider_override, assignee, reasoning_effort FROM tasks WHERE id=?',
                    (task_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                row = conn.execute(
                    'SELECT body, model_override, provider_override FROM tasks WHERE id=?',
                    (task_id,),
                ).fetchone()
                if row is not None:
                    row = (row[0], row[1], row[2], None, None)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise RuntimeError('Unable to read task fallback contract') from exc
    if row is None:
        return None
    body, model_override, provider_override, assignee, reasoning_effort = row
    try:
        route = resolve_task_worker_route(
            body=body,
            assignee=assignee,
            model_override=model_override,
            provider_override=provider_override,
            reasoning_effort=reasoning_effort,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError('Invalid task fallback contract') from exc
    if route is None:
        return None
    fallback = route.get('fallback_providers')
    return fallback
