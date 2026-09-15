"""Settle "was this file written?" against the file, not the tool call log.

The turn-end verifier records a failed ``write_file`` / ``patch`` and clears it
only when one of those same two tools later succeeds on the same path
(``FILE_MUTATING_TOOL_NAMES``). Every other route to disk is invisible to it: a
``terminal`` heredoc, ``sed -i``, a helper script, an external editor. When the
model recovers that way the stale entry survives, and the turn ends telling the
person the file "was NOT modified" while the new content sits on disk.

2026-09-15, rs101 ``t_00f5c386``: three ``patch`` calls failed on escape drift,
the model rewrote the files with a ``python3`` heredoc, and all three landed in
commit ``fcd4c7a`` — yet the footer named all three as unwritten, so the work
had to be verified by hand before it could be trusted.

The footer makes a claim about a file, so this checks the file. A fingerprint
is taken when the failure is recorded and compared at turn end; a path that
changed is dropped no matter what changed it.

Deliberately conservative: an entry with no fingerprint, or a path that cannot
be stat'd, is KEPT. Unverifiable is not the same as verified-unchanged, and a
warning that stays is cheaper than a silently dropped real failure.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Optional, Tuple

# Hash the head of the file rather than all of it: enough to separate a real
# rewrite from an untouched file without reading a large artifact twice per
# turn. Size and mtime come along, so a change past this window still shows up
# unless it also preserved both — which an editing tool does not do.
_HASH_BYTES = 64 * 1024

Fingerprint = Tuple[str, int]


def fingerprint_path(path: str) -> Optional[Fingerprint]:
    """Cheap content fingerprint, or ``None`` when the file isn't readable.

    ``None`` is a real state, not an error: ``write_file`` failing on a path
    that does not exist yet is the common case, and a file appearing later is
    exactly the recovery this module needs to catch.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            head = fh.read(_HASH_BYTES)
    except Exception:
        return None
    return (hashlib.sha256(head).hexdigest(), size)


def _absent(path: str) -> Optional[bool]:
    """``True`` the path is definitely gone, ``False`` present, ``None`` unknown.

    Separates "deleted since the failure" from "there but unreadable". Only the
    first is evidence that something ran; the second must not be read as a
    successful write.
    """
    try:
        return not os.path.exists(path)
    except Exception:
        return None


def mutation_recovered(recorded: Optional[Fingerprint], path: str) -> Optional[bool]:
    """Did *path* change since *recorded*?

    ``True`` changed, ``False`` unchanged, ``None`` undecidable. Only ``True``
    drops a failure, so anything short of positive evidence keeps the warning.
    """
    current = fingerprint_path(path)
    if current is not None:
        if recorded is None:
            return True  # the file appeared after the tool failed on it
        try:
            return tuple(recorded) != tuple(current)
        except Exception:
            return None  # malformed record: cannot decide, so do not drop it

    # Unreadable now. Gone is evidence of a change; unreadable-but-present, or
    # a path we cannot even test, is not.
    gone = _absent(path)
    if gone is None:
        return None
    if not gone:
        return None
    return False if recorded is None else True


def prune_recovered_mutations(failed: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Return *failed* without the paths that changed on disk anyway.

    Never mutates the caller's dict — the turn may still want the full record
    for logging — and never raises: one unreadable path must not cost the whole
    footer, so anything that throws is kept.
    """
    if not failed:
        return {}
    kept: Dict[str, Dict[str, Any]] = {}
    for path, info in failed.items():
        try:
            if not isinstance(info, dict) or "fingerprint" not in info:
                kept[path] = info  # not fingerprinted: nothing to compare
                continue
            if mutation_recovered(info.get("fingerprint"), path) is True:
                continue
            kept[path] = info
        except Exception:
            kept[path] = info
    return kept
