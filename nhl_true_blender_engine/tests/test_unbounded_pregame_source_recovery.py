"""Pregame source discovery continues until each game's puck-drop freeze."""
from pathlib import Path


def _recovery_loop():
    source = (Path(__file__).resolve().parents[2] / "run_true_blender.py").read_text()
    start = source.index("while True:", source.index("feedback=[]"))
    end = source.index("result['evidenceFeedbackLoop']=feedback", start)
    return source, source[start:end]


def test_recovery_has_no_fixed_refresh_count_and_stops_only_at_puck_drop():
    root = Path(__file__).resolve().parents[2]
    source, loop = _recovery_loop()
    census = (root / "nhl_true_blender_engine" / "gate_census.py").read_text()
    workflow = (root / ".github" / "workflows" / "nhl-true-blender.yml").read_text()

    assert "while True:" in loop
    assert "recovery_round += 1" in loop
    assert "RECOVERY_REFRESHES_PER_WORKFLOW_CYCLE" not in source
    assert "range(1," not in loop
    assert "await asyncio.sleep(60)" in loop
    assert "remainingPregameGameIdsAfterRefresh" in loop
    assert "SOURCE_SEARCH_REQUIRED" not in source
    assert "sourceSearchRequired" not in census
    assert "SOURCE_SEARCH_REQUIRED" not in census
    # Each pass recomputes the research set from the persisted gate ledger;
    # recovery_snapshot applies the original per-game puck-drop freeze.
    recovery = (root / "nhl_true_blender_engine" / "source_recovery.py").read_text()
    assert "game_started(game, now)" in recovery
    assert "RECOVERY_REFRESHES_PER_WORKFLOW_CYCLE" not in recovery
    assert "cron: '8,38 * * * *'" in workflow
    assert workflow.index("Restore authoritative compressed SQLite ledger") < workflow.index(
        "Run scheduled autonomous Blender phase")
    assert workflow.index("Run scheduled autonomous Blender phase") < workflow.index(
        "Persist original canonical G18 state and published site JSON")


def test_each_recovery_pass_refreshes_sources_and_reexecutes_original_gates():
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


def test_recovery_loop_is_not_a_scorer_selection_gate():
    _, loop = _recovery_loop()
    assert "emit(" not in loop
    assert "'PRIMARY'" not in loop
    assert "'TRANSFER'" not in loop
    assert "'WHO'" not in loop
