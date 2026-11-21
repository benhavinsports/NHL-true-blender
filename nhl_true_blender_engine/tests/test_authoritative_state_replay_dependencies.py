"""The live slate runs once on tested source; persistence cannot silently replay picks.

The former test searched for the removed `git reset --hard origin/main`
replay branch. The canonical workflow now safely cherry-picks state-only
output from the exact executed commit onto current main instead.
"""
from pathlib import Path


def test_authoritative_state_published_from_exact_executed_source():
    workflow=Path(".github/workflows/nhl-true-blender.yml").read_text()
    # A normal code push verifies code; it never starts competing live slates.
    assert "paths: ['.github/nhl-live-validation.json']" in workflow
    assert "cancel-in-progress: false" in workflow
    assert 'saved_state_commit="$(git rev-parse HEAD)"' in workflow
    assert 'executed_source_commit="$(git rev-parse HEAD^)"' in workflow
    # The source that actually selected skaters remains unchanged while a
    # separate worktree integrates its saved state into current main.
    assert 'git fetch origin main' in workflow
    assert 'git worktree add --detach "$persist_dir" origin/main' in workflow
    assert 'git -C "$persist_dir" cherry-pick --no-commit "$saved_state_commit"' in workflow
    assert 'git -C "$persist_dir" diff --cached --quiet' in workflow
    assert 'git -C "$persist_dir" push origin HEAD:main' in workflow
    assert 'git -C "$persist_dir" commit -m "Save original Blender run from tested source $executed_source_commit"' in workflow
    # In particular the bot may not pretend its old execution happened on
    # newly fetched selection logic or overwrite somebody else's card.
    assert "git reset --hard origin/main" not in workflow
    assert "git rebase origin/main" not in workflow
    assert "git push -f" not in workflow
    assert "git push --force" not in workflow


def test_production_changes_verify_before_the_separate_scheduled_run():
    verification=Path(".github/workflows/blender-verification.yml").read_text()
    for dependency in (
        "nhl_true_blender_engine/**", "run_true_blender.py", "*.py",
        "requirements.txt", "scripts/**", "site/**"
    ):
        assert dependency in verification
    assert "python -m compileall" in verification
    assert "python -m pytest -q --junitxml=integration-results.xml" in verification
    live=Path(".github/workflows/nhl-true-blender.yml").read_text()
    assert "python -m unittest discover -p 'test*.py' -v" in live
    assert "python -m pytest -q nhl_true_blender_engine/tests" in live
    assert "scripts/ledger_persistence.py restore" in live
    assert "git push origin HEAD:main" in live
