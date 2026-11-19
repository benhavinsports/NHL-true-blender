"""Ensure Github state commit reconciliation reruns only on real engine changes.

Synthetic workflow source contract; the production job still verifies the
newest exact source before replaying and NEVER force pushes its Core.
"""
from pathlib import Path


def test_reconcile_replays_for_production_modules_but_not_tests_only():
    content=Path(".github/workflows/nhl-true-blender.yml").read_text()
    begin=content.index('if ! git diff --quiet "$state_base" origin/main --')
    end=content.index('; then',begin)
    command=content[begin:end]
    for dependency in (
        "state/", "run_true_blender.py", "nhl_true_blender_engine/",
        "scripts/automatic_blender_cycle.py", "scripts/run_cycle.py",
        "scripts/ledger_persistence.py", "scripts/retract_invalid_core.py",
        "scripts/preserved_core_receipt.py",
        "scripts/refresh_selected_gate_exports.py",
        "scripts/publish_site_state.py", "scripts/verify_published_core.py",
    ):
        assert dependency in command
    # Root-level modules and newly added source adapters must never be
    # silently rebased onto a run executed by stale code.
    for dependency in (
        "engine.py", "gate_executor.py", "core_publication.py",
        "nhl_data.py", "deployment_sources.py", "postgame_grade.py",
        "postgame_audit.py", "requirements.txt",
        ".github/workflows/nhl-true-blender.yml",
        "scripts/", "scripts/public_survivor_snapshot.py",
        "scripts/download_moneypuck.py",
    ):
        assert dependency in command
    assert ":(exclude)nhl_true_blender_engine/tests/**" in command
    assert ":(exclude)scripts/tests/**" in command
    assert "git rebase origin/main" in content
    assert "git fetch origin main" in content
    assert "git push origin HEAD:main" in content
    assert "git push -f" not in content and "git push --force" not in content
