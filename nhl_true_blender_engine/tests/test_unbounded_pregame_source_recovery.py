"""Pregame source discovery continues across persisted scheduled cycles."""
from pathlib import Path

from nhl_true_blender_engine.source_recovery import RECOVERY_REFRESHES_PER_WORKFLOW_CYCLE


def _recovery_loop():
    source = (Path(__file__).resolve().parents[2] / "run_true_blender.py").read_text()
    start = source.index(
        "for recovery_round in range(1, RECOVERY_REFRESHES_PER_WORKFLOW_CYCLE + 1):",
        source.index("feedback=[]"))
    end = source.index("result['evidenceFeedbackLoop']=feedback", start)
    return source, source[start:end]


def test_recovery_is_batched_per_workflow_cycle_not_limited_per_slate():
    root = Path(__file__).resolve().parents[2]
    source, loop = _recovery_loop()
    census = (root / "nhl_true_blender_engine" / "gate_census.py").read_text()
    workflow = (root / ".github" / "workflows" / "nhl-true-blender.yml").read_text()

    assert RECOVERY_REFRESHES_PER_WORKFLOW_CYCLE == 1
    assert "while True:" not in loop
    assert "await asyncio.sleep(60)" not in loop
    assert "remainingPregameGameIdsAfterRefresh" in loop
    assert "SOURCE_SEARCH_REQUIRED" not in source
    assert "sourceSearchRequired" not in census
    assert "SOURCE_SEARCH_REQUIRED" not in census
    # The next scheduled cycle restores the same authoritative evidence ledger
    # before it repeats the source collectors and original G0-G18 execution.
    assert "cron: '8,38 * * * *'" in workflow
    assert workflow.index("Restore authoritative compressed SQLite ledger") < workflow.index(
        "Run scheduled autonomous Blender phase")
    assert workflow.index("Run scheduled autonomous Blender phase") < workflow.index(
        "Persist original canonical G18 state and published site JSON")


def test_recovery_batch_refreshes_sources_and_reexecutes_original_gates():
    source, loop = _recovery_loop()
    for required in (
        "recovery_snapshot(",
        "collect_history(",
        "collect_context(",
        "collect_edge(",
        "collect_season_goal_history(",
        "collect_secondary(",
        "fetch_and_ingest_lineups(",
        "fetch_and_ingest_additional_deployment(",
        "collect_edgehalla_deployment(",
        "collect_nhl_projected_goalies(",
        "collect_dated_goalie_projections(",
        "collect_dfo_goalies(",
        "collect_official_dressed(",
        "collect_goalie_pbp_fallback(",
        "review_g0_goalie_origins(",
        "execute(con,snapshot,date,stage)",
        "'noAutomaticPasses':True",
        "remainingPregameGameIdsAfterRefresh",
    ):
        assert required in loop, required
    assert "recovery_deadline" not in loop
    assert "same_as_prior_signature" not in loop
    assert "result['evidenceFeedbackLoop']=feedback" in source


def test_recovery_batch_is_not_a_scorer_selection_gate():
    _, loop = _recovery_loop()
    assert "emit(" not in loop
    assert "'PRIMARY'" not in loop
    assert "'TRANSFER'" not in loop
    assert "'WHO'" not in loop
