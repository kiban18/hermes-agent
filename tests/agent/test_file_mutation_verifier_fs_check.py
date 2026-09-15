"""The verifier must check the filesystem before saying a file was not written.

It tracked only ``write_file`` and ``patch`` outcomes
(``FILE_MUTATING_TOOL_NAMES``). A failure recorded there was cleared only by a
later success from one of those same two tools. Any other route to disk — a
``terminal`` heredoc, ``sed``, a helper script — left the stale failure in
place, and the turn ended by telling the user the file "was NOT modified".

2026-09-15, rs101 t_00f5c386: three ``patch`` calls failed on escape drift
(doubled backslashes against regex literals), the model recovered with a
``python3`` heredoc through ``terminal``, and all three files were written and
committed in ``fcd4c7a``. The footer still announced that none of them had
changed, so the person had to go verify the work by hand.

Claiming a file is unmodified is a claim about the file, so it is checked
against the file. A fingerprint is taken when the failure is recorded; at turn
end a changed fingerprint drops the entry regardless of which tool did it.

A file that cannot be stat'd at either end keeps its failure entry: unverified
is not the same as verified-unchanged, and the pre-existing warning is the
safer answer when the filesystem cannot settle it.
"""

from __future__ import annotations

import os

import pytest

from agent.file_mutation_fs_check import (
    fingerprint_path,
    prune_recovered_mutations,
)


def _entry(path, tool="patch", preview="Escape-drift detected"):
    return {"tool": tool, "error_preview": preview}


def test_file_rewritten_by_another_tool_is_pruned(tmp_path):
    """The rs101 case: patch failed, something else wrote the file anyway."""
    target = tmp_path / "local_clip_server.dart"
    target.write_text("before\n", encoding="utf-8")

    failed = {str(target): dict(_entry(str(target)),
                                fingerprint=fingerprint_path(str(target)))}

    # The model recovers through `terminal`, which the verifier never sees.
    os.utime(target, (0, 0))
    target.write_text("after\n", encoding="utf-8")

    assert prune_recovered_mutations(failed) == {}


def test_untouched_file_keeps_its_failure(tmp_path):
    """A genuine failure must still be reported."""
    target = tmp_path / "untouched.dart"
    target.write_text("before\n", encoding="utf-8")

    failed = {str(target): dict(_entry(str(target)),
                                fingerprint=fingerprint_path(str(target)))}

    assert list(prune_recovered_mutations(failed)) == [str(target)]


def test_same_size_different_content_is_pruned(tmp_path):
    """Size alone is not enough — a same-length rewrite still counts."""
    target = tmp_path / "same_size.mjs"
    target.write_text("aaaa\n", encoding="utf-8")

    failed = {str(target): dict(_entry(str(target)),
                                fingerprint=fingerprint_path(str(target)))}

    target.write_text("bbbb\n", encoding="utf-8")

    assert prune_recovered_mutations(failed) == {}


def test_file_created_after_the_failure_is_pruned(tmp_path):
    """write_file failed, the file did not exist, then something created it."""
    target = tmp_path / "created_later.txt"

    failed = {str(target): dict(_entry(str(target), tool="write_file"),
                                fingerprint=fingerprint_path(str(target)))}
    assert failed[str(target)]["fingerprint"] is None

    target.write_text("now here\n", encoding="utf-8")

    assert prune_recovered_mutations(failed) == {}


def test_still_missing_file_keeps_its_failure(tmp_path):
    target = tmp_path / "never_created.txt"
    failed = {str(target): dict(_entry(str(target), tool="write_file"),
                                fingerprint=fingerprint_path(str(target)))}

    assert list(prune_recovered_mutations(failed)) == [str(target)]


def test_entry_without_a_fingerprint_is_kept(tmp_path):
    """Unverifiable is not the same as unchanged — keep the old behaviour."""
    target = tmp_path / "no_fingerprint.txt"
    target.write_text("x\n", encoding="utf-8")

    failed = {str(target): _entry(str(target))}  # no fingerprint key

    assert list(prune_recovered_mutations(failed)) == [str(target)]


