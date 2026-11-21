"""Pregame source discovery continues until source resolution or puck drop."""
from pathlib import Path


def test_recovery_has_no_retry_count_deadline_or_source_search_stop_label():
    root = Path(__file__).resolve().parents[2]
    source = (root / "run_true_blender.py").read_text()
    census = (root / "nhl_true_blender_engine" / "gate_census.py").read_text()
    workflow = (root / ".github" / "workflows" / "nhl-true-blender.yml").read_text()

    assert "while True:" in source
    assert "recovery_deadline" not in source
    assert "time.monotonic" not in source
    assert "researchContinuesNextScheduledCycle" not in source
    assert "sourceResearchStatus" not in source
    assert "SOURCE_SEARCH_REQUIRED" not in source
    assert "sourceSearchRequired" not in census
    assert "SOURCE_SEARCH_REQUIRED" not in census
    assert "await asyncio.sleep(60)" in source
    assert "if not retry_snapshot['games']:" in source
    assert "for recovery_round in range(1, 4)" not in source
    assert "timeout-minutes: 28" not in workflow


def test_recovery_loop_refreshes_sources_and_reexecutes_original_gates():
    source = (Path(__file__).resolve().parents[2] / "run_true_blender.py").read_text()
    loop_start = source.index("while True:", source.index("feedback=[]"))
    loop_end = source.index("result['evidenceFeedbackLoop']=feedback", loop_start)
    loop = source[loop_start:loop_end]
    assert "recovery_snapshot(" in loop
    assert "collect_history(" in loop
    assert "collect_context(" in loop
    assert "collect_edge(" in loop
    assert "collect_secondary(" in loop
    assert "fetch_and_ingest_lineups(" in loop
    assert "collect_nhl_projected_goalies(" in loop
    assert "collect_goalie_pbp_fallback(" in loop
    assert "execute(con,snapshot,date,stage)" in loop
    assert "noAutomaticPasses':True" in loop
    assert "break" in loop
    assert "recovery_deadline" not in loop
    assert "same_as_prior_signature" not in loop


def test_recovery_loop_is_not_a_scorer_selection_gate():
    source = (Path(__file__).resolve().parents[2] / "run_true_blender.py").read_text()
    loop_start = source.index("while True:", source.index("feedback=[]"))
    loop_end = source.index("result['evidenceFeedbackLoop']=feedback", loop_start)
    loop = source[loop_start:loop_end]
    assert "emit(" not in loop
    assert "PRIMARY" not in loop
    assert "TRANSFER" not in loop
    assert "WHO" not in loop
