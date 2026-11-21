"""Pregame source recovery has no arbitrary retry-count cutoff."""
from pathlib import Path


def test_recovery_repeats_while_original_gate_evidence_changes():
    source = (Path(__file__).resolve().parents[2] / "run_true_blender.py").read_text()
    assert "while True:" in source
    assert "for recovery_round in range(1, 4)" not in source
    assert "same_as_prior_signature = recovery_signature == previous_recovery_signature" in source
    assert "if not retry_snapshot['games'] or same_as_prior_signature:" not in source
    assert "repeatedSignatureDoesNotEndSearch" in source
    assert "recovery_deadline = time.monotonic() + 12 * 60" in source
    assert "researchContinuesNextScheduledCycle" in source
    assert "next_unresolved=after.get(" in source
    assert "unresolved=next_unresolved" in source


def test_recovery_loop_is_not_a_scorer_selection_gate():
    source = (Path(__file__).resolve().parents[2] / "run_true_blender.py").read_text()
    loop_start = source.index("while True:", source.index("previous_recovery_signature"))
    loop_end = source.index("result['evidenceFeedbackLoop']=feedback", loop_start)
    loop = source[loop_start:loop_end]
    assert "recovery_snapshot(" in loop
    assert "execute(con,snapshot,date,stage)" in loop
    assert "noAutomaticPasses':True" in loop
    assert "emit(" not in loop