def test_pruning_never_raises_on_a_bad_path(tmp_path):
    """One unusable path must not cost the rest of the footer."""
    good = tmp_path / "good.txt"
    good.write_text("before\n", encoding="utf-8")
    failed = {
        "\x00not-a-path": dict(_entry("\x00not-a-path"), fingerprint=("x", 1)),
        str(good): dict(_entry(str(good)), fingerprint=fingerprint_path(str(good))),
    }

    kept = prune_recovered_mutations(failed)  # must not raise
    assert str(good) in kept  # genuinely untouched, still reported


def test_unreadable_file_keeps_its_failure(tmp_path):
    """Present but unreadable is undecidable, so the warning stays.

    The opposite of the deleted case below: nothing here says a write landed.
    """
    target = tmp_path / "locked.txt"
    target.write_text("before\n", encoding="utf-8")
    failed = {str(target): dict(_entry(str(target)),
                                fingerprint=fingerprint_path(str(target)))}

    os.chmod(target, 0o000)
    try:
        if fingerprint_path(str(target)) is not None:
            pytest.skip("this filesystem/user can still read a 0o000 file")
        assert list(prune_recovered_mutations(failed)) == [str(target)]
    finally:
        os.chmod(target, 0o600)


def test_deleted_after_the_failure_is_pruned(tmp_path):
    """A file removed during the turn did change, so "NOT modified" is wrong.

    A fingerprint only exists because the file was readable when the tool
    failed; its absence afterwards means something removed it.
    """
    target = tmp_path / "removed.txt"
    target.write_text("before\n", encoding="utf-8")
    failed = {str(target): dict(_entry(str(target)),
                                fingerprint=fingerprint_path(str(target)))}

    target.unlink()

    assert prune_recovered_mutations(failed) == {}


def test_original_dict_is_not_mutated(tmp_path):
    target = tmp_path / "copy.txt"
    target.write_text("before\n", encoding="utf-8")
    failed = {str(target): dict(_entry(str(target)),
                                fingerprint=fingerprint_path(str(target)))}
    target.write_text("after\n", encoding="utf-8")

    prune_recovered_mutations(failed)
    assert str(target) in failed


class _FakeAgent:
    """Enough of the agent surface for the recorder and the footer."""

    def __init__(self):
        self._turn_failed_file_mutations = {}
        self._turn_file_mutation_paths = set()
        self._checkpoint_mgr = None

    _record_file_mutation_result = None  # bound in the test


def test_recorder_stores_a_fingerprint_with_the_failure(tmp_path):
    """The wiring in run_agent must capture the fingerprint, not just the error."""
    from run_agent import AIAgent

    target = tmp_path / "wired.dart"
    target.write_text("before\n", encoding="utf-8")

    agent = _FakeAgent()
    AIAgent._record_file_mutation_result(
        agent,
        "patch",
        {"path": str(target)},
        {"error": "Escape-drift detected"},
        True,
    )

    entry = agent._turn_failed_file_mutations.get(str(target))
    assert entry is not None, agent._turn_failed_file_mutations
    assert "fingerprint" in entry
    assert entry["fingerprint"] == fingerprint_path(str(target))


def test_recorded_failure_is_dropped_once_the_file_changes(tmp_path):
    """End to end: patch fails, something else writes, footer must go quiet."""
    from run_agent import AIAgent

    target = tmp_path / "recovered.dart"
    target.write_text("before\n", encoding="utf-8")

    agent = _FakeAgent()
    AIAgent._record_file_mutation_result(
        agent, "patch", {"path": str(target)},
        {"error": "Escape-drift detected"}, True,
    )
    assert agent._turn_failed_file_mutations

    target.write_text("after\n", encoding="utf-8")  # recovery via terminal

    assert prune_recovered_mutations(agent._turn_failed_file_mutations) == {}
