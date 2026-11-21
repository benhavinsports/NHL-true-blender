"""The overlay must execute at its owning master-gate position, not as a batch."""
import inspect
import re

from nhl_true_blender_engine import engine


def _overlay_calls():
    source = inspect.getsource(engine.evaluate_skater)
    return [
        (match.start(), re.findall(r"'([^']+)'", match.group(1)))
        for match in re.finditer(r"source_steps\(\[([^\]]*)\],", source)
    ]


def test_overlay_owner_map_is_complete_and_one_to_one():
    assert set(engine.STEP_OWNER) == set(engine.OVERLAY)
    assert all(owner in engine.MASTER for owner in engine.STEP_OWNER.values())
    assert len(engine.STEP_OWNER) == 16
    assert len(engine.OVERLAY_EXECUTION_ORDER) == 16
    assert set(engine.OVERLAY_EXECUTION_ORDER) == set(engine.OVERLAY)
    assert len(set(engine.OVERLAY_EXECUTION_ORDER)) == 16


def test_overlay_runs_just_in_time_at_each_owner_gate():
    source = inspect.getsource(engine.evaluate_skater)
    calls = _overlay_calls()
    observed = [step for _, steps in calls for step in steps]
    assert observed == engine.OVERLAY_EXECUTION_ORDER
    assert "source_steps(OVERLAY[:OVERLAY.index('Step10.5')]" not in source
    assert "source_steps(OVERLAY[OVERLAY.index('Step10.5'):OVERLAY.index('Step14')]" not in source


def test_each_overlay_operation_is_invoked_before_its_owner_gate_verdict():
    source = inspect.getsource(engine.evaluate_skater)
    calls = _overlay_calls()
    for gate in engine.MASTER:
        owned = engine.STEPS_BY_GATE[gate]
        if not owned:
            continue
        gate_emit = source.index(f"emit('{gate}'")
        for step in owned:
            call = next(position for position, steps in calls if step in steps)
            assert call < gate_emit, f"{step} must execute before {gate} decides"


def test_archetype_tagging_is_executed_at_g4_before_later_finalist_gates():
    source = inspect.getsource(engine.evaluate_skater)
    step7 = source.index("source_steps(['Step5','Step7']")
    g4 = source.index("emit('G4'")
    g5 = source.index("emit('G5'")
    g10_5 = source.index("emit('G10.5'")
    g18 = source.index("emit('G18'")
    assert step7 < g4 < g5 < g10_5 < g18


def test_challenger_and_final_overlay_steps_wait_for_their_own_gates():
    source = inspect.getsource(engine.evaluate_skater)
    assert source.index("source_steps(['Step10.5']") < source.index("emit('G10.5'")
    assert source.index("source_steps(['Step13']") < source.index("emit('G13'")
    assert source.index("source_steps(['Step11']") < source.index("emit('G14'")
    assert source.index("source_steps(['Step12']") < source.index("emit('G16'")
    assert source.index("source_steps(['Step14']") < source.index("emit('G17'")
